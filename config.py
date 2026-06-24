# config.py - Bot Configuration
"""Configuration for Travel Check-In Bot."""

import os
from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv()

# --- Required ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "0"))  # Your private group chat ID

# --- Plate Recognizer Cloud API ---
PLATE_REC_TOKEN = os.getenv("PLATE_REC_TOKEN", "").strip()

# --- Timezone ---
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")

# --- Optional Emergency Contact ---
EMERGENCY_CONTACT_ID = None
_ec_raw = os.getenv("EMERGENCY_CONTACT_ID", "").strip()
if _ec_raw and _ec_raw.lower() not in ("optional_emergency_contact_user_id", "none", ""):
    try:
        EMERGENCY_CONTACT_ID = int(_ec_raw)
    except ValueError:
        print(f"Warning: Invalid EMERGENCY_CONTACT_ID '{_ec_raw}', ignoring.")
        EMERGENCY_CONTACT_ID = None

# --- Timing Settings ---
OVERDUE_BUFFER_MINUTES = int(os.getenv("OVERDUE_BUFFER_MINUTES", "10"))
SAFE_EXTENSION_MINUTES = int(os.getenv("SAFE_EXTENSION_MINUTES", "15"))
ESCALATION_AFTER_ALERTS = int(os.getenv("ESCALATION_AFTER_ALERTS", "2"))
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "trips.db")

# --- Logging ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
