import asyncio
import os
import random
from tqdm import tqdm
from playwright.async_api import async_playwright
from PyPDF2 import PdfWriter, PdfReader
from PyPDF2.generic import NameObject, ArrayObject, DictionaryObject

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
        
        # Capture raw links (including fragments)
        raw_links = await page.eval_on_selector_all(
            "#mw-content-text a", 
            "nodes => nodes.map(n => n.href).filter(href => href.includes('/w/cpp/'))"
        )
        # Extract unique base URLs for our download queue
        unique_base_urls = list(dict.fromkeys([l.split('#')[0] for l in raw_links]))[:20]
        
        # Central dictionary to hold all mapping metadata
        site_data = {} 
        pdf_temp_files = []
        current_page_offset = 0

        pbar = tqdm(total=len(unique_base_urls), desc="Scraping & Mapping", unit="pg")

        # --- PASS 1: Generate PDFs and Extract Anchor Coordinates ---
        for i, url in enumerate(unique_base_urls):
            temp_name = f"part_{i}.pdf"
            title = url.split('/')[-1].replace('_', ' ').capitalize()
            
            if i > 0: await asyncio.sleep(random.uniform(1.2, 2.5))

            try:
                await page.goto(url, wait_until="networkidle")
                await page.add_style_tag(content="#cpp-navigation, #cpp-p-search, #footer, .vector-menu { display: none !important; }")
                
                # 1. INJECT JS: Map every anchor's relative vertical position (0.0 to 1.0)
                anchor_map = await page.evaluate("""() => {
                    const elements = document.querySelectorAll('[id]');
                    const docHeight = document.documentElement.scrollHeight;
                    let data = {};
                    elements.forEach(el => {
                        const rect = el.getBoundingClientRect();
                        const absoluteY = rect.top + window.scrollY;
                        data[el.id] = absoluteY / docHeight; // e.g., 0.45 = 45% down the page
                    });
                    return data;
                }""")

                await page.pdf(path=temp_name, format="A4", print_background=True)
                
                reader = PdfReader(temp_name)
                page_count = len(reader.pages)
                
                # Store everything we need to route links later
                site_data[url] = {
                    "start_page": current_page_offset,
                    "total_pages": page_count,
                    "anchors": anchor_map
                }
                
                pdf_temp_files.append((temp_name, title, page_count))
                current_page_offset += page_count
            except Exception as e:
                pbar.write(f"Skip {url}: {e}")
            
            pbar.update(1)
        pbar.close()

        # --- PASS 2: Merge and Re-Link Anchors ---
        if pdf_temp_files:
            print("\nMerging and Rewriting Cross-References...")
            writer = PdfWriter()
            
            for temp_file, title, _ in pdf_temp_files:
                writer.append(temp_file)
            
            # Iterate through all links in the newly merged document
            for page_idx in range(len(writer.pages)):
                page_obj = writer.pages[page_idx]
                
                if "/Annots" in page_obj:
                    for annot in page_obj["/Annots"]:
                        obj = annot.get_object()
                        
                        if obj.get("/Subtype") == "/Link" and "/A" in obj:
                            action = obj["/A"]
                            if action.get("/S") == "/URI":
                                full_uri = action.get("/URI", "")
                                clean_uri = full_uri.split('#')[0].rstrip('/')
                                anchor_id = full_uri.split('#')[1] if '#' in full_uri else None
                                
                                # If the base URL is in our downloaded batch
                                if clean_uri in site_data:
                                    target_info = site_data[clean_uri]
                                    target_page = target_info["start_page"]
                                    
                                    # 2. CALCULATE EXACT PAGE: If there's an anchor, find its page offset
                                    if anchor_id and anchor_id in target_info["anchors"]:
                                        relative_y = target_info["anchors"][anchor_id]
                                        # Multiply percentage by total pages to get the page offset
                                        page_offset = int(relative_y * target_info["total_pages"])
                                        # Safety bound to ensure we don't overshoot the document bounds
                                        page_offset = min(page_offset, target_info["total_pages"] - 1)
                                        
                                        target_page += page_offset
                                    
                                    # Change Action: Web URI -> Internal PDF Jump
                                    new_action = DictionaryObject()
                                    new_action.update({
                                        NameObject("/S"): NameObject("/GoTo"),
                                        NameObject("/D"): ArrayObject([
                                            writer.pages[target_page].indirect_reference, 
                                            NameObject("/Fit") # Fit the target page to the window
                                        ])
                                    })
                                    obj.update({NameObject("/A"): new_action})

            # Add Sidebar Bookmarks
            current_idx = 0
            for _, title, count in pdf_temp_files:
                writer.add_outline_item(title, current_idx)
                current_idx += count

            with open(output_name, "wb") as f:
                writer.write(f)

            for f, _, _ in pdf_temp_files: os.remove(f)
            print(f"Success! {output_name} now supports deep-linking.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(create_linked_manual("https://en.cppreference.com/w/cpp/container", "CPP_Advanced_Manual.pdf"))