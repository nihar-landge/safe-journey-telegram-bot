# helpers.py - Timezone utilities
"""Helper functions for timezone handling."""

from datetime import datetime
import pytz
from config import TIMEZONE

# Create timezone objects once
LOCAL_TZ = pytz.timezone(TIMEZONE)
UTC = pytz.utc


def now_utc() -> datetime:
    """Get current time in UTC."""
    return datetime.now(UTC)


def now_local() -> datetime:
    """Get current time in local timezone."""
    return datetime.now(LOCAL_TZ)


def utc_to_local(dt: datetime) -> datetime:
    """Convert UTC datetime to local timezone."""
    if dt.tzinfo is None:
        # Naive datetime - assume it's UTC
        dt = pytz.utc.localize(dt)
    return dt.astimezone(LOCAL_TZ)


def local_to_utc(dt: datetime) -> datetime:
    """Convert local datetime to UTC."""
    if dt.tzinfo is None:
        dt = LOCAL_TZ.localize(dt)
    return dt.astimezone(UTC)


def format_datetime(dt: datetime, fmt: str = "%I:%M %p") -> str:
    """Format datetime in local timezone."""
    local_dt = utc_to_local(dt)
    return local_dt.strftime(fmt)


def format_datetime_full(dt: datetime) -> str:
    """Format datetime with date and time in local timezone."""
    local_dt = utc_to_local(dt)
    return local_dt.strftime("%d %b %Y, %I:%M %p")


def format_duration(minutes: int) -> str:
    """Format duration in hours and minutes."""
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    mins = minutes % 60
    if mins == 0:
        return f"{hours} hr"
    return f"{hours} hr {mins} min"
