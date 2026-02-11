import os
import json
import asyncio
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telethon import TelegramClient, errors

# =================================
# ENV VARIABLES
# =================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

# =================================
# FILES & DIRECTORIES
# =================================
DATA_FILE = "data.json"
SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

# =================================
# DATABASE
# =================================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    return json.load(open(DATA_FILE))

def save_data(d):
    json.dump(d, open(DATA_FILE, "w"), indent=2)

db = load_data()

# =================================
# KEYBOARD
# =================================
def keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📱 Login", "🚪 Logout"],
            ["➕ Add Chat", "➖ Remove Chat"],
            ["📋 List Chats"],
            ["📝 Set Message"],
            ["▶ Start Ads", "⏹ Stop Ads"],
            ["⏱ Interval", "📊 Status"],
        ],
        resize_keyboard=True,
    )

# =================================
# HELPERS
# =================================
def get_user(uid):
    uid = str(uid)
    if uid not in db:
        db[uid] = {
            "chats": [],
            "interval": 60,
            "message": "🔥 Default Ad Message 🔥",
            "running": False,
            "state": None,
            "phone": None,
        }
    return db[uid]

async def get_client(uid):
    return TelegramClient(f"{SESSIONS_DIR}/{uid}", API_ID, API_HASH)

# =================================
# ADS LOOP
# =================================
async def ads_loop(uid):
    user = get_user(uid)
    session_file = f"{SESSIONS_DIR}/{uid}"

    while user["running"]:
        try:
            async with TelegramClient(session_file, API_ID, API_HASH) as client:
                for chat in user["chats"]:
                    try:
                        await client.send_message(chat, user["message"])
                    except Exception:
                        continue
            await asyncio.sleep(user["interval"])
        except Exception:
            await asyncio.sleep(5)

# =================================
# START COMMAND
# =================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 AdBot running smoothly!",
        reply_markup=keyboard(),
    )

# =================================
# MAIN TEXT HANDLER
# =================================
async def text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    uid = update.message.from_user.id
    user = get_user(uid)

    # ===== LOGIN =====
    if msg == "📱 Login":
        user["state"] = "phone"
        save_data(db)
        await update.message.reply_text("Send phone number (+91xxxx)")
        return

    if user["state"] == "phone":
        user["phone"] = msg
        session_file = f"{SESSIONS_DIR}/{uid}"
        try:
            async with TelegramClient(session_file, API_ID, API_HASH) as client:
                await client.send_code_request(msg)
            user["state"] = "otp"
            save_data(db)
            await update.message.reply_text("Send OTP like: code12345")
        except Exception as e:
            await update.message.reply_text(f"❌ Error sending code: {str(e)}")
        return

    if user["state"] == "otp":
        if not msg.startswith("code"):
            await update.message.reply_text("Format must be: code12345")
            return
        code = msg[4:]
        session_file = f"{SESSIONS_DIR}/{uid}"
        try:
            async with TelegramClient(session_file, API_ID, API_HASH) as client:
                await client.sign_in(user["phone"], code)
            user["state"] = None
            save_data(db)
            await update.message.reply_text("✅ Login successful")
        except errors.SessionPasswordNeededError:
            await update.message.reply_text("Two-step verification required. Cannot login.")
        except Exception as e:
            await update.message.reply_text(f"❌ OTP login failed: {str(e)}")
        return

    # ===== LOGOUT =====
    if msg == "🚪 Logout":
        session_file = f"{SESSIONS_DIR}/{uid}.session"
        if os.path.exists(session_file):
            os.remove(session_file)
        await update.message.reply_text("Logged out")
        return

    # ===== SET MESSAGE =====
    if msg == "📝 Set Message":
        user["state"] = "set_message"
        await update.message.reply_text("Send your ad message text")
        return

    if user["state"] == "set_message":
        user["message"] = msg
        user["state"] = None
        save_data(db)
        await update.message.reply_text("✅ Message updated")
        return

    # ===== CHAT MANAGEMENT =====
    if msg == "➕ Add Chat":
        user["state"] = "add_chat"
        await update.message.reply_text("Send chat id or username")
        return

    if msg == "➖ Remove Chat":
        user["state"] = "remove_chat"
        await update.message.reply_text("Send chat id to remove")
        return

    if msg == "📋 List Chats":
        await update.message.reply_text(str(user["chats"]))
        return

    if user["state"] == "add_chat":
        user["chats"].append(msg)
        user["state"] = None
        save_data(db)
        await update.message.reply_text("Chat added")
        return

    if user["state"] == "remove_chat":
        if msg in user["chats"]:
            user["chats"].remove(msg)
        user["state"] = None
        save_data(db)
        await update.message.reply_text("Chat removed")
        return

    # ===== INTERVAL =====
    if msg == "⏱ Interval":
        user["state"] = "interval"
        await update.message.reply_text("Send seconds")
        return

    if user["state"] == "interval":
        try:
            user["interval"] = int(msg)
        except ValueError:
            await update.message.reply_text("Please send a valid number")
            return
        user["state"] = None
        save_data(db)
        await update.message.reply_text("Interval updated")
        return

    # ===== ADS =====
    if msg == "▶ Start Ads":
        if not user["chats"]:
            await update.message.reply_text("Add chats first")
            return
        user["running"] = True
        save_data(db)
        context.application.create_task(ads_loop(uid))
        await update.message.reply_text("Ads started")
        return

    if msg == "⏹ Stop Ads":
        user["running"] = False
        save_data(db)
        await update.message.reply_text("Ads stopped")
        return

    # ===== STATUS =====
    if msg == "📊 Status":
        await update.message.reply_text(
            f"Chats: {len(user['chats'])}\n"
            f"Interval: {user['interval']}s\n"
            f"Running: {user['running']}\n"
            f"Message:\n{user['message']}"
        )

# =================================
# MAIN
# =================================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT, text))
    print("🚀 Bot running smoothly")
    app.run_polling()

if __name__ == "__main__":
    main()
