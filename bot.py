import os
import sqlite3
import threading
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

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

DB_FILE = "users.db"


# =========================
# DATABASE
# =========================

db_lock = threading.Lock()

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


def register_user(message):
    user = message.from_user

    username = user.username or ""
    first_name = user.first_name or ""
    last_name = user.last_name or ""

    with db_lock:
        cursor.execute(
            """
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            """,
            (
                user.id,
                username,
                first_name,
                last_name
            )
        )

        conn.commit()


def get_user_count():
    with db_lock:
        cursor.execute("SELECT COUNT(*) FROM users")
        result = cursor.fetchone()

    return result[0]


def get_all_users():
    with db_lock:
        cursor.execute("SELECT user_id FROM users")
        rows = cursor.fetchall()

    return [row[0] for row in rows]


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

    bot.reply_to(message, text)


# =========================
# HELP
# =========================

@bot.message_handler(commands=["help"])
def help_command(message):
    register_user(message)

    text = (
        "📚 Available Commands\n\n"
        "/start - Start the bot\n"
        "/help - Show help\n"
        "/id - Show your Telegram ID\n"
        "/users - Show total users (admin only)\n"
        "/broadcast - Broadcast a message (admin only)"
    )

    bot.reply_to(message, text)


# =========================
# USER ID
# =========================

@bot.message_handler(commands=["id"])
def id_command(message):
    register_user(message)

    bot.reply_to(
        message,
        f"🆔 Your Telegram ID:\n\n{message.from_user.id}"
    )


# =========================
# ADMIN USERS
# =========================

@bot.message_handler(commands=["users"])
def users_command(message):
    register_user(message)

    if message.from_user.id != ADMIN_ID:
        bot.reply_to(
            message,
            "❌ You are not authorized to use this command."
        )
        return

    count = get_user_count()

    bot.reply_to(
        message,
        f"👥 Total registered users: {count}"
    )


# =========================
# ADMIN BROADCAST
# =========================

@bot.message_handler(commands=["broadcast"])
def broadcast_command(message):
    register_user(message)

    if message.from_user.id != ADMIN_ID:
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

    users = get_all_users()

    sent = 0
    failed = 0

    for user_id in users:
        try:
            bot.send_message(
                user_id,
                text
            )
            sent += 1

        except Exception:
            failed += 1

    bot.reply_to(
        message,
        "📢 Broadcast completed.\n\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}"
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
# FLASK HEALTH CHECK
# =========================

@app.route("/")
def home():
    return "Bot is running", 200


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
# START SERVER
# =========================

if __name__ == "__main__":
    render_url = os.getenv(
        "RENDER_EXTERNAL_URL"
    )

    if render_url:
        webhook_url = (
            render_url
            + "/webhook/"
            + BOT_TOKEN
        )

        bot.remove_webhook()
        bot.set_webhook(
            url=webhook_url
        )

    port = int(
        os.getenv("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port
)
