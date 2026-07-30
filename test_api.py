import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def test():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        await Stealth().apply_stealth_async(page)
        
        print("Visiting homepage...")
        await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        print("Fetching API...")
        url = "https://api.vivaaerobus.com/v1/booking/ZI4WTQ?lastName=Marquez"
        text = await page.evaluate(f'''async () => {{
            const res = await fetch("{url}");
            return await res.text();
        }}''')
        
        with open("debug_api_fetch.txt", "w", encoding="utf-8") as f:
            f.write(text)
        await browser.close()
        print("Done. Check debug_api_fetch.txt")

asyncio.run(test())
