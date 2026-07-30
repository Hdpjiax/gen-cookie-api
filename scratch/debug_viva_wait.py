import asyncio
import logging
import os
from app.connectors.stealth_browser import _random_context
from camoufox.async_api import AsyncCamoufox

logging.basicConfig(level=logging.INFO)

async def run():
    pnr = "ZI4WTQ"
    last_name = "MARQUEZ"
    
    cfg = _random_context()
    cfg["headless"] = True
    
    async with AsyncCamoufox(**cfg) as browser:
        page = await browser.new_page()
        
        logging.info("Warming up...")
        await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)
        
        booking_url = f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={last_name}"
        logging.info(f"Navigating to {booking_url}")
        await page.goto(booking_url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(8000)
        
        btn = await page.wait_for_selector("button:has-text('Pases de abordar'), a:has-text('Pases de abordar')", timeout=10000)
        if btn:
            logging.info("Clicking the 'Pases de abordar' button...")
            await btn.click()
            
            # Wait for "Cargando" to disappear, or just wait 15 seconds
            logging.info("Waiting 15 seconds for passes page to fully load...")
            for i in range(1, 6):
                await page.wait_for_timeout(3000)
                await page.screenshot(path=f"scratch/viva_load_step_{i}.png", full_page=True)
                logging.info(f"Saved scratch/viva_load_step_{i}.png")
                
            content = await page.content()
            with open("scratch/viva_loaded.html", "w", encoding="utf-8") as f:
                f.write(content)
                
            # List all buttons/links on the final page
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            print("\n--- Buttons and links after load ---")
            for tag in soup.find_all(["button", "a", "li", "span"]):
                text = tag.get_text().strip()
                if text:
                    classes = tag.get("class")
                    print(f"Tag: <{tag.name}> | Classes: {classes} | Text: {text[:60]}")
        else:
            logging.error("Button 'Pases de abordar' not found!")

asyncio.run(run())
