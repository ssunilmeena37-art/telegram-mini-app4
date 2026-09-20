import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from flask import Flask, request, render_template_string
import telebot

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 914679628

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing in Render Environment Variables")

bot = telebot.TeleBot(BOT_TOKEN)

app = Flask(__name__)

# Dashboard password Render Environment Variable से आएगा
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")

if not DASHBOARD_PASSWORD:
    raise RuntimeError(
        "DASHBOARD_PASSWORD is missing in Render Environment Variables"
    )

# =========================================================
# DATABASE
# =========================================================

conn = sqlite3.connect(
    "users.db",
    check_same_thread=False
)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    first_seen TEXT,
    last_seen TEXT
)
""")

conn.commit()


# पुराने database में columns missing हों तो add करो
def add_column_if_missing(column_name):
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]

    if column_name not in columns:
        cursor.execute(
            f"ALTER TABLE users ADD COLUMN {column_name} TEXT"
        )
        conn.commit()


add_column_if_missing("first_seen")
add_column_if_missing("last_seen")


# =========================================================
# TIME
# =========================================================

def now_utc():
    return datetime.now(timezone.utc)


def now_string():
    return now_utc().isoformat()


# =========================================================
# SAVE / UPDATE USER
# =========================================================

def save_user(user):
    current_time = now_string()

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user.id,)
    )

    exists = cursor.fetchone()

    if exists:
        cursor.execute("""
            UPDATE users
            SET username = ?,
                first_name = ?,
                last_seen = ?
            WHERE user_id = ?
        """, (
            user.username or "",
            user.first_name or "",
            current_time,
            user.id
        ))
    else:
        cursor.execute("""
            INSERT INTO users
            (user_id, username, first_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user.id,
            user.username or "",
            user.first_name or "",
            current_time,
            current_time
        ))

    conn.commit()


# =========================================================
# /START
# =========================================================

@bot.message_handler(commands=["start"])
def start(message):
    save_user(message.from_user)

    bot.reply_to(
        message,
        "👋 Welcome!\n\n"
        "You have been successfully registered."
    )


# =========================================================
# TRACK OTHER MESSAGES
# =========================================================

@bot.message_handler(
    func=lambda message: True,
    content_types=[
        "text",
        "photo",
        "video",
        "document",
        "audio",
        "voice",
        "sticker"
    ]
)
def track_activity(message):
    save_user(message.from_user)

    # Normal messages के लिए कोई automatic reply नहीं
    return


# =========================================================
# GET STATISTICS
# =========================================================

def get_statistics():

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    current = now_utc()

    today_start = current.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    active_24 = current - timedelta(hours=24)
    active_7 = current - timedelta(days=7)
    inactive_30 = current - timedelta(days=30)

    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE first_seen >= ?",
        (today_start.isoformat(),)
    )
    today_users = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE last_seen >= ?",
        (active_24.isoformat(),)
    )
    active_24_count = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE last_seen >= ?",
        (active_7.isoformat(),)
    )
    active_7_count = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM users WHERE last_seen < ?",
        (inactive_30.isoformat(),)
    )
    inactive_30_count = cursor.fetchone()[0]

    return {
        "total": total_users,
        "today": today_users,
        "active_24": active_24_count,
        "active_7": active_7_count,
        "inactive_30": inactive_30_count
    }


# =========================================================
# /STATS
# =========================================================

@bot.message_handler(commands=["stats"])
def stats_command(message):

    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return

    stats = get_statistics()

    text = (
        "📊 BOT STATISTICS\n\n"
        f"👥 Total Users: {stats['total']}\n"
        f"🆕 Today: {stats['today']}\n"
        f"🔥 Active (24h): {stats['active_24']}\n"
        f"📅 Active (7d): {stats['active_7']}\n"
        f"💤 Inactive (30d): {stats['inactive_30']}"
    )

    bot.reply_to(message, text)


# =========================================================
# /USERS
# =========================================================

@bot.message_handler(commands=["users"])
def users_command(message):

    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return

    stats = get_statistics()

    bot.reply_to(
        message,
        f"👥 Total users: {stats['total']}"
    )


# =========================================================
# /USERLIST
# =========================================================

@bot.message_handler(commands=["userlist"])
def userlist_command(message):

    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return

    cursor.execute("""
        SELECT user_id, username, first_name, first_seen, last_seen
        FROM users
        ORDER BY last_seen DESC
        LIMIT 50
    """)

    rows = cursor.fetchall()

    if not rows:
        bot.reply_to(message, "No users found.")
        return

    text = "👥 RECENT USERS\n\n"

    for user_id, username, first_name, first_seen, last_seen in rows:

        name = first_name or "Unknown"

        if username:
            text += f"• {name} (@{username})\n"
        else:
            text += f"• {name}\n"

        text += f"ID: {user_id}\n"
        text += f"Last: {last_seen}\n\n"

    # Telegram message limit से बचने के लिए छोटा हिस्सा भेजें
    if len(text) > 4000:
        text = text[:4000]

    bot.reply_to(message, text)


# =========================================================
# WEB DASHBOARD
# =========================================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Bot Dashboard</title>

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #f3f4f6;
            margin: 0;
            padding: 20px;
        }

        h1 {
            text-align: center;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            max-width: 1000px;
            margin: 30px auto;
        }

        .card {
            background: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 3px 12px rgba(0,0,0,0.08);
            text-align: center;
        }

        .number {
            font-size: 32px;
            font-weight: bold;
            margin-top: 10px;
        }

        .users {
            max-width: 1000px;
            margin: 30px auto;
            background: white;
            padding: 20px;
            border-radius: 15px;
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th, td {
            padding: 10px;
            border-bottom: 1px solid #ddd;
            text-align: left;
        }
    </style>
</head>

<body>

<h1>📊 BOT STATISTICS</h1>

<div class="grid">

    <div class="card">
        👥 Total Users
        <div class="number">{{ stats.total }}</div>
    </div>

    <div class="card">
        🆕 Today
        <div class="number">{{ stats.today }}</div>
    </div>

    <div class="card">
        🔥 Active 24h
        <div class="number">{{ stats.active_24 }}</div>
    </div>

    <div class="card">
        📅 Active 7d
        <div class="number">{{ stats.active_7 }}</div>
    </div>

    <div class="card">
        💤 Inactive 30d
        <div class="number">{{ stats.inactive_30 }}</div>
    </div>

</div>

<div class="users">

<h2>👤 Recent Users</h2>

<table>

<tr>
    <th>Name</th>
    <th>Username</th>
    <th>User ID</th>
    <th>Last Activity</th>
</tr>

{% for user in users %}

<tr>
    <td>{{ user[2] }}</td>
    <td>{{ user[1] }}</td>
    <td>{{ user[0] }}</td>
    <td>{{ user[4] }}</td>
</tr>

{% endfor %}

</table>

</div>

</body>
</html>
"""


# =========================================================
# DASHBOARD LOGIN
# =========================================================

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():

    password = request.args.get("password", "")

    if password != DASHBOARD_PASSWORD:
        return """
        <html>
        <body style="font-family:Arial;text-align:center;padding:50px;">
            <h2>🔐 Dashboard Protected</h2>
            <p>Use your dashboard password.</p>
        </body>
        </html>
        """, 401

    stats = get_statistics()

    cursor.execute("""
        SELECT user_id, username, first_name, first_seen, last_seen
        FROM users
        ORDER BY last_seen DESC
        LIMIT 100
    """)

    users = cursor.fetchall()

    return render_template_string(
        DASHBOARD_HTML,
        stats=type("Stats", (), stats),
        users=users
    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():
    return "Telegram bot is running successfully."


# =========================================================
# BOT THREAD
# =========================================================

def run_bot():
    bot.infinity_polling(
        skip_pending=True,
        timeout=30,
        long_polling_timeout=30
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port
  )
