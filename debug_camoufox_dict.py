import traceback
from camoufox.async_api import AsyncCamoufox
import asyncio

async def test():
    try:
        async with AsyncCamoufox(headless=True, os='windows', screen={'width': 1920, 'height': 1080}) as b:
            print('ok screen')
    except Exception as e:
        traceback.print_exc()
        
    try:
        async with AsyncCamoufox(headless=True, os='windows', geolocation={'latitude': 10, 'longitude': 10}) as b:
            print('ok geo')
    except Exception as e:
        traceback.print_exc()

asyncio.run(test())
