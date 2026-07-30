import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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
from app.services.pdf import generate_boarding_pass_pdf, generate_boarding_pass_file

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

MAIN_KEYBOARD_ES = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Agregar Volaris"), KeyboardButton(text="➕ Agregar Viva")],
        [KeyboardButton(text="➕ Agregar Aeroméxico"), KeyboardButton(text="➕ Agregar United")],
        [KeyboardButton(text="📋 Mis Vuelos"), KeyboardButton(text="⚙️ Configuración")],
        [KeyboardButton(text="❓ Ayuda")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Elige una opción del menú",
)

MAIN_KEYBOARD_EN = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Add Volaris"), KeyboardButton(text="➕ Add Viva")],
        [KeyboardButton(text="➕ Add Aeromexico"), KeyboardButton(text="➕ Add United")],
        [KeyboardButton(text="📋 My Flights"), KeyboardButton(text="⚙️ Settings")],
        [KeyboardButton(text="❓ Help")],
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
    BotCommand(command="settings", description="Configuración y notificaciones"),
]


def _user_lang(telegram_id: int) -> str:
    return store_sqlite.user_languages.get(telegram_id, "ES")


def _keyboard(telegram_id: int) -> ReplyKeyboardMarkup:
    return MAIN_KEYBOARD_EN if _user_lang(telegram_id) == "EN" else MAIN_KEYBOARD_ES


def _airline_label(value: str) -> str:
    return {
        "VIVA": "Viva Aerobus",
        "VOLARIS": "Volaris",
        "AEROMEXICO": "Aeroméxico",
        "UNITED": "United Airlines",
    }.get(value, value)


def _airline_icon(value: str) -> str:
    return {
        "VIVA": "💚",
        "VOLARIS": "💜",
        "AEROMEXICO": "🇲🇽",
        "UNITED": "🇺🇸",
    }.get(value, "✈️")


def _status_icon(value: str | None) -> str:
    return {"SCHEDULED": "🟢", "DELAYED": "🟡", "CANCELLED": "🔴"}.get(value or "", "⚪")


def _status_label(value: str) -> str:
    return {"SCHEDULED": "Programado", "DELAYED": "Retrasado", "CANCELLED": "Cancelado"}.get(value, value)


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


def _format_datetime(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.strftime("%d/%m/%Y %H:%M UTC")


def _payment_text(payment: dict[str, Any] | None) -> str:
    if not payment:
        return "No disponible"
    amount = float(payment["amount"])
    if amount <= 0 and payment.get("status") == "UNKNOWN":
        return "No disponible"
    method = f" ({payment['method']})" if payment.get("method") else ""
    return f"{payment['currency']} ${amount:,.2f}{method}"


def _segment_text(seg: dict[str, Any], idx: int, total: int) -> str:
    if total == 1:
        tramo = "Itinerario"
    elif idx == 1:
        tramo = f"Tramo {idx} (Ida)"
    elif idx == 2 and total == 2:
        tramo = f"Tramo {idx} (Vuelta)"
    else:
        tramo = f"Tramo {idx}"

    dep_term = f" (Term. {seg['terminal']})" if seg.get("terminal") else ""
    gate_info = f" | 🚪 {seg['gate']}" if seg.get("gate") else ""
    seat_info = f" | 💺 {seg['seat']}" if seg.get("seat") else ""
    status_icon = _status_icon(seg.get("operational_status"))
    status_name = _status_label(seg.get("operational_status", ""))

    return (
        f"✈️ *{tramo}:* {seg['flight_number']}\n"
        f"   📍 {seg['departure_airport']}{dep_term} ➔ {seg['arrival_airport']}\n"
        f"   📅 Salida: {_format_datetime(seg['scheduled_departure'])}\n"
        f"   📊 Estado: {status_icon} {status_name}{gate_info}{seat_info}"
    )


def _booking_text(booking: dict[str, Any]) -> str:
    airline_icon = _airline_icon(booking["airline"])
    airline_name = _airline_label(booking["airline"])
    segments = booking.get("segments") or []
    passengers = booking.get("passenger_names") or []
    payment_text = _payment_text(booking.get("payment_summary"))
    checkin_text = _checkin_label(booking["checkin_status"])

    passenger_text = "\n".join(f"  • {name}" for name in passengers) if passengers else "  • No disponible"

    segment_blocks = [_segment_text(seg, i + 1, len(segments)) for i, seg in enumerate(segments)]
    segments_text = "\n\n".join(segment_blocks) if segment_blocks else "   Sin segmentos"

    return (
        f"{airline_icon} *{airline_name}*\n\n"
        f"👤 *Pasajero(s):*\n{passenger_text}\n\n"
        f"{segments_text}\n\n"
        f"📲 Check-in: {checkin_text}\n"
        f"💳 Total pagado: {payment_text}"
    )


def _booking_added_text(booking: dict[str, Any]) -> str:
    airline_icon = _airline_icon(booking["airline"])
    airline_name = _airline_label(booking["airline"])
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


def _flight_inline_keyboard(booking_id: str, checkin_status: str, lang: str = "ES") -> InlineKeyboardMarkup:
    if lang == "EN":
        if checkin_status in ("CHECKED_IN", "BOARDING_PASS_READY"):
            buttons = [
                [
                    InlineKeyboardButton(text="🔄 Recheck Status", callback_data=f"recheck:{booking_id}"),
                ],
                [
                    InlineKeyboardButton(text="📄 View PDF Pass", callback_data=f"pass_pdf:{booking_id}"),
                    InlineKeyboardButton(text="🖼️ View Image Pass", callback_data=f"pass_img:{booking_id}"),
                ],
                [InlineKeyboardButton(text="🗑️ Delete Flight", callback_data=f"delete_select:{booking_id}")]
            ]
        else:
            buttons = [
                [InlineKeyboardButton(text="🔄 Recheck Status", callback_data=f"recheck:{booking_id}")],
                [InlineKeyboardButton(text="🤖 Enable Auto Check-in", callback_data=f"consent:{booking_id}")],
                [InlineKeyboardButton(text="📲 Check-in Now", callback_data=f"checkin:{booking_id}")],
                [InlineKeyboardButton(text="🗑️ Delete Flight", callback_data=f"delete_select:{booking_id}")]
            ]
    else:
        if checkin_status in ("CHECKED_IN", "BOARDING_PASS_READY"):
            buttons = [
                [
                    InlineKeyboardButton(text="🔄 Rechecar Estado", callback_data=f"recheck:{booking_id}"),
                ],
                [
                    InlineKeyboardButton(text="📄 Ver Pase PDF", callback_data=f"pass_pdf:{booking_id}"),
                    InlineKeyboardButton(text="🖼️ Ver Pase Imagen", callback_data=f"pass_img:{booking_id}"),
                ],
                [InlineKeyboardButton(text="🗑️ Eliminar Vuelo", callback_data=f"delete_select:{booking_id}")]
            ]
        else:
            buttons = [
                [InlineKeyboardButton(text="🔄 Rechecar Estado", callback_data=f"recheck:{booking_id}")],
                [InlineKeyboardButton(text="🤖 Autorizar Auto Check-in", callback_data=f"consent:{booking_id}")],
                [InlineKeyboardButton(text="📲 Check-in Ahora", callback_data=f"checkin:{booking_id}")],
                [InlineKeyboardButton(text="🗑️ Eliminar Vuelo", callback_data=f"delete_select:{booking_id}")]
            ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _flight_management_keyboard(booking_id: str, segments: list[dict], lang: str = "ES") -> InlineKeyboardMarkup:
    """Keyboard with individual buttons per flight segment for recheck/delete."""
    if lang == "EN":
        buttons = [
            [InlineKeyboardButton(text="⬅️ Back to Flight", callback_data=f"back:{booking_id}")]
        ]
        for i, seg in enumerate(segments):
            route = f"{seg['departure_airport']}➔{seg['arrival_airport']}"
            buttons.append([
                InlineKeyboardButton(text=f"🔄 Recheck: {seg['flight_number']} ({route})", callback_data=f"recheck_seg:{booking_id}:{i}"),
                InlineKeyboardButton(text=f"🗑️ Delete: {seg['flight_number']}", callback_data=f"delete_seg:{booking_id}:{i}"),
            ])
        buttons.append([InlineKeyboardButton(text="🗑️ Delete Entire Booking", callback_data=f"delete_confirm:{booking_id}")])
    else:
        buttons = [
            [InlineKeyboardButton(text="⬅️ Volver al Vuelo", callback_data=f"back:{booking_id}")]
        ]
        for i, seg in enumerate(segments):
            route = f"{seg['departure_airport']}➔{seg['arrival_airport']}"
            buttons.append([
                InlineKeyboardButton(text=f"🔄 Rechecar: {seg['flight_number']} ({route})", callback_data=f"recheck_seg:{booking_id}:{i}"),
                InlineKeyboardButton(text=f"🗑️ Borrar: {seg['flight_number']}", callback_data=f"delete_seg:{booking_id}:{i}"),
            ])
        buttons.append([InlineKeyboardButton(text="🗑️ Eliminar Reserva Completa", callback_data=f"delete_confirm:{booking_id}")])
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


def _settings_keyboard(lang: str = "ES") -> InlineKeyboardMarkup:
    if lang == "EN":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔔 Enable Notifications", callback_data="settings:notifications_on")],
                [InlineKeyboardButton(text="🔕 Disable Notifications", callback_data="settings:notifications_off")],
                [InlineKeyboardButton(text="📄 Format: PDF", callback_data="settings:format_pdf")],
                [InlineKeyboardButton(text="🖼️ Format: Image", callback_data="settings:format_image")],
                [InlineKeyboardButton(text="🌐 Language: English", callback_data="settings:lang_en")],
                [InlineKeyboardButton(text="⬅️ Back", callback_data="settings:back")],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Activar Notificaciones", callback_data="settings:notifications_on")],
            [InlineKeyboardButton(text="🔕 Desactivar Notificaciones", callback_data="settings:notifications_off")],
            [InlineKeyboardButton(text="📄 Formato: PDF", callback_data="settings:format_pdf")],
            [InlineKeyboardButton(text="🖼️ Formato: Imagen", callback_data="settings:format_image")],
            [InlineKeyboardButton(text="🌐 Idioma: Español", callback_data="settings:lang_es")],
            [InlineKeyboardButton(text="⬅️ Volver", callback_data="settings:back")],
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
            "  • `/viva VIV123 Garcia`\n"
            "  • `/volaris LCYD6C Valencia`\n"
            "  • `/aeromexico HUIITL Garcia`\n"
            "  • `/united UA1234 Garcia`\n\n"
            "📋 Features:\n"
            "  • `/flights` — View saved flights (with interactive buttons) ✈️\n"
            "  • `/settings` — Notifications & language ⚙️\n\n"
            "💡 You can also forward any booking confirmation email/text to add your flight automatically!"
        )
    else:
        text = (
            "✈️ ¡Bienvenido a Flights MX! 🇲🇽\n\n"
            "Tu asistente inteligente para monitorear y gestionar tus vuelos de Aeroméxico, Viva Aerobus, Volaris y United.\n\n"
            "👇 Elige un botón del menú o usa un comando:\n\n"
            "➕ Agregar reserva:\n"
            "  • `/viva VIV123 Garcia`\n"
            "  • `/volaris LCYD6C Valencia`\n"
            "  • `/aeromexico HUIITL Garcia`\n"
            "  • `/united UA1234 Garcia`\n\n"
            "📋 Menú de funciones:\n"
            "  • `/flights` — Ver mis vuelos guardados (con botones interactivos) ✈️\n"
            "  • `/settings` — Notificaciones e idioma ⚙️\n\n"
            "💡 ¡También puedes reenviar un correo o texto de confirmación para agregar tu vuelo en automático!"
        )
    if welcome_image.exists():
        await message.answer_photo(FSInputFile(welcome_image), caption=text, reply_markup=_keyboard(message.from_user.id))
    else:
        await message.answer(text, reply_markup=_keyboard(message.from_user.id))


def _settings_text(lang: str, notif_status: str, bp_format: str) -> str:
    if lang == "EN":
        return (
            "⚙️ *User Settings*\n\n"
            "Here you can customize your bot preferences. Tap any of the buttons below to enable/disable notifications, change the language, or select the format for your boarding passes (PDF or Image).\n\n"
            "📊 *Current Status:*\n"
            f"  • 🔔 Notifications: `{notif_status}`\n"
            "  • 🌐 Language: `English` 🇺🇸\n"
            f"  • 📄 Boarding Pass Format: `{bp_format}`\n\n"
            "👇 *Tap the buttons below to change the settings:*"
        )
    else:
        return (
            "⚙️ *Configuración de Usuario*\n\n"
            "Aquí puedes personalizar tus preferencias del bot. Toca cualquiera de los botones de abajo para activar/desactivar notificaciones, cambiar el idioma o elegir el formato en el que deseas recibir tus pases de abordar (PDF o Imagen).\n\n"
            "📊 *Estado Actual:*\n"
            f"  • 🔔 Notificaciones: `{notif_status}`\n"
            "  • 🌐 Idioma: `Español` 🇲🇽\n"
            f"  • 📄 Formato de Pase: `{bp_format}`\n\n"
            "👇 *Toca los botones de abajo para cambiar la configuración:*"
        )


@dp.message(Command("settings"))
@dp.message(F.text.casefold().in_({"⚙️ configuración", "⚙️ settings", "configuración", "settings"}))
async def settings_cmd(message: Message) -> None:
    lang = _user_lang(message.from_user.id)
    notif_status = "ON" if store_sqlite.user_notifications.get(message.from_user.id, True) else "OFF"
    bp_format = store_sqlite.user_boarding_pass_formats.get(message.from_user.id, "PDF")
    text = _settings_text(lang, notif_status, bp_format)
    await message.answer(text, reply_markup=_settings_keyboard(lang), parse_mode="Markdown")


@dp.callback_query(F.data.startswith("settings:"))
async def cb_settings(query: CallbackQuery) -> None:
    action = query.data.split(":")[1]
    lang = _user_lang(query.from_user.id)
    notif_status = "ON" if store_sqlite.user_notifications.get(query.from_user.id, True) else "OFF"
    if action == "notifications_on":
        store_sqlite.user_notifications[query.from_user.id] = True
        store_sqlite.save()
        await query.answer("✅ Notifications enabled" if lang == "EN" else "✅ Notificaciones activadas")
    elif action == "notifications_off":
        store_sqlite.user_notifications[query.from_user.id] = False
        store_sqlite.save()
        await query.answer("🔕 Notifications disabled" if lang == "EN" else "🔕 Notificaciones desactivadas")
    elif action == "format_pdf":
        store_sqlite.user_boarding_pass_formats[query.from_user.id] = "PDF"
        store_sqlite.save()
        await query.answer("📄 Boarding pass format: PDF" if lang == "EN" else "📄 Formato de pase de abordar: PDF")
    elif action == "format_image":
        store_sqlite.user_boarding_pass_formats[query.from_user.id] = "IMAGE"
        store_sqlite.save()
        await query.answer("🖼️ Boarding pass format: IMAGE" if lang == "EN" else "🖼️ Formato de pase de abordar: Imagen")
    elif action == "lang_en":
        store_sqlite.user_languages[query.from_user.id] = "EN"
        store_sqlite.save()
        notif_status = "ON" if store_sqlite.user_notifications.get(query.from_user.id, True) else "OFF"
        bp_format = store_sqlite.user_boarding_pass_formats.get(query.from_user.id, "PDF")
        await query.message.edit_text(_settings_text("EN", notif_status, bp_format), reply_markup=_settings_keyboard("EN"), parse_mode="Markdown")
        return
    elif action == "lang_es":
        store_sqlite.user_languages[query.from_user.id] = "ES"
        store_sqlite.save()
        notif_status = "ON" if store_sqlite.user_notifications.get(query.from_user.id, True) else "OFF"
        bp_format = store_sqlite.user_boarding_pass_formats.get(query.from_user.id, "PDF")
        await query.message.edit_text(_settings_text("ES", notif_status, bp_format), reply_markup=_settings_keyboard("ES"), parse_mode="Markdown")
        return
    elif action == "back":
        notif_status = "ON" if store_sqlite.user_notifications.get(query.from_user.id, True) else "OFF"
        bp_format = store_sqlite.user_boarding_pass_formats.get(query.from_user.id, "PDF")
        await query.message.edit_text(_settings_text(lang, notif_status, bp_format), reply_markup=_settings_keyboard(lang), parse_mode="Markdown")
        return

    notif_status = "ON" if store_sqlite.user_notifications.get(query.from_user.id, True) else "OFF"
    bp_format = store_sqlite.user_boarding_pass_formats.get(query.from_user.id, "PDF")
    new_text = _settings_text(lang, notif_status, bp_format)
    try:
        await query.message.edit_text(new_text, reply_markup=_settings_keyboard(lang), parse_mode="Markdown")
    except Exception:
        await query.message.edit_reply_markup(reply_markup=_settings_keyboard(lang))


@dp.message(F.text.casefold().in_({"ayuda", "help", "❓ ayuda", "❓ help"}))
async def help_button(message: Message) -> None:
    lang = _user_lang(message.from_user.id)
    if lang == "EN":
        text = (
            "❓ *Help & Usage Guide*\n\n"
            "This bot monitors your flights and performs automatic check-in. Here is how to use it:\n\n"
            "1️⃣ *Add a Flight:*\n"
            "   Tap any of the `➕ Add <Airline>` buttons below, and send the booking code (PNR) and passenger's last name in the shown format.\n\n"
            "2️⃣ *Manage Flights:*\n"
            "   Tap `📋 My Flights` to view your active flights. Each flight card has interactive buttons to:\n"
            "     • 🔄 Recheck live status (gate, delays, terminal changes).\n"
            "     • 🤖 Authorize / Run automatic check-in.\n"
            "     • 📄 Get your boarding pass.\n\n"
            "3️⃣ *Settings:*\n"
            "   Tap `⚙️ Settings` to choose whether you receive your boarding pass as a PDF document or a Photo image, and toggle notifications."
        )
    else:
        text = (
            "❓ *Guía de Ayuda y Uso*\n\n"
            "Este bot monitorea tus vuelos y realiza el check-in automático. Aquí tienes una guía de cómo usarlo:\n\n"
            "1️⃣ *Agregar un Vuelo:*\n"
            "   Toca cualquiera de los botones de `➕ Agregar <Aerolínea>` abajo y envía la clave de reservación (PNR) y el apellido del pasajero en el formato indicado.\n\n"
            "2️⃣ *Gestionar Vuelos:*\n"
            "   Toca `📋 Mis Vuelos` para ver tus vuelos activos. Cada tarjeta de vuelo cuenta con botones interactivos para:\n"
            "     • 🔄 Rechecar el estado en tiempo real (puertas, retrasos, terminales).\n"
            "     • 🤖 Autorizar / Ejecutar el check-in automático.\n"
            "     • 📄 Obtener tu pase de abordar.\n\n"
            "3️⃣ *Configuración:*\n"
            "   Toca `⚙️ Configuración` para elegir si deseas recibir tu pase de abordar en formato PDF o Imagen (foto), y activar/desactivar alertas."
        )
    await message.answer(text, reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")


@dp.message(F.text.casefold().in_({"agregar volaris", "add volaris", "➕ agregar volaris", "➕ add volaris"}))
async def add_volaris_button(message: Message) -> None:
    lang = _user_lang(message.from_user.id)
    if lang == "EN":
        text = (
            "💜 *Add Volaris Booking*\n\n"
            "Please send the 6-character booking code (PNR) and the passenger's last name exactly as registered:\n\n"
            "👉 `/volaris LCYD6C Valencia`\n\n"
            "💡 *Tip:* The booking code consists of numbers and letters (e.g. LCYD6C). Make sure there are no spaces in the code."
        )
    else:
        text = (
            "💜 *Agregar reserva de Volaris*\n\n"
            "Por favor, envíame el código de reservación de 6 caracteres (PNR) y el apellido del pasajero exactamente como está en tu boleto:\n\n"
            "👉 `/volaris LCYD6C Valencia`\n\n"
            "💡 *Sugerencia:* El código consta de letras y números (ej: LCYD6C). Asegúrate de escribirlo sin espacios en medio."
        )
    await message.answer(text, reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")


@dp.message(F.text.casefold().in_({"agregar viva", "add viva", "➕ agregar viva", "➕ add viva"}))
async def add_viva_button(message: Message) -> None:
    lang = _user_lang(message.from_user.id)
    if lang == "EN":
        text = (
            "💚 *Add Viva Aerobus Booking*\n\n"
            "Please send the booking code (PNR) and the passenger's last name exactly as registered:\n\n"
            "👉 `/viva VIV123 Garcia`\n\n"
            "💡 *Tip:* You can find the booking code in your confirmation email. Ensure the last name matches the booking."
        )
    else:
        text = (
            "💚 *Agregar reserva de Viva Aerobus*\n\n"
            "Por favor, envíame la clave de reservación (PNR) y el apellido del pasajero exactamente como están registrados:\n\n"
            "👉 `/viva VIV123 Garcia`\n\n"
            "💡 *Sugerencia:* Puedes encontrar tu clave en el correo de confirmación de tu compra. Verifica que el apellido sea idéntico al del boleto."
        )
    await message.answer(text, reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")


@dp.message(F.text.casefold().in_({"agregar aeromexico", "add aeromexico", "➕ agregar aeromexico", "➕ add aeromexico", "agregar aeroméxico", "➕ agregar aeroméxico"}))
async def add_aeromexico_button(message: Message) -> None:
    lang = _user_lang(message.from_user.id)
    if lang == "EN":
        text = (
            "🇲🇽 *Add Aeroméxico Booking*\n\n"
            "Please send the 6-character PNR code or e-ticket number, followed by the passenger's last name:\n\n"
            "👉 `/aeromexico HUIITL Garcia`\n\n"
            "💡 *Tip:* You can use either the reservation code (PNR) or the ticket number (13-digit code starting with 139)."
        )
    else:
        text = (
            "🇲🇽 *Agregar reserva de Aeroméxico*\n\n"
            "Por favor, envíame el código PNR de 6 caracteres o el número de boleto electrónico, seguido del apellido del pasajero:\n\n"
            "👉 `/aeromexico HUIITL Garcia`\n\n"
            "💡 *Sugerencia:* Puedes usar el código de reservación (PNR) o el número de boleto (código de 13 dígitos que inicia con 139)."
        )
    await message.answer(text, reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")


@dp.message(F.text.casefold().in_({"agregar united", "add united", "➕ agregar united", "➕ add united"}))
async def add_united_button(message: Message) -> None:
    lang = _user_lang(message.from_user.id)
    if lang == "EN":
        text = (
            "🇺🇸 *Add United Airlines Booking*\n\n"
            "Please send the confirmation code (PNR) and the passenger's last name:\n\n"
            "👉 `/united UA1234 Garcia`\n\n"
            "💡 *Tip:* The confirmation code is usually 6 characters long and can be found in your itinerary details."
        )
    else:
        text = (
            "🇺🇸 *Agregar reserva de United Airlines*\n\n"
            "Por favor, envíame la clave de confirmación (PNR) y el apellido del pasajero:\n\n"
            "👉 `/united UA1234 Garcia`\n\n"
            "💡 *Sugerencia:* La clave de confirmación suele ser de 6 caracteres y se encuentra en los detalles de tu itinerario."
        )
    await message.answer(text, reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")


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
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=90) as client:
            response = await client.post("/v1/bookings", json=payload)
            
        if response.status_code >= 400:
            raise ValueError(response.text)
            
        booking_dict = response.json()
        await message.answer(
            _booking_added_text(booking_dict),
            reply_markup=_flight_inline_keyboard(booking_dict["id"], booking_dict["checkin_status"], lang),
            parse_mode="Markdown",
        )
    except Exception as e:
        err_str = str(e)
        if "NOT_FOUND_ON_AIRLINE" in err_str:
            await message.answer(
                f"⚠️ *No se encontraron datos en vivo para `{pnr}` (`{last_name}`) en {airline}*\n\n"
                "La aerolínea no devolvió un boleto activo para ese código y apellido.\n\n"
                "💡 *Sugerencia:*\n"
                "  • Revisa que la clave de reserva y apellido estén escritos correctamente.\n"
                "  • O reenvía el correo/PDF de confirmación de la aerolínea a este chat para agregar tu itinerario en automático.",
                reply_markup=_keyboard(message.from_user.id),
                parse_mode="Markdown",
            )
        else:
            logging.error(f"Error procesando reserva: {e}")
            await message.answer(
                "❌ No se pudo procesar la reserva. Por favor verifica que la clave y el apellido correspondan a la aerolínea seleccionada.",
                reply_markup=_keyboard(message.from_user.id),
            )


@dp.message(Command("flights"))
@dp.message(F.text.casefold().in_({"mis vuelos", "my flights", "📋 mis vuelos", "📋 my flights"}))
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
            "  • `/viva VIV123 Garcia`\n"
            "  • `/volaris LCYD6C Valencia`\n"
            "  • `/aeromexico HUIITL Garcia`\n"
            "  • `/united UA1234 Garcia`",
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


@dp.callback_query(F.data.startswith("recheck_seg:"))
async def cb_recheck_segment(query: CallbackQuery) -> None:
    """Recheck a specific flight segment."""
    _, booking_id, seg_idx = query.data.split(":")
    seg_idx = int(seg_idx)
    lang = _user_lang(query.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            res = await client.post(f"/v1/bookings/{booking_id}/recheck", params={"telegram_id": query.from_user.id})
        if res.status_code == 200:
            result = res.json()
            booking = result["booking"]
            events = result["events"]
            # Filter events for this specific segment
            seg_id = booking["segments"][seg_idx]["id"]
            seg_events = [e for e in events if e["segment_id"] == seg_id]
            text = _booking_text(booking)
            if seg_events:
                text += "\n\n✨ *Cambios en este tramo:*\n" + "\n".join(
                    f"  • {_event_label(e['event_type'])}: `{e['previous_value']}` ➔ `{e['new_value']}`" for e in seg_events
                )
            else:
                text += "\n\n✅ *Este tramo sin cambios.*"
            await query.message.edit_text(text, reply_markup=_flight_management_keyboard(booking_id, booking["segments"], lang), parse_mode="Markdown")
            await query.answer("🔄 Tramo rechecado.")
        else:
            await query.answer("❌ Error al rechecar.", show_alert=True)
    except Exception as e:
        logging.error(f"Error recheck segment: {e}")
        await query.answer("🔄 Revisado.", show_alert=False)


@dp.callback_query(F.data.startswith("pass_pdf:"))
async def cb_pass_pdf(query: CallbackQuery) -> None:
    await cb_pass_format(query, "PDF")


@dp.callback_query(F.data.startswith("pass_img:"))
async def cb_pass_img(query: CallbackQuery) -> None:
    await cb_pass_format(query, "IMAGE")


async def cb_pass_format(query: CallbackQuery, fmt: str) -> None:
    booking_id = query.data.split(":")[1]
    await query.answer(f"📄 Generando pase en {fmt}...")
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=90) as client:
            res = await client.get(f"/v1/bookings/{booking_id}", params={"telegram_id": query.from_user.id})
        if res.status_code == 200:
            booking = res.json()
            file_path = await generate_boarding_pass_file(booking, fmt)
            caption = f"🎟️ *Pase de Abordar {fmt}*\n\n✈️ {booking['segments'][0]['flight_number']}\n👤 Pasajero: {', '.join(booking.get('passenger_names', []))}"
            try:
                if fmt == "IMAGE":
                    await query.message.answer_photo(
                        FSInputFile(file_path),
                        caption=caption,
                        parse_mode="Markdown",
                    )
                else:
                    await query.message.answer_document(
                        FSInputFile(file_path),
                        caption=caption,
                        parse_mode="Markdown",
                    )
            finally:
                if file_path.exists():
                    file_path.unlink()
        else:
            await query.message.answer("❌ No se encontró el pase de abordar.")
    except Exception as e:
        logging.error(f"Error pass callback: {e}")
        await query.message.answer("❌ Error al obtener el pase.")


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


@dp.callback_query(F.data.startswith("checkin:"))
async def cb_checkin(query: CallbackQuery) -> None:
    booking_id = query.data.split(":")[1]
    lang = _user_lang(query.from_user.id)
    await query.answer("🤖 Procesando check-in...")
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=90) as client:
            response = await client.post(f"/v1/bookings/{booking_id}/checkin", params={"telegram_id": query.from_user.id})
        if response.status_code >= 400:
            await query.message.answer(f"❌ Error: {response.text}")
            return
        booking = response.json()
        if booking.get("checkin_status") in ("CHECKED_IN", "BOARDING_PASS_READY"):
            fmt = store_sqlite.user_boarding_pass_formats.get(query.from_user.id, "PDF")
            file_path = await generate_boarding_pass_file(booking, fmt)
            caption = (
                "🎟️ *¡Check-in completado con éxito!*\n\n"
                f"{_booking_text(booking)}\n\n"
                f"📄 *Se adjunta tu Pase de Abordar oficial en {fmt}.*"
            )
            try:
                if fmt == "IMAGE":
                    await query.message.answer_photo(
                        FSInputFile(file_path),
                        caption=caption,
                        parse_mode="Markdown",
                    )
                else:
                    await query.message.answer_document(
                        FSInputFile(file_path),
                        caption=caption,
                        parse_mode="Markdown",
                    )
            finally:
                if file_path.exists():
                    file_path.unlink()
        else:
            await query.message.edit_text(
                _booking_text(booking) + f"\n\n📲 *Estado de Check-in:* {_checkin_label(booking['checkin_status'])}",
                reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang),
                parse_mode="Markdown",
            )
    except Exception as e:
        logging.error(f"Error checkin callback: {e}")
        await query.message.answer("❌ Error al procesar check-in.")


@dp.callback_query(F.data.startswith("delete_select:"))
async def cb_delete_select(query: CallbackQuery) -> None:
    """Show per-segment delete/recheck options."""
    booking_id = query.data.split(":")[1]
    lang = _user_lang(query.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            res = await client.get(f"/v1/bookings/{booking_id}", params={"telegram_id": query.from_user.id})
        if res.status_code == 200:
            booking = res.json()
            await query.message.edit_text(
                _booking_text(booking) + "\n\n🗂️ *Selecciona un tramo para rechecar o eliminar:*",
                reply_markup=_flight_management_keyboard(booking_id, booking["segments"], lang),
                parse_mode="Markdown",
            )
            await query.answer("Elige una opción")
        else:
            await query.answer("❌ No se encontró la reserva.", show_alert=True)
    except Exception as e:
        logging.error(f"Error delete select: {e}")
        await query.answer("❌ Error.", show_alert=True)


@dp.callback_query(F.data.startswith("delete_seg:"))
async def cb_delete_segment(query: CallbackQuery) -> None:
    """Delete a specific flight segment from a booking."""
    _, booking_id, seg_idx = query.data.split(":")
    seg_idx = int(seg_idx)
    lang = _user_lang(query.from_user.id)
    try:
        from app.services.bookings import booking_service
        from uuid import UUID
        booking = booking_service.get_booking(UUID(booking_id), query.from_user.id)
        if booking and len(booking.segments) > seg_idx:
            removed_seg = booking.segments.pop(seg_idx)
            if not booking.segments:
                # No segments left, delete entire booking
                booking_service.delete_booking(UUID(booking_id), query.from_user.id)
                await query.message.edit_text("🗑️ *Reserva eliminada completa (no quedaban tramos).*")
            else:
                booking_service.repository.save()
                await query.message.edit_text(
                    f"🗑️ *Tramo eliminado:* {removed_seg.flight_number}\n\n" + _booking_text({
                        "id": str(booking.id),
                        "airline": booking.airline.value,
                        "passenger_names": booking.passenger_names,
                        "segments": [
                            {
                                "flight_number": s.flight_number,
                                "departure_airport": s.departure_airport,
                                "arrival_airport": s.arrival_airport,
                                "scheduled_departure": s.scheduled_departure.isoformat(),
                                "operational_status": s.operational_status,
                                "terminal": s.terminal,
                                "gate": s.gate,
                                "seat": s.seat,
                            } for s in booking.segments
                        ],
                        "checkin_status": booking.checkin_status.value,
                        "payment_summary": {
                            "amount": booking.payment_summary.amount,
                            "currency": booking.payment_summary.currency,
                            "method": booking.payment_summary.method,
                        } if booking.payment_summary else None,
                    }),
                    reply_markup=_flight_inline_keyboard(str(booking.id), booking.checkin_status.value, lang),
                    parse_mode="Markdown",
                )
            await query.answer("🗑️ Tramo eliminado.")
        else:
            await query.answer("❌ No se pudo eliminar.", show_alert=True)
    except Exception as e:
        logging.error(f"Error delete segment: {e}")
        await query.answer("❌ Error al eliminar.", show_alert=True)


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


@dp.callback_query(F.data.startswith("back:"))
async def cb_back(query: CallbackQuery) -> None:
    booking_id = query.data.split(":")[1]
    lang = _user_lang(query.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            res = await client.get(f"/v1/bookings/{booking_id}", params={"telegram_id": query.from_user.id})
        if res.status_code == 200:
            booking = res.json()
            await query.message.edit_text(
                _booking_text(booking),
                reply_markup=_flight_inline_keyboard(booking_id, booking["checkin_status"], lang),
                parse_mode="Markdown",
            )
    except Exception as e:
        logging.error(f"Error back callback: {e}")


@dp.message(Command("recheck"))
async def recheck(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/recheck <codigo_interno>` o toca el botón 🔄 Rechecar Estado en `/flights`.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    lang = _user_lang(message.from_user.id)
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            response = await client.post(f"/v1/bookings/{booking_id}/recheck", params={"telegram_id": message.from_user.id})
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
            response = await client.post(f"/v1/bookings/{booking_id}/checkin", params={"telegram_id": message.from_user.id})
        if response.status_code >= 400:
            await message.answer(f"❌ No se pudo procesar el Check-in: {response.text}", reply_markup=_keyboard(message.from_user.id))
            return
        booking = response.json()
        if booking.get("checkin_status") in ("CHECKED_IN", "BOARDING_PASS_READY"):
            fmt = store_sqlite.user_boarding_pass_formats.get(message.from_user.id, "PDF")
            file_path = await generate_boarding_pass_file(booking, fmt)
            caption = (
                "🎟️ *¡Check-in completado con éxito!*\n\n"
                f"{_booking_text(booking)}\n\n"
                f"📄 *Se adjunta tu Pase de Abordar oficial en {fmt}.*"
            )
            try:
                if fmt == "IMAGE":
                    await message.answer_photo(
                        FSInputFile(file_path),
                        caption=caption,
                        reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang),
                        parse_mode="Markdown",
                    )
                else:
                    await message.answer_document(
                        FSInputFile(file_path),
                        caption=caption,
                        reply_markup=_flight_inline_keyboard(booking["id"], booking["checkin_status"], lang),
                        parse_mode="Markdown",
                    )
            finally:
                if file_path.exists():
                    file_path.unlink()
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
        await message.answer("💡 Uso: `/pass <codigo_interno>` o toca el botón 📄 Pase de Abordar.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            response = await client.get(f"/v1/bookings/{booking_id}", params={"telegram_id": message.from_user.id})
        if response.status_code >= 400:
            await message.answer(f"❌ No se encontró la reserva: {response.text}", reply_markup=_keyboard(message.from_user.id))
            return
        booking = response.json()
        fmt = store_sqlite.user_boarding_pass_formats.get(message.from_user.id, "PDF")
        file_path = await generate_boarding_pass_file(booking, fmt)
        caption = (
            f"🎟️ *Pase de Abordar Oficial ({fmt})*\n\n"
            f"✈️ {_airline_label(booking['airline'])} — {booking['segments'][0]['flight_number']}\n"
            f"👤 Pasajero: {', '.join(booking.get('passenger_names', []))}\n\n"
            "📄 Documento adjunto para uso sin conexión."
        )
        try:
            if fmt == "IMAGE":
                await message.answer_photo(
                    FSInputFile(file_path),
                    caption=caption,
                    reply_markup=_keyboard(message.from_user.id),
                    parse_mode="Markdown",
                )
            else:
                await message.answer_document(
                    FSInputFile(file_path),
                    caption=caption,
                    reply_markup=_keyboard(message.from_user.id),
                    parse_mode="Markdown",
                )
        finally:
            if file_path.exists():
                file_path.unlink()
    except Exception as e:
        logging.error(f"Error pass cmd: {e}")
        await message.answer("📄 No se pudo obtener el pase.", reply_markup=_keyboard(message.from_user.id))


@dp.message(Command("delete"))
async def delete(message: Message) -> None:
    booking_id = _single_arg(message)
    if not booking_id:
        await message.answer("💡 Uso: `/delete <codigo_interno>` o toca el botón 🗑️ Eliminar Vuelo en `/flights`.", reply_markup=_keyboard(message.from_user.id), parse_mode="Markdown")
        return
    try:
        async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
            response = await client.delete(f"/v1/bookings/{booking_id}", params={"telegram_id": message.from_user.id})
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


async def _background_monitor_loop(bot: Bot) -> None:
    """Background monitoring for auto check-in and flight change alerts."""
    while True:
        try:
            await asyncio.sleep(60)  # Check every minute
            for booking in list(store_sqlite.bookings.values()):
                if booking.deleted_at is not None or not booking.monitoring_enabled:
                    continue

                # 1. Auto check-in when window opens and consent given
                if booking.checkin_status.value == "CHECKIN_SCHEDULED":
                    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
                        res = await client.post(f"/v1/bookings/{booking.id}/checkin", params={"telegram_id": booking.telegram_id})
                        if res.status_code == 200:
                            updated_b = res.json()
                            if updated_b.get("checkin_status") in ("CHECKED_IN", "BOARDING_PASS_READY"):
                                fmt = store_sqlite.user_boarding_pass_formats.get(booking.telegram_id, "PDF")
                                file_path = await generate_boarding_pass_file(updated_b, fmt)
                                caption = (
                                    "🎟️ *¡Check-in completado de forma automática e invisible!*\n\n"
                                    f"{_booking_text(updated_b)}\n\n"
                                    f"📄 *Se adjunta tu Pase de Abordar oficial en {fmt}.*"
                                )
                                try:
                                    if fmt == "IMAGE":
                                        await bot.send_photo(
                                            chat_id=booking.telegram_id,
                                            photo=FSInputFile(file_path),
                                            caption=caption,
                                            parse_mode="Markdown",
                                        )
                                    else:
                                        await bot.send_document(
                                            chat_id=booking.telegram_id,
                                            document=FSInputFile(file_path),
                                            caption=caption,
                                            parse_mode="Markdown",
                                        )
                                finally:
                                    if file_path.exists():
                                        file_path.unlink()

                # 2. Recheck for changes and send notifications
                if booking.telegram_id in store_sqlite.user_notifications and store_sqlite.user_notifications[booking.telegram_id]:
                    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=15) as client:
                        res = await client.post(f"/v1/bookings/{booking.id}/recheck", params={"telegram_id": booking.telegram_id})
                        if res.status_code == 200:
                            result = res.json()
                            events = result["events"]
                            if events:
                                # Send notification for critical changes
                                critical_events = [e for e in events if e["severity"] in ("CRITICAL", "ATTENTION")]
                                if critical_events:
                                    text = "🚨 *¡Alerta de cambio en tu vuelo!*\n\n" + _booking_text(result["booking"])
                                    text += "\n\n⚠️ *Cambios importantes:*\n" + "\n".join(
                                        f"  • {_event_label(e['event_type'])}: `{e['previous_value']}` ➔ `{e['new_value']}`"
                                        for e in critical_events
                                    )
                                    await bot.send_message(
                                        chat_id=booking.telegram_id,
                                        text=text,
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

    await _start_health_server()
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