"""
Test curl_cffi to bypass Akamai TLS fingerprinting on Viva Aerobus API.
curl_cffi impersonates the exact TLS/HTTP2 fingerprint of real Chrome/Firefox.
"""
import asyncio
from curl_cffi.requests import AsyncSession

async def test_booking(pnr: str, last_name: str):
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-MX,es;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://www.vivaaerobus.com",
        "Referer": f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={last_name}",
        "sec-ch-ua": '"Google Chrome";v="137", "Chromium";v="137", "Not/A)Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }

    async with AsyncSession(impersonate="chrome136") as session:
        # First visit homepage to get cookies
        print("Warming up on homepage...")
        r = await session.get(
            "https://www.vivaaerobus.com/es-mx",
            headers={"Accept": "text/html", "Accept-Language": "es-MX,es;q=0.9"},
            timeout=30,
        )
        print(f"Homepage: {r.status_code}")

        # Now try multiple booking API endpoints
        endpoints = [
            f"https://api.vivaaerobus.com/web/vb/v1/booking/{pnr}?lastName={last_name}",
            f"https://api.vivaaerobus.com/web/v1/booking/{pnr}?lastName={last_name}",
            f"https://api.vivaaerobus.com/v1/booking/{pnr}?lastName={last_name}",
        ]
        for url in endpoints:
            print(f"\nTrying: {url}")
            try:
                r2 = await session.get(url, headers=headers, timeout=15)
                print(f"Status: {r2.status_code}")
                print(f"Content-Type: {r2.headers.get('content-type', 'N/A')}")
                print(f"Response (first 500 chars):\n{r2.text[:500]}")
            except Exception as e:
                print(f"Error: {e}")

asyncio.run(test_booking("HEYN2G", "Valverde Ponce"))
