import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import aiohttp
import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    FSInputFile,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.config import settings
from app.repositories.sqlite import store_sqlite
from app.services.extractor import extract_booking_details_from_text
from app.services.pdf import generate_boarding_pass_pdf

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

MAIN_KEYBOARD_ES = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Agregar Volaris"), KeyboardButton(text="Agregar Viva")],
        [KeyboardButton(text="Agregar Aeromexico"), KeyboardButton(text="Agregar United")],
        [KeyboardButton(text="Mis vuelos"), KeyboardButton(text="Ayuda")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Elige una opción del menú",
)

MAIN_KEYBOARD_EN = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Add Volaris"), KeyboardButton(text="Add Viva")],
        [KeyboardButton(text="Add Aeromexico"), KeyboardButton(text="Add United")],
        [KeyboardButton(text="My flights"), KeyboardButton(text="Help")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Select an option from menu",
)

BOT_COMMANDS = [
    BotCommand(command="start", description="Abrir menú principal / Open main menu"),
    BotCommand(command="volaris", description="Agregar reserva Volaris"),
    BotCommand(command="viva", description="Agregar reserva Viva Aerobus"),
    BotCommand(command="aeromexico", description="Agregar reserva Aeroméxico"),
    BotCommand(command="united", description="Agregar reserva United"),
    BotCommand(command="flights", description="Ver mis vuelos guardados"),
    BotCommand(command="recheck", description="Revisar cambios de una reserva"),
    BotCommand(command="consent", description="Autorizar check-in seguro"),
    BotCommand(command="checkin", description="Ejecutar check-in automático"),
    BotCommand(command="pass", description="Ver pase de abordar (PDF/QR)"),
    BotCommand(command="lang", description="Cambiar idioma / Switch language"),
    BotCommand(command="delete", description="Eliminar una reserva"),
]


def _user_lang(telegram_id: int) -> str:
    return store_sqlite.user_languages.get(telegram_id, "ES")


def _keyboard(telegram_id: int) -> ReplyKeyboardMarkup:
    return MAIN_KEYBOARD_EN if _user_lang(telegram_id) == "EN" else MAIN_KEYBOARD_ES


@dp.message(Command("start"))
async def start(message: Message) -> None:
    lang = _user_lang(message.from_user.id)
    welcome_image = Path("assets/flights-mx-welcome.png")
    if lang == "EN":
        text = (
            "✈️ Welcome to Flights MX! 🇲🇽\n\n"
            "Your smart assistant for flight monitoring and automated check-in.\n\n"
            "👇 Select a menu button or use a command:\n\n"
            "➕ Add reservation:\n"
            "  • /viva VIV123 Garcia\n"
            "  • /volaris LCYD6C Valencia\n"
            "  • /aeromexico HUIITL Garcia\n"
            "  • /united UA1234 Garcia\n\n"
            "📋 Features:\n"
            "  • /flights — View saved flights ✈️\n"
            "  • /recheck <id> — Check flight updates 🔄\n"
            "  • /consent <id> P1 — Authorize silent check-in 🤖\n"
            "  • /checkin <id> — Trigger automated check-in 🎟️\n"
            "  • /pass <id> — Download PDF Boarding Pass 📄\n"
            "  • /lang — Switch language (ES / EN) 🌐\n"
            "  • /delete <id> — Remove reservation 🗑️\n\n"
            "💡 You can also forward any booking confirmation email/text to add your flight automatically!"
        )
    else:
        text = (
            "✈️ ¡Bienvenido a Flights MX! 🇲🇽\n\n"
            "Tu asistente inteligente para monitorear y gestionar tus vuelos de Aeroméxico, Viva Aerobus, Volaris y United.\n\n"
            "👇 Elige un botón del menú o usa un comando:\n\n"
            "➕ Agregar reserva:\n"
            "  • /viva VIV123 Garcia\n"
            "  • /volaris LCYD6C Valencia\n"
            "  • /aeromexico HUIITL Garcia\n"
            "  • /united UA1234 Garcia\n\n"
            "📋 Menú de funciones:\n"
            "  • /flights — Ver mis vuelos guardados ✈️\n"
            "  • /recheck <id> — Revisar cambios de itinerario 🔄\n"
            "  • /consent <id> P1 — Autorizar check-in automático 🤖\n"
            "  • /checkin <id> — Ejecutar check-in silencioso 🎟️\n"
            "  • /pass <id> — Ver pase de abordar (PDF/QR) 📄\n"
            "  • /lang — Cambiar idioma (ES / EN) 🌐\n"
            "  • /delete <id> — Eliminar una reserva 🗑️\n\n"
            "💡 ¡También puedes reenviar un correo o texto de confirmación para agregar tu vuelo automáticamente!"
        )
    if welcome_image.exists():
        await message.answer_photo(FSInputFile(welcome_image), caption=text, reply_markup=_keyboard(message.from_user.id))
    else:
        await message.answer(text, reply_markup=_keyboard(message.from_user.id))


@dp.message(Command("lang"))
async def switch_language(message: Message) -> None:
    current = _user_lang(message.from_user.id)
    new_lang = "EN" if current == "ES" else "ES"
    store_sqlite.user_languages[message.from_user.id] = new_lang
    store_sqlite.save()
    if new_lang == "EN":
        await message.answer("🌐 Language switched to **English** 🇺🇸", reply_markup=MAIN_KEYBOARD_EN, parse_mode="Markdown")
    else:
        await message.answer("🌐 Idioma cambiado a **Español** 🇲🇽", reply_markup=MAIN_KEYBOARD_ES, parse_mode="Markdown")


@dp.message(F.text.casefold().in_({"ayuda", "help"}))
async def help_button(message: Message) -> None:
    await start(message)


@dp.message(F.text.casefold().in_({"agregar volaris", "add volaris"}))
async def add_volaris_button(message: Message) -> None:
    kb = _keyboard(message.from_user.id)
    await message.answer(
        "💜 Agregar vuelo de Volaris\n\n"
        "Envíame tu código de reserva y tu apellido así:\n\n"
        "👉 `/volaris LCYD6C Valencia`\n\n"
        "Formato: /volaris CODIGO APELLIDO",
        reply_markup=kb,
        parse_mode="Markdown",
    )


@dp.message(F.text.casefold().in_({"agregar viva", "add viva"}))
async def add_viva_button(message: Message) -> None:
    kb = _keyboard(message.from_user.id)
    await message.answer(
        "💚 Agregar vuelo de Viva Aerobus\n\n"
        "Envíame tu código de reserva y tu apellido así:\n\n"
        "👉 `/viva VIV123 Garcia`\n\n"
        "Formato: /viva CODIGO APELLIDO",
        reply_markup=kb,
        parse_mode="Markdown",
    )


@dp.message(F.text.casefold().in_({"agregar aeromexico", "add aeromexico"}))
async def add_aeromexico_button(message: Message) -> None:
    kb = _keyboard(message.from_user.id)
    await message.answer(
        "🇲🇽 Agregar vuelo de Aeroméxico\n\n"
        "Envíame tu PNR/eTicket y tu apellido así:\n\n"
        "👉 `/aeromexico HUIITL Garcia`\n\n"
        "Formato: /aeromexico PNR_O_ETICKET APELLIDO",
        reply_markup=kb,
        parse_mode="Markdown",
    )


@dp.message(F.text.casefold().in_({"agregar united", "add united"}))
async def add_united_button(message: Message) -> None:
    kb = _keyboard(message.from_user.id)
    await message.answer(
        "🇺🇸 Agregar vuelo de United Airlines\n\n"
        "Envíame tu confirmación/eTicket y tu apellido así:\n\n"
        "👉 `/united UA1234 Garcia`\n\n"
        "Formato: /united CONFIRMACION_O_ETICKET APELLIDO",
        reply_markup=kb,
        parse_mode="Markdown",
    )


@dp.message(Command("add"))
async def add_booking(message: Message) -> None:
    parts = _parts(message.text)
    if len(parts) < 4:
        await message.answer(
            "💡 Uso: `/add VOLARIS LCYD6C Valencia`\n\n"
            "O usa directamente los comandos por aerolínea:\n"
            "  • `/viva VIV123 Garcia`\n"
            "  • `/volaris LCYD6C Valencia`\n"
            "  • `/aeromexico HUIITL Garcia`\n"
            "  • `/united UA1234 Garcia`",
            reply_markup=_keyboard(message.from_user.id),
            parse_mode="Markdown",
        )
        return
    await _create_booking(message, parts[1].upper(), parts[2], " ".join(parts[3:]))


@dp.message(Command("viva"))
async def add_viva(message: Message) -> None:
    await _create_airline_booking(message, "VIVA", "💚 Uso: `/viva VIV123 Garcia`")


@dp.message(Command("volaris"))
async def add_volaris(message: Message) -> None:
    await _create_airline_booking(message, "VOLARIS", "💜 Uso: `/volaris LCYD6C Valencia`")


@dp.message(Command("aeromexico"))
async def add_aeromexico(message: Message) -> None:
    await _create_airline_booking(message, "AEROMEXICO", "🇲🇽 Uso: `/aeromexico HUIITL Garcia`")


@dp.message(Command("united"))
async def add_united(message: Message) -> None:
    await _create_airline_booking(message, "UNITED", "🇺🇸 Uso: `/united UA1234 Garcia`")


async def _create_airline_booking(message: Message, airline: str, usage: str) -> None:
    parts = _parts(message.text)
    if len(parts) < 3:
        await message.answer(usage, reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    await _create_booking(message, airline, parts[1], " ".join(parts[2:]))


async def _create_booking(message: Message, airline: str, pnr: str, last_name: str) -> None:
    payload = {
        "telegram_id": message.from_user.id,
        "airline": airline,
        "pnr": pnr,
        "last_name": last_name,
    }
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
        response = await client.post("/v1/bookings", json=payload)
    if response.status_code >= 400:
        await message.answer(
            "❌ No pude agregar esa reserva.\n\n"
            "Por favor revisa que el código y apellido estén correctos, y que elegiste la aerolínea correspondiente.",
            reply_markup=_keyboard(message.from_user.id),
        )
        return
    booking = response.json()
    await message.answer(_booking_added_text(booking), reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")


@dp.message(Command("flights"))
@dp.message(F.text.casefold().in_({"mis vuelos", "my flights"}))
async def flights(message: Message) -> None:
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
        response = await client.get("/v1/bookings", params={"telegram_id": message.from_user.id})
    if response.status_code >= 400:
        await message.answer(f"❌ No pude obtener tus vuelos: {response.text}", reply_markup=_keyboard(message.from_user.id))
        return
    bookings = response.json()
    if not bookings:
        await message.answer(
            "📭 No tienes reservas guardadas por el momento.\n\n"
            "¡Agrega la primera fácilmente con estos comandos!\n"
            "  • /viva VIV123 Garcia\n"
            "  • /volaris LCYD6C Valencia\n"
            "  • /aeromexico HUIITL Garcia\n"
            "  • /united UA1234 Garcia",
            reply_markup=_keyboard(message.from_user.id),
        )
        return
    
    text = "📋 *Tus Vuelos Guardados*\n\n" + "\n\n".join(_booking_text(booking) for booking in bookings)
    await message.answer(
        text,
        reply_markup=_keyboard(message.from_user.id),
        parse_mode="Markdown",
    )


@dp.message(Command("recheck"))
async def recheck(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/recheck <codigo_interno>`", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
        response = await client.post(
            f"/v1/bookings/{booking_id}/recheck", params={"telegram_id": message.from_user.id}
        )
    if response.status_code >= 400:
        await message.answer(f"❌ Error al realizar recheck: {response.text}", reply_markup=_keyboard(message.from_user.id))
        return
    result = response.json()
    events = result["events"]
    text = "🔄 *Revisión de itinerario completada*\n\n" + _booking_text(result["booking"])
    if events:
        text += "\n\n✨ *Cambios detectados:*\n" + "\n".join(
            f"  • {_event_label(event['event_type'])}: `{event['previous_value']}` ➔ `{event['new_value']}`"
            for event in events
        )
    else:
        text += "\n\n✅ *Sin cambios por ahora. Tu vuelo se mantiene a tiempo.*"
    await message.answer(text, reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")


@dp.message(Command("consent"))
async def consent(message: Message) -> None:
    parts = _parts(message.text)
    if len(parts) < 3:
        await message.answer("💡 Uso: `/consent <codigo_interno> P1`", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
        response = await client.post(
            f"/v1/bookings/{parts[1]}/checkin-consent",
            params={"telegram_id": message.from_user.id},
            json={"passenger_scope": parts[2:]},
        )
    if response.status_code >= 400:
        await message.answer(f"❌ No se pudo registrar consentimiento: {response.text}", reply_markup=_keyboard(message.from_user.id))
        return
    await message.answer(
        "🤖 *Check-in automático autorizado*\n\n"
        "✅ Quedó guardado tu consentimiento para los pasajeros seleccionados.\n\n"
        "🛡️ *Reglas de seguridad activas:*\n"
        "  • Omisión del paso de selección de asiento (asignación aleatoria gratuita a $0 MXN por la aerolínea).\n"
        "  • Sin compras de equipaje extra, seguros o servicios adicionales.\n"
        "  • Si se requiere pago, CAPTCHA o autenticación manual, el proceso se pausará de forma segura.\n\n"
        "💡 *El bot ejecutará el check-in automáticamente en segundo plano cuando se abra la ventana.*",
        reply_markup=_keyboard(message.from_user.id),
        parse_mode="Markdown",
    )


@dp.message(Command("checkin"))
async def checkin_command(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/checkin <codigo_interno>`", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
        response = await client.post(
            f"/v1/bookings/{booking_id}/checkin",
            params={"telegram_id": message.from_user.id},
        )
    if response.status_code >= 400:
        await message.answer(f"❌ No se pudo procesar el Check-in: {response.text}", reply_markup=_keyboard(message.from_user.id))
        return
    booking = response.json()
    if booking.get("checkin_status") in ("CHECKED_IN", "BOARDING_PASS_READY"):
        pdf_file = generate_boarding_pass_pdf(booking, {})
        await message.answer_document(
            FSInputFile(pdf_file),
            caption=(
                "🎟️ *¡Check-in completado con éxito!*\n\n"
                f"{_booking_text(booking)}\n\n"
                "📄 *Se adjunta tu Pase de Abordar oficial en PDF.*"
            ),
            reply_markup=_keyboard(message.from_user.id),
            parse_mode="Markdown",
        )
    else:
        await message.answer(
            f"📲 *Estado de Check-in:* {_checkin_label(booking['checkin_status'])}\n\n"
            "💡 Asegúrate de autorizar primero con `/consent <codigo_interno> P1`",
            reply_markup=_keyboard(message.from_user.id),
            parse_mode="Markdown",
        )


@dp.message(Command("pass"))
async def pass_command(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/pass <codigo_interno>`", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
        response = await client.get(
            f"/v1/bookings/{booking_id}",
            params={"telegram_id": message.from_user.id},
        )
    if response.status_code >= 400:
        await message.answer(f"❌ No se encontró la reserva: {response.text}", reply_markup=_keyboard(message.from_user.id))
        return
    booking = response.json()
    pdf_file = generate_boarding_pass_pdf(booking, {})
    await message.answer_document(
        FSInputFile(pdf_file),
        caption=(
            "🎟️ *Pase de Abordar Oficial (PDF)*\n\n"
            f"✈️ {_airline_label(booking['airline'])} — {booking['segments'][0]['flight_number']}\n"
            f"👤 Pasajero: {', '.join(booking.get('passenger_names', []))}\n\n"
            "📄 Documento adjunto para uso sin conexión."
        ),
        reply_markup=_keyboard(message.from_user.id),
        parse_mode="Markdown",
    )


@dp.message(Command("delete"))
async def delete(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/delete <codigo_interno>`", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
        response = await client.delete(
            f"/v1/bookings/{booking_id}", params={"telegram_id": message.from_user.id}
        )
    if response.status_code >= 400:
        await message.answer(f"❌ No se pudo eliminar la reserva: {response.text}", reply_markup=_keyboard(message.from_user.id))
        return
    await message.answer(
        "🗑️ *Reserva eliminada*\n\n"
        "Se ha detenido el monitoreo del vuelo y revocado los accesos asociados.",
        reply_markup=_keyboard(message.from_user.id),
        parse_mode="Markdown",
    )


@dp.message(F.text)
async def fallback(message: Message) -> None:
    extracted = extract_booking_details_from_text(message.text)
    if extracted:
        await _create_booking(message, extracted["airline"], extracted["pnr"], extracted["last_name"])
        return
    await message.answer("💡 Usa /start o toca una opción del menú.", reply_markup=_keyboard(message.from_user.id))


def _parts(text: str | None) -> list[str]:
    return (text or "").split()


def _single_arg(message: Message) -> str | None:
    parts = _parts(message.text)
    return parts[1] if len(parts) == 2 else None


def _booking_text(booking: dict[str, Any]) -> str:
    airline_icon = _airline_icon(booking['airline'])
    airline_name = _airline_label(booking['airline'])
    segments = booking.get("segments") or []
    passengers = booking.get("passenger_names") or []
    passenger_text = "\n".join(f"  • {name}" for name in passengers) if passengers else "  • No disponible"
    payment_text = _payment_text(booking.get("payment_summary"))
    checkin_text = _checkin_label(booking['checkin_status'])

    segment_blocks = []
    num_segments = len(segments)
    for idx, seg in enumerate(segments, start=1):
        if num_segments == 1:
            tramo_label = "Itinerario"
        elif idx == 1:
            tramo_label = f"Tramo {idx} (Ida)"
        elif idx == 2 and num_segments == 2:
            tramo_label = f"Tramo {idx} (Vuelta)"
        else:
            tramo_label = f"Tramo {idx}"

        dep_term = f" (Term. {seg['terminal']})" if seg.get('terminal') else ""
        gate_info = f" | Puerta: {seg['gate']}" if seg.get('gate') else ""
        seat_info = f" | Asiento: {seg['seat']}" if seg.get('seat') else ""
        status_icon = _status_icon(seg.get('operational_status'))
        status_name = _status_label(seg.get('operational_status'))

        segment_blocks.append(
            f"✈️ *{tramo_label}:* {seg['flight_number']}\n"
            f"   📍 {seg['departure_airport']}{dep_term} ➔ {seg['arrival_airport']}\n"
            f"   📅 Salida: {_format_datetime(seg['scheduled_departure'])}\n"
            f"   📊 Estado: {status_icon} {status_name}{gate_info}{seat_info}"
        )

    segments_text = "\n\n".join(segment_blocks)

    return (
        f"{airline_icon} *{airline_name}*\n"
        f"🔖 Código interno: `{booking['id']}`\n\n"
        f"👤 *Pasajero(s):*\n{passenger_text}\n\n"
        f"{segments_text}\n\n"
        f"📲 Check-in: {checkin_text}\n"
        f"💳 Total pagado: {payment_text}"
    )


def _booking_added_text(booking: dict[str, Any]) -> str:
    airline_icon = _airline_icon(booking['airline'])
    airline_name = _airline_label(booking['airline'])
    first_seg = booking["segments"][0]
    route = f"{first_seg['departure_airport']} ➔ {first_seg['arrival_airport']}"
    if len(booking["segments"]) > 1:
        route += " (Ida y Vuelta)"

    return (
        "🎉 *¡Reserva agregada correctamente!*\n\n"
        f"{airline_icon} *{airline_name}* — Vuelo {first_seg['flight_number']}\n"
        f"📍 Ruta: {route}\n"
        f"📅 Salida: {_format_datetime(first_seg['scheduled_departure'])}\n\n"
        "────────────────────────\n"
        f"{_booking_text(booking)}\n"
        "────────────────────────\n\n"
        "💡 Puedes consultar tus vuelos en el menú o actualizar con:\n"
        f"/recheck `{booking['id']}`"
    )


def _payment_text(payment: dict[str, Any] | None) -> str:
    if not payment:
        return "No disponible"
    amount = float(payment["amount"])
    if amount <= 0 and payment.get("status") == "UNKNOWN":
        return "No disponible"
    method = f" ({payment['method']})" if payment.get("method") else ""
    return f"{payment['currency']} ${amount:,.2f}{method}"


def _format_datetime(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.strftime("%d/%m/%Y %H:%M UTC")


def _airline_label(value: str) -> str:
    return {
        "VIVA": "Viva Aerobus",
        "VOLARIS": "Volaris",
        "AEROMEXICO": "Aeroméxico",
        "UNITED": "United Airlines",
    }.get(value, value)


def _airline_icon(value: str) -> str:
    return {
        "VIVA": "💚 ✈️",
        "VOLARIS": "💜 ✈️",
        "AEROMEXICO": "🇲🇽 ✈️",
        "UNITED": "🇺🇸 ✈️",
    }.get(value, "✈️")


def _status_icon(value: str | None) -> str:
    return {
        "SCHEDULED": "🟢",
        "DELAYED": "🟡",
        "CANCELLED": "🔴",
    }.get(value or "", "⚪")


def _status_label(value: str) -> str:
    return {
        "SCHEDULED": "Programado",
        "DELAYED": "Retrasado",
        "CANCELLED": "Cancelado",
    }.get(value, value)


def _checkin_label(value: str) -> str:
    return {
        "NOT_ELIGIBLE": "⏳ Todavía no disponible",
        "CHECKIN_SCHEDULED": "🤖 Programado con consentimiento",
        "CHECKIN_WINDOW_OPEN": "📲 Disponible para Check-in",
        "ACTION_REQUIRED": "⚠️ Requiere acción manual",
        "CHECKED_IN": "✅ Check-in completado",
        "BOARDING_PASS_READY": "🎟️ Pase de abordar listo",
        "CHECKIN_FAILED": "❌ No se pudo completar",
        "CHECKIN_EXPIRED": "⌛ Ventana expirada",
    }.get(value, value)


def _event_label(value: str) -> str:
    return {
        "DELAY": "⏱️ Cambio de horario",
        "EARLY": "⏩ Salida adelantada",
        "CANCELLATION": "⚠️ Estado del vuelo",
        "GATE": "🚪 Puerta",
        "TERMINAL": "🏢 Terminal",
        "SEAT": "💺 Asiento",
        "ITINERARY": "🗺️ Itinerario",
        "CHECKIN": "📲 Check-in",
    }.get(value, value)


async def _background_monitor_loop(bot: Bot) -> None:
    """Monitoreo proactivo en segundo plano para check-in automático y alertas de vuelo."""
    while True:
        try:
            await asyncio.sleep(20)
            # Scan all active bookings in SQLite database
            for booking in list(store_sqlite.bookings.values()):
                if booking.deleted_at is not None:
                    continue
                # If consent given and scheduled, trigger auto check-in
                if booking.checkin_status.value == "CHECKIN_SCHEDULED":
                    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
                        res = await client.post(
                            f"/v1/bookings/{booking.id}/checkin",
                            params={"telegram_id": booking.telegram_id},
                        )
                        if res.status_code == 200:
                            updated_b = res.json()
                            if updated_b.get("checkin_status") in ("CHECKED_IN", "BOARDING_PASS_READY"):
                                pdf_path = generate_boarding_pass_pdf(updated_b, {})
                                await bot.send_document(
                                    chat_id=booking.telegram_id,
                                    document=FSInputFile(pdf_path),
                                    caption=(
                                        "🎟️ *¡Check-in completado de forma automática e invisible!*\n\n"
                                        f"{_booking_text(updated_b)}\n\n"
                                        "📄 *Se adjunta tu Pase de Abordar oficial en PDF.*"
                                    ),
                                    parse_mode="Markdown",
                                )
        except Exception as e:
            logging.error(f"Error en worker de monitoreo: {e}")


async def _safe_set_commands(bot: Bot) -> None:
    for attempt in range(5):
        try:
            await bot.set_my_commands(BOT_COMMANDS)
            logging.info("Comandos de Telegram configurados correctamente.")
            return
        except Exception as e:
            logging.warning(f"Error al conectar con Telegram para configurar comandos ({e}). Reintentando en 3s (intento {attempt + 1}/5)...")
            await asyncio.sleep(3)


async def main() -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN no esta configurado en .env")
    
    session = AiohttpSession(timeout=45.0)
    bot = Bot(settings.telegram_bot_token, session=session)
    await _safe_set_commands(bot)
    asyncio.create_task(_background_monitor_loop(bot))

    while True:
        try:
            await dp.start_polling(bot)
            break
        except (aiohttp.ClientError, asyncio.TimeoutError, TelegramNetworkError) as e:
            logging.warning(f"Conexión a Telegram interrumpida ({e}). Reintentando en 5 segundos...")
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logging.error(f"Error en polling: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
