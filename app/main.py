from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.routers import bookings, health

app = FastAPI(title="Flights MX Bot API", version="0.1.0")
app.include_router(health.router)
app.include_router(bookings.router, prefix="/v1")


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})
