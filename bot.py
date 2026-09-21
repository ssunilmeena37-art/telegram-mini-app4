import os
import sqlite3
import threading
from datetime import datetime, timedelta

from flask import Flask
import telebot

ADMIN_ID = 914679628
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

conn = sqlite3.connect("users.db", check_same_thread=False)
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
    subscribed_until TEXT
)
""")

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


def now_text():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def register_user(message):
    user = message.from_user
    uid = user.id
    username = user.username
    first_name = user.first_name or ""
    now = now_text()

    with db_lock:
        cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (uid,)
        )
        exists = cursor.fetchone()

        if exists:
            cursor.execute("""
                UPDATE users
                SET username = ?, first_name = ?, last_activity = ?,
                    messages = messages + 1
                WHERE user_id = ?
            """, (username, first_name, now, uid))
        else:
            cursor.execute("""
                INSERT INTO users
                (user_id, username, first_name, first_seen,
                 last_activity, messages)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (uid, username, first_name, now, now))

        cursor.execute("""
            UPDATE bot_stats
            SET value = value + 1
            WHERE key = 'messages'
        """)

        conn.commit()


def record_command():
    with db_lock:
        cursor.execute("""
            UPDATE bot_stats
            SET value = value + 1
            WHERE key = 'commands'
        """)
        conn.commit()


def is_admin(message):
    return message.from_user.id == ADMIN_ID


def admin_only(message):
    if not is_admin(message):
        bot.reply_to(
            message,
            "⛔ This command is available to the admin only."
        )
        return False
    return True


@bot.message_handler(commands=["start"])
def start(message):
    register_user(message)
    record_command()

    bot.reply_to(
        message,
        "👋 <b>Welcome!</b>\n\n"
        "You have been successfully registered."
    )


@bot.message_handler(commands=["help"])
def help_command(message):
    register_user(message)
    record_command()

    if is_admin(message):
        text = (
            "🛠 <b>Admin Commands</b>\n\n"
            "/stats - Bot statistics\n"
            "/users - Recent users\n"
            "/user ID - User details\n"
            "/subscribe ID DAYS - Add subscription\n"
            "/unsubscribe ID - Remove subscription\n"
            "/broadcast TEXT - Send message to all users\n"
            "/help - Show this help"
        )
    else:
        text = (
            "ℹ️ <b>Commands</b>\n\n"
            "/start - Register\n"
            "/help - Help"
        )

    bot.reply_to(message, text)


@bot.message_handler(commands=["stats"])
def stats(message):
    if not admin_only(message):
        return

    register_user(message)
    record_command()

    with db_lock:
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE subscribed = 1
            AND (
                subscribed_until IS NULL
                OR subscribed_until >= ?
            )
        """, (now_text(),))

        active_subscribers = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COALESCE(SUM(messages), 0)
            FROM users
        """)

        messages = cursor.fetchone()[0]

        cursor.execute("""
            SELECT value FROM bot_stats
            WHERE key = 'commands'
        """)

        commands = cursor.fetchone()[0]

        today = datetime.utcnow().strftime("%Y-%m-%d")

        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE first_seen LIKE ?
        """, (today + "%",))

        today_users = cursor.fetchone()[0]

    bot.reply_to(
        message,
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total Users: <b>{total}</b>\n"
        f"🟢 Active Subscribers: <b>{active_subscribers}</b>\n"
        f"💬 Messages: <b>{messages}</b>\n"
        f"⚡ Commands: <b>{commands}</b>\n"
        f"📅 New Today: <b>{today_users}</b>"
    )


@bot.message_handler(commands=["users"])
def users(message):
    if not admin_only(message):
        return

    register_user(message)
    record_command()

    with db_lock:
        cursor.execute("""
            SELECT user_id, username, first_name, first_seen,
                   last_activity, messages, subscribed,
                   subscribed_until
            FROM users
            ORDER BY last_activity DESC
            LIMIT 30
        """)

        rows = cursor.fetchall()

    if not rows:
        bot.reply_to(message, "No users registered yet.")
        return

    lines = ["👥 <b>Recent Users</b>\n"]

    for row in rows:
        uid, username, first_name, first_seen, last_activity, messages, subscribed, until = row

        name = first_name or "Unknown"
        uname = f"@{username}" if username else "No username"
        status = "🟢 Subscribed" if subscribed else "⚪ Not subscribed"

        lines.append(
            f"• <b>{name}</b>\n"
            f"  Username: {uname}\n"
            f"  ID: <code>{uid}</code>\n"
            f"  Messages: {messages}\n"
            f"  {status}\n"
            f"  Last: {last_activity}\n"
        )

    bot.reply_to(message, "\n".join(lines))


@bot.message_handler(commands=["user"])
def user_details(message):
    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split(maxsplit=1)

    if len(parts) != 2 or not parts[1].strip().isdigit():
        bot.reply_to(
            message,
            "Usage:\n<code>/user 123456789</code>"
        )
        return

    uid = int(parts[1].strip())

    with db_lock:
        cursor.execute("""
            SELECT user_id, username, first_name, first_seen,
                   last_activity, messages, subscribed,
                   subscribed_until
            FROM users
            WHERE user_id = ?
        """, (uid,))

        row = cursor.fetchone()

    if not row:
        bot.reply_to(message, "❌ User not found.")
        return

    uid, username, first_name, first_seen, last_activity, messages, subscribed, until = row

    status = "🟢 Active" if subscribed else "⚪ Not subscribed"

    if subscribed and until:
        try:
            if datetime.strptime(
                until,
                "%Y-%m-%d %H:%M:%S"
            ) < datetime.utcnow():
                status = "🔴 Subscription expired"
        except ValueError:
            pass

    bot.reply_to(
        message,
        "👤 <b>User Details</b>\n\n"
        f"Name: <b>{first_name or 'Unknown'}</b>\n"
        f"Username: @{username if username else 'None'}\n"
        f"ID: <code>{uid}</code>\n"
        f"First Seen: {first_seen}\n"
        f"Last Activity: {last_activity}\n"
        f"Messages: {messages}\n"
        f"Subscription: {status}\n"
        f"Until: {until or 'N/A'}"
    )


@bot.message_handler(commands=["subscribe"])
def subscribe(message):
    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split()

    if (
        len(parts) != 3
        or not parts[1].isdigit()
        or not parts[2].isdigit()
    ):
        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/subscribe USER_ID DAYS</code>\n\n"
            "Example:\n"
            "<code>/subscribe 123456789 30</code>"
        )
        return

    uid = int(parts[1])
    days = int(parts[2])

    if days <= 0:
        bot.reply_to(
            message,
            "❌ Days must be greater than 0."
        )
        return

    with db_lock:
        cursor.execute(
            "SELECT subscribed_until FROM users WHERE user_id = ?",
            (uid,)
        )

        row = cursor.fetchone()

        if not row:
            bot.reply_to(message, "❌ User not found.")
            return

        current_until = row[0]
        base = datetime.utcnow()

        if current_until:
            try:
                parsed = datetime.strptime(
                    current_until,
                    "%Y-%m-%d %H:%M:%S"
                )

                if parsed > base:
                    base = parsed

            except ValueError:
                pass

        new_until = base + timedelta(days=days)

        new_until_text = new_until.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        cursor.execute("""
            UPDATE users
            SET subscribed = 1,
                subscribed_until = ?
            WHERE user_id = ?
        """, (new_until_text, uid))

        conn.commit()

    bot.reply_to(
        message,
        "✅ <b>Subscription updated</b>\n\n"
        f"User ID: <code>{uid}</code>\n"
        f"Added: <b>{days} days</b>\n"
        f"Valid until: <b>{new_until_text} UTC</b>"
    )


@bot.message_handler(commands=["unsubscribe"])
def unsubscribe(message):
    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/unsubscribe USER_ID</code>"
        )
        return

    uid = int(parts[1])

    with db_lock:
        cursor.execute("""
            UPDATE users
            SET subscribed = 0,
                subscribed_until = NULL
            WHERE user_id = ?
        """, (uid,))

        changed = cursor.rowcount
        conn.commit()

    if changed:
        bot.reply_to(
            message,
            f"✅ Subscription removed for <code>{uid}</code>."
        )
    else:
        bot.reply_to(
            message,
            "❌ User not found."
        )


@bot.message_handler(commands=["broadcast"])
def broadcast(message):
    if not admin_only(message):
        return

    register_user(message)
    record_command()

    text = message.text.partition(" ")[2].strip()

    if not text:
        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/broadcast Your message here</code>"
        )
        return

    with db_lock:
        cursor.execute("SELECT user_id FROM users")
        user_ids = [
            row[0]
            for row in cursor.fetchall()
        ]

    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1

    bot.reply_to(
        message,
        "📢 <b>Broadcast complete</b>\n\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}"
    )


@bot.message_handler(content_types=["text"])
def all_text(message):
    if message.text.startswith("/"):
        return

    register_user(message)


@app.route("/")
def home():
    return "Telegram bot is running", 200


@app.route("/health")
def health():
    return "OK", 200


def run_bot():
    print("Removing webhook...")
    bot.remove_webhook()

    print("Starting Telegram polling...")

    bot.infinity_polling(
        timeout=30,
        long_polling_timeout=30,
        skip_pending=True,
        allowed_updates=["message"]
    )


if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=port
    )
