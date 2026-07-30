import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

profile_dir = Path("browser_profiles/viva")
profile_dir.mkdir(parents=True, exist_ok=True)

async def test(pnr, last_name):
    async with async_playwright() as p:
        context = await p.firefox.launch_persistent_context(
            str(profile_dir),
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
            locale="es-MX",
            timezone_id="America/Mexico_City",
        )

        captured_api = []

        async def handle_request(request):
            url = request.url
            if "api.vivaaerobus.com" in url:
                print(f"  [REQ] {url[:120]}")
                hdrs = request.headers
                if "authorization" in hdrs:
                    print(f"    Authorization: {hdrs['authorization'][:100]}")
                if "x-api-key" in hdrs:
                    print(f"    x-api-key: {hdrs['x-api-key'][:60]}")

        async def handle_response(response):
            try:
                url = response.url
                ct = response.headers.get("content-type", "")
                if "vivaaerobus.com" in url and "json" in ct and response.status in [200, 401, 403]:
                    print(f"  [RESP {response.status}] {url[:120]}")
                    if response.status == 200:
                        data = await response.json()
                        captured_api.append({"url": url, "data": data})
            except Exception:
                pass

        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        page.on("request", handle_request)
        page.on("response", handle_response)

        deep_link = f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={last_name}"
        print(f"\nWarming up on homepage first...")
        await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        try:
            await page.click("text='Aceptar'", timeout=2000)
            await page.wait_for_timeout(1000)
        except Exception:
            pass
        print(f"Navigating: {deep_link}")
        await page.goto(deep_link, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(8000)

        page_text = await page.evaluate("document.body.innerText")
        print(f"\nPage text preview:")
        # Find relevant part
        for line in page_text.split("\n"):
            line = line.strip()
            if line and len(line) > 3:
                print(f"  {line}")

        if captured_api:
            with open("debug_viva_api.json", "w", encoding="utf-8") as f:
                json.dump(captured_api, f, indent=2, ensure_ascii=False)
            print(f"\nViva API calls captured: {len(captured_api)}")

        await context.close()

asyncio.run(test("HEYN2G", "Valverde Ponce"))
