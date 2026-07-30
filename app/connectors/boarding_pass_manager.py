import logging
import asyncio
import os
import random
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from typing import Any

logger = logging.getLogger(__name__)


async def _save_page_as_pdf(page, pdf_path: str) -> None:
    """
    Saves a Playwright page as a PDF. Falls back to screenshot + Pillow PDF conversion
    if page.pdf() is not supported (e.g. on Firefox/Camoufox).
    """
    from pathlib import Path
    p_path = Path(pdf_path)
    try:
        await page.pdf(
            path=str(p_path),
            print_background=True,
            margin={"top": "20px", "right": "20px", "bottom": "20px", "left": "20px"},
        )
    except Exception as e:
        import uuid
        from PIL import Image
        logger.info(f"Native page.pdf() failed ({e}). Falling back to screenshot PDF conversion...")
        
        temp_png = p_path.with_suffix(".temp.png")
        await page.screenshot(path=str(temp_png), full_page=True)
        try:
            if temp_png.exists():
                with Image.open(temp_png) as img:
                    img_rgb = img.convert("RGB")
                    img_rgb.save(str(p_path), "PDF")
                logger.info(f"Successfully saved PDF via screenshot: {p_path}")
        finally:
            if temp_png.exists():
                try:
                    os.remove(temp_png)
                except Exception:
                    pass


async def download_boarding_passes(airline_code: str, pnr: str, last_name: str) -> list[dict[str, Any]] | None:
    """
    Downloads real boarding passes by automating the airline website.
    Returns a list of boarding pass data with download URLs.
    """
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        logger.error("camoufox not installed")
        return None

    logger.info(f"Downloading real boarding passes for {airline_code} {pnr}")

    attempt_os = random.choice(["windows", "macos"])
    cfg = {
        "os": attempt_os,
        "humanize": True,
        "headless": True,
        "geoip": True,
    }
    
    # Try to load residential proxy if available
    try:
        from app.connectors.stealth_browser import parse_proxy_setting
        proxy_dict = parse_proxy_setting(os.getenv("RESIDENTIAL_PROXY_URL"))
        if proxy_dict:
            cfg["proxy"] = proxy_dict
    except Exception: pass

    try:
        if airline_code == "VOLARIS":
            return await _volaris_bp_flow(cfg, pnr, last_name)
        elif airline_code == "VIVA":
            return await _viva_bp_flow(cfg, pnr, last_name)
        elif airline_code == "AEROMEXICO":
            return await _aeromexico_bp_flow(cfg, pnr, last_name)
        elif airline_code == "UNITED":
            return await _united_bp_flow(cfg, pnr, last_name)
    except Exception as e:
        logger.error(f"Error downloading boarding passes for {airline_code} {pnr}: {e}")
        
    return None

async def _save_screenshot(page, prefix: str) -> str:
    # Ensure passes dir exists
    import os
    os.makedirs("passes", exist_ok=True)
    filename = f"passes/{prefix}_{int(datetime.now().timestamp())}.png"
    await page.screenshot(path=filename, full_page=True)
    return filename

async def _volaris_bp_flow(cfg: dict, pnr: str, last_name: str) -> list[dict]:
    # We use the mobile API because Volaris web does not support showing boarding passes
    # Use MoreLogin ADB automation to open Volaris app and pull boarding pass
    from app.connectors.morelogin_mobile import MoreLoginMobileManager
    
    local_path = MoreLoginMobileManager.get_volaris_boarding_pass(pnr, last_name)
    
    if local_path:
        return [{
            "passenger_id": "P1",
            "download_url": local_path,
            "expires_at": datetime.now(UTC) + timedelta(days=1),
        }]
    
    # Fallback if MoreLogin fails or isn't running
    from camoufox.async_api import AsyncCamoufox
    
    cfg["os"] = "macos"
    async with AsyncCamoufox(**cfg) as browser:
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
            viewport={'width': 390, 'height': 844},
        )
        page = await context.new_page()
        await page.goto("https://www.volaris.com/mytrips", wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)
        
        # Accept cookies
        cookie_btn = await page.query_selector("button:has-text('Accept All'), button:has-text('Aceptar')")
        if cookie_btn:
            try:
                await cookie_btn.click()
                await page.wait_for_timeout(1000)
            except Exception: pass
            
        await page.fill('input[name="pnr"], input[formcontrolname="bookingCode"], input[placeholder*="reservación"]', pnr)
        await page.wait_for_timeout(500)
        await page.fill('input[name="lastName"], input[formcontrolname="lastName"], input[placeholder*="apellidos"]', last_name)
        
        btn = await page.query_selector('button[type="submit"]')
        if btn:
            await btn.click()
            await page.wait_for_timeout(10000)
            
        filename = await _save_screenshot(page, f"VOLARIS_{pnr}")
        return [{
            "passenger_id": "P1",
            "download_url": filename,
            "expires_at": datetime.now(UTC) + timedelta(days=1),
        }]

async def _viva_bp_flow(cfg: dict, pnr: str, last_name: str) -> list[dict]:
    from camoufox.async_api import AsyncCamoufox
    import uuid
    import os
    
    # Use stealth random context for Viva
    from app.connectors.stealth_browser import _random_context
    stealth_cfg = _random_context()
    stealth_cfg["headless"] = cfg.get("headless", True)
    
    downloaded_files = []
    
    async with AsyncCamoufox(**stealth_cfg) as browser:
        context = await browser.new_context()
        page = await context.new_page()
        
        async def on_download(download):
            path = f"boarding_passes/VIVA_{pnr}_{uuid.uuid4().hex[:8]}.pdf"
            os.makedirs("boarding_passes", exist_ok=True)
            await download.save_as(path)
            downloaded_files.append(path)
            
        context.on("download", on_download)
        
        # Navigate to homepage first to set cookies
        await page.goto("https://www.vivaaerobus.com/es-mx", wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)
        
        booking_url = f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={quote(last_name)}"
        await page.goto(booking_url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(8000)
        
        # Click download passes (First Click / Dropdown trigger)
        bp_selectors = [
            "button:has-text('Pases de abordar')",
            "a:has-text('Pases de abordar')",
            "button:has-text('Pase de abordar')",
            "a:has-text('Pase de abordar')",
            "button:has-text('Descargar pases')",
            "button:has-text('Descargar pase')",
            "a:has-text('Descargar pases')",
            "a:has-text('Descargar pase')",
        ]
        
        btn_bp = None
        for sel in bp_selectors:
            try:
                btn_bp = await page.wait_for_selector(sel, timeout=3000)
                if btn_bp:
                    logger.info(f"Viva BP flow: Clicking primary button: {sel}")
                    await btn_bp.click()
                    await page.wait_for_timeout(3000)
                    break
            except Exception:
                pass
                
        if btn_bp:
            try:
                # Wait for "Cargando" spinner to disappear
                await page.wait_for_selector("text=Cargando", state="detached", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(3000)
            
            # Dismiss cookie banner on the Check-in page if present
            try:
                cookie_btn = await page.wait_for_selector("button.accept-btn, button:has-text('Aceptar')", timeout=3000)
                if cookie_btn:
                    logger.info("Viva BP flow: Dismissing cookie banner on Check-in page...")
                    await cookie_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            # Option A: Try clicking the individual passenger QR/boarding pass link directly
            qr_clicked = False
            for sel in [".pass-available", ".boarding-container", "text=Pase de abordar"]:
                try:
                    qr_btn = await page.wait_for_selector(sel, timeout=2000)
                    if qr_btn:
                        logger.info(f"Viva BP flow: Found passenger QR/boarding pass element with: {sel}. Clicking it...")
                        await qr_btn.scroll_into_view_if_needed()
                        await qr_btn.click()
                        await page.wait_for_timeout(4000)
                        qr_clicked = True
                        break
                except Exception:
                    pass

            # Option B: Fallback to dropdown button sequence
            if not qr_clicked:
                # Find the dropdown button on Check-in page
                btn_dropdown = None
                for sel in bp_selectors:
                    try:
                        btn_dropdown = await page.wait_for_selector(sel, timeout=2000)
                        if btn_dropdown:
                            logger.info(f"Viva BP flow: Found dropdown button: {sel}")
                            await btn_dropdown.scroll_into_view_if_needed()
                            await btn_dropdown.click()
                            await page.wait_for_timeout(3000)
                            break
                    except Exception:
                        pass
                
            # ── Handle boarding pass modal if it appeared on screen ──
            modal_selectors = [
                "text=Obtén tu pase de abordar",
                "text=Obten tu pase de abordar",
                "text=Documento PDF",
                "text=Descargar mi pase"
            ]
            is_modal_open = False
            for sel in modal_selectors:
                try:
                    el = await page.wait_for_selector(sel, timeout=3000)
                    if el:
                        is_modal_open = True
                        logger.info(f"Viva BP flow: Detected boarding pass modal using: {sel}")
                        break
                except Exception:
                    pass

            if is_modal_open:
                # 1. Click "Documento PDF" card to select it
                pdf_card = None
                pdf_card_selectors = [
                    "text=Documento PDF",
                    "text=documento pdf",
                    "div:has-text('Documento PDF')",
                    "span:has-text('Documento PDF')",
                    "p:has-text('Documento PDF')"
                ]
                for sel in pdf_card_selectors:
                    try:
                        pdf_card = await page.wait_for_selector(sel, timeout=2000)
                        if pdf_card:
                            logger.info(f"Viva BP flow: Clicking PDF card selection using: {sel}")
                            await pdf_card.scroll_into_view_if_needed()
                            await pdf_card.click()
                            await page.wait_for_timeout(2000)
                            break
                    except Exception:
                        pass

                # 2. Click "Descargar mi pase" button
                dl_btn = None
                dl_btn_selectors = [
                    "button:has-text('Descargar mi pase')",
                    "button:has-text('Descargar')",
                    "text=Descargar mi pase",
                    "text=Descargar pase"
                ]
                for sel in dl_btn_selectors:
                    try:
                        dl_btn = await page.wait_for_selector(sel, timeout=2000)
                        if dl_btn:
                            logger.info(f"Viva BP flow: Clicking download button using: {sel}")
                            break
                    except Exception:
                        pass

                if dl_btn:
                    logger.info("Viva BP flow: Clicking modal download button and expecting download...")
                    await dl_btn.scroll_into_view_if_needed()
                    try:
                        async with page.expect_download(timeout=15000) as dl_info:
                            await dl_btn.click()
                        dl = await dl_info.value
                        path = f"boarding_passes/VIVA_{pnr}_{uuid.uuid4().hex[:8]}.pdf"
                        os.makedirs("boarding_passes", exist_ok=True)
                        await dl.save_as(path)
                        downloaded_files.append(path)
                        logger.info(f"Viva BP flow: Download successful: {path}")
                    except Exception as e:
                        logger.warning(f"Viva BP flow: Download trigger failed: {e}")

            # ── Fallback C: Search for standard dropdown options or print options if modal didn't download ──
            if not downloaded_files:
                btn_opt = None
                for sel in option_selectors:
                    try:
                        btn_opt = await page.wait_for_selector(sel, timeout=2000)
                        if btn_opt:
                            logger.info(f"Viva BP flow: Clicking download option: {sel}")
                            await btn_opt.click()
                            await page.wait_for_timeout(5000)
                            break
                    except Exception:
                        pass
                    
        # Check for new tab as fallback
        pages = context.pages
        if len(pages) > 1 and not downloaded_files:
            new_page = pages[-1]
            await new_page.wait_for_load_state()
            path = f"boarding_passes/VIVA_{pnr}_{uuid.uuid4().hex[:8]}.pdf"
            os.makedirs("boarding_passes", exist_ok=True)
            await _save_page_as_pdf(new_page, path)
            downloaded_files.append(path)
            
        if downloaded_files:
            return [{
                "passenger_id": "P1", # the PDF usually contains all passes
                "download_url": downloaded_files[0],
                "expires_at": datetime.now(UTC) + timedelta(days=1),
            }]
        
        # Fallback to screenshot if download didn't trigger
        filename = await _save_screenshot(page, f"VIVA_{pnr}_fallback")
        return [{
            "passenger_id": "P1",
            "download_url": filename,
            "expires_at": datetime.now(UTC) + timedelta(days=1),
        }]

async def _aeromexico_bp_flow(cfg: dict, pnr: str, last_name: str) -> list[dict]:
    from camoufox.async_api import AsyncCamoufox
    import uuid
    import os
    
    # Use stealth random context for Aeromexico
    from app.connectors.stealth_browser import _random_context
    stealth_cfg = _random_context()
    stealth_cfg["headless"] = cfg.get("headless", True)
    
    downloaded_files = []
    
    async with AsyncCamoufox(**stealth_cfg) as browser:
        page = await browser.new_page()
        
        async def on_download(download):
            path = f"boarding_passes/AEROMEXICO_{pnr}_{uuid.uuid4().hex[:8]}.pdf"
            os.makedirs("boarding_passes", exist_ok=True)
            await download.save_as(path)
            downloaded_files.append(path)
            
        page.on("download", on_download)
        
        booking_url = f"https://www.aeromexico.com/es-mx/administra-tu-viaje/trips?last-name={quote(last_name)}&pnr={pnr}"
        await page.goto(booking_url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(8000)
        
        # Click download passes
        btn_bp = await page.query_selector("button:has-text('Pase de abordar'), button:has-text('Boarding pass'), button:has-text('Descargar')")
        if btn_bp:
            await btn_bp.click()
            await page.wait_for_timeout(10000)
            
        if downloaded_files:
            return [{
                "passenger_id": "P1",
                "download_url": downloaded_files[0],
                "expires_at": datetime.now(UTC) + timedelta(days=1),
            }]
            
        filename = await _save_screenshot(page, f"AEROMEXICO_{pnr}_fallback")
        return [{
            "passenger_id": "P1",
            "download_url": filename,
            "expires_at": datetime.now(UTC) + timedelta(days=1),
        }]

async def _united_bp_flow(cfg: dict, pnr: str, last_name: str) -> list[dict]:
    from camoufox.async_api import AsyncCamoufox
    import uuid
    import os
    
    # Use stealth random context for United
    from app.connectors.stealth_browser import _random_context
    stealth_cfg = _random_context()
    stealth_cfg["headless"] = cfg.get("headless", True)
    
    downloaded_files = []
    
    async with AsyncCamoufox(**stealth_cfg) as browser:
        page = await browser.new_page()
        
        async def on_download(download):
            path = f"boarding_passes/UNITED_{pnr}_{uuid.uuid4().hex[:8]}.pdf"
            os.makedirs("boarding_passes", exist_ok=True)
            await download.save_as(path)
            downloaded_files.append(path)
            
        page.on("download", on_download)
        
        await page.goto("https://www.united.com/en/mx/manageres/mytrips", wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(4000)
        
        last_name_nospace = last_name.replace(" ", "").upper()
        
        inp1 = await page.query_selector("input[name*='confirmation']")
        if inp1: await inp1.fill(pnr)
        inp2 = await page.query_selector("input[name*='lastName']")
        if inp2: 
            await inp2.fill(last_name_nospace)
            await page.wait_for_timeout(500)
            await inp2.press("Enter")
            
        await page.wait_for_timeout(15000) # give more time for United to load
        
        # Click download passes
        btn_bp = await page.query_selector("button:has-text('Boarding pass'), button:has-text('Pase de abordar'), button:has-text('Print'), button:has-text('Download')")
        if btn_bp:
            await btn_bp.click()
            await page.wait_for_timeout(10000)
            
        if downloaded_files:
            return [{
                "passenger_id": "P1",
                "download_url": downloaded_files[0],
                "expires_at": datetime.now(UTC) + timedelta(days=1),
            }]
            
        filename = await _save_screenshot(page, f"UNITED_{pnr}_fallback")
        return [{
            "passenger_id": "P1",
            "download_url": filename,
            "expires_at": datetime.now(UTC) + timedelta(days=1),
        }]
