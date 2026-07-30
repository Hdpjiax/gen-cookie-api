"""
Test using Camoufox - a Firefox fork patched at binary level to bypass Akamai Bot Manager.
"""
import asyncio
import json
from urllib.parse import quote

VIVA_API_KEY = "zasqyJdSc92MhWMxYu6vW3hqhxLuDwKog3mqoYkf"


async def test(pnr: str, last_name: str):
    from camoufox.async_api import AsyncCamoufox

    captured = []

    async with AsyncCamoufox(headless=True, os="windows", humanize=True) as browser:
        page = await browser.new_page()

        async def handle_request(request):
            url = request.url
            if "api.vivaaerobus.com" in url and "booking" in url:
                print(f"  [REQ] {url[:130]}")
                hdrs = dict(request.headers)
                if "x-api-key" in hdrs:
                    print(f"    x-api-key: {hdrs['x-api-key'][:60]}")

        async def handle_response(response):
            try:
                url = response.url
                if "vivaaerobus.com" in url and response.status in [200, 401, 403]:
                    ct = response.headers.get("content-type", "")
                    if "booking" in url:
                        print(f"  [RESP {response.status} {ct[:20]}] {url[:130]}")
                    if "json" in ct and "booking" in url and response.status == 200:
                        data = await response.json()
                        captured.append({"url": url, "data": data, "status": response.status})
            except Exception:
                pass

        page.on("request", handle_request)
        page.on("response", handle_response)

        print("Camoufox: warming up with human behavior...")
        await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # Simulate human scroll
        await page.evaluate("window.scrollBy(0, 300)")
        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollBy(0, 200)")
        await page.wait_for_timeout(1000)
        await page.evaluate("window.scrollBy(0, -100)")
        await page.wait_for_timeout(2000)

        # Accept cookies
        try:
            await page.click("text='Aceptar'", timeout=2000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        deep_link = f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={quote(last_name)}"
        print(f"Navigating: {deep_link}")
        await page.goto(deep_link, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(10000)  # Wait longer for Akamai to process

        page_text = await page.evaluate("document.body.innerText")
        print(f"\nPage text preview (first 600 chars):")
        for line in page_text.split("\n"):
            line = line.strip()
            if line and len(line) > 3:
                print(f"  {line}")

        if captured:
            with open("debug_camoufox.json", "w", encoding="utf-8") as f:
                json.dump(captured, f, indent=2, ensure_ascii=False)
            print(f"\nCaptured {len(captured)} booking API responses!")

asyncio.run(test("HEYN2G", "Valverde Ponce"))
