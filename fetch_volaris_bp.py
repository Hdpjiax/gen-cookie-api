import asyncio
import httpx
import json

async def fetch_volaris():
    pnr = "HLPT4R"
    last_name = "Cetina Sanchez"
    
    headers = {
        "User-Agent": "VolarisApp/4.2.0 (iOS; iPhone15,2; iOS 17.5.1; Scale/3.00)",
        "Accept": "application/json",
        "X-App-Version": "4.2.0",
        "X-Device-Platform": "iOS",
        "X-Locale": "es_MX",
    }
    
    print("Obteniendo datos de Volaris para", pnr, last_name)
    
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            # 1. Obtener la reserva
            url = f"https://mobile.volaris.com/api/v1/booking/{pnr}?lastName={last_name}&includeDetails=true"
            r = await client.get(url)
            print("Status de la Reserva:", r.status_code)
            
            with open("volaris_debug_booking.json", "w", encoding="utf-8") as f:
                json.dump(r.json(), f, indent=2)
                
            # 2. Intentar obtener pases de abordar (plural y singular)
            url2 = f"https://mobile.volaris.com/api/v1/booking/{pnr}/boardingPasses?lastName={last_name}"
            r2 = await client.get(url2)
            print("Status BoardingPasses:", r2.status_code)
            try:
                with open("volaris_debug_bps.json", "w", encoding="utf-8") as f:
                    json.dump(r2.json(), f, indent=2)
            except:
                pass
                
            url3 = f"https://mobile.volaris.com/api/v1/booking/{pnr}/boardingPass?lastName={last_name}"
            r3 = await client.get(url3)
            print("Status BoardingPass (singular):", r3.status_code)
            try:
                with open("volaris_debug_bp.json", "w", encoding="utf-8") as f:
                    json.dump(r3.json(), f, indent=2)
            except:
                pass

            print("\n¡Listo! Por favor envíame el contenido de los archivos volaris_debug_*.json")
            
    except Exception as e:
        print("Error de conexión:", e)

if __name__ == "__main__":
    asyncio.run(fetch_volaris())
