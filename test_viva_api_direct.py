"""
Direct call to Viva Aerobus booking API using curl_cffi (bypasses TLS fingerprinting)
with the discovered x-api-key.
"""
import asyncio
import json
from urllib.parse import quote
from curl_cffi.requests import AsyncSession

VIVA_API_KEY = "zasqyJdSc92MhWMxYu6vW3hqhxLuDwKog3mqoYkf"

async def test_booking_api(pnr: str, last_name: str):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://www.vivaaerobus.com",
        "Referer": f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={last_name}",
        "x-api-key": VIVA_API_KEY,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }

    async with AsyncSession(impersonate="chrome136") as session:
        # Warm up with homepage first to get cookies
        print("Warming up on homepage...")
        await session.get(
            "https://www.vivaaerobus.com/es-mx",
            headers={"Accept": "text/html", "Accept-Language": "es-MX,es;q=0.9"},
            timeout=30,
        )

        # Try the exact endpoint the frontend uses
        url = (
            f"https://api.vivaaerobus.com/web/v1/booking/full"
            f"?pnr={pnr}&lastName={quote(last_name)}&IncludeVoucherDetails=true"
        )
        print(f"\nCalling: {url}")
        r = await session.get(url, headers=headers, timeout=30)
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")

        if r.status_code == 200:
            data = r.json()
            print(f"\n✅ SUCCESS! Keys: {list(data.keys())}")
            with open("debug_booking_full.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("Saved to debug_booking_full.json")
        else:
            print(f"Response: {r.text[:300]}")

asyncio.run(test_booking_api("HEYN2G", "Valverde Ponce"))
