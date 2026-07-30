import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def test():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        await Stealth().apply_stealth_async(page)

        captured_json = []

        async def handle_response(response):
            try:
                if "booking" in response.url.lower() or "trip" in response.url.lower():
                    if response.status == 200 and "json" in response.headers.get("content-type", ""):
                        data = await response.json()
                        if isinstance(data, dict):
                            captured_json.append(data)
                            print(f"Captured JSON from: {response.url}")
            except Exception:
                pass

        page.on("response", handle_response)

        deep_link = "https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr=HEYN2G&lastName=Valverde%20Ponce"
        print(f"Navigating to: {deep_link}")
        await page.goto(deep_link, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(7000)

        page_text = await page.evaluate("document.body.innerText")
        with open("debug_manage_text.txt", "w", encoding="utf-8") as f:
            f.write(page_text)

        if captured_json:
            import json
            with open("debug_manage_json.json", "w", encoding="utf-8") as f:
                json.dump(captured_json[0], f, indent=2, ensure_ascii=False)
            print(f"JSON captured! Keys: {list(captured_json[0].keys())}")
        else:
            print("No JSON captured.")

        print(f"Page text length: {len(page_text)}")
        print("First 500 chars:")
        print(page_text[:500])
        await browser.close()

asyncio.run(test())
