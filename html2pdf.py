import asyncio
import os
import random
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from PyPDF2 import PdfWriter, PdfReader
from PyPDF2.generic import NameObject, ArrayObject, DictionaryObject

def normalize_path(url_str):
    """
    Strips protocols (http/https), domains, and trailing slashes.
    Example: 'https://en.cppreference.com/w/cpp/vector/' becomes '/w/cpp/vector'
    """
    if not isinstance(url_str, str):
        url_str = str(url_str)
    parsed = urlparse(url_str)
    return parsed.path.rstrip('/')

async def create_linked_manual(base_url, output_name):
    CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=CHROME_PATH,
            args=["--headless=new"]
        )
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        page = await context.new_page()

        print(f"--- Analyzing {base_url} ---")
        await page.goto(base_url, wait_until="networkidle")
        
        raw_links = await page.eval_on_selector_all(
            "#mw-content-text a", 
            "nodes => nodes.map(n => n.href).filter(href => href.includes('/w/cpp/'))"
        )
        # Limit to 20 for testing; increase this to capture more internal links later
        unique_base_urls = list(dict.fromkeys([l.split('#')[0] for l in raw_links]))[:20]
        
        site_data = {} 
        pdf_temp_files = []
        current_page_offset = 0

        print(f"Scraping {len(unique_base_urls)} pages...")

        # --- PASS 1: Generate PDFs ---
        for i, url in enumerate(unique_base_urls):
            temp_name = f"part_{i}.pdf"
            title = url.split('/')[-1].replace('_', ' ').capitalize()
            norm_path = normalize_path(url) # Normalize the key
            
            if i > 0: await asyncio.sleep(random.uniform(1.2, 2.5))

            try:
                await page.goto(url, wait_until="networkidle")
                await page.add_style_tag(content="#cpp-navigation, #cpp-p-search, #footer, .vector-menu { display: none !important; }")
                
                anchor_map = await page.evaluate("""() => {
                    const elements = document.querySelectorAll('[id]');
                    const docHeight = document.documentElement.scrollHeight;
                    let data = {};
                    elements.forEach(el => {
                        data[el.id] = (el.getBoundingClientRect().top + window.scrollY) / docHeight;
                    });
                    return data;
                }""")

                await page.pdf(path=temp_name, format="A4", print_background=True)
                
                reader = PdfReader(temp_name)
                page_count = len(reader.pages)
                
                site_data[norm_path] = {
                    "start_page": current_page_offset,
                    "total_pages": page_count,
                    "anchors": anchor_map
                }
                
                pdf_temp_files.append((temp_name, title, page_count))
                current_page_offset += page_count
            except Exception as e:
                print(f"Skip {url}: {e}")

        # --- PASS 2: Merge and Re-Link Anchors ---
        if pdf_temp_files:
            print("\nMerging and mapping internal paths...")
            writer = PdfWriter()
            
            for temp_file, title, _ in pdf_temp_files:
                writer.append(temp_file)
            
            link_rewrites = 0

            for page_idx in range(len(writer.pages)):
                page_obj = writer.pages[page_idx]
                
                if "/Annots" in page_obj:
                    for annot in page_obj["/Annots"]:
                        obj = annot.get_object()
                        
                        if obj.get("/Subtype") == "/Link" and "/A" in obj:
                            action = obj["/A"]
                            if action.get("/S") == "/URI":
                                full_uri = str(action.get("/URI", ""))
                                
                                # Normalize the PDF's internal link destination
                                clean_pdf_path = normalize_path(full_uri)
                                anchor_id = full_uri.split('#')[1] if '#' in full_uri else None
                                
                                # Check if this path exists in our downloaded data
                                if clean_pdf_path in site_data:
                                    target_info = site_data[clean_pdf_path]
                                    target_page = target_info["start_page"]
                                    
                                    if anchor_id and anchor_id in target_info["anchors"]:
                                        relative_y = target_info["anchors"][anchor_id]
                                        page_offset = int(relative_y * target_info["total_pages"])
                                        page_offset = min(page_offset, target_info["total_pages"] - 1)
                                        target_page += page_offset
                                    
                                    # Overwrite the URI action with an internal GoTo action
                                    new_action = DictionaryObject()
                                    new_action.update({
                                        NameObject("/S"): NameObject("/GoTo"),
                                        NameObject("/D"): ArrayObject([
                                            writer.pages[target_page].indirect_reference, 
                                            NameObject("/Fit") 
                                        ])
                                    })
                                    obj[NameObject("/A")] = new_action
                                    link_rewrites += 1

            current_idx = 0
            for _, title, count in pdf_temp_files:
                writer.add_outline_item(title, current_idx)
                current_idx += count

            with open(output_name, "wb") as f:
                writer.write(f)

            for f, _, _ in pdf_temp_files: os.remove(f)
            print(f"Success! Rewrote {link_rewrites} links to internal targets.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(create_linked_manual("https://en.cppreference.com/w/cpp/container", "CPP_Fixed_Links.pdf"))