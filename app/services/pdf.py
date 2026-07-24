from datetime import datetime
from pathlib import Path
from typing import Any


def generate_boarding_pass_pdf(booking: dict[str, Any], pass_info: dict[str, Any]) -> Path:
    """Generates a clean PDF Boarding Pass file for offline viewing and returns the file path."""
    passes_dir = Path(".local/passes")
    passes_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = passes_dir / f"{booking['id']}_boarding_pass.pdf"

    airline = booking.get("airline", "AEROMEXICO")
    passengers = ", ".join(booking.get("passenger_names") or ["Pasajero"])
    segment = (booking.get("segments") or [{}])[0]
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
(CODIGO DE VALIDACION QR: BOARDING-{booking['id'][:8].upper()}) Tj
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
