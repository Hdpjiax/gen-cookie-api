import asyncio
from app.connectors.stealth_browser import StealthBrowserManager

async def main():
    import logging
    logging.basicConfig(level=logging.INFO)
    print("Iniciando stealth browser...")
    json_data, page_text = await StealthBrowserManager.fetch_live_booking_stealth("VOLARIS", "LCYD6C", "Ortega")
    print(f"JSON data detectado: {bool(json_data)}")
    print(f"Page text length: {len(page_text) if page_text else 0}")
    
    if not page_text:
        print("El navegador invisible falló y no devolvió texto. (Posible falta de playwright install)")

if __name__ == "__main__":
    asyncio.run(main())
