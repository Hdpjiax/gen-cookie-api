import asyncio
import os
from app.connectors.stealth_browser import StealthBrowserManager

async def test():
    print("Testing Volaris Stealth Browser for IFS2JW / Ramirez")
    from app.connectors.stealth_browser import StealthBrowserManager
    json_data, page_text = await StealthBrowserManager.fetch_live_booking_stealth("VOLARIS", "IFS2JW", "Ramirez")
    
    if json_data:
        print(f"Captured {len(json_data)} JSONs!")
        from app.connectors.live_web import LiveAirlineConnector
        from app.domain.models import AirlineCode
        conn = LiveAirlineConnector(AirlineCode.VOLARIS)
        for jd in json_data:
            try:
                res = conn._parse_volaris_live(jd, "IFS2JW", "Ramirez")
                if res:
                    print("SUCCESSFULLY PARSED:")
                    import json
                    print(json.dumps(res, indent=2, default=str))
            except Exception as e:
                import traceback
                print("FAILED PARSING JSON snippet:")
                print(str(jd)[:200])
                traceback.print_exc()
    else:
        print("Captured 0 JSONs")

asyncio.run(test())
