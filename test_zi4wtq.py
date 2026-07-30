import asyncio
from app.connectors.stealth_browser import StealthBrowserManager

async def test():
    print("Testing ZI4WTQ / Marquez")
    json_data, page_text = await StealthBrowserManager.fetch_live_booking_stealth("VIVA", "ZI4WTQ", "Marquez")
    
    if json_data:
        print(f"Captured {len(json_data)} JSONs")
    else:
        print("Captured 0 JSONs")
        
    print(f"\nPage text (first 1000 chars):\n{page_text[:1000]}")

asyncio.run(test())
