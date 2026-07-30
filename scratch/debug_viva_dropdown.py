import asyncio
import logging
import os
import traceback
from dotenv import load_dotenv
load_dotenv()

from app.connectors.stealth_browser import _random_context, parse_proxy_setting
from camoufox.async_api import AsyncCamoufox

logging.basicConfig(level=logging.INFO)

async def run():
    pnr = "ZI4WTQ"
    last_name = "MARQUEZ"
    
    cfg = _random_context()
    cfg["headless"] = True
    
    # Load residential proxy
    proxy_dict = parse_proxy_setting(os.getenv("RESIDENTIAL_PROXY_URL"))
    if proxy_dict:
        cfg["proxy"] = proxy_dict
        logging.info("Using residential proxy.")
    
    async with AsyncCamoufox(**cfg) as browser:
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            logging.info("Warming up...")
            await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(3000)
            
            booking_url = f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={last_name}"
            logging.info(f"Navigating to {booking_url}")
            await page.goto(booking_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(10000)
            
            # Click 1st button on Manage Trip page
            btn1 = await page.wait_for_selector("button:has-text('Pases de abordar'), a:has-text('Pases de abordar')", timeout=15000)
            logging.info("Clicking the 1st 'Pases de abordar' button...")
            await btn1.click()
            
            # Wait for Check-in page to load
            logging.info("Waiting for Check-in page...")
            await page.wait_for_timeout(8000)
            try:
                await page.wait_for_selector("text=Cargando", state="detached", timeout=20000)
                logging.info("Loading spinner detached.")
            except Exception: pass
            await page.wait_for_timeout(3000)
            
            # Find the 2nd button (dropdown)
            btn2 = await page.wait_for_selector("button:has-text('Pases de abordar'), a:has-text('Pases de abordar')", timeout=10000)
            logging.info("Clicking 2nd button to open dropdown...")
            await btn2.click()
            await page.wait_for_timeout(3000)
            
            # Take screenshot of the open dropdown
            await page.screenshot(path="scratch/dropdown_opened.png", full_page=True)
            logging.info("Saved scratch/dropdown_opened.png")
            
            # Dump all elements on page while dropdown is open
            content = await page.content()
            with open("scratch/dropdown_opened.html", "w", encoding="utf-8") as f:
                f.write(content)
                
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")
            print("\n--- All elements containing text while dropdown is open ---")
            for tag in soup.find_all(True):
                # Only check direct text to avoid repeating parent/child text
                text = "".join([t for t in tag.contents if isinstance(t, str)]).strip()
                if text and len(text) > 1:
                    print(f"<{tag.name}> [classes={tag.get('class')}, id={tag.get('id')}]: {text}")
            
        except Exception as e:
            logging.error(f"Error: {e}")
            await page.screenshot(path="scratch/dropdown_error.png", full_page=True)
            logging.info("Saved scratch/dropdown_error.png")

asyncio.run(run())
