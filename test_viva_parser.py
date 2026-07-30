import json
from app.connectors.live_web import LiveAirlineConnector
from app.domain.models import AirlineCode
import asyncio

async def test():
    with open("debug_camoufox.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    
    conn = LiveAirlineConnector(AirlineCode.VIVA)
    
    for jd in data:
        # Some are just list of items, assuming debug_camoufox contains a list of json responses
        if isinstance(jd, dict) and "data" in jd:
            res = conn._parse_viva_live(jd, "HEYN2G", "Valverde Ponce")
            if res:
                print(json.dumps(res, indent=2, default=str))
                return
    
    print("Failed to parse")

asyncio.run(test())
