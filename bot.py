import os
import asyncio
import sqlite3
from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

# ==========================================

bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

clients = {}          # per user client
states = {}           # login states
ads_tasks = {}        # running loops
user_db = "data.db"


# ================= DATABASE =================

def db():
    return sqlite3.connect(user_db, check_same_thread=False)


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("PRAGMA journal_mode=WAL;")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        uid INTEGER PRIMARY KEY,
        message TEXT,
        interval INTEGER DEFAULT 5,
        logs INTEGER DEFAULT 0,
        log_chat TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chats(
        uid INTEGER,
        chat TEXT
    )
    """)

    con.commit()
    con.close()


init_db()


# ================= BUTTON UI =================

def main_buttons():
    return [
        [Button.text("📱 Login"), Button.text("🚪 Logout")],
        [Button.text("➕ Add Chat"), Button.text("➖ Remove Chat")],
        [Button.text("📋 List Chats")],
        [Button.text("✏️ Set Message")],
        [Button.text("▶ Start Ads"), Button.text("⏹ Stop Ads")],
        [Button.text("⏱ Interval"), Button.text("📊 Status")],
        [Button.text("📝 Toggle Logs")]
    ]


clients = {}

async def get_client(uid):
    if uid in clients:
        client = clients[uid]
        if not client.is_connected():
            await client.connect()
        return client

    client = TelegramClient(f"sessions/{uid}", API_ID, API_HASH)
    await client.connect()

    clients[uid] = client
    return client

# ================= LOGIN =========≠=========

# ================= LOGIN =================

@bot.on(events.NewMessage(pattern="📱 Login"))
async def login(e):
    uid = e.sender_id

    # Initialize user login state
    states[uid] = {
        "step": "phone",
        "phone": None,
        "hash": None
    }

    await e.reply(
        "📱 Send your phone number with country code\nExample:\n+919999999999"
    )


# ================= OTP / 2FA HANDLER =================

@bot.on(events.NewMessage(func=lambda e: e.sender_id in states))
async def otp_handler(e):
    uid = e.sender_id
    st = states[uid]
    text = e.raw_text.strip()

    # 🚫 Ignore button presses
    ignore_buttons = {b.text for row in main_buttons() for b in row}
    if text in ignore_buttons:
        return

    # Get or create client
    client = await get_client(uid)

    # ----- PHONE STEP -----
    if st["step"] == "phone":
        phone = text

        # Validate phone
        if not phone or not phone.startswith("+") or not phone[1:].isdigit():
            await e.reply("❌ Invalid phone number format.\nSend like +919999999999")
            return

        try:
            result = await client.send_code_request(phone)
        except Exception as ex:
            await e.reply(f"❌ Phone error: {ex}")
            return

        st["phone"] = phone
        st["hash"] = result.phone_code_hash
        st["step"] = "otp"
        await e.reply("📩 Send OTP like:\ncode12345")
        return

    # ----- OTP STEP -----
    if st["step"] == "otp" and text.lower().startswith("code"):
        code = text.replace("code", "").strip()
        try:
            await client.sign_in(st["phone"], code, phone_code_hash=st["hash"])
            states.pop(uid)
            await e.reply("✅ Login successful", buttons=main_buttons())

        except SessionPasswordNeededError:
            st["step"] = "2fa"
            await e.reply("🔒 2FA enabled. Send your 2FA password")

        except Exception as ex:
            await e.reply(f"❌ OTP failed: {ex}")
        return

    # ----- 2FA STEP -----
    if st["step"] == "2fa":
        try:
            await client.sign_in(password=text)
            states.pop(uid)
            await e.reply("✅ Login successful", buttons=main_buttons())
        except Exception as ex:
            await e.reply(f"❌ 2FA failed: {ex}")

# ================= LOGOUT =================

@bot.on(events.NewMessage(pattern="🚪 Logout"))
async def logout(e):
    uid = e.sender_id
    if uid in clients:
        await clients[uid].log_out()
        clients.pop(uid)
    await e.reply("Logged out")


# ================= CHAT MGMT =================

@bot.on(events.NewMessage(pattern="➕ Add Chat"))
async def add_chat(e):
    states[e.sender_id] = {"step": "add_chat"}
    await e.reply("Send chat id or username")


@bot.on(events.NewMessage(pattern="➖ Remove Chat"))
async def remove_chat(e):
    states[e.sender_id] = {"step": "remove_chat"}
    await e.reply("Send chat id or username")


@bot.on(events.NewMessage(pattern="📋 List Chats"))
async def list_chats(e):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT chat FROM chats WHERE uid=?", (e.sender_id,))
    rows = cur.fetchall()
    con.close()

    if not rows:
        await e.reply("No chats")
    else:
        await e.reply("\n".join(x[0] for x in rows))


# ================= MESSAGE =================

@bot.on(events.NewMessage(pattern="✏️ Set Message"))
async def set_msg(e):
    states[e.sender_id] = {"step": "set_msg"}
    await e.reply("Send new message")


# ================= INTERVAL =================

@bot.on(events.NewMessage(pattern="⏱ Interval"))
async def set_interval(e):
    states[e.sender_id] = {"step": "interval"}
    await e.reply("Send seconds")


# ================= TOGGLE LOGS =================

@bot.on(events.NewMessage(pattern="📝 Toggle Logs"))
async def toggle_logs(e):
    con = db()
    cur = con.cursor()

    cur.execute("SELECT logs FROM users WHERE uid=?", (e.sender_id,))
    row = cur.fetchone()

    if not row or row[0] == 0:
        cur.execute("INSERT OR REPLACE INTO users(uid,logs) VALUES(?,1)", (e.sender_id,))
        await e.reply("Logs enabled. Send log channel id/username")
        states[e.sender_id] = {"step": "log_chat"}
    else:
        cur.execute("UPDATE users SET logs=0 WHERE uid=?", (e.sender_id,))
        await e.reply("Logs disabled")

    con.commit()
    con.close()

# ================== ADS LOOP ==================
async def ads_loop(uid):
    while uid in ads_tasks:
        try:
            client = await get_client(uid)
            if not client.is_connected():
                await client.connect()

            # Fetch user settings
            con = db()
            cur = con.cursor()
            cur.execute("SELECT message, interval, logs, log_chat FROM users WHERE uid=?", (uid,))
            row = cur.fetchone()
            if not row:
                await client.send_message(uid, "❌ You are not registered")
                con.close()
                return
            msg, interval, logs, log_chat = row

            cur.execute("SELECT chat FROM chats WHERE uid=?", (uid,))
            chats = [x[0] for x in cur.fetchall()]
            con.close()

            for c in chats:
                try:
                    await client.send_message(c, msg)
                    if logs and log_chat:
                        try:
                            await client.send_message(log_chat, f"✅ Sent to {c}")
                        except Exception as e:
                            print("LOG ERROR:", e)
                except Exception as e:
                    print(f"SEND ERROR to {c}:", e)

            await asyncio.sleep(interval)

        except asyncio.CancelledError:
            print(f"Ads task for {uid} cancelled")
            return
        except Exception as e:
            print("ADS LOOP ERROR:", e)
            await asyncio.sleep(5)



# ================== START/STOP ADS ==================
@bot.on(events.NewMessage(pattern="▶ Start Ads"))
async def start_ads(e):
    uid = e.sender_id
    if uid in ads_tasks:
        await e.reply("⚠️ Ads already running")
        return
    ads_tasks[uid] = asyncio.create_task(ads_loop(uid))
    await e.reply("✅ Ads started")


@bot.on(events.NewMessage(pattern="⏹ Stop Ads"))
async def stop_ads(e):
    uid = e.sender_id
    task = ads_tasks.pop(uid, None)
    if task:
        task.cancel()
        await e.reply("🛑 Ads stopped")
    else:
        await e.reply("⚠️ Ads not running")

# ================= STATUS =================

@bot.on(events.NewMessage(pattern="📊 Status"))
async def status(e):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT interval FROM users WHERE uid=?", (e.sender_id,))
    r = cur.fetchone()
    interval = r[0] if r else 5
    con.close()

    running = e.sender_id in ads_tasks

    await e.reply(
        f"Chats: running\nInterval: {interval}s\nRunning: {running}"
    )


# ================= RUN =================

print("Bot running...")
bot.run_until_disconnected()
