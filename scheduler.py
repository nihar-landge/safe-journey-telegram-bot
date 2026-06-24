# scheduler.py - Background Overdue Checker
"""Overdue trip checker using PTB JobQueue — no manual asyncio loop needed."""

import logging
from datetime import datetime

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import (
    OVERDUE_BUFFER_MINUTES, SAFE_EXTENSION_MINUTES,
    ESCALATION_AFTER_ALERTS, CHECK_INTERVAL_SECONDS, EMERGENCY_CONTACT_ID
)
from database import get_all_active_trips, increment_overdue_count, update_trip_status
from helpers import now_utc, format_datetime

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point — called once from bot.py on_startup
# ---------------------------------------------------------------------------

def setup_scheduler(job_queue) -> None:
    """Register the repeating overdue-check job with PTB's JobQueue."""
    job_queue.run_repeating(
        callback=check_overdue_trips,
        interval=CHECK_INTERVAL_SECONDS,
        first=10,   # Wait 10 s after startup before the first check
        name="overdue_checker",
    )
    logger.info(f"Overdue checker registered — interval: {CHECK_INTERVAL_SECONDS}s")


# ---------------------------------------------------------------------------
# Job callback — PTB calls this on schedule, catches any exception automatically
# ---------------------------------------------------------------------------

async def check_overdue_trips(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check all active trips for overdue status (JobQueue callback)."""
    bot = context.bot
    now = now_utc()
    active_trips = await get_all_active_trips()

    for trip in active_trips:
        trip_id      = trip['trip_id']
        start_time   = datetime.fromisoformat(trip['start_time'])
        expected     = trip['expected_minutes']
        overdue_count = trip['overdue_count']
        user_id      = trip['user_id']
        destination  = trip['destination_text']

        elapsed   = (now - start_time).total_seconds() / 60
        threshold = expected + OVERDUE_BUFFER_MINUTES

        # First alert — trip just went overdue
        if elapsed >= threshold and overdue_count == 0:
            await _send_overdue_alert(bot, trip_id, destination, expected, elapsed, user_id)
            await increment_overdue_count(trip_id)
            logger.info(f"Trip {trip_id}: first overdue alert sent ({int(elapsed)} min elapsed)")

        # Second alert — user tapped Safe but still no check-in
        elif overdue_count == 1:
            if elapsed >= threshold + SAFE_EXTENSION_MINUTES:
                await _send_overdue_alert(bot, trip_id, destination, expected, elapsed, user_id)
                new_count = await increment_overdue_count(trip_id)
                logger.info(f"Trip {trip_id}: second overdue alert sent ({int(elapsed)} min elapsed)")

                if new_count >= ESCALATION_AFTER_ALERTS:
                    await _auto_escalate(bot, trip, elapsed)

        # Beyond escalation threshold — keep alerting every SAFE_EXTENSION_MINUTES
        elif overdue_count >= ESCALATION_AFTER_ALERTS:
            next_alert = threshold + (overdue_count * SAFE_EXTENSION_MINUTES)
            if elapsed >= next_alert:
                await _send_overdue_alert(bot, trip_id, destination, expected, elapsed, user_id)
                await increment_overdue_count(trip_id)
                await _auto_escalate(bot, trip, elapsed)
                logger.info(f"Trip {trip_id}: escalation alert #{overdue_count} sent")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

async def _send_overdue_alert(bot: Bot, trip_id: int, destination: str,
                               expected: int, elapsed: float, user_id: int) -> None:
    """Send an overdue alert with action buttons to the traveller."""
    keyboard = [
        [InlineKeyboardButton("Safe - I'm fine, just delayed", callback_data=f"safe:{trip_id}")],
        [InlineKeyboardButton("End Trip",                       callback_data=f"end:{trip_id}")],
        [InlineKeyboardButton("SOS",                            callback_data=f"sos:{trip_id}")],
    ]
    text = (
        "Trip Overdue\n\n"
        f"Destination: {destination}\n"
        f"Expected: {expected} min\n"
        f"Elapsed:  {int(elapsed)} min\n\n"
        "Please respond:"
    )
    try:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.error(f"Trip {trip_id}: failed to send overdue alert — {e}")


async def _auto_escalate(bot: Bot, trip: dict, elapsed: float) -> None:
    """Escalate to the emergency contact when the traveller is unresponsive."""
    contact_id = EMERGENCY_CONTACT_ID
    if not contact_id:
        logger.warning(f"Trip {trip['trip_id']}: no emergency contact set, skipping escalation")
        return

    start_time = datetime.fromisoformat(trip['start_time'])
    text = (
        "AUTO-ESCALATION: No Response to Overdue Alerts\n\n"
        f"Traveler did not respond to {trip['overdue_count']} overdue alerts.\n\n"
        f"Destination: {trip['destination_text']}\n"
        f"Start location: {trip['start_lat']}, {trip['start_lon']}\n"
        f"Trip started: {format_datetime(start_time)}\n"
        f"Expected duration: {trip['expected_minutes']} min\n"
        f"Elapsed duration:  {int(elapsed)} min\n\n"
        "Last known location: Start point (no live tracking)\n\n"
        "Please try to contact them immediately."
    )
    try:
        await bot.send_message(chat_id=contact_id, text=text)
        await update_trip_status(trip['trip_id'], 'sos')
        logger.info(f"Trip {trip['trip_id']}: escalation message sent to contact {contact_id}")
    except Exception as e:
        logger.error(f"Trip {trip['trip_id']}: failed to send escalation — {e}")
