import json
from app.connectors.live_web import LiveAirlineConnector
from app.domain.models import AirlineCode

def main():
    data = json.load(open('aeromexico_booking.json'))
    conn = LiveAirlineConnector(AirlineCode.AEROMEXICO)
    res = conn._parse_aeromexico_live(data, "FEMDZQ", "TRUJILLO")
    if res:
        print("SUCCESSFULLY PARSED:")
        print(json.dumps(res, indent=2, default=str))
    else:
        print("FAILED TO PARSE")

if __name__ == "__main__":
    main()
