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

cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
)

conn.commit()


# Add new columns to old database if needed
def add_column_if_missing(column_name, column_type):
    with db_lock:
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]

        if column_name not in columns:
            cursor.execute(
                f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"
            )
            conn.commit()


add_column_if_missing("last_seen", "TEXT")
add_column_if_missing("status", "TEXT")


# =========================
# REGISTER / UPDATE USER
# =========================

def register_user(message):
    user = message.from_user

    username = user.username or ""
    first_name = user.first_name or ""
    last_name = user.last_name or ""

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
            VALUES (?, ?, ?, ?, ?, ?, ?)
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
                username,
                first_name,
                last_name,
                now,
                now,
                "active"
            )
        )

        conn.commit()


# =========================
# ADMIN CHECK
# =========================

def is_admin(message):
    return message.from_user.id == ADMIN_ID


# =========================
# GET STATISTICS
# =========================

def get_statistics():
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
            """
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
# START
# =========================

@bot.message_handler(commands=["start"])
def start_command(message):

    register_user(message)

    name = message.from_user.first_name or "User"

    text = (
        f"👋 Hello {name}!\n\n"
        "Welcome to the bot.\n\n"
        "Use /help to see available commands."
    )

    bot.reply_to(
        message,
        text
    )


# =========================
# HELP
# =========================

@bot.message_handler(commands=["help"])
def help_command(message):

    register_user(message)

    text = (
        "📚 Commands\n\n"
        "/start - Start bot\n"
        "/help - Help\n"
        "/id - Your Telegram ID\n"
        "/stats - Subscriber statistics\n"
        "/users - User list\n"
        "/broadcast - Broadcast message"
    )

    bot.reply_to(
        message,
        text
    )


# =========================
# USER ID
# =========================

@bot.message_handler(commands=["id"])
def id_command(message):

    register_user(message)

    bot.reply_to(
        message,
        f"🆔 Your Telegram ID:\n\n"
        f"{message.from_user.id}"
    )


# =========================
# SUBSCRIBER STATS
# =========================

@bot.message_handler(commands=["stats"])
def stats_command(message):

    register_user(message)

    if not is_admin(message):
        bot.reply_to(
            message,
            "❌ You are not authorized to use this command."
        )
        return

    active, deleted, total = get_statistics()

    text = (
        "📊 Subscribers\n\n"
        f"🟢 Active: {active}\n"
        "🔇 Muted: Not available\n"
        f"🗑 Deleted: {deleted}\n"
        f"👥 Total: {total}\n\n"
        "👤 Users\n"
        "👥 Group chats: Not tracked"
    )

    bot.reply_to(
        message,
        text
    )


# =========================
# USERS LIST
# =========================

@bot.message_handler(commands=["users"])
def users_command(message):

    register_user(message)

    if not is_admin(message):
        bot.reply_to(
            message,
            "❌ You are not authorized to use this command."
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

        users = cursor.fetchall()

    if not users:
        bot.reply_to(
            message,
            "👥 No users found."
        )
        return

    bot.reply_to(
        message,
        f"👥 Total Users: {len(users)}"
    )

    for (
        user_id,
        username,
        first_name,
        last_name,
        joined_at,
        last_seen,
        status
    ) in users:

        name_parts = []

        if first_name:
            name_parts.append(first_name)

        if last_name:
            name_parts.append(last_name)

        name = (
            " ".join(name_parts)
            if name_parts
            else "No name"
        )

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
            "👤 User\n\n"
            f"Name: {name}\n"
            f"Username: {username_text}\n"
            f"ID: {user_id}\n"
            f"Status: {status_text}\n"
            f"Joined: {joined_at}\n"
            f"Last interaction: {last_seen or 'Unknown'}"
        )

        try:
            bot.send_message(
                message.chat.id,
                text
            )
        except Exception:
            pass


# =========================
# BROADCAST
# =========================

@bot.message_handler(commands=["broadcast"])
def broadcast_command(message):

    register_user(message)

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
            OR status IS NULL
            """
        )

        rows = cursor.fetchall()

    sent = 0
    failed = 0

    for row in rows:

        user_id = row[0]

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
        "📢 Broadcast completed.\n\n"
        f"🟢 Sent: {sent}\n"
        f"🗑 Failed/Deleted: {failed}"
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

    json_string = request.get_data().decode(
        "utf-8"
    )

    update = types.Update.de_json(
        json_string
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

    render_url = render_url.rstrip("/")

    webhook_url = (
        render_url
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
