# Flights MX Bot API

MVP backend for an authorized Telegram assistant that manages reservations for Viva Aerobus, Volaris, Aeromexico, and United Airlines.

The current implementation provides:

- FastAPI v1 endpoints for bookings, manual recheck, check-in consent, boarding passes, and deletion.
- Normalized domain models for bookings, segments, snapshots, events, and check-in status.
- Safe URL import with HTTPS allowlist and SSRF-oriented host/IP blocking.
- Airline connector interface plus deterministic mock connectors for local development.
- Snapshot hashing, diff detection, event deduplication, and safe `ACTION_REQUIRED` behavior.
- Unit tests for URL safety, diff/dedupe, connector policy, and API ownership checks.
- Brand assets in `assets/` for the Telegram bot logo and welcome image.

## Local Usage

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
pytest
```

## Pasos para hacerlo funcionar

1. Crea un bot en Telegram con `@BotFather` y copia el token.
2. Copia `.env.example` a `.env`.
3. En `.env`, reemplaza `TELEGRAM_BOT_TOKEN=pon_aqui_el_token_de_botfather` por tu token real.
4. Instala dependencias:

```powershell
python -m pip install -e ".[dev]"
```

5. En una terminal, arranca la API:

```powershell
.\scripts\start_api.ps1
```

6. En otra terminal, arranca el bot:

```powershell
.\scripts\start_bot.ps1
```

7. Abre tu bot en Telegram y prueba:

```text
/start
/viva ABC123 Garcia
/volaris LCYD6C Valencia
/aeromexico ABC123 Garcia
/united ABC123 Garcia
/recheck <booking_id>
/consent <booking_id> P1
/delete <booking_id>
```

Los datos locales se guardan en `.local/bookings.json`.

## Safety Rules

This MVP deliberately does not automate real airline portals. Production connectors must respect explicit consent, never buy extras, never modify travel, never bypass CAPTCHA/MFA/fraud controls, and must fail closed with `ACTION_REQUIRED` when eligibility is uncertain.
