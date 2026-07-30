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
        logging.info("Using residential proxy for debug session.")
    
    async with AsyncCamoufox(**cfg) as browser:
        context = await browser.new_context()
        page = await context.new_page()
        
        downloaded_files = []
        async def on_download(download):
            path = f"scratch/test_passes/VIVA_{pnr}.pdf"
            os.makedirs("scratch/test_passes", exist_ok=True)
            await download.save_as(path)
            logging.info(f"DOWNLOAD TRIGGERED: Saved to {path}")
            downloaded_files.append(path)
            
        context.on("download", on_download)
        
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
            
            # Wait for Check-in page to load and second button to be visible
            logging.info("Waiting for Check-in page to load...")
            await page.wait_for_timeout(8000)
            
            # Dismiss any "Cargando" state
            try:
                await page.wait_for_selector("text=Cargando", state="detached", timeout=20000)
                logging.info("Spinner 'Cargando' has disappeared.")
            except Exception:
                logging.info("No spinner 'Cargando' detected or timeout waiting for it to detach.")
            
            await page.screenshot(path="scratch/viva_double_1.png", full_page=True)
            logging.info("Saved scratch/viva_double_1.png")
            
            # Find the second button on the Check-in page
            btn2 = await page.wait_for_selector("button:has-text('Pases de abordar'), a:has-text('Pases de abordar')", timeout=10000)
            logging.info("Clicking the 2nd 'Pases de abordar' button (dropdown)...")
            await btn2.click()
            await page.wait_for_timeout(3000)
            
            await page.screenshot(path="scratch/viva_double_2.png", full_page=True)
            logging.info("Saved scratch/viva_double_2.png")
            
            # Now search for dropdown options like "Descargar", "PDF", "Imprimir"
            logging.info("Searching for dropdown menu options...")
            option_selectors = [
                "button:has-text('Descargar pases')",
                "button:has-text('Descargar pase')",
                "button:has-text('Descargar PDF')",
                "button:has-text('Descargar')",
                "a:has-text('Descargar pases')",
                "a:has-text('Descargar pase')",
                "a:has-text('Descargar PDF')",
                "a:has-text('Descargar')",
                "span:has-text('Descargar')",
                "span:has-text('PDF')",
                "text=Descargar",
                "text=PDF"
            ]
            
            btn_opt = None
            for sel in option_selectors:
                try:
                    btn_opt = await page.wait_for_selector(sel, timeout=3000)
                    if btn_opt:
                        logging.info(f"Found option button/link with selector: {sel}")
                        break
                except Exception:
                    pass
            
            if btn_opt:
                logging.info("Clicking the download option button...")
                await btn_opt.click()
                await page.wait_for_timeout(6000)
            else:
                logging.warning("No download option found in the dropdown!")
                
            await page.screenshot(path="scratch/viva_double_3.png", full_page=True)
            logging.info("Saved scratch/viva_double_3.png")
            
            # Check for new tabs
            pages = context.pages
            logging.info(f"Total open pages: {len(pages)}")
            if len(pages) > 1:
                new_page = pages[-1]
                await new_page.wait_for_load_state()
                await new_page.screenshot(path="scratch/viva_double_new_tab.png", full_page=True)
                logging.info("Saved scratch/viva_double_new_tab.png")
                
                title = await new_page.title()
                logging.info(f"New page title: {title}")
            
            # Save final page HTML
            content = await page.content()
            with open("scratch/viva_double_final.html", "w", encoding="utf-8") as f:
                f.write(content)
                
            logging.info(f"Final downloads count: {len(downloaded_files)}")
            
        except Exception as e:
            logging.error(f"Error occurred: {e}")
            logging.error(traceback.format_exc())
            await page.screenshot(path="scratch/viva_double_error.png", full_page=True)
            logging.info("Saved scratch/viva_double_error.png")

asyncio.run(run())
