import os
import sqlite3
import threading
from datetime import datetime, timedelta

from flask import Flask, request
import telebot
from telebot import types


# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if not ADMIN_ID_RAW:
    raise RuntimeError("ADMIN_ID environment variable is missing")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    raise RuntimeError("ADMIN_ID must contain only your numeric Telegram ID")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

DB_FILE = "users.db"
db_lock = threading.Lock()
broadcast_waiting = set()


# =========================
# DATABASE
# =========================

conn = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    last_name TEXT DEFAULT '',
    joined_at TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT DEFAULT 'active'
)
""")

conn.commit()


# =========================
# DATABASE HELPERS
# =========================

def now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def register_user(message):
    user = message.from_user
    now = now_text()

    with db_lock:
        cursor.execute("""
            INSERT INTO users (
                user_id,
                username,
                first_name,
                last_name,
                joined_at,
                last_seen,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                last_seen = excluded.last_seen,
                status = 'active'
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            user.last_name or "",
            now,
            now
        ))
        conn.commit()


def is_admin(message):
    return message.from_user.id == ADMIN_ID


def get_stats():
    cutoff = (
        datetime.now() - timedelta(days=7)
    ).strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE status = 'active'
            AND last_seen >= ?
        """, (cutoff,))
        active = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE status = 'deleted'
        """)
        deleted = cursor.fetchone()[0]

    return active, deleted, total


def get_users():
    with db_lock:
        cursor.execute("""
            SELECT
                user_id,
                username,
                first_name,
                last_name,
                joined_at,
                last_seen,
                status
            FROM users
            ORDER BY joined_at DESC
        """)
        return cursor.fetchall()


def get_broadcast_users():
    with db_lock:
        cursor.execute("""
            SELECT user_id
            FROM users
            WHERE status != 'deleted'
        """)
        return [row[0] for row in cursor.fetchall()]


def mark_deleted(user_id):
    with db_lock:
        cursor.execute("""
            UPDATE users
            SET status = 'deleted'
            WHERE user_id = ?
        """, (user_id,))
        conn.commit()


# =========================
# DASHBOARD
# =========================

def dashboard_text():
    active, deleted, total = get_stats()

    return (
        "📊 <b>Subscribers</b>\n\n"
        f"🟢 <b>Active:</b> {active}\n"
        "🔇 <b>Muted:</b> —\n"
        f"🗑 <b>Deleted:</b> {deleted}\n"
        f"👥 <b>Total:</b> {total}\n\n"
        "👤 <b>Users</b>\n"
        "👥 Group chats: Not tracked\n\n"
        "ℹ️ Active = interacted with the bot "
        "during the last 7 days.\n"
        "🔇 Telegram Bot API does not provide "
        "a user's notification-mute status."
    )


def dashboard_markup():
    keyboard = types.InlineKeyboardMarkup(row_width=2)

    keyboard.add(
        types.InlineKeyboardButton(
            "👥 Subscribers",
            callback_data="subscribers"
        ),
        types.InlineKeyboardButton(
            "📊 Refresh",
            callback_data="refresh"
        )
    )

    keyboard.add(
        types.InlineKeyboardButton(
            "📨 Send New Post",
            callback_data="broadcast"
        ),
        types.InlineKeyboardButton(
            "📋 User List",
            callback_data="userlist"
        )
    )

    return keyboard


def send_dashboard(chat_id, message_id=None):
    text = dashboard_text()
    markup = dashboard_markup()

    if message_id is None:
        return bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            reply_markup=markup
        )

    return bot.edit_message_text(
        text,
        chat_id,
        message_id,
        parse_mode="HTML",
        reply_markup=markup
    )


# =========================
# START
# =========================

@bot.message_handler(commands=["start"])
def start_command(message):
    if message.chat.type == "private":
        register_user(message)

    name = message.from_user.first_name or "User"

    bot.reply_to(
        message,
        f"👋 Hello {name}!\n\n"
        "Welcome to the bot.\n\n"
        "Use /help to see available commands."
    )


# =========================
# HELP
# =========================

@bot.message_handler(commands=["help"])
def help_command(message):
    if message.chat.type == "private":
        register_user(message)

    bot.reply_to(
        message,
        "📚 <b>Commands</b>\n\n"
        "/start - Start the bot\n"
        "/help - Show help\n"
        "/id - Show your Telegram ID\n"
        "/dashboard - Open admin dashboard\n"
        "/stats - Show subscriber statistics\n"
        "/users - Show user list\n"
        "/broadcast - Send a message to users",
        parse_mode="HTML"
    )


# =========================
# ID
# =========================

@bot.message_handler(commands=["id"])
def id_command(message):
    if message.chat.type == "private":
        register_user(message)

    bot.reply_to(
        message,
        f"🆔 Your Telegram ID:\n\n{message.from_user.id}"
    )


# =========================
# DASHBOARD COMMAND
# =========================

@bot.message_handler(commands=["dashboard", "stats"])
def dashboard_command(message):
    if not is_admin(message):
        bot.reply_to(
            message,
            "❌ You are not authorized to use this command."
        )
        return

    send_dashboard(message.chat.id)


# =========================
# USER LIST COMMAND
# =========================

@bot.message_handler(commands=["users"])
def users_command(message):
    if not is_admin(message):
        bot.reply_to(
            message,
            "❌ You are not authorized to use this command."
        )
        return

    rows = get_users()

    if not rows:
        bot.reply_to(
            message,
            "👥 No subscribers found."
        )
        return

    bot.send_message(
        message.chat.id,
        f"👥 <b>Total users:</b> {len(rows)}",
        parse_mode="HTML"
    )

    for row in rows:
        (
            user_id,
            username,
            first_name,
            last_name,
            joined_at,
            last_seen,
            status
        ) = row

        name = " ".join(
            part for part in [first_name, last_name]
            if part
        ) or "No name"

        username_text = (
            f"@{username}"
            if username
            else "No username"
        )

        status_text = (
            "🟢 Active"
            if status == "active"
            else "🗑 Deleted/Blocked"
        )

        text = (
            f"👤 <b>{name}</b>\n\n"
            f"Username: {username_text}\n"
            f"ID: <code>{user_id}</code>\n"
            f"Status: {status_text}\n"
            f"Joined: {joined_at}\n"
            f"Last seen: {last_seen}"
        )

        try:
            bot.send_message(
                message.chat.id,
                text,
                parse_mode="HTML"
            )
        except Exception:
            pass


# =========================
# BROADCAST COMMAND
# =========================

@bot.message_handler(commands=["broadcast"])
def broadcast_command(message):
    if not is_admin(message):
        bot.reply_to(
            message,
            "❌ You are not authorized to use this command."
        )
        return

    text = message.text.replace(
        "/broadcast",
        "",
        1
    ).strip()

    if not text:
        bot.reply_to(
            message,
            "Usage:\n/broadcast Your message here"
        )
        return

    send_broadcast(message.chat.id, text)


def send_broadcast(admin_chat_id, text):
    user_ids = get_broadcast_users()

    sent = 0
    failed = 0

    for user_id in user_ids:
        try:
            bot.send_message(user_id, text)
            sent += 1
        except Exception:
            failed += 1
            mark_deleted(user_id)

    bot.send_message(
        admin_chat_id,
        "📨 <b>Broadcast completed</b>\n\n"
        f"🟢 Sent: {sent}\n"
        f"🗑 Failed/Deleted: {failed}",
        parse_mode="HTML"
    )


# =========================
# INLINE BUTTONS
# =========================

@bot.callback_query_handler(
    func=lambda call: call.data in {
        "subscribers",
        "refresh",
        "broadcast",
        "userlist"
    }
)
def dashboard_callback(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(
            call.id,
            "Not authorized.",
            show_alert=True
        )
        return

    if call.data in {"subscribers", "refresh"}:
        try:
            send_dashboard(
                call.message.chat.id,
                call.message.message_id
            )
        except Exception:
            pass

        bot.answer_callback_query(
            call.id,
            "Dashboard updated"
        )
        return

    if call.data == "broadcast":
        broadcast_waiting.add(call.from_user.id)

        bot.answer_callback_query(call.id)

        bot.send_message(
            call.message.chat.id,
            "📨 <b>Send the message now.</b>\n\n"
            "The next message you send will be "
            "broadcast to registered users.\n\n"
            "Send /cancel to cancel.",
            parse_mode="HTML"
        )
        return

    if call.data == "userlist":
        bot.answer_callback_query(call.id)
        users_command(call.message)


# =========================
# CANCEL BROADCAST
# =========================

@bot.message_handler(commands=["cancel"])
def cancel_command(message):
    if message.from_user.id in broadcast_waiting:
        broadcast_waiting.discard(message.from_user.id)

        bot.reply_to(
            message,
            "❌ Broadcast cancelled."
        )
    else:
        bot.reply_to(
            message,
            "There is no active broadcast."
        )


# =========================
# NORMAL TEXT
# =========================

@bot.message_handler(content_types=["text"])
def all_text(message):
    if message.text.startswith("/"):
        return

    if message.from_user.id == ADMIN_ID:
        if message.from_user.id in broadcast_waiting:
            broadcast_waiting.discard(message.from_user.id)

            send_broadcast(
                message.chat.id,
                message.text
            )
            return

    if message.chat.type == "private":
        register_user(message)

    bot.reply_to(
        message,
        "I received your message.\n\n"
        "Use /help to see available commands."
    )


# =========================
# FLASK HOME
# =========================

@app.route("/")
def home():
    return "Bot is running", 200


# =========================
# HEALTH CHECK
# =========================

@app.route("/health")
def health():
    return "OK", 200


# =========================
# TELEGRAM WEBHOOK
# =========================

@app.route(
    f"/webhook/{BOT_TOKEN}",
    methods=["POST"]
)
def webhook():
    json_string = request.get_data().decode("utf-8")

    update = types.Update.de_json(
        json_string
    )

    bot.process_new_updates(
        [update]
    )

    return "OK", 200


# =========================
# WEBHOOK SETUP
# =========================

def setup_webhook():
    render_url = os.getenv(
        "RENDER_EXTERNAL_URL"
    )

    if not render_url:
        print("RENDER_EXTERNAL_URL is missing")
        return

    webhook_url = (
        render_url.rstrip("/")
        + "/webhook/"
        + BOT_TOKEN
    )

    bot.remove_webhook()

    bot.set_webhook(
        url=webhook_url
    )

    print("Webhook set successfully")


# =========================
# START SERVER
# =========================

setup_webhook()

if __name__ == "__main__":
    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
)
