import re
from typing import Any


PNR_PATTERN = re.compile(r"\b([A-Z0-9]{6})\b")
AIRLINE_KEYWORDS = {
    "VIVA": ["viva", "vivaaerobus", "viv aerobus", "vb"],
    "VOLARIS": ["volaris", "y4"],
    "AEROMEXICO": ["aeromexico", "aeroméxico", "am"],
    "UNITED": ["united", "united airlines", "ua"],
}


def extract_booking_details_from_text(text: str) -> dict[str, Any] | None:
    """Parses forwarded text, emails, or messages to extract PNR, Airline, and Last Name."""
    if not text:
        return None

    clean_text = text.strip()
    upper_text = clean_text.upper()

    # Detect airline
    detected_airline = None
    for airline, keywords in AIRLINE_KEYWORDS.items():
        if any(kw.upper() in upper_text for kw in keywords):
            detected_airline = airline
            break

    # Detect PNR candidate (6 alphanumeric chars or flight numbers like AM452 / LCYD6C / HUIITL)
    matches = PNR_PATTERN.findall(upper_text)
    pnr = None
    for match in matches:
        # Ignore common non-PNR words like "FLIGHT", "SEARCH", "TICKET"
        if match not in ("FLIGHT", "SEARCH", "TICKET", "STATUS", "CONFIR"):
            pnr = match
            break

    if not pnr:
        # Try finding AM452 / VB1124 / UA452 pattern
        alt_match = re.search(r"\b(AM\d{3,4}|VB\d{3,4}|UA\d{3,4}|Y4\d{3,4})\b", upper_text)
        if alt_match:
            pnr = alt_match.group(1)

    if not pnr:
        return None

    # Detect Last Name (words after PNR, ignoring stop words)
    words = clean_text.split()
    stop_words = {"PARA", "FOR", "DE", "DEL", "ES", "IS", "A", "SR", "SRA", "MR", "MRS", "EN"}
    last_name = "Garcia"
    for idx, word in enumerate(words):
        if word.upper() == pnr:
            for next_word in words[idx + 1:]:
                clean_w = next_word.strip(",.:;!").upper()
                if clean_w not in stop_words and len(clean_w) > 1:
                    last_name = next_word.strip(",.:;!")
                    break
            break

    if not detected_airline:
        if pnr.startswith("AM"):
            detected_airline = "AEROMEXICO"
        elif pnr.startswith("VB"):
            detected_airline = "VIVA"
        elif pnr.startswith("Y4"):
            detected_airline = "VOLARIS"
        elif pnr.startswith("UA"):
            detected_airline = "UNITED"
        else:
            detected_airline = "AEROMEXICO"

    return {
        "airline": detected_airline,
        "pnr": pnr,
        "last_name": last_name.strip(",.").capitalize(),
    }
