import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import aiohttp
import httpx
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramConflictError, TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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


def _flight_inline_keyboard(booking_id: str, checkin_status: str, lang: str = "ES") -> InlineKeyboardMarkup:
    if lang == "EN":
        buttons = [
            [
                InlineKeyboardButton(text="🔄 Recheck Status", callback_data=f"recheck:{booking_id}"),
                InlineKeyboardButton(text="📄 Pass PDF", callback_data=f"pass:{booking_id}"),
            ]
        ]
        if checkin_status not in ("CHECKED_IN", "BOARDING_PASS_READY"):
            buttons.append([
                InlineKeyboardButton(text="🤖 Enable Auto Check-in", callback_data=f"consent:{booking_id}")
            ])
        buttons.append([
            InlineKeyboardButton(text="🗑️ Delete Flight", callback_data=f"delete_confirm:{booking_id}")
        ])
    else:
        buttons = [
            [
                InlineKeyboardButton(text="🔄 Rechecar Estado", callback_data=f"recheck:{booking_id}"),
                InlineKeyboardButton(text="📄 Pase PDF", callback_data=f"pass:{booking_id}"),
            ]
        ]
        if checkin_status not in ("CHECKED_IN", "BOARDING_PASS_READY"):
            buttons.append([
                InlineKeyboardButton(text="🤖 Autorizar Auto Check-in", callback_data=f"consent:{booking_id}")
            ])
        buttons.append([
            InlineKeyboardButton(text="🗑️ Eliminar Vuelo", callback_data=f"delete_confirm:{booking_id}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _delete_confirm_keyboard(booking_id: str, lang: str = "ES") -> InlineKeyboardMarkup:
    if lang == "EN":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Yes, Delete", callback_data=f"delete_do:{booking_id}"),
                    InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel:{booking_id}"),
                ]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Sí, eliminar vuelo", callback_data=f"delete_do:{booking_id}"),
                InlineKeyboardButton(text="❌ Cancelar", callback_data=f"cancel:{booking_id}"),
            ]
        ]
    )


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
            "  • /flights — View saved flights (with interactive buttons) ✈️\n"
            "  • /lang — Switch language (ES / EN) 🌐\n\n"
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
            "  • /flights — Ver mis vuelos guardados (con botones interactivos) ✈️\n"
            "  • /lang — Cambiar idioma (ES / EN) 🌐\n\n"
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
    lang = _user_lang(message.from_user.id)
    try:
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
        await message.answer(
            _booking_added_text(booking),
            reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang),
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Error HTTP en _create_booking ({settings.api_base_url}): {e}")
        try:
            from app.schemas import BookingCreate
            from app.services.bookings import booking_service
            booking_obj = await booking_service.create_booking(BookingCreate(**payload))
            booking_dict = {
                "id": str(booking_obj.id),
                "airline": booking_obj.airline.value,
                "passenger_names": booking_obj.passenger_names,
                "segments": [
                    {
                        "flight_number": seg.flight_number,
                        "departure_airport": seg.departure_airport,
                        "arrival_airport": seg.arrival_airport,
                        "scheduled_departure": seg.scheduled_departure.isoformat(),
                        "operational_status": seg.operational_status,
                        "terminal": seg.terminal,
                        "gate": seg.gate,
                        "seat": seg.seat,
                    }
                    for seg in booking_obj.segments
                ],
                "checkin_status": booking_obj.checkin_status.value,
                "payment_summary": {
                    "amount": booking_obj.payment_summary.amount,
                    "currency": booking_obj.payment_summary.currency,
                    "method": booking_obj.payment_summary.method,
                } if booking_obj.payment_summary else None,
            }
            await message.answer(
                _booking_added_text(booking_dict),
                reply_markup=_flight_inline_keyboard(booking_dict["id"], booking_dict["checkin_status"], lang),
                parse_mode="Markdown",
            )
        except Exception as inner_e:
            logging.error(f"Error fallback en _create_booking: {inner_e}")
            await message.answer(
                "❌ Ocurrió un error al procesar la reserva.\n\n"
                "Asegúrate de que la API esté iniciada y las variables de entorno configuradas.",
                reply_markup=_keyboard(message.from_user.id),
            )


@dp.message(Command("flights"))
@dp.message(F.text.casefold().in_({"mis vuelos", "my flights"}))
async def flights(message: Message) -> None:
    lang = _user_lang(message.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            response = await client.get("/v1/bookings", params={"telegram_id": message.from_user.id})
        if response.status_code >= 400:
            await message.answer(f"❌ No pude obtener tus vuelos: {response.text}", reply_markup=_keyboard(message.from_user.id))
            return
        bookings = response.json()
    except Exception as e:
        logging.error(f"Error cargando vuelos: {e}")
        bookings = [
            {
                "id": str(b.id),
                "airline": b.airline.value,
                "passenger_names": b.passenger_names,
                "segments": [
                    {
                        "flight_number": seg.flight_number,
                        "departure_airport": seg.departure_airport,
                        "arrival_airport": seg.arrival_airport,
                        "scheduled_departure": seg.scheduled_departure.isoformat(),
                        "operational_status": seg.operational_status,
                        "terminal": seg.terminal,
                        "gate": seg.gate,
                        "seat": seg.seat,
                    }
                    for seg in b.segments
                ],
                "checkin_status": b.checkin_status.value,
                "payment_summary": {
                    "amount": b.payment_summary.amount,
                    "currency": b.payment_summary.currency,
                    "method": b.payment_summary.method,
                } if b.payment_summary else None,
            }
            for b in store_sqlite.bookings.values()
            if b.telegram_id == message.from_user.id and b.deleted_at is None
        ]

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

    await message.answer("📋 *Tus Vuelos Guardados*", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
    for booking in bookings:
        await message.answer(
            _booking_text(booking),
            reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang),
            parse_mode="Markdown",
        )


@dp.callback_query(F.data.startswith("recheck:"))
async def cb_recheck(query: CallbackQuery) -> None:
    booking_id = query.data.split(":")[1]
    lang = _user_lang(query.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            res = await client.post(f"/v1/bookings/{booking_id}/recheck", params={"telegram_id": query.from_user.id})
        if res.status_code == 200:
            result = res.json()
            booking = result["booking"]
            events = result["events"]
            text = _booking_text(booking)
            if events:
                text += "\n\n✨ *Cambios detectados:*\n" + "\n".join(
                    f"  • {_event_label(e['event_type'])}: `{e['previous_value']}` ➔ `{e['new_value']}`" for e in events
                )
            else:
                text += "\n\n✅ *Vuelo al día y a tiempo.*"
            await query.message.edit_text(text, reply_markup=_flight_inline_keyboard(booking_id, booking["checkin_status"], lang), parse_mode="Markdown")
            await query.answer("🔄 Vuelo rechecado correctamente.")
        else:
            await query.answer("❌ Error al rechecar vuelo.", show_alert=True)
    except Exception as e:
        logging.error(f"Error recheck callback: {e}")
        await query.answer("🔄 Estado revisado.", show_alert=False)


@dp.callback_query(F.data.startswith("pass:"))
async def cb_pass(query: CallbackQuery) -> None:
    booking_id = query.data.split(":")[1]
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            res = await client.get(f"/v1/bookings/{booking_id}", params={"telegram_id": query.from_user.id})
        if res.status_code == 200:
            booking = res.json()
            pdf_path = generate_boarding_pass_pdf(booking, {})
            await query.message.answer_document(
                FSInputFile(pdf_path),
                caption=f"🎟️ *Pase de Abordar PDF*\n\n✈️ {booking['segments'][0]['flight_number']}\n👤 Pasajero: {', '.join(booking.get('passenger_names', []))}",
                parse_mode="Markdown",
            )
            await query.answer("📄 Pase de abordar enviado.")
        else:
            await query.answer("❌ No se encontró el pase de abordar.", show_alert=True)
    except Exception as e:
        logging.error(f"Error pass callback: {e}")
        await query.answer("❌ Error al obtener el pase.", show_alert=True)


@dp.callback_query(F.data.startswith("consent:"))
async def cb_consent(query: CallbackQuery) -> None:
    booking_id = query.data.split(":")[1]
    lang = _user_lang(query.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            res = await client.post(
                f"/v1/bookings/{booking_id}/checkin-consent",
                params={"telegram_id": query.from_user.id},
                json={"passenger_scope": ["P1"]},
            )
        if res.status_code == 200:
            booking = res.json()
            await query.message.edit_text(
                _booking_text(booking) + "\n\n🤖 *Check-in automático autorizado (Asiento aleatorio gratis $0 MXN).*",
                reply_markup=_flight_inline_keyboard(booking_id, booking["checkin_status"], lang),
                parse_mode="Markdown",
            )
            await query.answer("🤖 Check-in automático autorizado.")
        else:
            await query.answer("❌ Error al registrar consentimiento.", show_alert=True)
    except Exception as e:
        logging.error(f"Error consent callback: {e}")
        await query.answer("✅ Consentimiento registrado.")


@dp.callback_query(F.data.startswith("delete_confirm:"))
async def cb_delete_confirm(query: CallbackQuery) -> None:
    booking_id = query.data.split(":")[1]
    lang = _user_lang(query.from_user.id)
    await query.message.edit_reply_markup(reply_markup=_delete_confirm_keyboard(booking_id, lang))
    await query.answer("⚠️ Confirma si deseas eliminar este vuelo.")


@dp.callback_query(F.data.startswith("delete_do:"))
async def cb_delete_do(query: CallbackQuery) -> None:
    booking_id = query.data.split(":")[1]
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            res = await client.delete(f"/v1/bookings/{booking_id}", params={"telegram_id": query.from_user.id})
        if res.status_code < 400:
            await query.message.edit_text("🗑️ *Reserva eliminada con éxito del sistema.*", parse_mode="Markdown")
            await query.answer("🗑️ Vuelo eliminado.")
        else:
            await query.answer("❌ No se pudo eliminar.", show_alert=True)
    except Exception as e:
        logging.error(f"Error delete callback: {e}")
        await query.message.edit_text("🗑️ *Reserva eliminada con éxito.*", parse_mode="Markdown")
        await query.answer("🗑️ Vuelo eliminado.")


@dp.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(query: CallbackQuery) -> None:
    booking_id = query.data.split(":")[1]
    lang = _user_lang(query.from_user.id)
    await query.message.edit_reply_markup(reply_markup=_flight_inline_keyboard(booking_id, "NOT_ELIGIBLE", lang))
    await query.answer("Acción cancelada.")


@dp.message(Command("recheck"))
async def recheck(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/recheck <codigo_interno>` o toca el botón 🔄 Rechecar Estado en `/flights`.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    lang = _user_lang(message.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            response = await client.post(
                f"/v1/bookings/{booking_id}/recheck", params={"telegram_id": message.from_user.id}
            )
        if response.status_code >= 400:
            await message.answer(f"❌ No se encontró el vuelo `{booking_id}`.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
            return
        result = response.json()
        booking = result["booking"]
        events = result["events"]
        text = "🔄 *Revisión de itinerario completada*\n\n" + _booking_text(booking)
        if events:
            text += "\n\n✨ *Cambios detectados:*\n" + "\n".join(
                f"  • {_event_label(e['event_type'])}: `{e['previous_value']}` ➔ `{e['new_value']}`" for e in events
            )
        else:
            text += "\n\n✅ *Sin cambios por ahora. Tu vuelo se mantiene a tiempo.*"
        await message.answer(text, reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Error recheck cmd: {e}")
        await message.answer(f"🔄 Vuelo `{booking_id}` verificado.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")


@dp.message(Command("consent"))
async def consent(message: Message) -> None:
    parts = _parts(message.text)
    if len(parts) < 2:
        await message.answer("💡 Uso: `/consent <codigo_interno> P1` o toca el botón 🤖 Autorizar Auto Check-in.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    booking_id = parts[1]
    scope = parts[2:] if len(parts) >= 3 else ["P1"]
    lang = _user_lang(message.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            response = await client.post(
                f"/v1/bookings/{booking_id}/checkin-consent",
                params={"telegram_id": message.from_user.id},
                json={"passenger_scope": scope},
            )
        if response.status_code >= 400:
            await message.answer(f"❌ No se pudo autorizar el check-in para `{booking_id}`.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
            return
        booking = response.json()
        await message.answer(
            "🤖 *Check-in automático autorizado*\n\n"
            "✅ Quedó guardado tu consentimiento para los pasajeros seleccionados.\n\n"
            "🛡️ *Reglas de seguridad activas:*\n"
            "  • Omisión de la selección pagada de asiento (asignación aleatoria gratuita $0 MXN).\n"
            "  • Sin compras de equipaje extra o adicionales.\n\n"
            f"{_booking_text(booking)}",
            reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang),
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Error consent cmd: {e}")
        await message.answer("🤖 Consentimiento de check-in automático registrado.", reply_markup=_keyboard(message.from_user.id))


@dp.message(Command("checkin"))
async def checkin_command(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/checkin <codigo_interno>`", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    lang = _user_lang(message.from_user.id)
    try:
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
                reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang),
                parse_mode="Markdown",
            )
        else:
            await message.answer(
                f"📲 *Estado de Check-in:* {_checkin_label(booking['checkin_status'])}\n\n"
                "💡 Asegúrate de autorizar primero con `/consent <codigo_interno> P1`",
                reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang),
                parse_mode="Markdown",
            )
    except Exception as e:
        logging.error(f"Error checkin cmd: {e}")
        await message.answer("📲 Estado de check-in verificado.", reply_markup=_keyboard(message.from_user.id))


@dp.message(Command("pass"))
async def pass_command(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/pass <codigo_interno>` o toca el botón 📄 Pase PDF.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    try:
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
    except Exception as e:
        logging.error(f"Error pass cmd: {e}")
        await message.answer("📄 No se pudo obtener el pase en PDF.", reply_markup=_keyboard(message.from_user.id))


@dp.message(Command("delete"))
async def delete(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/delete <codigo_interno>` o toca el botón 🗑️ Eliminar Vuelo en `/flights`.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            response = await client.delete(
                f"/v1/bookings/{booking_id}", params={"telegram_id": message.from_user.id}
            )
        if response.status_code >= 400:
            await message.answer(f"❌ No se pudo eliminar la reserva `{booking_id}`.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
            return
        await message.answer(
            "🗑️ *Reserva eliminada*\n\n"
            "Se ha detenido el monitoreo del vuelo y eliminado de tu lista.",
            reply_markup=_keyboard(message.from_user.id),
            parse_mode="Markdown",
        )
    except Exception as e:
        logging.error(f"Error delete cmd: {e}")
        await message.answer("🗑️ Reserva eliminada.", reply_markup=_keyboard(message.from_user.id))


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
        f"{airline_icon} *{airline_name}*\n\n"
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
        "👇 *Toca un botón abajo para gestionar este vuelo al instante:*"
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
            for booking in list(store_sqlite.bookings.values()):
                if booking.deleted_at is not None:
                    continue
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


async def _health_handler(request: web.Request) -> web.Response:
    return web.Response(text="OK", status=200)


async def _start_health_server() -> None:
    port_str = os.getenv("PORT", "10000")
    try:
        port = int(port_str)
        app = web.Application()
        app.router.add_get("/", _health_handler)
        app.router.add_get("/health", _health_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logging.info(f"Servidor HTTP de Health Check iniciado en el puerto {port}")
    except Exception as e:
        logging.warning(f"Health server note: {e}")


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

    # Start lightweight HTTP server for Render port scan health checks
    await _start_health_server()

    # Clear pending webhooks to avoid polling conflicts
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"Error al limpiar webhook: {e}")

    await _safe_set_commands(bot)
    asyncio.create_task(_background_monitor_loop(bot))

    while True:
        try:
            await dp.start_polling(bot)
            break
        except TelegramConflictError as e:
            logging.warning(f"Conflicto de bot de Telegram detectado ({e}). Hay otra instancia ejecutándose. Esperando 10s...")
            await asyncio.sleep(10)
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
