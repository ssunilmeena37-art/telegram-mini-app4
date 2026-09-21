import os
import sqlite3
import threading
from datetime import datetime, timedelta

from flask import Flask
import telebot


# =========================
# CONFIG
# =========================

ADMIN_ID = 914679628
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)


# =========================
# DATABASE
# =========================

conn = sqlite3.connect(
    "users.db",
    check_same_thread=False
)

cursor = conn.cursor()
db_lock = threading.Lock()


cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    first_seen TEXT NOT NULL,
    last_activity TEXT NOT NULL,
    messages INTEGER DEFAULT 0,
    subscribed INTEGER DEFAULT 0,
    subscribed_until TEXT,
    muted INTEGER DEFAULT 0,
    deleted INTEGER DEFAULT 0,
    chat_type TEXT DEFAULT 'private'
)
""")


# पुराने database के लिए missing columns
for column, definition in [
    ("muted", "INTEGER DEFAULT 0"),
    ("deleted", "INTEGER DEFAULT 0"),
    ("chat_type", "TEXT DEFAULT 'private'")
]:
    try:
        cursor.execute(
            f"ALTER TABLE users ADD COLUMN {column} {definition}"
        )
    except sqlite3.OperationalError:
        pass


cursor.execute("""
CREATE TABLE IF NOT EXISTS bot_stats (
    key TEXT PRIMARY KEY,
    value INTEGER DEFAULT 0
)
""")


for key in ("messages", "commands"):
    cursor.execute(
        "INSERT OR IGNORE INTO bot_stats(key, value) VALUES (?, 0)",
        (key,)
    )

conn.commit()


# =========================
# HELPERS
# =========================

def now_text():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def register_user(message):

    user = message.from_user

    uid = user.id
    username = user.username
    first_name = user.first_name or ""
    chat_type = message.chat.type
    now = now_text()

    with db_lock:

        exists = cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (uid,)
        ).fetchone()

        if exists:

            cursor.execute("""
                UPDATE users
                SET username = ?,
                    first_name = ?,
                    last_activity = ?,
                    chat_type = ?,
                    messages = messages + 1
                WHERE user_id = ?
            """, (
                username,
                first_name,
                now,
                chat_type,
                uid
            ))

        else:

            cursor.execute("""
                INSERT INTO users (
                    user_id,
                    username,
                    first_name,
                    first_seen,
                    last_activity,
                    messages,
                    chat_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                uid,
                username
