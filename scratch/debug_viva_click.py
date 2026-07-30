import asyncio
import logging
import random
from app.connectors.stealth_browser import _random_context
from camoufox.async_api import AsyncCamoufox

logging.basicConfig(level=logging.INFO)

async def run():
    pnr = "ZI4WTQ"
    last_name = "MARQUEZ" # Ensure all uppercase
    
    cfg = _random_context()
    cfg["headless"] = True
    
    async with AsyncCamoufox(**cfg) as browser:
        page = await browser.new_page()
        
        logging.info("Warming up on homepage...")
        await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)
        
        booking_url = f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={last_name}"
        logging.info(f"Navigating to {booking_url}")
        await page.goto(booking_url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(10000)
        
        # Take initial screenshot
        await page.screenshot(path="scratch/viva_before_click.png", full_page=True)
        logging.info("Saved scratch/viva_before_click.png")
        
        btn = await page.wait_for_selector("button:has-text('Pases de abordar'), a:has-text('Pases de abordar')", timeout=10000)
        if btn:
            logging.info("Clicking the 'Pases de abordar' button...")
            await btn.click()
            await page.wait_for_timeout(4000)
            
            # Take screenshot after click
            await page.screenshot(path="scratch/viva_after_click.png", full_page=True)
            logging.info("Saved scratch/viva_after_click.png")
            
            # Print HTML and text of buttons on page after click
            content = await page.content()
            with open("scratch/viva_after_click.html", "w", encoding="utf-8") as f:
                f.write(content)
                
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            print("\n--- Buttons and links after click ---")
            for tag in soup.find_all(["button", "a", "li", "span"]):
                text = tag.get_text().strip()
                if text and any(x in text.lower() for x in ["pase", "abordar", "descargar", "imprimir", "pdf", "mail", "correo"]):
                    classes = tag.get("class")
                    print(f"Tag: <{tag.name}> | Classes: {classes} | Text: {text}")
        else:
            logging.error("Button 'Pases de abordar' not found!")

asyncio.run(run())
