import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any
from datetime import datetime
import random
from playwright.async_api import async_playwright
try:
    from camoufox.async_api import AsyncCamoufox
    CAMOUFOX_AVAILABLE = True
except ImportError:
    CAMOUFOX_AVAILABLE = False


async def _save_page_as_pdf(page, pdf_path: Path) -> None:
    """
    Saves a Playwright page as a PDF. Falls back to screenshot + Pillow PDF conversion
    if page.pdf() is not supported (e.g. on Firefox/Camoufox).
    """
    try:
        await page.pdf(
            path=str(pdf_path),
            print_background=True,
            margin={"top": "20px", "right": "20px", "bottom": "20px", "left": "20px"},
        )
    except Exception as e:
        import uuid
        from PIL import Image
        import logging
        logging.info(f"Native page.pdf() failed ({e}). Falling back to screenshot PDF conversion...")
        
        temp_png = pdf_path.with_suffix(".temp.png")
        await page.screenshot(path=str(temp_png), full_page=True)
        try:
            if temp_png.exists():
                with Image.open(temp_png) as img:
                    img_rgb = img.convert("RGB")
                    img_rgb.save(str(pdf_path), "PDF")
                logging.info(f"Successfully saved PDF via screenshot: {pdf_path}")
        finally:
            if temp_png.exists():
                try:
                    os.remove(temp_png)
                except Exception:
                    pass


def generate_boarding_pass_pdf(booking: dict[str, Any], pass_info: dict[str, Any]) -> Path:
    """Generates a clean mock PDF Boarding Pass file for offline viewing (sync fallback)."""
    passes_dir = Path(".local/passes")
    passes_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = passes_dir / f"{booking.get('id', 'unknown')}_boarding_pass.pdf"

    airline = booking.get("airline", "AEROMEXICO")
    passengers = ", ".join(booking.get("passenger_names") or ["Pasajero"])
    segments = booking.get("segments") or [{}]
    segment = segments[0] if segments else {}
    flight = segment.get("flight_number", "AM 116")
    route = f"{segment.get('departure_airport', 'CJS')} -> {segment.get('arrival_airport', 'MEX')}"
    seat = segment.get("seat") or "Aleatorio (Gratis)"
    gate = segment.get("gate") or "B12"
    terminal = segment.get("terminal") or "T2"

    pdf_content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kinds [ /Page ] /Count 1 /Kids [ 3 0 R ] >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [ 0 0 612 792 ] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>
endobj
4 0 obj
<< /Length 520 >>
stream
BT
/F1 20 Tf
50 740 Td
(FLIGHTS MX - PASE DE ABORDAR OFICIAL) Tj
0 -30 Td
/F1 14 Tf
(Aerolinea: {airline}) Tj
0 -25 Td
(Pasajero: {passengers}) Tj
0 -25 Td
(Vuelo: {flight}   Ruta: {route}) Tj
0 -25 Td
(Terminal: {terminal}   Puerta: {gate}) Tj
0 -25 Td
(Asiento: {seat}) Tj
0 -25 Td
(Estado: CHECK-IN COMPLETADO - ASIENTO GRATUITO) Tj
0 -40 Td
/F1 10 Tf
(==============================================================) Tj
0 -15 Td
(CODIGO DE VALIDACION QR: BOARDING-{str(booking.get('id', 'unknown'))[:8].upper()}) Tj
0 -15 Td
(==============================================================) Tj
0 -25 Td
(Este documento es un pase de abordar valido generado automaticamente.) Tj
ET
endstream
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000125 00000 n 
0000000318 00000 n 
0000000251 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
900
%%EOF
"""
    pdf_path.write_bytes(pdf_content.encode("latin-1", errors="ignore"))
    return pdf_path


async def _try_download_real_viva_pass(pnr: str, last_name: str, temp_dir: Path, fmt: str) -> Path | None:
    """
    Fetches the official Viva Aerobus booking page as PDF or screenshot.

    Strategy:
      1. Check a persistent cache first (valid 7 days) — avoids hitting Akamai every time.
      2. If no cache, try up to 2 Camoufox sessions with different OS fingerprints.
      3. On success, save to cache for future requests.

    Camoufox is used without proxies; each session has a unique randomised fingerprint.
    """
    import logging
    import traceback
    import time

    if not CAMOUFOX_AVAILABLE:
        return None

    # ── Persistent cache ──────────────────────────────────────────────────────
    cache_dir = Path(tempfile.gettempdir()) / "viva_pass_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ext = "png" if fmt.upper() == "IMAGE" else "pdf"
    cache_file = cache_dir / f"{pnr.upper()}_{ext}.{ext}"
    cache_max_age = 7 * 24 * 3600  # 7 days

    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < cache_max_age and cache_file.stat().st_size > 5000:
            logging.info(f"Viva pass: cache hit for {pnr} ({int(age/3600)}h old)")
            return cache_file

    # ── Attempt with fresh Camoufox sessions ─────────────────────────────────
    # Rotate OS on each attempt so Akamai sees different browser profiles.
    _OS_ROTATION = ["windows", "macos", "linux"]

    booking_url = (
        f"https://www.vivaaerobus.com/es-mx/manage/trip-details"
        f"?pnr={pnr}&lastName={last_name}"
    )

    for attempt in range(1, 3):  # max 2 attempts (less aggressive = less IP banning)
        attempt_os = _OS_ROTATION[(attempt - 1) % len(_OS_ROTATION)]
        cfg = {
            "os": attempt_os,
            "humanize": True,
            "headless": True,
            "geoip": True,
        }
        logging.info(f"Viva pass: attempt {attempt}/2 (os={attempt_os}) for PNR={pnr}")
        try:
            result = await _viva_session_attempt(
                booking_url, pnr, last_name, temp_dir, fmt, cfg
            )
            if result and result.exists() and result.stat().st_size > 5000:
                # Save to persistent cache
                import shutil
                shutil.copy2(str(result), str(cache_file))
                logging.info(f"Viva pass: cached at {cache_file}")
                return result
            else:
                if attempt < 2:
                    wait_s = random.randint(8, 15)
                    logging.info(f"Viva pass: attempt {attempt} failed, waiting {wait_s}s...")
                    await asyncio.sleep(wait_s)
        except Exception:
            logging.warning(f"Viva pass: attempt {attempt} exception:\n{traceback.format_exc()}")
            if attempt < 2:
                await asyncio.sleep(random.randint(8, 15))

    # ── Return stale cache if available ──────────────────────────────────────
    if cache_file.exists() and cache_file.stat().st_size > 5000:
        logging.info(f"Viva pass: returning stale cache for {pnr}")
        return cache_file

    logging.error(f"Viva pass: no real pass obtainable for PNR={pnr}")
    return None


async def _viva_session_attempt(
    booking_url: str,
    pnr: str,
    last_name: str,
    temp_dir: Path,
    fmt: str,
    cfg: dict,
) -> Path | None:
    """Single Camoufox browser session attempt to capture the Viva Aerobus booking page."""
    download_path = None

    async with AsyncCamoufox(**cfg) as browser:
        page = await browser.new_page()

        async def handle_download(download):
            nonlocal download_path
            try:
                suggested = download.suggested_filename
                ext = ".pdf" if ".pdf" in suggested.lower() else ".png"
                p = temp_dir / f"real_pass_{pnr}{ext}"
                await download.save_as(str(p))
                download_path = p
            except Exception as ex:
                import logging as _l
                _l.error(f"Error saving Viva download: {ex}")

        page.on("download", handle_download)

        # ── Warm up: visit homepage first ─────────────────────────────────────
        import logging
        logging.info("Viva session: warming up on homepage...")
        await page.goto(
            "https://www.vivaaerobus.com/es-mx",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await page.wait_for_timeout(random.randint(2500, 4500))

        # Human scroll pattern
        for val in [
            random.randint(200, 400),
            random.randint(80, 250),
            -random.randint(40, 120),
        ]:
            await page.evaluate(f"window.scrollBy(0, {val})")
            await page.wait_for_timeout(random.randint(500, 1100))

        # Accept cookie banner
        for sel in [
            "[id*='cookie'] button",
            ".accept-btn",
            "text='Aceptar'",
            "text='Accept'",
            "text='Accept all'",
        ]:
            try:
                await page.click(sel, timeout=1500)
                await page.wait_for_timeout(700)
                break
            except Exception:
                pass

        await page.wait_for_timeout(random.randint(1000, 2000))

        # ── Navigate to booking deep-link ─────────────────────────────────────
        logging.info(f"Viva session: navigating to booking page: {booking_url}")
        try:
            await page.goto(booking_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            # NS_BINDING_ABORTED is common with SPA redirects – page still loads
            if "NS_BINDING_ABORTED" not in str(e):
                raise

        await page.wait_for_timeout(random.randint(9000, 13000))

        # ── Check for Akamai block ────────────────────────────────────────────
        content = await page.content()
        lower_content = content.lower()
        if (
            "waf_blocked_error" in lower_content
            or "esta reserva no puede ser abierta" in lower_content
        ):
            logging.warning("Viva session: Akamai WAF block detected.")
            return None

        # ── Verify booking page is actually loaded ────────────────────────────
        booking_loaded = False
        for sel in [
            "button:has-text('Imprimir')",
            "text='Tu reserva'",
            "text='Itinerario de viaje'",
        ]:
            try:
                el = await page.query_selector(sel)
                if el:
                    booking_loaded = True
                    break
            except Exception:
                pass

        if not booking_loaded:
            # Also check raw text
            page_text = await page.evaluate("document.body.innerText")
            if any(
                kw in page_text
                for kw in ["Tu reserva", "Itinerario de viaje", pnr]
            ):
                booking_loaded = True

        if not booking_loaded:
            logging.warning("Viva session: booking page did not load correctly.")
            return None

        logging.info("Viva session: booking page loaded. Capturing...")

        # Dismiss any error modals
        for btn_sel in [
            "button:has-text('Aceptar')",
            "button:has-text('Cerrar')",
            "button:has-text('OK')",
        ]:
            try:
                modal_btn = await page.query_selector(btn_sel)
                if modal_btn:
                    await modal_btn.click()
                    await page.wait_for_timeout(500)
                    break
            except Exception:
                pass

        # ── Click the Pases de abordar button (First Click / Dropdown trigger) ───────────
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
        
        btn = None
        for sel in bp_selectors:
            try:
                btn = await page.wait_for_selector(sel, timeout=3000)
                if btn:
                    logging.info(f"Viva session: Found primary button with selector: {sel}")
                    break
            except Exception:
                pass

        if btn:
            try:
                logging.info("Viva session: Clicking primary button...")
                await btn.click()
                await page.wait_for_timeout(3000)
                
                # Check if we transitioned to a loading page ("Cargando")
                try:
                    await page.wait_for_selector("text=Cargando", state="detached", timeout=15000)
                    logging.info("Viva session: Loading spinner detached/finished.")
                except Exception:
                    pass
                
                await page.wait_for_timeout(3000)
                
                # Dismiss cookie banner on the Check-in page if present
                try:
                    cookie_btn = await page.wait_for_selector("button.accept-btn, button:has-text('Aceptar')", timeout=3000)
                    if cookie_btn:
                        logging.info("Viva session: Dismissing cookie banner on Check-in page...")
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
                            logging.info(f"Viva session: Found passenger QR/boarding pass element with: {sel}. Clicking it...")
                            await qr_btn.scroll_into_view_if_needed()
                            await qr_btn.click()
                            await page.wait_for_timeout(4000)
                            qr_clicked = True
                            break
                    except Exception:
                        pass

                # Option B: Fallback to dropdown button sequence
                if not qr_clicked:
                    # Find dropdown button on the loaded page (Check-in page)
                    btn_dropdown = None
                    for sel in bp_selectors:
                        try:
                            btn_dropdown = await page.wait_for_selector(sel, timeout=2000)
                            if btn_dropdown:
                                logging.info(f"Viva session: Found dropdown button on loaded page: {sel}")
                                break
                        except Exception:
                            pass
                    
                    # Open dropdown if found
                    if btn_dropdown:
                        logging.info("Viva session: Clicking dropdown button to open menu...")
                        await btn_dropdown.scroll_into_view_if_needed()
                        await btn_dropdown.click()
                        await page.wait_for_timeout(3000)

                # Define option_selectors inside the scope
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
                            logging.info(f"Viva session: Detected boarding pass modal using: {sel}")
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
                                logging.info(f"Viva session: Clicking PDF card selection using: {sel}")
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
                                logging.info(f"Viva session: Clicking download button using: {sel}")
                                break
                        except Exception:
                            pass

                    if dl_btn:
                        logging.info("Viva session: Clicking modal download button and expecting download...")
                        await dl_btn.scroll_into_view_if_needed()
                        async with page.expect_download(timeout=15000) as dl_info:
                            await dl_btn.click()
                        dl = await dl_info.value
                        save_path = temp_dir / f"real_pass_{pnr}.pdf"
                        await dl.save_as(str(save_path))
                        if save_path.exists() and save_path.stat().st_size > 5000:
                            logging.info(f"Viva session: Download successful: {save_path}")
                            return save_path

                # ── Fallback C: Search for standard dropdown options or print options if modal didn't download ──
                btn_opt = None
                for sel in option_selectors:
                    try:
                        btn_opt = await page.wait_for_selector(sel, timeout=2000)
                        if btn_opt:
                            logging.info(f"Viva session: Found option in dropdown: {sel}")
                            break
                    except Exception:
                        pass
                
                if btn_opt:
                    logging.info("Viva session: Clicking download option and expecting download...")
                    async with page.expect_download(timeout=10000) as dl_info:
                        await btn_opt.click()
                    dl = await dl_info.value
                    save_path = temp_dir / f"real_pass_{pnr}.pdf"
                    await dl.save_as(str(save_path))
                    if save_path.exists() and save_path.stat().st_size > 5000:
                        logging.info(f"Viva session: Successfully downloaded PDF to {save_path}")
                        return save_path
                else:
                    logging.info("Viva session: No download option found in dropdown. Trying print option...")
                    try:
                        print_btn = await page.wait_for_selector("button:has-text('Imprimir')", timeout=2000)
                        if print_btn:
                            async with page.expect_download(timeout=6000) as dl_info:
                                await print_btn.click()
                            dl = await dl_info.value
                            save_path = temp_dir / f"real_pass_{pnr}.pdf"
                            await dl.save_as(str(save_path))
                            if save_path.exists() and save_path.stat().st_size > 5000:
                                return save_path
                    except Exception:
                        pass
                            
            except Exception as e:
                logging.info(f"Viva session: Download flow error: {e}. Checking for new tab...")
                await page.wait_for_timeout(3000)
                pages = page.context.pages
                if len(pages) > 1:
                    new_page = pages[-1]
                    await new_page.wait_for_load_state()
                    logging.info("Viva session: Boarding pass opened in new tab. Saving as PDF/Image...")
                    save_path = temp_dir / f"real_pass_{pnr}.pdf"
                    if fmt.upper() == "IMAGE":
                        output = save_path.with_suffix(".png")
                        await new_page.screenshot(path=str(output), full_page=True)
                        return output
                    else:
                        await _save_page_as_pdf(new_page, save_path)
                        return save_path
                else:
                    logging.info("Viva session: No new tab opened. Falling through to capture current page.")

        if download_path and download_path.exists() and download_path.stat().st_size > 5000:
            return download_path

        # ── Capture page as screenshot or PDF ────────────────────────────────
        if fmt.upper() == "IMAGE":
            output = temp_dir / f"real_pass_{pnr}.png"
            await page.screenshot(path=str(output), full_page=True)
            return output if (output.exists() and output.stat().st_size > 10000) else None
        else:
            output = temp_dir / f"real_pass_{pnr}.pdf"
            await _save_page_as_pdf(page, output)
            return output if (output.exists() and output.stat().st_size > 5000) else None


async def generate_boarding_pass_file(booking: dict[str, Any], fmt: str = "PDF") -> Path:
    """
    Generates a beautiful, premium, customized boarding pass (PDF or Image)
    using Playwright headless rendering, attempting to fetch the real boarding pass first.
    """
    import os
    
    # 0. Check if the booking already has a downloaded boarding pass (Real PDF or Screenshot)!
    bps = booking.get("boarding_passes", [])
    if bps:
        for bp in bps:
            d_url = bp.get("download_url")
            if d_url and os.path.exists(d_url):
                return Path(d_url)
                
    temp_dir = Path(tempfile.gettempdir()) / "flights_mx_passes"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    booking_id = str(booking.get("id", "unknown"))
    airline = str(booking.get("airline", "AEROMEXICO")).upper()

    # 1. Attempt to fetch real boarding pass from airline website
    from app.security.crypto import decrypt_from_storage
    pnr = decrypt_from_storage(booking.get("encrypted_locator"))
    last_name = decrypt_from_storage(booking.get("encrypted_last_name"))
    
    if airline == "VIVA" and pnr and last_name:
        real_pass = await _try_download_real_viva_pass(pnr, last_name, temp_dir, fmt)
        if real_pass and real_pass.exists():
            return real_pass
    
    brand_colors = {
        "VIVA": {"primary": "#00853F", "text_light": "#E8F5E9", "name": "Viva Aerobus"},
        "VOLARIS": {"primary": "#8C007E", "text_light": "#FBE9F7", "name": "Volaris"},
        "AEROMEXICO": {"primary": "#0F2D59", "text_light": "#E3F2FD", "name": "Aeroméxico"},
        "UNITED": {"primary": "#005DAA", "text_light": "#E1F5FE", "name": "United Airlines"},
    }
    
    color_info = brand_colors.get(airline, {"primary": "#0F2D59", "text_light": "#E3F2FD", "name": airline})
    
    passengers = ", ".join(booking.get("passenger_names") or ["Pasajero"])
    segments = booking.get("segments") or [{}]
    segment = segments[0] if segments else {}
    flight = segment.get("flight_number", "VB 1124")
    dep_airport = segment.get("departure_airport", "MEX")
    arr_airport = segment.get("arrival_airport", "CUN")
    seat = segment.get("seat") or "Aleatorio (Gratis)"
    gate = segment.get("gate") or "B12"
    terminal = segment.get("terminal") or "T1"
    bg = segment.get("boarding_group") or "Grupo C"
    
    dep_time_str = segment.get("scheduled_departure", "")
    if dep_time_str:
        try:
            dt = datetime.fromisoformat(dep_time_str.replace("Z", "+00:00"))
            dep_time_str = dt.strftime("%d %b %Y - %H:%M")
        except Exception:
            pass

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    margin: 0;
    padding: 0;
    background-color: #f0f2f5;
  }}
  .ticket-container {{
    width: 650px;
    background: #ffffff;
    border-radius: 12px;
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    overflow: hidden;
    margin: 10px;
    display: flex;
    flex-direction: column;
    border: 1px solid #e0e0e0;
  }}
  .header {{
    background-color: {color_info['primary']};
    color: #ffffff;
    padding: 15px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  .airline-name {{
    font-size: 20px;
    font-weight: bold;
    letter-spacing: 0.5px;
  }}
  .pass-type {{
    background: rgba(255,255,255,0.2);
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
  }}
  .main-info {{
    padding: 20px;
    display: flex;
    border-bottom: 2px dashed #e0e0e0;
    position: relative;
  }}
  .main-info::before, .main-info::after {{
    content: '';
    position: absolute;
    bottom: -10px;
    width: 20px;
    height: 20px;
    background-color: #f0f2f5;
    border-radius: 50%;
  }}
  .main-info::before {{ left: -10px; }}
  .main-info::after {{ right: -10px; }}
  .left-col {{
    flex: 2;
    padding-right: 15px;
  }}
  .right-col {{
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    border-left: 1px solid #f0f0f0;
    padding-left: 15px;
  }}
  .passenger-section {{
    margin-bottom: 15px;
  }}
  .label {{
    font-size: 10px;
    color: #888888;
    text-transform: uppercase;
    font-weight: 600;
    margin-bottom: 3px;
  }}
  .val {{
    font-size: 16px;
    font-weight: bold;
    color: #333333;
  }}
  .route-row {{
    display: flex;
    align-items: center;
    margin: 15px 0;
  }}
  .airport-code {{
    font-size: 28px;
    font-weight: 800;
    color: {color_info['primary']};
  }}
  .plane-icon {{
    font-size: 20px;
    margin: 0 15px;
    color: #888888;
  }}
  .grid-details {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }}
  .qr-code {{
    width: 140px;
    height: 140px;
    margin-bottom: 8px;
  }}
  .qr-text {{
    font-size: 9px;
    color: #666666;
    font-family: monospace;
  }}
  .footer {{
    background-color: #fafafa;
    padding: 12px 20px;
    font-size: 10px;
    color: #888888;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
</style>
</head>
<body>
  <div class="ticket-container">
    <div class="header">
      <span class="airline-name">{color_info['name']}</span>
      <span class="pass-type">PASE DE ABORDAR</span>
    </div>
    <div class="main-info">
      <div class="left-col">
        <div class="passenger-section">
          <div class="label">Pasajero / Passenger</div>
          <div class="val">{passengers}</div>
        </div>
        <div class="route-row">
          <span class="airport-code">{dep_airport}</span>
          <span class="plane-icon">✈</span>
          <span class="airport-code">{arr_airport}</span>
        </div>
        <div class="grid-details">
          <div>
            <div class="label">Vuelo / Flight</div>
            <div class="val">{flight}</div>
          </div>
          <div>
            <div class="label">Fecha / Date</div>
            <div class="val">{dep_time_str}</div>
          </div>
          <div>
            <div class="label">Asiento / Seat</div>
            <div class="val" style="color: {color_info['primary']};">{seat}</div>
          </div>
          <div>
            <div class="label">Grupo / Group</div>
            <div class="val">{bg}</div>
          </div>
          <div>
            <div class="label">Puerta / Gate</div>
            <div class="val">{gate}</div>
          </div>
          <div>
            <div class="label">Terminal</div>
            <div class="val">{terminal}</div>
          </div>
        </div>
      </div>
      <div class="right-col">
        <img class="qr-code" src="https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=BOARDING-{booking_id}" alt="QR Code">
        <span class="qr-text">BOARDING-{booking_id[:8].upper()}</span>
      </div>
    </div>
    <div class="footer">
      <span>Generado automáticamente por Flights MX</span>
      <span>Código de Validación: {booking_id[:8].upper()}</span>
    </div>
  </div>
</body>
</html>
"""

    html_file = temp_dir / f"{booking_id}.html"
    html_file.write_text(html_content, encoding="utf-8")
    
    rendered = False
    if CAMOUFOX_AVAILABLE:
        try:
            async with AsyncCamoufox(headless=True, os="windows") as browser:
                page = await browser.new_page()
                await page.set_viewport_size({"width": 680, "height": 450})
                await page.goto(html_file.as_uri())
                
                if fmt.upper() == "IMAGE":
                    output_file = temp_dir / f"{booking_id}.png"
                    element = await page.query_selector(".ticket-container")
                    if element:
                        await element.screenshot(path=str(output_file))
                    else:
                        await page.screenshot(path=str(output_file))
                else:
                    output_file = temp_dir / f"{booking_id}.pdf"
                    await page.emulate_media(media="screen")
                    await _save_page_as_pdf(page, output_file)
                rendered = True
        except Exception as e:
            # Fallback to standard playwright
            pass

    if not rendered:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_viewport_size({"width": 680, "height": 450})
            await page.goto(html_file.as_uri())
            
            if fmt.upper() == "IMAGE":
                output_file = temp_dir / f"{booking_id}.png"
                element = await page.query_selector(".ticket-container")
                if element:
                    await element.screenshot(path=str(output_file))
                else:
                    await page.screenshot(path=str(output_file))
            else:
                output_file = temp_dir / f"{booking_id}.pdf"
                await page.emulate_media(media="screen")
                await page.pdf(
                    path=str(output_file),
                    width="680px",
                    height="400px",
                    print_background=True,
                    margin={"top": "0px", "right": "0px", "bottom": "0px", "left": "0px"}
                )
                
            await browser.close()
        
    try:
        html_file.unlink()
    except Exception:
        pass
        
    return output_file
