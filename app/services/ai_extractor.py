import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Initialize OpenAI client (API key must be set in environment variables)
# Se puede usar OPENAI_API_KEY o AI_API_KEY para proveedores gratis como Groq u OpenRouter.
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
base_url = os.getenv("AI_BASE_URL") # Deja en None para usar OpenAI por defecto
model_name = os.getenv("AI_MODEL", "llama-3.3-70b-versatile") # Modelo por defecto

client = None
if api_key:
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

SYSTEM_PROMPT = """
You are a specialized AI designed to extract flight booking information from chaotic HTML or raw text scraped from airline websites.
Your goal is to accurately identify the passenger(s), the payment summary, and the flight segments, regardless of the language or the airline.

Return ONLY a valid JSON object matching exactly this schema, with no markdown formatting or extra text:

{
  "pnr": "XY895L",
  "last_name": "Garcia",
  "passengers": [
    { "id": "P1", "display_name": "First Last" }
  ],
  "payment_summary": {
    "amount": 0.0,
    "currency": "MXN",
    "method": "Tarjeta",
    "status": "PAID"
  },
  "segments": [
    {
      "flight_number": "Y4 123",
      "departure_airport": "MEX",
      "arrival_airport": "CUN",
      "scheduled_departure": "2026-07-30T10:00:00+00:00",
      "estimated_departure": "2026-07-30T10:00:00+00:00",
      "operational_status": "SCHEDULED",
      "gate": "A1",
      "terminal": "T1",
      "seat": "Sin asignar",
      "boarding_group": "Grupo A"
    }
  ]
}

Instructions:
1. "pnr": Extract the booking reference (usually 6 alphanumeric characters).
2. "last_name": Extract the primary last name associated with the booking.
3. "passengers": Extract full names. Assign IDs P1, P2, etc.
4. "payment_summary": Extract total paid, currency. If not found, use 0.0 and MXN.
5. "segments": Extract each flight leg.
   - "flight_number": e.g. "VB 1024" or "AM 400"
   - "departure_airport" / "arrival_airport": Use IATA 3-letter codes if possible.
   - "scheduled_departure": Must be ISO 8601 format with timezone. If year/date missing, guess upcoming dates. 
   - "operational_status": "SCHEDULED", "BOARDING", "DELAYED", "CANCELLED", etc.
   - "seat": Extracted seat or "Sin asignar".
   
If the data indicates no booking was found or it's an error page, return an empty JSON object: {}.
"""

async def extract_booking_via_llm(page_text: str, pnr: str, last_name: str) -> dict[str, Any] | None:
    """Uses the LLM to extract booking data from raw text/HTML."""
    if not page_text or not client:
        logger.warning("No page text provided or AI_API_KEY is missing.")
        return None

    try:
        # Truncate text to avoid token limits if it's a massive HTML page
        safe_text = page_text[:25000]
        
        with open('debug_page_text.txt', 'w', encoding='utf-8') as df:
            df.write(safe_text)
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Booking Ref: {pnr}, Last Name: {last_name}\n\nRaw Page Text:\n{safe_text}"}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        with open('debug_llm_response.txt', 'w', encoding='utf-8') as df:
            df.write(str(content))
        if not content:
            return None
            
        data = json.loads(content)
        
        if not data or "segments" not in data or not data["segments"]:
            logger.info("LLM extraction yielded empty or invalid booking data.")
            return None
            
        return data

    except Exception as e:
        logger.error(f"Error extracting booking via LLM: {e}")
        return None
