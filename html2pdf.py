import asyncio
import os
import random
import re
from tqdm import tqdm
from playwright.async_api import async_playwright
from PyPDF2 import PdfWriter, PdfReader
from PyPDF2.generic import NameObject, TextStringObject, DictionaryObject, ArrayObject

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
        
        # Capture links
        raw_links = await page.eval_on_selector_all(
            "#mw-content-text a", 
            "nodes => nodes.map(n => n.href).filter(href => href.includes('/w/cpp/'))"
        )
        # Limit to 25 for stability; clean fragments
        unique_links = list(dict.fromkeys([l.split('#')[0] for l in raw_links]))[:25]
        
        url_to_page_map = {} # Maps URL -> Start Page Index
        pdf_temp_files = []
        current_page_offset = 0

        pbar = tqdm(total=len(unique_links), desc="Processing Pages", unit="pg")

        # Pass 1: Convert and Map
        for i, url in enumerate(unique_links):
            temp_name = f"part_{i}.pdf"
            title = url.split('/')[-1].replace('_', ' ').capitalize()
            
            if i > 0: await asyncio.sleep(random.uniform(1, 2))

            try:
                await page.goto(url, wait_until="networkidle")
                await page.add_style_tag(content="#cpp-navigation, #footer, .vector-menu { display: none !important; }")
                
                await page.pdf(path=temp_name, format="A4", print_background=True)
                
                reader = PdfReader(temp_name)
                page_count = len(reader.pages)
                
                # Store the mapping
                url_to_page_map[url] = current_page_offset
                pdf_temp_files.append((temp_name, title, page_count))
                
                current_page_offset += page_count
            except Exception as e:
                pbar.write(f"Skip {url}: {e}")
            
            pbar.update(1)
        pbar.close()

        # Pass 2: Merge and Re-Link
        if pdf_temp_files:
            print("\nMerging and Rewriting Internal Links...")
            writer = PdfWriter()
            
            # Add all pages to the writer first
            for temp_file, title, _ in pdf_temp_files:
                writer.append(temp_file)
            
            # Now, iterate through all pages in the NEW document to fix links
            for page_idx in range(len(writer.pages)):
                page_obj = writer.pages[page_idx]
                
                if "/Annots" in page_obj:
                    for annot in page_obj["/Annots"]:
                        obj = annot.get_object()
                        # Check if it's a Link (/Subtype /Link) with an External Action (/A /S /URI)
                        if obj.get("/Subtype") == "/Link" and "/A" in obj:
                            action = obj["/A"]
                            if action.get("/S") == "/URI":
                                uri = action.get("/URI")
                                clean_uri = uri.split('#')[0].rstrip('/')
                                
                                # If this URI is one of the pages we downloaded
                                if clean_uri in url_to_page_map:
                                    target_page = url_to_page_map[clean_uri]
                                    
                                    # Change the Action from URI (Web) to GoTo (Internal)
                                    new_action = DictionaryObject()
                                    new_action.update({
                                        NameObject("/S"): NameObject("/GoTo"),
                                        NameObject("/D"): ArrayObject([
                                            writer.pages[target_page].indirect_reference, 
                                            NameObject("/Fit")
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

            # Cleanup
            for f, _, _ in pdf_temp_files: os.remove(f)
            print(f"Success! {output_name} is now fully cross-referenced.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(create_linked_manual("https://en.cppreference.com/w/cpp/container", "CPP_Offline_Manual.pdf"))