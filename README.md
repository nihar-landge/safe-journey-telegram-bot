# 🛡️ Safe Journey Telegram Bot

A Telegram bot for solo travellers and late-night commuters. You start a trip, and the bot watches the clock. If you go quiet, it alerts your emergency contact.

## ✨ Features

- **Guided trip start (4 steps):** vehicle photo, live location pin, destination, expected time (1–300 min)
- **Number plate reading:** optional OCR through the Plate Recognizer API. The trip continues if the plate can't be read.
- **Server-side timer:** a background job checks all active trips, so it works even if your phone dies.
- **Overdue alerts:** when your time plus a buffer runs out, the bot sends buttons: ✅ Safe, 🛑 End Trip, 🆘 SOS.
- **Auto-escalation:** if you ignore repeated alerts, your emergency contact gets the destination, start coordinates, start time and elapsed time.
- **One-tap SOS:** an instant alert to your emergency contact.
- **Safe arrival check:** confirm you are safe and share your end location to close the trip.
- **Trip summary:** destination, plate, start and end location, actual vs expected duration.
- **Cancel anytime:** with a confirmation step.
- **Owner-only buttons:** only the traveller can press the alert buttons.
- **Timezone-aware:** times are stored in UTC and shown in local time.
- **Zero setup database:** SQLite is created on first run.

## 🧰 Tech Stack

| Part | Use |
|---|---|
| Python 3 | Language |
| python-telegram-bot (with JobQueue) | Bot and background checks |
| asyncio + aiosqlite | Non-blocking SQLite storage |
| Plate Recognizer API (via requests) | Number plate OCR |
| pytz | Timezones |
| python-dotenv | Config from `.env` |

## 🚀 Quick Start

```bash
git clone https://github.com/nihar-landge/safe-journey-telegram-bot.git
cd safe-journey-telegram-bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file (see `.env.example`). `BOT_TOKEN` is required. Leave `PLATE_REC_TOKEN` empty to skip OCR. Then run:

```bash
python bot.py
```

## 💬 Commands and Buttons

| Action | What it does |
|---|---|
| `/start` | Show the menu, or your active trip |
| `/setcontact <telegram_user_id> <name>` | Save an emergency contact |
| 📸 Start Trip | Begin the guided flow |
| 🛑 End Trip | Confirm safety and share your final location |
| ❌ Cancel Trip | Cancel the active trip |

## ⚙️ How It Works

| File | Job |
|---|---|
| `bot.py` | Conversations, commands, SOS |
| `scheduler.py` | Repeating job: overdue alerts and escalation |
| `database.py` | Users and trips in SQLite |
| `ocr.py` | Plate Recognizer calls |
| `config.py` | Settings and timings |
| `helpers.py` | Time and format helpers |

**Alert flow:** trip runs → time + buffer passes → alert → tap Safe to extend the check → no reply → alert again → contact is notified.

## 🗄️ Data Stored

- **users:** user ID, chat ID, emergency contact
- **trips:** start and end location, photo ID, number plate, expected time, status, overdue count

## 🔒 Notes

- Never commit `.env` or the database file.
- There is no live tracking. The contact gets the start point only.
- Check the logs if alerts don't send.

## 📄 License

MIT © Nihar Landge
