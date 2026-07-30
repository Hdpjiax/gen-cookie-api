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
        
        downloaded_files = []
        async def on_download(download):
            path = f"scratch/test_passes/VIVA_MODAL_{pnr}.pdf"
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
            
            # Click 1st button
            btn1 = await page.wait_for_selector("button:has-text('Pases de abordar'), a:has-text('Pases de abordar')", timeout=15000)
            logging.info("Clicking the 1st 'Pases de abordar' button...")
            await btn1.click()
            
            # Wait for Check-in page
            logging.info("Waiting for Check-in page...")
            await page.wait_for_timeout(8000)
            try:
                await page.wait_for_selector("text=Cargando", state="detached", timeout=20000)
                logging.info("Loading spinner detached.")
            except Exception: pass
            await page.wait_for_timeout(3000)
            
            # Dismiss cookie banner
            try:
                cookie_btn = await page.wait_for_selector("button.accept-btn, button:has-text('Aceptar')", timeout=3000)
                if cookie_btn:
                    logging.info("Dismissing cookie banner...")
                    await cookie_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception: pass
            
            # Try to trigger the modal (we can click the dropdown button or the passenger card qr button)
            triggered = False
            for sel in ["button:has-text('Pases de abordar')", ".pass-available", ".boarding-container"]:
                try:
                    btn = await page.wait_for_selector(sel, timeout=3000)
                    if btn:
                        logging.info(f"Clicking selector to trigger modal: {sel}")
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        await page.wait_for_timeout(4000)
                        triggered = True
                        break
                except Exception:
                    pass
            
            if triggered:
                await page.screenshot(path="scratch/modal_open_attempt.png", full_page=True)
                logging.info("Saved scratch/modal_open_attempt.png")
                
                # Check if "Documento PDF" exists and click it
                try:
                    pdf_card = await page.wait_for_selector("text=Documento PDF, text=documento pdf", timeout=5000)
                    if pdf_card:
                        logging.info("Found 'Documento PDF' option. Clicking it...")
                        await pdf_card.scroll_into_view_if_needed()
                        await pdf_card.click()
                        await page.wait_for_timeout(2000)
                        
                        await page.screenshot(path="scratch/modal_pdf_selected.png", full_page=True)
                        logging.info("Saved scratch/modal_pdf_selected.png")
                        
                        # Click "Descargar mi pase" and expect download
                        download_btn = await page.wait_for_selector("button:has-text('Descargar mi pase'), text=Descargar mi pase", timeout=5000)
                        if download_btn:
                            logging.info("Found 'Descargar mi pase' button. Clicking it and expecting download...")
                            await download_btn.scroll_into_view_if_needed()
                            
                            async with page.expect_download(timeout=12000) as dl_info:
                                await download_btn.click()
                            dl = await dl_info.value
                            logging.info("Download completed successfully!")
                        else:
                            logging.error("'Descargar mi pase' button not found!")
                    else:
                        logging.error("'Documento PDF' option not found in modal!")
                except Exception as ex:
                    logging.error(f"Failed inside modal interaction: {ex}")
                    logging.error(traceback.format_exc())
            else:
                logging.error("Failed to trigger boarding pass modal.")
                
            await page.screenshot(path="scratch/modal_final_state.png", full_page=True)
            logging.info("Saved scratch/modal_final_state.png")
            
        except Exception as e:
            logging.error(f"Error: {e}")
            logging.error(traceback.format_exc())

asyncio.run(run())
