import asyncio
from app.connectors.stealth_browser import StealthBrowserManager

async def main():
    print("Testing Aeromexico Stealth Browser for FEMDZQ / TRUJILLO")
    json_data, page_text = await StealthBrowserManager.fetch_live_booking_stealth("AEROMEXICO", "FEMDZQ", "TRUJILLO")
    
    import json
    if json_data:
        print(f"Captured {len(json_data)} JSONs!")
        from app.connectors.live_web import LiveAirlineConnector
        from app.domain.models import AirlineCode
        conn = LiveAirlineConnector(AirlineCode.AEROMEXICO)
        for jd in json_data:
            try:
                res = conn._parse_aeromexico_live(jd, "FEMDZQ", "TRUJILLO")
                if res:
                    print("SUCCESSFULLY PARSED:")
                    print(json.dumps(res, indent=2, default=str))
            except Exception as e:
                import traceback
                print("FAILED PARSING JSON snippet:")
                print(str(jd)[:200])
                traceback.print_exc()
    else:
        print("Captured 0 JSONs")

if __name__ == "__main__":
    asyncio.run(main())
