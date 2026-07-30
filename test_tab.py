import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def test():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        await Stealth().apply_stealth_async(page)
        
        await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        
        print("Clicking tab...")
        try:
            await page.click("text='Mi reserva'", force=True)
            await page.wait_for_timeout(2000)
        except Exception as e:
            print("Tab click failed:", e)
            
        html = await page.content()
        with open("tab.html", "w", encoding="utf-8") as f:
            f.write(html)
        await browser.close()

asyncio.run(test())
