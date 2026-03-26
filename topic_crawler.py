import asyncio
from urllib.parse import urlparse
from playwright.async_api import async_playwright

def normalize_path(url_str):
    parsed = urlparse(str(url_str))
    return parsed.path.rstrip('/')

async def analyze_topic(start_url, max_depth=1):
    # Standard path for Google Chrome on macOS
    CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    
    async with async_playwright() as p:
        # Added the fix: args=["--headless=new"]
        browser = await p.chromium.launch(
            headless=True, 
            executable_path=CHROME_PATH,
            args=["--headless=new"]
        )
        page = await browser.new_page()
        
        visited = set()
        queue = [(start_url, 0)] # (url, current_depth)

        print(f"--- Analyzing Topic Hierarchy for: {start_url} ---")
        
        while queue:
            current_url, depth = queue.pop(0)
            norm_path = normalize_path(current_url)
            
            if norm_path in visited or depth > max_depth:
                continue
            
            visited.add(norm_path)
            indent = "  " * depth
            # Print just the last part of the URL for the tree view
            print(f"{indent}📄 {norm_path.split('/')[-1] or 'root'}")

            try:
                # Use domcontentloaded for faster "dry run" scanning
                await page.goto(current_url, wait_until="domcontentloaded", timeout=30000)
                
                # Logic: Find links that share the same base path to avoid leaving the topic
                base_filter = start_url.split('.html')[0]
                links = await page.eval_on_selector_all(
                    "#mw-content-text a", 
                    f"(nodes, base) => nodes.map(n => n.href).filter(h => h.startsWith(base))",
                    base_filter
                )
                
                for link in list(dict.fromkeys(links)):
                    queue.append((link, depth + 1))
                    
            except Exception:
                continue

        print("\n--- Summary ---")
        print(f"Total Unique Pages Found: {len(visited)}")
        print(f"Estimated PDF Pages: ~{len(visited) * 2} (approximate)")
        
        await browser.close()

if __name__ == "__main__":
    # Test with Objects page
    asyncio.run(analyze_topic("https://en.cppreference.com/w/cpp/language/objects.html", max_depth=1))