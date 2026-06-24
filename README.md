# Safe Journey — Telegram Travel Check-In Bot

A small Telegram bot to help solo travellers and late-night commuters stay safe. Start a trip, share a vehicle photo and location, set expected duration — the bot monitors the trip and notifies an emergency contact if the traveller becomes unresponsive.

## Quick features
- Guided trip flow: photo → start location → destination → expected time
- Optional cloud OCR (Plate Recognizer) to read number plates from a photo
- Background monitoring with overdue alerts and escalation to an emergency contact
- Async, non-blocking code: python-telegram-bot + aiosqlite
- Timezone-aware (UTC storage, local display)

## Get running (short)
1. Clone:
   git clone https://github.com/nihar-landge/safe-journey-telegram-bot.git
   cd safe-journey-telegram-bot

2. Create & activate venv:
   python -m venv venv
   source venv/bin/activate     # macOS / Linux
   venv\Scripts\activate        # Windows

3. Install:
   pip install -r requirements.txt

4. Create a `.env` (see `.env.example`) and run:
   python bot.py

The bot creates the SQLite DB automatically on first run.

## Commands (user)
- /start — show menu or active trip info
- /setcontact <telegram_user_id> <name> — set your emergency contact

UI buttons:
- 📸 Start Trip — begin guided registration
- 🛑 End Trip — confirm safety + share final location
- ❌ Cancel Trip — cancel active trip

Overdue alert actions:
- Safe — extend check window
- End Trip — finish trip flow
- SOS — send emergency alert now

## How it works (simple)
- bot.py handles conversations and commands.
- database.py stores trips and users in SQLite (aiosqlite).
- ocr.py sends images to Plate Recognizer (optional).
- scheduler.py runs a repeating job that checks active trips and sends alerts / escalates.

## Data stored
- users: user id, chat id, emergency contact
- trips: start/end location, photo id, detected number plate, expected time, status, overdue count
Do not commit the DB or .env to version control.

## Notes & troubleshooting
- BOT_TOKEN is required.
- If OCR is not needed, leave PLATE_REC_TOKEN empty; OCR will be skipped.
- Check logs for scheduling or sending errors.
- Keep `.env` secret.

## License
MIT — author: Nihar Landge
