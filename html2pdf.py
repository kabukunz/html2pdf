import asyncio
import os
import random
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from PyPDF2 import PdfWriter, PdfReader
from PyPDF2.generic import NameObject, ArrayObject, DictionaryObject

def normalize_path(url_str):
    parsed = urlparse(str(url_str))
    return parsed.path.rstrip('/')

async def create_linked_manual(base_url, output_name):
    CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, executable_path=CHROME_PATH, args=["--headless=new"])
        context = await browser.new_context(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")
        page = await context.new_page()

        print(f"--- Analyzing {base_url} ---")
        await page.goto(base_url, wait_until="networkidle")
        
        # We now look for links EVERYWHERE (including the sidebar) to build our universe
        all_page_links = await page.eval_on_selector_all(
            "a", 
            "nodes => nodes.map(n => n.href).filter(href => href.includes('/w/cpp/'))"
        )
        
        # Defining our "Internal Universe" (Download limit kept at 25 for this example)
        internal_urls = list(dict.fromkeys([l.split('#')[0] for l in all_page_links]))[:25]
        internal_paths = [normalize_path(u) for u in internal_urls]
        
        site_data = {} 
        pdf_temp_files = []
        current_page_offset = 0

        print(f"Downloading {len(internal_urls)} pages with Sidebar preserved...")

        for i, url in enumerate(internal_urls):
            temp_name = f"part_{i}.pdf"
            title = url.split('/')[-1].replace('_', ' ').capitalize()
            norm_path = normalize_path(url)
            
            if i > 0: await asyncio.sleep(random.uniform(1.0, 2.0))

            try:
                await page.goto(url, wait_until="networkidle")
                
                # 1. VISUAL TAGGING (Now applied to ALL links, including Sidebar)
                await page.evaluate("""([paths]) => {
                    const links = document.querySelectorAll('a');
                    links.forEach(link => {
                        try {
                            const path = new URL(link.href).pathname.replace(/\/$/, "");
                            if (!paths.includes(path)) {
                                link.style.color = "#888"; 
                                link.style.textDecoration = "none";
                                link.style.borderBottom = "1px dotted #aaa";
                            } else {
                                link.style.color = "#0000EE"; 
                                link.style.fontWeight = "bold";
                            }
                        } catch(e) {}
                    });
                }""", [internal_paths])

                # 2. CSS ADJUSTMENT: Restore Sidebar, but hide search and footer
                await page.add_style_tag(content="""
                    #cpp-p-search, #footer, .printfooter { display: none !important; }
                    
                    /* Ensure the sidebar doesn't overlap the main content on A4 */
                    #cpp-navigation { 
                        position: relative !important; 
                        float: left !important; 
                        width: 160px !important; 
                        font-size: 0.75em !important;
                    }
                    #content { 
                        margin-left: 170px !important; 
                        padding: 10px !important; 
                        border: none !important; 
                        min-width: 0 !important;
                    }
                    body { background: white !important; font-size: 12px !important; }
                """)

                # 3. ANCHOR MAPPING
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
                site_data[norm_path] = {"start_page": current_page_offset, "total_pages": page_count, "anchors": anchor_map}
                pdf_temp_files.append((temp_name, title, page_count))
                current_page_offset += page_count

            except Exception as e:
                print(f"Skip {url}: {e}")

        # --- MERGE & REWRITE INTERNAL LINKS ---
        if pdf_temp_files:
            writer = PdfWriter()
            for temp_file, _, _ in pdf_temp_files:
                writer.append(temp_file)
            
            rewrites = 0
            for page_idx in range(len(writer.pages)):
                page_obj = writer.pages[page_idx]
                if "/Annots" in page_obj:
                    for annot in page_obj["/Annots"]:
                        obj = annot.get_object()
                        if obj.get("/Subtype") == "/Link" and "/A" in obj:
                            action = obj["/A"]
                            if action.get("/S") == "/URI":
                                full_uri = str(action.get("/URI", ""))
                                clean_pdf_path = normalize_path(full_uri)
                                if clean_pdf_path in site_data:
                                    target_info = site_data[clean_pdf_path]
                                    target_page = target_info["start_page"]
                                    anchor_id = full_uri.split('#')[1] if '#' in full_uri else None
                                    if anchor_id and anchor_id in target_info["anchors"]:
                                        target_page += int(target_info["anchors"][anchor_id] * target_info["total_pages"])
                                    
                                    new_action = DictionaryObject()
                                    new_action.update({
                                        NameObject("/S"): NameObject("/GoTo"),
                                        NameObject("/D"): ArrayObject([writer.pages[target_page].indirect_reference, NameObject("/Fit")])
                                    })
                                    obj[NameObject("/A")] = new_action
                                    rewrites += 1

            with open(output_name, "wb") as f:
                writer.write(f)

            for f, _, _ in pdf_temp_files: os.remove(f)
            print(f"Done! Created {output_name} with sidebar and {rewrites} internal links.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(create_linked_manual("https://en.cppreference.com/w/cpp/container", "CPP_Manual_With_Sidebar.pdf"))