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
            
            # Click 1st button
            btn1 = await page.wait_for_selector("button:has-text('Pases de abordar'), a:has-text('Pases de abordar')", timeout=15000)
            logging.info("Clicking the 1st 'Pases de abordar' button...")
            await btn1.click()
            
            # Wait for passenger card to load
            logging.info("Waiting up to 30s for .pass-available to be visible...")
            qr_btn = await page.wait_for_selector(".pass-available, .boarding-container", timeout=30000)
            logging.info("Passenger card / QR button is now visible!")
            
            await page.screenshot(path="scratch/viva_qr_visible.png", full_page=True)
            
            # Click it!
            logging.info("Clicking the QR button...")
            await qr_btn.click()
            await page.wait_for_timeout(5000)
            
            await page.screenshot(path="scratch/viva_qr_clicked.png", full_page=True)
            logging.info("Saved scratch/viva_qr_clicked.png")
            
            # Print open pages count
            logging.info(f"Open pages: {len(context.pages)}")
            
        except Exception as e:
            logging.error(f"Error: {e}")
            logging.error(traceback.format_exc())
            await page.screenshot(path="scratch/viva_qr_error.png", full_page=True)
            logging.info("Saved scratch/viva_qr_error.png")

asyncio.run(run())
