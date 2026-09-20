import os
import sqlite3
import threading
from flask import Flask
import telebot

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 914679628

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is missing")

bot = telebot.TeleBot(BOT_TOKEN)

# =========================
# DATABASE
# =========================

conn = sqlite3.connect(
    "users.db",
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT
)
""")

conn.commit()


def save_user(user):
    cursor.execute("""
        INSERT OR REPLACE INTO users
        (user_id, username, first_name)
        VALUES (?, ?, ?)
    """, (
        user.id,
        user.username or "",
        user.first_name or ""
    ))

    conn.commit()


# =========================
# START COMMAND
# =========================

@bot.message_handler(commands=["start"])
def start(message):
    save_user(message.from_user)

    bot.reply_to(
        message,
        "👋 Welcome!\n\n"
        "You have been successfully registered."
    )


# =========================
# USER COUNT
# =========================

@bot.message_handler(commands=["users"])
def users_command(message):

    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return

    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]

    bot.reply_to(
        message,
        f"👥 Total users: {count}"
    )


# =========================
# USER LIST
# =========================

@bot.message_handler(commands=["userlist"])
def userlist_command(message):

    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return

    cursor.execute("""
        SELECT user_id, username, first_name
        FROM users
        ORDER BY user_id DESC
        LIMIT 50
    """)

    rows = cursor.fetchall()

    if not rows:
        bot.reply_to(message, "No users found.")
        return

    text = "👥 Users:\n\n"

    for user_id, username, first_name in rows:
        name = first_name or "Unknown"

        if username:
            text += f"• {name} (@{username})\n"
        else:
            text += f"• {name}\n"

        text += f"ID: {user_id}\n\n"

    bot.reply_to(message, text)


# =========================
# FLASK SERVER
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Telegram bot is running!"


# =========================
# RUN
# =========================

def run_bot():
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )


if __name__ == "__main__":

    bot_thread = threading.Thread(
        target=run_bot,
        daemon=True
    )

    bot_thread.start()

    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port
    )
