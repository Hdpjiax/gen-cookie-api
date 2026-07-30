import asyncio
import json
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def test():
    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        await Stealth().apply_stealth_async(page)

        all_requests = []

        async def handle_response(response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct and response.status == 200:
                    url = response.url
                    # Only capture API-looking calls, not static assets
                    if any(k in url.lower() for k in ["booking", "pnr", "trip", "reservation", "passenger", "flight", "manage"]):
                        data = await response.json()
                        all_requests.append({"url": url, "data": data})
                        print(f"API JSON from: {url}")
            except Exception:
                pass

        page.on("response", handle_response)

        deep_link = "https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr=ZI4WTQ&lastName=Marquez"
        print(f"Navigating to: {deep_link}")
        await page.goto(deep_link, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(10000)  # Wait longer for all XHR to fire

        with open("debug_all_requests.json", "w", encoding="utf-8") as f:
            json.dump(all_requests, f, indent=2, ensure_ascii=False)

        print(f"\nTotal API JSON responses captured: {len(all_requests)}")
        for r in all_requests:
            print(f"  - {r['url'][:120]}")

        await browser.close()

asyncio.run(test())
