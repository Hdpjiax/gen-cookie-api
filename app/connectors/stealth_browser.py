"""
Stealth Browser Manager - Anti-fingerprinting browser automation.

Strategy per airline:
  VIVA      → Camoufox (Firefox patched at binary level) + humanize=True + deep link
  VOLARIS   → Camoufox + deep link (Akamai lite protection)
  AEROMEXICO→ Camoufox + deep link (lighter bot protection)
  UNITED    → Camoufox + deep link (lighter bot protection)

Each invocation uses a FRESH session with a RANDOMIZED fingerprint (OS, screen, locale,
timezone, etc.) — no persistent profiles. This prevents Akamai/DataDome from correlating
different users' lookups and keeps every request stateless.
"""
import logging
import os
import random
from typing import Any
from urllib.parse import quote


# ── Randomisation pools ───────────────────────────────────────────────────────

_OS_POOL = ["windows", "macos", "linux"]

# (latitude, longitude, timezone_id, locale)
_LOCATIONS = [
    (19.4326, -99.1332, "America/Mexico_City", "es-MX"),
    (20.9674, -89.5926, "America/Merida",      "es-MX"),
    (25.6866, -100.3161, "America/Monterrey",  "es-MX"),
    (20.6597, -103.3496, "America/Guadalajara","es-MX"),
]

_SCREEN_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
]


def _random_context() -> dict[str, Any]:
    """Generate a randomised Camoufox launch config for a single session."""
    return {
        "os": "windows",    # Lock to Windows to match host and avoid Akamai WebGL/font mismatch detection
        "humanize": True,   # Adds realistic delays, mouse movements, scroll patterns
        "headless": True,
        "geoip": True,      # Automatically set timezone and geolocation based on proxy IP (or local IP)
    }


def parse_proxy_setting(proxy_str: str | None) -> dict[str, str] | None:
    if not proxy_str:
        return None

    clean = proxy_str.strip()
    for prefix in ("geolocation://", "http://", "https://"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            break

    parts = clean.split("@")
    if len(parts) == 2:
        user_pass = parts[0]
        host_port_region = parts[1]
        up_split = user_pass.split(":")
        username = up_split[0] if len(up_split) > 0 else ""
        password = up_split[1] if len(up_split) > 1 else ""
        hp_split = host_port_region.split(":")
        host = hp_split[0]
        port = hp_split[1] if len(hp_split) > 1 else "10080"
        return {"server": f"http://{host}:{port}", "username": username, "password": password}

    return {"server": f"http://{clean}"}


# ── Per-airline deep-link configurations ─────────────────────────────────────

def _viva_url(pnr: str, last_name: str) -> tuple[str, str]:
    """Returns (warmup_url, booking_url) for Viva Aerobus."""
    warmup = "https://www.vivaaerobus.com/es-mx"
    booking = f"https://www.vivaaerobus.com/es-mx/manage/trip-details?pnr={pnr}&lastName={quote(last_name)}"
    return warmup, booking


def _volaris_url(pnr: str, last_name: str) -> tuple[str, str]:
    """Returns (warmup_url, booking_url) for Volaris."""
    warmup = "https://www.volaris.com"
    booking = "https://www.volaris.com/mytrips"
    return warmup, booking


def _aeromexico_url(pnr: str, last_name: str) -> tuple[str, str]:
    """Returns (warmup_url, booking_url) for Aeromexico."""
    warmup = "https://www.aeromexico.com/es-mx/administra-tu-viaje"
    booking = f"https://www.aeromexico.com/es-mx/administra-tu-viaje/trips?last-name={quote(last_name)}&pnr={pnr}"
    return warmup, booking


def _united_url(pnr: str, last_name: str) -> tuple[str, str]:
    """Returns (warmup_url, booking_url) for United Airlines."""
    warmup = "https://www.united.com/en/mx"
    booking = "https://www.united.com/en/mx/manageres/mytrips"
    return warmup, booking


_AIRLINE_URLS = {
    "VIVA":      _viva_url,
    "VOLARIS":   _volaris_url,
    "AEROMEXICO": _aeromexico_url,
    "UNITED":    _united_url,
}


# ── Dedicated United Airlines session ────────────────────────────────────────

async def _united_camoufox_session(
    pnr: str, last_name: str
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Dedicated Camoufox session for United Airlines.

    Flow:
      1. Warm up on united.com/en/mx (builds trust cookies).
      2. Navigate to /en/mx/manageres/mytrips (the MR lookup form).
      3. Fill PNR and last name — United strips spaces from multi-word surnames
         e.g. "NUNEZ CASTRO" → "NUNEZCASTRO".
      4. Submit form and wait for redirect to /en/mx/manageres/tripdetails.
      5. Intercept the booking API JSON response and return it + page text.
    """
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        logging.warning("camoufox not installed")
        return None, None

    # United strips spaces from compound last names
    last_name_nospace = last_name.replace(" ", "").upper()

    # Rotate OS fingerprint to avoid bot detection
    attempt_os = random.choice(["windows", "macos"])
    cfg = {
        "os": attempt_os,
        "humanize": True,
        "headless": True,
        "geoip": True,
    }

    logging.info(f"United Camoufox session | os={attempt_os} | PNR={pnr} | name={last_name_nospace}")

    try:
        captured_json: list[dict[str, Any]] = []

        async with AsyncCamoufox(**cfg) as browser:
            page = await browser.new_page()

            # Intercept United booking API responses
            async def handle_response(response):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" not in ct:
                        return
                    url_lower = response.url.lower()
                    if any(kw in url_lower for kw in [
                        "managereservation", "tripdetails", "retrieve",
                        "pnr", "booking", "reservation", "lookup", "mytrips"
                    ]):
                        data = await response.json()
                        if isinstance(data, dict):
                            captured_json.append(data)
                            logging.info(f"United: captured JSON from {response.url[:120]}")
                except Exception:
                    pass

            page.on("response", handle_response)

            # ── Step 1: Warm up on MX homepage ───────────────────────────────
            logging.info("United: warming up on /en/mx...")
            await page.goto(
                "https://www.united.com/en/mx",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(random.randint(2500, 4000))

            # Human scroll
            for val in [random.randint(150, 350), random.randint(80, 200), -random.randint(40, 100)]:
                await page.evaluate(f"window.scrollBy(0, {val})")
                await page.wait_for_timeout(random.randint(500, 1000))

            # Accept cookie/consent banner
            for sel in [
                "button[id*='accept']",
                "button:has-text('Accept')",
                "button:has-text('Aceptar')",
                "[class*='cookie'] button",
            ]:
                try:
                    await page.click(sel, timeout=1500)
                    await page.wait_for_timeout(600)
                    break
                except Exception:
                    pass

            await page.wait_for_timeout(random.randint(1000, 2000))

            # ── Step 2: Navigate to My Trips form ────────────────────────────
            logging.info("United: navigating to mytrips form...")
            try:
                await page.goto(
                    "https://www.united.com/en/mx/manageres/mytrips",
                    wait_until="domcontentloaded",
                    timeout=35000,
                )
            except Exception as e:
                if "NS_BINDING_ABORTED" not in str(e):
                    raise
            await page.wait_for_timeout(random.randint(3000, 5000))

            # ── Step 3: Fill PNR field ────────────────────────────────────────
            pnr_filled = False
            for sel in [
                "input[name*='confirmation']",
                "input[name*='Confirmation']",
                "input[id*='reservationNumber']",
                "input[name*='reservationNumber']",
                "input[placeholder*='Confirmation']",
                "input[placeholder*='confirmation']",
                "input[aria-label*='Confirmation']",
                "input[aria-label*='confirmation']",
                "input[id*='confirmation']",
                "input[id*='pnr']",
                "input[name*='pnr']",
            ]:
                try:
                    inp = await page.wait_for_selector(sel, timeout=3000)
                    if inp:
                        await inp.click()
                        await page.wait_for_timeout(300)
                        await inp.fill(pnr)
                        pnr_filled = True
                        logging.info(f"United: PNR filled with {sel}")
                        break
                except Exception:
                    pass

            # ── Step 4: Fill last name (no spaces) ───────────────────────────
            ln_filled = False
            for sel in [
                "input[id*='lastName']",
                "input[name*='lastName']",
                "input[placeholder*='Last']",
                "input[placeholder*='last']",
                "input[aria-label*='Last name']",
                "input[aria-label*='Apellido']",
                "input[id*='last']",
                "input[name*='last']",
            ]:
                try:
                    inp = await page.wait_for_selector(sel, timeout=3000)
                    if inp:
                        await inp.click()
                        await page.wait_for_timeout(300)
                        await inp.fill(last_name_nospace)
                        await page.wait_for_timeout(500)
                        await inp.press("Enter")
                        ln_filled = True
                        logging.info(f"United: last name '{last_name_nospace}' filled and submitted with {sel}")
                        break
                except Exception:
                    pass

            if not pnr_filled or not ln_filled:
                logging.warning(f"United: could not fill form (pnr={pnr_filled}, ln={ln_filled})")
                page_text = await page.evaluate("document.body.innerText")
                return None, page_text

            # ── Step 5: Submit and wait for tripdetails ───────────────────────
            # Skipped click because we already pressed Enter in the last name field.
            # Wait for redirect to tripdetails
            logging.info("United: waiting for tripdetails page...")
            try:
                await page.wait_for_url(
                    "**/manageres/tripdetails**",
                    timeout=20000,
                )
            except Exception:
                # Fallback to waiting for a few seconds if the url rule doesn't match perfectly
                await page.wait_for_timeout(5000)
            await page.wait_for_timeout(random.randint(6000, 9000))

            page_text = await page.evaluate("document.body.innerText")

            if captured_json:
                return captured_json, page_text
            return None, page_text

    except Exception as e:
        logging.error(f"United Camoufox session error: {e}")
        return None, None


# ── Core browser session ──────────────────────────────────────────────────────

async def _camoufox_session(
    warmup_url: str,
    booking_url: str,
    booking_keywords: list[str],
    proxy_dict: dict | None = None,
    pnr: str | None = None,
    last_name: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Generic Camoufox session:
      1. Fresh randomised fingerprint (no persistent profile).
      2. Visit warmup URL to generate trust signals.
      3. Human-like scroll on warmup page.
      4. Navigate to booking deep link.
      5. Return (first captured JSON dict, full page text).
    """
    try:
        from camoufox.async_api import AsyncCamoufox
    except ImportError:
        logging.warning("camoufox not installed. Run: pip install camoufox && python -m camoufox fetch")
        return None, None

    cfg = _random_context()
    if proxy_dict:
        cfg["proxy"] = proxy_dict

    logging.info(f"Camoufox session | os={cfg.get('os')}")

    try:
        captured_json: list[dict[str, Any]] = []

        async with AsyncCamoufox(**cfg) as browser:
            page = await browser.new_page()

            async def handle_response(response):
                try:
                    if "json" in response.headers.get("content-type", ""):
                        url_lower = response.url.lower()
                        if "contentful" in url_lower or "lottie" in url_lower:
                            return
                        if any(kw in url_lower for kw in booking_keywords):
                            data = await response.json()
                            if isinstance(data, dict):
                                captured_json.append(data)
                                logging.info(f"Camoufox captured JSON from: {response.url[:100]} (Status: {response.status})")
                except Exception:
                    pass

            page.on("response", handle_response)

            # ── Warmup visit ──────────────────────────────────────────────────
            logging.info(f"Camoufox warmup: {warmup_url}")
            await page.goto(warmup_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(random.randint(2500, 4000))

            # Human-like scroll
            scroll_amt = random.randint(200, 500)
            await page.evaluate(f"window.scrollBy(0, {scroll_amt})")
            await page.wait_for_timeout(random.randint(800, 1500))
            await page.evaluate(f"window.scrollBy(0, {random.randint(100, 300)})")
            await page.wait_for_timeout(random.randint(600, 1200))
            await page.evaluate(f"window.scrollBy(0, -{random.randint(50, 150)})")
            await page.wait_for_timeout(random.randint(1000, 2000))

            # Accept cookie banners
            for selector in ["text='Aceptar'", "text='Accept'", "text='Accept all'", "[id*='cookie'] button", ".accept-btn"]:
                try:
                    await page.click(selector, timeout=1500)
                    await page.wait_for_timeout(800)
                    break
                except Exception:
                    pass

            # ── Navigate to booking deep link ─────────────────────────────────
            logging.info(f"Camoufox booking: {booking_url}")
            await page.goto(booking_url, wait_until="domcontentloaded", timeout=35000)
            await page.wait_for_timeout(random.randint(5000, 8000))

            # ── Form filling fallback (Volaris / Aeromexico / United) ─────────
            if pnr and last_name:
                try:
                    pnr_selector = "input[formcontrolname*='reservation'], input[name*='pnr'], input[name*='code'], input[id*='pnr'], input[placeholder*='PNR'], input[placeholder*='código'], input[aria-label*='código']"
                    pnr_input = await page.wait_for_selector(pnr_selector, timeout=8000)
                    if pnr_input:
                        await pnr_input.fill(pnr)
                        await page.wait_for_timeout(500)
                        
                    last_selector = "input[formcontrolname*='last'], input[name*='last'], input[id*='last'], input[placeholder*='apellido'], input[placeholder*='Last'], input[aria-label*='apellido']"
                    last_input = await page.wait_for_selector(last_selector, timeout=3000)
                    if last_input:
                        await last_input.fill(last_name)
                        await page.wait_for_timeout(500)
                        
                    btn_selector = "button[type='submit'], button:has-text('Buscar'), button:has-text('Find'), button:has-text('Go to my trip'), button:has-text('Ir a mi viaje'), button:has-text('Ir a mi reserva')"
                    submit_btn = await page.wait_for_selector(btn_selector, timeout=5000)
                    if submit_btn and pnr_input and last_input:
                        logging.info("Camoufox: Found booking form, filling and submitting...")
                        await submit_btn.click()
                        await page.wait_for_timeout(random.randint(8000, 12000))
                except Exception as e:
                    logging.info(f"Camoufox form fallback note (this is normal for deep links): {e}")

            # Give single page apps extra time to render after form submit or deep link
            await page.wait_for_timeout(3000)

            page_text = await page.evaluate("document.body.innerText")

            if captured_json:
                return captured_json, page_text
            return None, page_text

    except Exception as e:
        logging.info(f"Camoufox session error: {e}")
        return None, None


# ── Public API ────────────────────────────────────────────────────────────────

class StealthBrowserManager:
    """Manages fresh, stateless Camoufox browser sessions with randomised anti-fingerprinting."""

    # Keywords used to identify booking API responses for each airline
    _CAPTURE_KEYWORDS: dict[str, list[str]] = {
        "VIVA":       ["booking", "basket", "passenger"],
        "VOLARIS":    ["booking", "reservation", "retrieve", "itinerary"],
        "AEROMEXICO": ["booking", "reservation", "pnr", "retrieve"],
        "UNITED":     ["booking", "reservation", "trip", "pnr"],
    }

    @staticmethod
    async def fetch_airline_page_stealth(url: str, pnr: str, last_name: str) -> str | None:
        """Legacy single-URL fetch — kept for backwards compatibility."""
        _, page_text = await _camoufox_session(
            warmup_url=url,
            booking_url=url,
            booking_keywords=["booking", "reservation"],
            proxy_dict=parse_proxy_setting(os.getenv("RESIDENTIAL_PROXY_URL")),
            pnr=pnr,
            last_name=last_name,
        )
        return page_text

    @staticmethod
    async def fetch_live_booking_stealth(
        airline_code: str, pnr: str, last_name: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Main entry point. Dispatches to the correct airline handler.

        Each call creates a FRESH session with a NEW random fingerprint —
        no state is shared between calls or between different users.
        """
        proxy_dict = parse_proxy_setting(os.getenv("RESIDENTIAL_PROXY_URL"))
        url_fn = _AIRLINE_URLS.get(airline_code)

        if url_fn is None:
            logging.warning(f"No stealth handler for airline: {airline_code}")
            return None, None

        warmup_url, booking_url = url_fn(pnr, last_name)
        keywords = StealthBrowserManager._CAPTURE_KEYWORDS.get(airline_code, ["booking"])

        # United uses a dedicated form-based session (not the generic deep-link flow)
        if airline_code == "UNITED":
            return await _united_camoufox_session(pnr, last_name)

        return await _camoufox_session(
            warmup_url=warmup_url,
            booking_url=booking_url,
            booking_keywords=keywords,
            proxy_dict=proxy_dict,
            pnr=pnr,
            last_name=last_name,
        )
