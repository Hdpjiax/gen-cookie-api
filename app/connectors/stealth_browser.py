import asyncio
import logging
import random
from typing import Any

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
]


class StealthBrowserManager:
    """Manages ephemeral private incognito browser sessions with randomized anti-fingerprinting stealth."""

    @staticmethod
    async def fetch_airline_page_stealth(url: str, pnr: str, last_name: str) -> str | None:
        """Executes a stealth private incognito browser session with fingerprint noise and zero history trace."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logging.info("Playwright module not installed, skipping stealth browser navigation.")
            return None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--incognito",
                    ],
                )

                # Randomized fingerprint context parameters
                random_ua = random.choice(USER_AGENTS)
                random_vp = random.choice(VIEWPORTS)

                context = await browser.new_context(
                    user_agent=random_ua,
                    viewport=random_vp,
                    locale="es-MX",
                    timezone_id="America/Mexico_City",
                    java_script_enabled=True,
                    ignore_https_errors=True,
                )

                # Anti-fingerprint stealth script injection
                await context.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'languages', {get: () => ['es-MX', 'es', 'en-US', 'en']});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    window.chrome = { runtime: {} };
                    """
                )

                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                content = await page.content()

                # Cleanly dispose context & browser with zero history retention
                await context.close()
                await browser.close()
                return content

        except Exception as e:
            logging.info(f"Stealth browser navigation info: {e}")
            return None

    @staticmethod
    async def fetch_live_booking_stealth(airline_code: str, pnr: str, last_name: str) -> dict[str, Any] | None:
        """Executes a stealth private incognito browser session, fills search form, and extracts real booking data."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--incognito",
                    ],
                )

                random_ua = random.choice(USER_AGENTS)
                random_vp = random.choice(VIEWPORTS)

                context = await browser.new_context(
                    user_agent=random_ua,
                    viewport=random_vp,
                    locale="es-MX",
                    timezone_id="America/Mexico_City",
                    java_script_enabled=True,
                    ignore_https_errors=True,
                )

                await context.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'languages', {get: () => ['es-MX', 'es', 'en-US', 'en']});
                    """
                )

                page = await context.new_page()

                captured_json: list[dict[str, Any]] = []

                async def handle_response(response):
                    try:
                        if (
                            "booking" in response.url.lower()
                            or "pnr" in response.url.lower()
                            or "retrieve" in response.url.lower()
                        ):
                            if response.status == 200 and "json" in response.headers.get("content-type", ""):
                                data = await response.json()
                                if isinstance(data, dict):
                                    captured_json.append(data)
                    except Exception:
                        pass

                page.on("response", handle_response)

                url_map = {
                    "VOLARIS": "https://www.volaris.com/my-trips",
                    "AEROMEXICO": "https://www.aeromexico.com/es-mx/mi-reserva",
                    "VIVA": "https://www.vivaaerobus.com/es-mx/my-booking",
                    "UNITED": "https://www.united.com/en/us/fly/reservation-finder.html",
                }
                url = url_map.get(airline_code, "https://www.volaris.com/my-trips")
                await page.goto(url, wait_until="domcontentloaded", timeout=12000)

                try:
                    pnr_input = await page.query_selector(
                        "input[name*='pnr'], input[name*='code'], input[id*='pnr'], input[placeholder*='PNR'], input[placeholder*='código']"
                    )
                    if pnr_input:
                        await pnr_input.fill(pnr)

                    last_input = await page.query_selector(
                        "input[name*='last'], input[id*='last'], input[placeholder*='apellido'], input[placeholder*='Last']"
                    )
                    if last_input:
                        await last_input.fill(last_name)

                    submit_btn = await page.query_selector(
                        "button[type='submit'], input[type='submit'], button:has-text('Buscar'), button:has-text('Find')"
                    )
                    if submit_btn:
                        await submit_btn.click()
                        await page.wait_for_timeout(3000)
                except Exception as e:
                    logging.info(f"Form submission stealth note: {e}")

                await context.close()
                await browser.close()

                if captured_json:
                    return captured_json[0]
                return None

        except Exception as e:
            logging.info(f"Stealth live booking error: {e}")
            return None
