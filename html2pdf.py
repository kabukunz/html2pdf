import asyncio
import os
import random
from tqdm import tqdm
from playwright.async_api import async_playwright
from PyPDF2 import PdfMerger

async def create_reference_book(base_url, output_name):
    CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    if not os.path.exists(CHROME_PATH):
        print(f"Error: Chrome not found at {CHROME_PATH}")
        return

    async with async_playwright() as p:
        print(f"--- Launching System Chrome (New Headless Mode) ---")
        
        # We explicitly pass '--headless=new' to avoid the 'Old Headless' error
        browser = await p.chromium.launch(
            headless=True,
            executable_path=CHROME_PATH,
            args=["--headless=new"] 
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await page.goto(base_url, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"Initial load failed: {e}")
            await browser.close()
            return

        # Scrape links
        links = await page.eval_on_selector_all(
            "#mw-content-text a", 
            "nodes => nodes.map(n => n.href).filter(href => href.includes('/w/cpp/'))"
        )
        unique_links = list(dict.fromkeys([l.split('#')[0] for l in links]))[:20] 
        
        pdf_files = []
        pbar = tqdm(total=len(unique_links), desc="Converting Pages", unit="pg")

        for i, url in enumerate(unique_links):
            temp_pdf = f"part_{i}.pdf"
            if i > 0:
                await asyncio.sleep(random.uniform(1.5, 3.0))

            try:
                await page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Custom CSS for C++ Reference
                await page.add_style_tag(content="""
                    #cpp-navigation, #cpp-p-search, #footer, .vector-menu { display: none !important; }
                    #content { margin-left: 0 !important; padding: 20px !important; border: none !important; }
                    body { background: white !important; }
                """)

                await page.pdf(path=temp_pdf, format="A4", print_background=True)
                pdf_files.append(temp_pdf)
            except Exception as e:
                pbar.write(f"Error on {url}: {e}")
            
            pbar.update(1)

        pbar.close()

        if pdf_files:
            print("\nMerging files...")
            merger = PdfMerger()
            for pdf in pdf_files:
                merger.append(pdf)
            merger.write(output_name)
            merger.close()
            for pdf in pdf_files:
                os.remove(pdf)
            print(f"Created: {output_name}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(create_reference_book("https://en.cppreference.com/w/cpp/container", "CPP_Manual.pdf"))