# bot.py - Travel Check-In Bot
"""Main bot application for Travel Check-In Bot."""

import logging
from datetime import datetime
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

from config import (
    BOT_TOKEN, GROUP_CHAT_ID, EMERGENCY_CONTACT_ID,
    OVERDUE_BUFFER_MINUTES, SAFE_EXTENSION_MINUTES
)
from database import (
    init_db, create_trip, get_active_trip, get_trip,
    update_trip_status, increment_overdue_count,
    get_or_create_user, set_emergency_contact
)
from scheduler import setup_scheduler
from helpers import now_utc, now_local, utc_to_local, format_datetime, format_datetime_full
from ocr import extract_number_plate

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Conversation States ---
(
    START_TRIP, ASK_PHOTO, ASK_START_LOCATION, ASK_DESTINATION,
    ASK_DURATION, TRIP_ACTIVE, END_SAFETY_CHECK, END_LOCATION,
    CANCEL_CONFIRM
) = range(9)

# --- Keyboards ---

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu with persistent buttons."""
    keyboard = [[KeyboardButton("📸 Start Trip")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def active_trip_keyboard() -> ReplyKeyboardMarkup:
    """Menu shown when trip is active."""
    keyboard = [
        [KeyboardButton("🛑 End Trip")],
        [KeyboardButton("❌ Cancel Trip")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def cancel_during_conversation_keyboard() -> ReplyKeyboardMarkup:
    """Cancel button shown during Start Trip conversation."""
    keyboard = [[KeyboardButton("❌ Cancel")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# --- Helper Functions ---

def format_trip_summary(trip: dict) -> str:
    """Format trip completion summary."""
    start = datetime.fromisoformat(trip['start_time'])
    end = datetime.fromisoformat(trip['end_time']) if trip['end_time'] else None
    duration = int((end - start).total_seconds() / 60) if end else 0

    text = ("Trip Completed\n\n"
            f"To: {trip['destination_text']}\n")
    if trip['number_plate']:
        text += f"Vehicle: {trip['number_plate']}\n"
    text += (f"Start Location: {trip['start_lat']:.4f}, {trip['start_lon']:.4f}\n")
    if trip['end_lat'] and trip['end_lon']:
        text += f"End Location: {trip['end_lat']:.4f}, {trip['end_lon']:.4f}\n"
    text += (f"Start: {format_datetime_full(start)}\n"
             f"End: {format_datetime_full(end) if end else 'N/A'}\n"
             f"Duration: {duration} min\n"
             f"Expected: {trip['expected_minutes']} min\n")
    if trip['safety_confirmed']:
        text += "Safety confirmed: Yes"
    return text


async def send_sos_alert(context: ContextTypes.DEFAULT_TYPE, trip: dict,
                         triggered_by: str = "user") -> None:
    """Send SOS alert to emergency contact."""
    contact_id = EMERGENCY_CONTACT_ID
    if not contact_id:
        await context.bot.send_message(
            chat_id=trip['user_id'],
            text="SOS triggered, but no emergency contact is set. Please configure one with /setcontact"
        )
        return

    start_time = datetime.fromisoformat(trip['start_time'])
    now = now_utc()
    elapsed = int((now - start_time).total_seconds() / 60)

    trigger_text = "User manually triggered SOS" if triggered_by == "user" else "Auto-escalation"

    text = ("SOS ALERT\n"
            f"{trigger_text}\n\n"
            f"Destination: {trip['destination_text']}\n"
            f"Start location: {trip['start_lat']}, {trip['start_lon']}\n"
            f"Trip started: {format_datetime(start_time)}\n"
            f"Expected duration: {trip['expected_minutes']} min\n"
            f"Current duration: {elapsed} min\n\n"
            "Last known location: Start point (no live tracking)")

    try:
        await context.bot.send_message(chat_id=contact_id, text=text, parse_mode="HTML")
        await context.bot.send_message(
            chat_id=trip['user_id'],
            text="SOS alert sent to your emergency contact."
        )
        await update_trip_status(trip['trip_id'], 'sos')
    except Exception as e:
        logger.error(f"Failed to send SOS: {e}")
        await context.bot.send_message(
            chat_id=trip['user_id'],
            text="Failed to send SOS alert. Please contact help directly."
        )


# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    await get_or_create_user(user.id, update.effective_chat.id)

    active = await get_active_trip(user.id)
    if active:
        start_time = datetime.fromisoformat(active['start_time'])
        await update.message.reply_text(
            f"Welcome back! You have an active trip to {active['destination_text']} "
            f"(started at {format_datetime(start_time)}).",
            parse_mode="HTML",
            reply_markup=active_trip_keyboard()
        )
    else:
        await update.message.reply_text(
            "Welcome to Travel Check-In Bot!\n\n"
            "Tap Start Trip to begin a new journey.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )


async def set_contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setcontact command."""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /setcontact <telegram_user_id> <name>\n"
            "Example: /setcontact 123456789 Mom"
        )
        return

    try:
        contact_id = int(args[0])
        contact_name = " ".join(args[1:])
        await set_emergency_contact(update.effective_user.id, contact_id, contact_name)
        await update.message.reply_text(
            f"Emergency contact set: {contact_name} (ID: {contact_id})",
            parse_mode="HTML"
        )
    except ValueError:
        await update.message.reply_text("Invalid user ID. Please provide a number.")


# --- Start Trip Flow ---

async def start_trip_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'Start Trip' button press."""
    user_id = update.effective_user.id

    active = await get_active_trip(user_id)
    if active:
        start_time = datetime.fromisoformat(active['start_time'])
        await update.message.reply_text(
            f"You already have an active trip to {active['destination_text']} "
            f"(started at {format_datetime(start_time)}).\n\n"
            "End that trip first or Cancel it.",
            parse_mode="HTML",
            reply_markup=active_trip_keyboard()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Step 1/4: Please send a photo of your vehicle.\n\n"
        "Tap Cancel anytime to abort.",
        parse_mode="HTML",
        reply_markup=cancel_during_conversation_keyboard()
    )
    return ASK_PHOTO


async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive vehicle photo and extract number plate."""
    if not update.message.photo:
        await update.message.reply_text("Please send a photo. Try again.")
        return ASK_PHOTO

    photo = update.message.photo[-1]
    photo_file_id = photo.file_id
    context.user_data['photo_file_id'] = photo_file_id

    await update.message.reply_text("Reading number plate...")
    try:
        photo_file = await context.bot.get_file(photo_file_id)
        image_bytes = await photo_file.download_as_bytearray()
        plate = extract_number_plate(bytes(image_bytes))

        if plate:
            context.user_data['number_plate'] = plate
            await update.message.reply_text(f"Number plate detected: {plate}")
        else:
            context.user_data['number_plate'] = None
            await update.message.reply_text("Could not read number plate. Continuing without it.")
    except Exception as e:
        logger.error(f"OCR error: {e}")
        context.user_data['number_plate'] = None
        await update.message.reply_text("Could not read number plate. Continuing without it.")

    await update.message.reply_text(
        "Step 2/4: Please share your current location (one-time pin).\n\n"
        "Tap the attachment icon -> Location -> Send your current location\n\n"
        "Tap Cancel anytime to abort.",
        parse_mode="HTML",
        reply_markup=cancel_during_conversation_keyboard()
    )
    return ASK_START_LOCATION


async def receive_start_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive start location."""
    location = update.message.location
    if not location:
        await update.message.reply_text(
            "Please send a location pin. Try again.\n\n"
            "Tap Cancel anytime to abort.",
            reply_markup=cancel_during_conversation_keyboard()
        )
        return ASK_START_LOCATION

    context.user_data['start_lat'] = location.latitude
    context.user_data['start_lon'] = location.longitude

    await update.message.reply_text(
        "Location saved!\n\n"
        "Step 3/4: Where are you going? (Type your destination)\n\n"
        "Tap Cancel anytime to abort.",
        parse_mode="HTML",
        reply_markup=cancel_during_conversation_keyboard()
    )
    return ASK_DESTINATION


async def receive_destination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive destination text."""
    destination = update.message.text.strip()
    if not destination:
        await update.message.reply_text("Please enter a destination. Try again.")
        return ASK_DESTINATION

    context.user_data['destination'] = destination

    await update.message.reply_text(
        f"Destination: {destination}\n\n"
        "Step 4/4: How long do you expect the trip to take? (in minutes)\n\n"
        "Tap Cancel anytime to abort.",
        parse_mode="HTML",
        reply_markup=cancel_during_conversation_keyboard()
    )
    return ASK_DURATION


async def receive_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive expected duration and create trip."""
    try:
        duration = int(update.message.text.strip())
        if duration <= 0 or duration > 300:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Please enter a valid number of minutes (1-300). Try again.\n\n"
            "Tap Cancel anytime to abort.",
            reply_markup=cancel_during_conversation_keyboard()
        )
        return ASK_DURATION

    user_id = update.effective_user.id

    trip_id = await create_trip(
        user_id=user_id,
        photo_file_id=context.user_data['photo_file_id'],
        number_plate=context.user_data.get('number_plate'),
        start_lat=context.user_data['start_lat'],
        start_lon=context.user_data['start_lon'],
        destination_text=context.user_data['destination'],
        expected_minutes=duration
    )

    context.user_data['trip_id'] = trip_id

    buffer_info = f" (+{OVERDUE_BUFFER_MINUTES} min buffer)"

    await update.message.reply_text(
        f"Trip started!\n\n"
        f"To: {context.user_data['destination']}\n"
        f"Expected: {duration} min{buffer_info}\n"
        f"Timer running on server.\n\n"
        "Have a safe journey!",
        parse_mode="HTML",
        reply_markup=active_trip_keyboard()
    )

    context.user_data.clear()
    context.user_data['trip_id'] = trip_id

    return ConversationHandler.END


# --- End Trip Flow ---

async def end_trip_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'End Trip' button press."""
    user_id = update.effective_user.id
    active = await get_active_trip(user_id)

    if not active:
        await update.message.reply_text(
            "No active trip found. Start a new trip with Start Trip.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    context.user_data['ending_trip_id'] = active['trip_id']
    destination = active['destination_text']

    keyboard = [
        [InlineKeyboardButton("Yes", callback_data="safety_yes")],
        [InlineKeyboardButton("No", callback_data="safety_no")]
    ]

    await update.message.reply_text(
        f"End Trip\n\n"
        f"Have you reached {destination} safely?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return END_SAFETY_CHECK


async def safety_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle safety check response."""
    query = update.callback_query
    await query.answer()

    trip_id = context.user_data.get('ending_trip_id')
    if not trip_id:
        await query.edit_message_text("Session expired. Please try again.")
        return ConversationHandler.END

    trip = await get_trip(trip_id)
    if not trip or trip['status'] != 'active':
        await query.edit_message_text("Trip already ended or cancelled.")
        return ConversationHandler.END

    if query.data == "safety_yes":
        await query.edit_message_text(
            "Safety confirmed!\n\n"
            "Please share your current location pin to close the trip.\n\n"
            "Send your actual current location, not a saved place.",
            parse_mode="HTML"
        )
        return END_LOCATION

    elif query.data == "safety_no":
        keyboard = [
            [InlineKeyboardButton("SOS - Send emergency alert", callback_data="sos_now")],
            [InlineKeyboardButton("Share current location", callback_data="share_loc")],
            [InlineKeyboardButton("I'm okay, just not there yet", callback_data="not_there")],
        ]
        await query.edit_message_text(
            "Safety not confirmed.\n\nWhat would you like to do?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return END_SAFETY_CHECK


async def safety_not_confirmed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'not confirmed' follow-up options."""
    query = update.callback_query
    await query.answer()

    trip_id = context.user_data.get('ending_trip_id')
    trip = await get_trip(trip_id) if trip_id else None

    if query.data == "sos_now":
        if trip:
            await send_sos_alert(context, trip, triggered_by="user")
        await query.edit_message_text("SOS alert sent. Trip remains active.")
        return ConversationHandler.END

    elif query.data == "share_loc":
        await query.edit_message_text(
            "Please share your current location."
        )
        return END_LOCATION

    elif query.data == "not_there":
        await query.edit_message_text(
            "Got it. Trip remains active.\n\n"
            "Tap End Trip when you arrive safely.",
            parse_mode="HTML"
        )
        return ConversationHandler.END


async def receive_end_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive end location and close trip."""
    location = update.message.location
    if not location:
        await update.message.reply_text(
            "Please send a location pin. Try again.\n\n"
            "Tap the attachment icon -> Location -> Send your current location"
        )
        return END_LOCATION

    trip_id = context.user_data.get('ending_trip_id')
    if not trip_id:
        await update.message.reply_text("Session expired. Please try again.")
        return ConversationHandler.END

    trip = await get_trip(trip_id)
    if not trip:
        await update.message.reply_text("Trip not found.")
        return ConversationHandler.END

    now = now_utc()
    await update_trip_status(
        trip_id=trip_id,
        status='completed',
        end_lat=location.latitude,
        end_lon=location.longitude,
        end_time=now.isoformat(),
        safety_confirmed=1
    )

    trip = await get_trip(trip_id)
    summary = format_trip_summary(trip)

    await update.message.reply_text(
        summary,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard()
    )

    context.user_data.clear()
    return ConversationHandler.END


# --- Cancel Trip Flow ---

async def cancel_trip_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle 'Cancel Trip' button press."""
    user_id = update.effective_user.id
    active = await get_active_trip(user_id)

    if not active:
        await update.message.reply_text(
            "No active trip to cancel.",
            reply_markup=main_menu_keyboard()
        )
        return ConversationHandler.END

    context.user_data['cancelling_trip_id'] = active['trip_id']
    destination = active['destination_text']

    keyboard = [
        [InlineKeyboardButton("Yes, cancel", callback_data="confirm_cancel")],
        [InlineKeyboardButton("No, keep it", callback_data="abort_cancel")]
    ]

    await update.message.reply_text(
        f"Cancel Trip\n\n"
        f"Are you sure you want to cancel the trip to {destination}?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CANCEL_CONFIRM


async def cancel_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle cancel confirmation."""
    query = update.callback_query
    await query.answer()

    if query.data == "abort_cancel":
        await query.edit_message_text("Trip kept active.")
        return ConversationHandler.END

    trip_id = context.user_data.get('cancelling_trip_id')
    if trip_id:
        await update_trip_status(
            trip_id=trip_id,
            status='cancelled',
            end_time=now_utc().isoformat()
        )
        await query.edit_message_text("Trip cancelled.")
    else:
        await query.edit_message_text("Session expired.")

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Ready for your next trip!",
        reply_markup=main_menu_keyboard()
    )

    context.user_data.clear()
    return ConversationHandler.END


# --- Callback Query Handlers (Overdue Alerts) ---

async def overdue_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle overdue alert button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data or ":" not in data:
        return

    action, trip_id_str = data.split(":", 1)
    try:
        trip_id = int(trip_id_str)
    except ValueError:
        return

    trip = await get_trip(trip_id)
    if not trip or trip['status'] != 'active':
        await query.edit_message_text("This trip is no longer active.")
        return

    user_id = update.effective_user.id
    if trip['user_id'] != user_id:
        await query.answer("Not your trip!", show_alert=True)
        return

    if action == "safe":
        await query.edit_message_text(
            "Got it. I'll check again in 15 minutes. Stay safe!",
            parse_mode="HTML"
        )
        logger.info(f"User {user_id} marked trip {trip_id} as safe, extending check")

    elif action == "end":
        context.user_data['ending_trip_id'] = trip_id
        destination = trip['destination_text']

        keyboard = [
            [InlineKeyboardButton("Yes", callback_data="safety_yes")],
            [InlineKeyboardButton("No", callback_data="safety_no")]
        ]

        await query.edit_message_text(
            f"End Trip\n\n"
            f"Have you reached {destination} safely?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif action == "sos":
        await send_sos_alert(context, trip, triggered_by="user")
        await query.edit_message_text("SOS alert sent to emergency contact.")


# --- Fallback Handlers ---

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel any ongoing conversation."""
    await update.message.reply_text(
        "Cancelled.",
        reply_markup=main_menu_keyboard()
    )
    context.user_data.clear()
    return ConversationHandler.END


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown messages."""
    active = await get_active_trip(update.effective_user.id)
    if active:
        await update.message.reply_text(
            "I'm not sure what you mean.\n\n"
            "Tap End Trip when you arrive, or Cancel Trip.",
            parse_mode="HTML",
            reply_markup=active_trip_keyboard()
        )
    else:
        await update.message.reply_text(
            "I'm not sure what you mean.\n\n"
            "Tap Start Trip to begin a new journey.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )


# --- Main Application ---

def main() -> None:
    """Run the bot."""
    application = Application.builder().token(BOT_TOKEN).build()

    start_trip_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"Start Trip"), start_trip_trigger)
        ],
        states={
            ASK_PHOTO: [
                MessageHandler(filters.PHOTO, receive_photo),
                MessageHandler(filters.Regex(r"Cancel"), cancel_conversation),
            ],
            ASK_START_LOCATION: [
                MessageHandler(filters.LOCATION, receive_start_location),
                MessageHandler(filters.Regex(r"Cancel"), cancel_conversation),
            ],
            ASK_DESTINATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_destination),
                MessageHandler(filters.Regex(r"Cancel"), cancel_conversation),
            ],
            ASK_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_duration),
                MessageHandler(filters.Regex(r"Cancel"), cancel_conversation),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    end_trip_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"End Trip"), end_trip_trigger)
        ],
        states={
            END_SAFETY_CHECK: [
                CallbackQueryHandler(safety_check_callback, pattern=r"^safety_(yes|no)$"),
                CallbackQueryHandler(safety_not_confirmed_callback, pattern=r"^(sos_now|share_loc|not_there)$"),
            ],
            END_LOCATION: [MessageHandler(filters.LOCATION, receive_end_location)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    cancel_trip_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(r"Cancel Trip"), cancel_trip_trigger)
        ],
        states={
            CANCEL_CONFIRM: [CallbackQueryHandler(cancel_confirm_callback, pattern=r"^(confirm_cancel|abort_cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("setcontact", set_contact_command))
    application.add_handler(start_trip_conv)
    application.add_handler(end_trip_conv)
    application.add_handler(cancel_trip_conv)
    application.add_handler(CallbackQueryHandler(overdue_callback, pattern=r"^(safe|end|sos):\d+$"))
    # application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))

    async def on_startup(app):
        """Initialize DB and register scheduler inside the running event loop."""
        await init_db()
        logger.info("Database initialized")
        setup_scheduler(app.job_queue)

    application.post_init = on_startup

    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
