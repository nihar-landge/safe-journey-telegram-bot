# database.py - SQLite Database Layer
"""Database operations for Travel Check-In Bot."""

import aiosqlite
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from config import DB_PATH


@asynccontextmanager
async def get_db():
    """Async context manager for database operations."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


async def init_db() -> None:
    """Initialize database tables."""
    async with get_db() as conn:
        await conn.executescript("""
            CREATE TABLE IF NOT EXISTS trips (
                trip_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                photo_file_id   TEXT,
                number_plate    TEXT,
                start_lat       REAL,
                start_lon       REAL,
                end_lat         REAL,
                end_lon         REAL,
                destination_text TEXT NOT NULL,
                start_time      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time        TIMESTAMP,
                expected_minutes INTEGER NOT NULL,
                status          TEXT DEFAULT 'active'
                                CHECK(status IN ('active', 'completed', 'cancelled', 'sos')),
                safety_confirmed BOOLEAN DEFAULT 0,
                overdue_count   INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id         INTEGER PRIMARY KEY,
                telegram_chat_id INTEGER,
                emergency_contact_id INTEGER,
                emergency_contact_name TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_trips_user_status
                ON trips(user_id, status);

            CREATE INDEX IF NOT EXISTS idx_trips_status
                ON trips(status);
        """)


async def create_trip(user_id: int, photo_file_id: str, number_plate: str,
                      start_lat: float, start_lon: float,
                      destination_text: str, expected_minutes: int) -> int:
    """Create a new trip. Returns trip_id."""
    from helpers import now_utc
    async with get_db() as conn:
        cursor = await conn.execute(
            """INSERT INTO trips (user_id, photo_file_id, number_plate, start_lat, start_lon,
                destination_text, expected_minutes, status, start_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (user_id, photo_file_id, number_plate, start_lat, start_lon,
             destination_text, expected_minutes, now_utc().isoformat())
        )
        return cursor.lastrowid


async def get_active_trip(user_id: int) -> Optional[Dict[str, Any]]:
    """Get the active trip for a user."""
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM trips WHERE user_id = ? AND status = 'active' LIMIT 1",
            (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_trip(trip_id: int) -> Optional[Dict[str, Any]]:
    """Get a trip by ID."""
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM trips WHERE trip_id = ?", (trip_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_trip_status(trip_id: int, status: str, **kwargs) -> None:
    """Update trip status and optional fields."""
    allowed_fields = {'end_lat', 'end_lon', 'end_time', 'safety_confirmed', 'overdue_count'}

    async with get_db() as conn:
        await conn.execute(
            "UPDATE trips SET status = ? WHERE trip_id = ?", (status, trip_id)
        )
        for key, value in kwargs.items():
            if key in allowed_fields:
                await conn.execute(
                    f"UPDATE trips SET {key} = ? WHERE trip_id = ?", (value, trip_id)
                )


async def increment_overdue_count(trip_id: int) -> int:
    """Increment overdue count and return new value."""
    async with get_db() as conn:
        await conn.execute(
            "UPDATE trips SET overdue_count = overdue_count + 1 WHERE trip_id = ?",
            (trip_id,)
        )
        cursor = await conn.execute(
            "SELECT overdue_count FROM trips WHERE trip_id = ?", (trip_id,)
        )
        row = await cursor.fetchone()
        return row[0]


async def get_all_active_trips() -> List[Dict[str, Any]]:
    """Get all active trips (for scheduler)."""
    async with get_db() as conn:
        cursor = await conn.execute("SELECT * FROM trips WHERE status = 'active'")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_or_create_user(user_id: int, chat_id: int) -> Dict[str, Any]:
    """Get or create user record."""
    async with get_db() as conn:
        cursor = await conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)

        await conn.execute(
            "INSERT INTO users (user_id, telegram_chat_id) VALUES (?, ?)",
            (user_id, chat_id)
        )
        cursor = await conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row)


async def set_emergency_contact(user_id: int, contact_id: int, contact_name: str) -> None:
    """Set emergency contact for a user."""
    async with get_db() as conn:
        await conn.execute(
            "UPDATE users SET emergency_contact_id = ?, emergency_contact_name = ? WHERE user_id = ?",
            (contact_id, contact_name, user_id)
        )
