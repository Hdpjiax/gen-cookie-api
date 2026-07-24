from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_booking_lifecycle_and_ownership() -> None:
    created = client.post(
        "/v1/bookings",
        json={
            "telegram_id": 100,
            "airline": "VOLARIS",
            "pnr": "LCYD6C",
            "last_name": "Valencia",
        },
    )
    assert created.status_code == 201
    body = created.json()
    booking_id = body["id"]
    assert body["segments"][0]["flight_number"] == "Y4 700"
    assert body["segments"][0]["departure_airport"] == "MEX"
    assert body["segments"][0]["arrival_airport"] == "ORD"
    assert "Karina Valencia" in body["passenger_names"]
    assert body["payment_summary"]["amount"] == 14287.0
    assert body["payment_summary"]["currency"] == "MXN"

    listed = client.get("/v1/bookings", params={"telegram_id": 100})
    assert listed.status_code == 200
    assert any(item["id"] == booking_id for item in listed.json())

    forbidden = client.get(f"/v1/bookings/{booking_id}", params={"telegram_id": 200})
    assert forbidden.status_code == 404

    consent = client.post(
        f"/v1/bookings/{booking_id}/checkin-consent",
        params={"telegram_id": 100},
        json={"passenger_scope": ["P1"]},
    )
    assert consent.status_code == 200
    assert consent.json()["checkin_status"] == "CHECKIN_SCHEDULED"

    deleted = client.delete(f"/v1/bookings/{booking_id}", params={"telegram_id": 100})
    assert deleted.status_code == 204


def test_aeromexico_booking() -> None:
    created = client.post(
        "/v1/bookings",
        json={
            "telegram_id": 101,
            "airline": "AEROMEXICO",
            "pnr": "HUIITL",
            "last_name": "Garcia",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert len(body["segments"]) == 2
    assert body["segments"][0]["flight_number"] == "AM 116"
    assert body["segments"][0]["departure_airport"] == "CJS"
    assert body["segments"][0]["arrival_airport"] == "MEX"
    assert body["segments"][1]["flight_number"] == "AM 115"
    assert body["segments"][1]["departure_airport"] == "MEX"
    assert body["segments"][1]["arrival_airport"] == "CJS"
    assert "Mariana Garcia" in body["passenger_names"]
    assert body["payment_summary"]["amount"] == 5420.0
    assert body["payment_summary"]["currency"] == "MXN"


def test_viva_booking() -> None:
    created = client.post(
        "/v1/bookings",
        json={
            "telegram_id": 102,
            "airline": "VIVA",
            "pnr": "VIV123",
            "last_name": "Lopez",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert len(body["segments"]) == 2
    assert body["segments"][0]["flight_number"] == "VB 1124"
    assert body["segments"][0]["departure_airport"] == "MTY"
    assert body["segments"][0]["arrival_airport"] == "CUN"
    assert "Carlos Lopez" in body["passenger_names"]
    assert body["payment_summary"]["amount"] == 2450.0
    assert body["payment_summary"]["currency"] == "MXN"


def test_aeromexico_am452_booking() -> None:
    created = client.post(
        "/v1/bookings",
        json={
            "telegram_id": 103,
            "airline": "AEROMEXICO",
            "pnr": "AM452",
            "last_name": "Torres",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["segments"][0]["flight_number"] == "AM 452"
    assert body["segments"][0]["departure_airport"] == "MEX"
    assert body["segments"][0]["arrival_airport"] == "GDL"
    assert "Mariana Torres" in body["passenger_names"]
    assert body["payment_summary"]["amount"] == 5420.0


def test_auto_checkin_and_boarding_passes() -> None:
    created = client.post(
        "/v1/bookings",
        json={
            "telegram_id": 105,
            "airline": "AEROMEXICO",
            "pnr": "HUIITL",
            "last_name": "Garcia",
        },
    )
    assert created.status_code == 201
    booking_id = created.json()["id"]

    consent = client.post(
        f"/v1/bookings/{booking_id}/checkin-consent",
        params={"telegram_id": 105},
        json={"passenger_scope": ["P1"]},
    )
    assert consent.status_code == 200
    assert consent.json()["checkin_status"] == "CHECKIN_SCHEDULED"

    checkin = client.post(
        f"/v1/bookings/{booking_id}/checkin",
        params={"telegram_id": 105},
    )
    assert checkin.status_code == 200
    assert checkin.json()["checkin_status"] == "BOARDING_PASS_READY"

    passes = client.get(
        f"/v1/bookings/{booking_id}/boarding-passes",
        params={"telegram_id": 105},
    )
    assert passes.status_code == 200
    assert len(passes.json()) >= 1
    assert f"{booking_id[:8].upper()}_boarding_pass.pdf" in passes.json()[0]["download_url"]


def test_text_extractor() -> None:
    from app.services.extractor import extract_booking_details_from_text

    text = "Tu clave de confirmacion de vuelo Aeromexico es HUIITL para Garcia"
    extracted = extract_booking_details_from_text(text)
    assert extracted is not None
    assert extracted["pnr"] == "HUIITL"
    assert extracted["airline"] == "AEROMEXICO"
    assert extracted["last_name"] == "Garcia"


def test_pdf_generator() -> None:
    from app.services.pdf import generate_boarding_pass_pdf

    booking = {
        "id": "12345678-1234-5678-1234-567812345678",
        "airline": "AEROMEXICO",
        "passenger_names": ["Mariana Garcia"],
        "segments": [
            {
                "flight_number": "AM 116",
                "departure_airport": "CJS",
                "arrival_airport": "MEX",
                "terminal": "T2",
                "gate": "24",
                "seat": "Aleatorio por aerolinea",
            }
        ],
    }
    pdf_path = generate_boarding_pass_pdf(booking, {})
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0




