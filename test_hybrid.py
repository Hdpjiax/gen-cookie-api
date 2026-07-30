"""
Hybrid strategy: Firefox generates valid Akamai sensor cookie,
then curl_cffi uses that cookie to call the booking API directly.
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import quote
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from curl_cffi.requests import AsyncSession

VIVA_API_KEY = "zasqyJdSc92MhWMxYu6vW3hqhxLuDwKog3mqoYkf"
profile_dir = Path("browser_profiles/viva")
profile_dir.mkdir(parents=True, exist_ok=True)


async def get_akamai_cookies() -> dict:
    """Use Firefox persistent profile to generate valid Akamai sensor cookies."""
    async with async_playwright() as p:
        context = await p.firefox.launch_persistent_context(
            str(profile_dir),
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
            locale="es-MX",
            timezone_id="America/Mexico_City",
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)

        print("Firefox: visiting homepage to generate Akamai cookies...")
        await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)  # Let sensor JS run and set cookies

        # Extract all cookies
        cookies = await context.cookies()
        cookie_dict = {c["name"]: c["value"] for c in cookies if "vivaaerobus" in c.get("domain", "")}

        print(f"Extracted {len(cookie_dict)} cookies from Firefox:")
        for k, v in cookie_dict.items():
            print(f"  {k}: {v[:60]}...")

        await context.close()
        return cookie_dict


async def call_booking_api(pnr: str, last_name: str, cookies: dict):
    """Use curl_cffi with Akamai cookies to call the booking API."""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-MX,es;q=0.9,en-US;q=0.8",
        "Origin": "https://www.vivaaerobus.com",
        "Referer": f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={quote(last_name)}",
        "x-api-key": VIVA_API_KEY,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }

    url = (
        f"https://api.vivaaerobus.com/web/v1/booking/full"
        f"?pnr={pnr}&lastName={quote(last_name)}&IncludeVoucherDetails=true"
    )

    async with AsyncSession(impersonate="firefox135") as session:
        # Set the Akamai cookies from Firefox
        for name, value in cookies.items():
            session.cookies.set(name, value, domain="vivaaerobus.com")

        print(f"\ncurl_cffi: calling {url}")
        r = await session.get(url, headers=headers, timeout=30)
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")

        if r.status_code == 200:
            data = r.json()
            print(f"\nSUCCESS! Keys: {list(data.keys())}")
            with open("debug_booking_full.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("Saved to debug_booking_full.json")
        else:
            print(f"Response ({len(r.text)} bytes): {r.text[:300]}")


async def main():
    cookies = await get_akamai_cookies()
    await call_booking_api("HEYN2G", "Valverde Ponce", cookies)

asyncio.run(main())
