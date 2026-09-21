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

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

if ADMIN_ID == 0:
    raise RuntimeError("ADMIN_ID environment variable is missing")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

DB_FILE = "users.db"
db_lock = threading.Lock()


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
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    joined_at TEXT,
    last_seen TEXT,
    status TEXT DEFAULT 'active'
)
""")

conn.commit()


# =========================
# REGISTER USER
# =========================

def register_user(message):

    user = message.from_user

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    with db_lock:

        cursor.execute(
            """
            INSERT INTO users
            (
                user_id,
                username,
                first_name,
                last_name,
                joined_at,
                last_seen,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'active')

            ON CONFLICT(user_id)
            DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                last_seen = excluded.last_seen,
                status = 'active'
            """,
            (
                user.id,
                user.username or "",
                user.first_name or "",
                user.last_name or "",
                now,
                now
            )
        )

        conn.commit()


# =========================
# ADMIN CHECK
# =========================

def is_admin(message):

    return message.from_user.id == ADMIN_ID


# =========================
# STATISTICS
# =========================

def get_stats():

    cutoff = (
        datetime.now()
        - timedelta(days=7)
    ).strftime("%Y-%m-%d %H:%M:%S")

    with db_lock:

        cursor.execute(
            "SELECT COUNT(*) FROM users"
        )

        total = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE status = 'active'
            AND last_seen >= ?
            """,
            (cutoff,)
        )

        active = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE status = 'deleted'
            """
        )

        deleted = cursor.fetchone()[0]

    return active, deleted, total


# =========================
# DASHBOARD BUTTONS
# =========================

def dashboard_markup():

    keyboard = types.InlineKeyboardMarkup()

    keyboard.row(
        types.InlineKeyboardButton(
            "👥 Subscribers",
            callback_data="subscribers"
        ),
        types.InlineKeyboardButton(
            "📊 Refresh",
            callback_data="refresh"
        )
    )

    keyboard.row(
        types.InlineKeyboardButton(
            "📨 Send New Post",
            callback_data="broadcast_help"
        ),
        types.InlineKeyboardButton(
            "📋 User List",
            callback_data="userlist"
        )
    )

    return keyboard


# =========================
# DASHBOARD TEXT
# =========================

def dashboard_text():

    active, deleted, total = get_stats()

    return (
        "📊 <b>Subscribers</b>\n\n"
        f"🟢 <b>Active:</b> {active}\n"
        "🔇 <b>Muted:</b> "
        "Not available via Telegram Bot API\n"
        f"🗑 <b>Deleted:</b> {deleted}\n"
        f"👥 <b>Total:</b> {total}\n\n"
        "👤 <b>Users</b>\n"
        "👥 Group chats: Not tracked\n\n"
        "🕐 Active = interacted with "
        "the bot in the last 7 days."
    )


# =========================
# START
# =========================

@bot.message_handler(commands=["start"])
def start_command(message):

    if message.chat.type == "private":
        register_user(message)

    bot.reply_to(
        message,
        "👋 Hello!\n\n"
        "Welcome to the bot.\n\n"
        "Use /dashboard to open "
        "the subscriber dashboard."
    )


# =========================
# DASHBOARD
# =========================

@bot.message_handler(
    commands=["dashboard", "stats"]
)
def dashboard_command(message):

    if not is_admin(message):

        bot.reply_to(
            message,
            "❌ You are not authorized "
            "to use this command."
        )

        return

    bot.send_message(
        message.chat.id,
        dashboard_text(),
        parse_mode="HTML",
        reply_markup=dashboard_markup()
    )


# =========================
# USERS LIST
# =========================

@bot.message_handler(commands=["users"])
def users_command(message):

    if not is_admin(message):

        bot.reply_to(
            message,
            "❌ You are not authorized "
            "to use this command."
        )

        return

    with db_lock:

        cursor.execute(
            """
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
            """
        )

        rows = cursor.fetchall()

    if not rows:

        bot.reply_to(
            message,
            "👥 No subscribers found."
        )

        return

    bot.send_message(
        message.chat.id,
        f"👥 <b>Total Subscribers:</b> {len(rows)}",
        parse_mode="HTML"
    )

    for (
        user_id,
        username,
        first_name,
        last_name,
        joined_at,
        last_seen,
        status
    ) in rows:

        name = " ".join(
            x
            for x in [
                first_name,
                last_name
            ]
            if x
        ) or "No name"

        username_text = (
            f"@{username}"
            if username
            else "No username"
        )

        icon = (
            "🟢"
            if status == "active"
            else "🗑"
        )

        text = (
            f"{icon} <b>{name}</b>\n\n"
            f"Username: {username_text}\n"
            f"ID: <code>{user_id}</code>\n"
            f"Status: {status}\n"
            f"Joined: {joined_at}\n"
            f"Last seen: "
            f"{last_seen or 'Unknown'}"
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
# BROADCAST
# =========================

@bot.message_handler(
    commands=["broadcast"]
)
def broadcast_command(message):

    if not is_admin(message):

        bot.reply_to(
            message,
            "❌ You are not authorized "
            "to use this command."
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
            "Usage:\n"
            "/broadcast Your message here"
        )

        return

    with db_lock:

        cursor.execute(
            """
            SELECT user_id
            FROM users
            WHERE status != 'deleted'
            """
        )

        rows = cursor.fetchall()

    sent = 0
    failed = 0

    for (user_id,) in rows:

        try:

            bot.send_message(
                user_id,
                text
            )

            sent += 1

        except Exception:

            failed += 1

            with db_lock:

                cursor.execute(
                    """
                    UPDATE users
                    SET status = 'deleted'
                    WHERE user_id = ?
                    """,
                    (user_id,)
                )

                conn.commit()

    bot.reply_to(
        message,
        "📨 <b>Broadcast completed</b>\n\n"
        f"🟢 Sent: {sent}\n"
        f"🗑 Failed/Deleted: {failed}",
        parse_mode="HTML"
    )


# =========================
# DASHBOARD BUTTON ACTIONS
# =========================

@bot.callback_query_handler(
    func=lambda call: call.data in [
        "subscribers",
        "refresh",
        "broadcast_help",
        "userlist"
    ]
)
def dashboard_callback(call):

    if call.from_user.id != ADMIN_ID:

        bot.answer_callback_query(
            call.id,
            "Not authorized.",
            show_alert=True
        )

        return

    if call.data in [
        "subscribers",
        "refresh"
    ]:

        bot.edit_message_text(
            dashboard_text(),
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=dashboard_markup()
        )

        bot.answer_callback_query(
            call.id,
            "Updated"
        )

    elif call.data == "broadcast_help":

        bot.answer_callback_query(
            call.id
        )

        bot.send_message(
            call.message.chat.id,
            "📨 Send a new post with:\n\n"
            "/broadcast Your message here"
        )

    elif call.data == "userlist":

        bot.answer_callback_query(
            call.id
        )

        users_command(
            call.message
        )


# =========================
# NORMAL TEXT
# =========================

@bot.message_handler(
    content_types=["text"]
)
def all_text(message):

    if message.text.startswith("/"):
        return

    if message.chat.type == "private":
        register_user(message)

    bot.reply_to(
        message,
        "Use /dashboard to open "
        "the subscriber dashboard."
    )


# =========================
# HOME
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

    update = types.Update.de_json(
        request.get_data().decode("utf-8")
    )

    bot.process_new_updates(
        [update]
    )

    return "OK", 200


# =========================
# SET WEBHOOK
# =========================

def setup_webhook():

    render_url = os.getenv(
        "RENDER_EXTERNAL_URL"
    )

    if not render_url:
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
