import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, request, render_template_string
import telebot
from telebot import types


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# तुम्हारी Admin ID — इसे नहीं बदलना
ADMIN_ID = 914679628

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")

DB_FILE = "users.db"


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN is missing in Render Environment Variables"
    )

if not DASHBOARD_PASSWORD:
    raise RuntimeError(
        "DASHBOARD_PASSWORD is missing in Render Environment Variables"
    )


bot = telebot.TeleBot(
    BOT_TOKEN,
    parse_mode="HTML"
)

app = Flask(__name__)

DB_LOCK = threading.RLock()


# ============================================================
# DATABASE
# ============================================================

def get_db():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    return conn


def init_db():

    with DB_LOCK:

        conn = get_db()

        try:

            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (

                    user_id INTEGER PRIMARY KEY,

                    username TEXT DEFAULT '',

                    first_name TEXT DEFAULT '',

                    first_seen TEXT NOT NULL,

                    last_seen TEXT NOT NULL,

                    message_count INTEGER DEFAULT 0,

                    command_count INTEGER DEFAULT 0

                )
            """)

            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(users)"
                ).fetchall()
            }

            if "username" not in columns:

                conn.execute(
                    "ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''"
                )

            if "first_name" not in columns:

                conn.execute(
                    "ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT ''"
                )

            if "first_seen" not in columns:

                conn.execute(
                    "ALTER TABLE users ADD COLUMN first_seen TEXT"
                )

            if "last_seen" not in columns:

                conn.execute(
                    "ALTER TABLE users ADD COLUMN last_seen TEXT"
                )

            if "message_count" not in columns:

                conn.execute(
                    "ALTER TABLE users ADD COLUMN message_count INTEGER DEFAULT 0"
                )

            if "command_count" not in columns:

                conn.execute(
                    "ALTER TABLE users ADD COLUMN command_count INTEGER DEFAULT 0"
                )

            conn.commit()

        finally:

            conn.close()


init_db()


# ============================================================
# TIME
# ============================================================

def now_utc():

    return datetime.now(timezone.utc)


def now_iso():

    return now_utc().isoformat()


def start_of_today():

    return now_utc().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )


def start_of_yesterday():

    return start_of_today() - timedelta(days=1)


# ============================================================
# SAVE / UPDATE USER
# ============================================================

def save_user(user, is_command=False):

    current_time = now_iso()

    username = user.username or ""
    first_name = user.first_name or ""

    with DB_LOCK:

        conn = get_db()

        try:

            existing = conn.execute(
                "SELECT user_id FROM users WHERE user_id = ?",
                (user.id,)
            ).fetchone()

            if existing:

                if is_command:

                    conn.execute("""
                        UPDATE users

                        SET username = ?,
                            first_name = ?,
                            last_seen = ?,
                            message_count =
                                COALESCE(message_count, 0) + 1,
                            command_count =
                                COALESCE(command_count, 0) + 1

                        WHERE user_id = ?

                    """, (
                        username,
                        first_name,
                        current_time,
                        user.id
                    ))

                else:

                    conn.execute("""
                        UPDATE users

                        SET username = ?,
                            first_name = ?,
                            last_seen = ?,
                            message_count =
                                COALESCE(message_count, 0) + 1

                        WHERE user_id = ?

                    """, (
                        username,
                        first_name,
                        current_time,
                        user.id
                    ))

            else:

                conn.execute("""
                    INSERT INTO users (

                        user_id,
                        username,
                        first_name,
                        first_seen,
                        last_seen,
                        message_count,
                        command_count

                    )

                    VALUES (?, ?, ?, ?, ?, ?, ?)

                """, (
                    user.id,
                    username,
                    first_name,
                    current_time,
                    current_time,
                    1,
                    1 if is_command else 0
                ))

            conn.commit()

        finally:

            conn.close()


# ============================================================
# STATISTICS
# ============================================================

def count_users(condition="", params=()):

    with DB_LOCK:

        conn = get_db()

        try:

            query = "SELECT COUNT(*) FROM users"

            if condition:

                query += " WHERE " + condition

            return conn.execute(
                query,
                params
            ).fetchone()[0]

        finally:

            conn.close()


def get_statistics():

    current = now_utc()

    today = start_of_today()

    yesterday = start_of_yesterday()

    tomorrow = today + timedelta(days=1)

    active_24 = current - timedelta(hours=24)

    active_7 = current - timedelta(days=7)

    active_30 = current - timedelta(days=30)

    inactive_30 = active_30

    inactive_60 = current - timedelta(days=60)


    total = count_users()


    today_new = count_users(
        "first_seen >= ? AND first_seen < ?",
        (
            today.isoformat(),
            tomorrow.isoformat()
        )
    )


    yesterday_new = count_users(
        "first_seen >= ? AND first_seen < ?",
        (
            yesterday.isoformat(),
            today.isoformat()
        )
    )


    active_24_count = count_users(
        "last_seen >= ?",
        (active_24.isoformat(),)
    )


    active_7_count = count_users(
        "last_seen >= ?",
        (active_7.isoformat(),)
    )


    active_30_count = count_users(
        "last_seen >= ?",
        (active_30.isoformat(),)
    )


    inactive_30_count = count_users(
        "last_seen < ?",
        (inactive_30.isoformat(),)
    )


    inactive_60_count = count_users(
        "last_seen < ?",
        (inactive_60.isoformat(),)
    )


    month_start = today.replace(day=1)


    this_month = count_users(
        "first_seen >= ?",
        (month_start.isoformat(),)
    )


    with DB_LOCK:

        conn = get_db()

        try:

            totals = conn.execute("""
                SELECT

                    COALESCE(SUM(message_count), 0),

                    COALESCE(SUM(command_count), 0)

                FROM users
            """).fetchone()

        finally:

            conn.close()


    return {

        "total": total,

        "today": today_new,

        "yesterday": yesterday_new,

        "month": this_month,

        "active_24": active_24_count,

        "active_7": active_7_count,

        "active_30": active_30_count,

        "inactive_30": inactive_30_count,

        "inactive_60": inactive_60_count,

        "messages": totals[0],

        "commands": totals[1]

    }


# ============================================================
# STATISTICS TEXT
# ============================================================

def statistics_text():

    stats = get_statistics()

    return (

        "📊 <b>BOT STATISTICS</b>\n"

        "━━━━━━━━━━━━━━━━━━\n\n"

        f"👥 <b>Total Users:</b> {stats['total']}\n"

        f"🆕 <b>Today New:</b> {stats['today']}\n"

        f"📅 <b>Yesterday New:</b> {stats['yesterday']}\n"

        f"🗓️ <b>This Month New:</b> {stats['month']}\n\n"

        f"🔥 <b>Active 24 Hours:</b> {stats['active_24']}\n"

        f"📅 <b>Active 7 Days:</b> {stats['active_7']}\n"

        f"🟢 <b>Active 30 Days:</b> {stats['active_30']}\n\n"

        f"💤 <b>Inactive 30+ Days:</b> {stats['inactive_30']}\n"

        f"💤 <b>Inactive 60+ Days:</b> {stats['inactive_60']}\n\n"

        f"💬 <b>Total Messages:</b> {stats['messages']}\n"

        f"⚡ <b>Total Commands:</b> {stats['commands']}\n\n"

        "━━━━━━━━━━━━━━━━━━"

    )


# ============================================================
# ADMIN CHECK
# ============================================================

def admin_only(message):

    if message.from_user.id != ADMIN_ID:

        bot.reply_to(
            message,
            "❌ <b>Unauthorized.</b>"
        )

        return False

    return True


# ============================================================
# START
# ============================================================

@bot.message_handler(commands=["start"])
def start(message):

    save_user(
        message.from_user,
        is_command=True
    )

    bot.reply_to(
        message,

        "👋 <b>Welcome!</b>\n\n"

        "You have been successfully registered."
    )


# ============================================================
# STATS BUTTONS
# ============================================================

def stats_keyboard():

    keyboard = types.InlineKeyboardMarkup(
        row_width=2
    )


    keyboard.add(

        types.InlineKeyboardButton(
            "👥 Total Users",
            callback_data="stats_total"
        ),

        types.InlineKeyboardButton(
            "🆕 Today",
            callback_data="stats_today"
        )

    )


    keyboard.add(

        types.InlineKeyboardButton(
            "🔥 Active 24h",
            callback_data="stats_24"
        ),

        types.InlineKeyboardButton(
            "📅 Active 7d",
            callback_data="stats_7"
        )

    )


    keyboard.add(

        types.InlineKeyboardButton(
            "🟢 Active 30d",
            callback_data="stats_30"
        ),

        types.InlineKeyboardButton(
            "💤 Inactive",
            callback_data="stats_inactive"
        )

    )


    keyboard.add(

        types.InlineKeyboardButton(
            "👤 Recent Users",
            callback_data="stats_users"
        ),

        types.InlineKeyboardButton(
            "🔄 Refresh",
            callback_data="stats_refresh"
        )

    )


    return keyboard


# ============================================================
# /STATS
# ============================================================

@bot.message_handler(
    commands=["stats", "stat", "botstats"]
)
def stats_command(message):

    save_user(
        message.from_user,
        is_command=True
    )

    if not admin_only(message):

        return


    bot.reply_to(

        message,

        statistics_text(),

        reply_markup=stats_keyboard()

    )


# ============================================================
# STATS BUTTON ACTIONS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("stats_")
)
def stats_callback(call):

    if call.from_user.id != ADMIN_ID:

        bot.answer_callback_query(
            call.id,
            "Unauthorized",
            show_alert=True
        )

        return


    action = call.data


    if action == "stats_total":

        stats = get_statistics()

        text = (
            "👥 <b>Total Users:</b> "
            f"{stats['total']}"
        )


    elif action == "stats_today":

        stats = get_statistics()

        text = (
            "🆕 <b>New Users Today:</b> "
            f"{stats['today']}"
        )


    elif action == "stats_24":

        stats = get_statistics()

        text = (
            "🔥 <b>Active Last 24 Hours:</b> "
            f"{stats['active_24']}"
        )


    elif action == "stats_7":

        stats = get_statistics()

        text = (
            "📅 <b>Active Last 7 Days:</b> "
            f"{stats['active_7']}"
        )


    elif action == "stats_30":

        stats = get_statistics()

        text = (
            "🟢 <b>Active Last 30 Days:</b> "
            f"{stats['active_30']}"
        )


    elif action == "stats_inactive":

        stats = get_statistics()

        text = (

            "💤 <b>Inactive 30+ Days:</b> "
            f"{stats['inactive_30']}\n\n"

            "💤 <b>Inactive 60+ Days:</b> "
            f"{stats['inactive_60']}"

        )


    elif action == "stats_users":

        send_recent_users(
            call.message.chat.id
        )

        bot.answer_callback_query(call.id)

        return


    else:

        text = statistics_text()


    bot.edit_message_text(

        text,

        call.message.chat.id,

        call.message.message_id,

        reply_markup=stats_keyboard()

    )


    bot.answer_callback_query(call.id)


# ============================================================
# USER LIST
# ============================================================

def get_users(
    limit=50,
    condition="",
    params=()
):

    with DB_LOCK:

        conn = get_db()

        try:

            query = """

                SELECT

                    user_id,
                    username,
                    first_name,
                    first_seen,
                    last_seen,
                    message_count,
                    command_count

                FROM users

            """


            if condition:

                query += " WHERE " + condition


            query += """

                ORDER BY last_seen DESC

                LIMIT ?

            """


            return conn.execute(

                query,

                tuple(params) + (limit,)

            ).fetchall()

        finally:

            conn.close()


def format_user_list(
    rows,
    title="👥 RECENT USERS"
):

    if not rows:

        return (
            f"<b>{title}</b>\n\n"
            "No users found."
        )


    lines = [

        f"<b>{title}</b>",

        "━━━━━━━━━━━━━━━━━━"

    ]


    for row in rows:

        (

            user_id,
            username,
            first_name,
            first_seen,
            last_seen,
            messages,
            commands

        ) = row


        name = first_name or "Unknown"

        account = (
            f"@{username}"
            if username
            else "No username"
        )


        lines.append(

            f"👤 <b>{name}</b> ({account})\n"

            f"ID: <code>{user_id}</code>\n"

            f"Last: {last_seen}\n"

            f"Messages: {messages} | "
            f"Commands: {commands}\n"

        )


    return "\n".join(lines)


def send_recent_users(chat_id):

    rows = get_users(
        limit=25
    )


    text = format_user_list(rows)


    if len(text) > 3900:

        text = (
            text[:3900]
            + "\n\n…"
        )


    bot.send_message(
        chat_id,
        text
    )


# ============================================================
# /USERS
# ============================================================

@bot.message_handler(
    commands=["users", "userlist"]
)
def users_command(message):

    save_user(
        message.from_user,
        is_command=True
    )


    if not admin_only(message):

        return


    send_recent_users(
        message.chat.id
    )


# ============================================================
# TRACK ALL OTHER MESSAGES
# ============================================================

@bot.message_handler(
    func=lambda message: True,

    content_types=[

        "text",
        "photo",
        "video",
        "document",
        "audio",
        "voice",
        "sticker",
        "animation",
        "contact",
        "location",
        "venue"

    ]
)
def track_activity(message):

    save_user(
        message.from_user,
        is_command=False
    )


# ============================================================
# WEB DASHBOARD
# ============================================================

DASHBOARD_HTML = """

<!DOCTYPE html>

<html>

<head>

<meta
name="viewport"
content="width=device-width, initial-scale=1"
>

<meta
http-equiv="refresh"
content="30"
>

<title>Bot Dashboard</title>


<style>

body {

    font-family: Arial, sans-serif;

    background: #f3f4f6;

    margin: 0;

    padding: 20px;

    color: #111827;

}


h1 {

    text-align: center;

}


.grid {

    display: grid;

    grid-template-columns:
        repeat(
            auto-fit,
            minmax(180px, 1fr)
        );

    gap: 15px;

    max-width: 1100px;

    margin: 30px auto;

}


.card {

    background: white;

    padding: 22px;

    border-radius: 15px;

    box-shadow:
        0 3px 12px
        rgba(0,0,0,.08);

    text-align: center;

}


.number {

    font-size: 32px;

    font-weight: bold;

    margin-top: 10px;

}


.users {

    max-width: 1100px;

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


th,
td {

    padding: 10px;

    border-bottom:
        1px solid #ddd;

    text-align: left;

    white-space: nowrap;

}


.small {

    text-align: center;

    color: #6b7280;

}

</style>

</head>


<body>


<h1>
📊 BOT STATISTICS
</h1>


<p class="small">
Auto refresh: 30 seconds
</p>


<div class="grid">


<div class="card">

👥 Total Users

<div class="number">
{{ stats["total"] }}
</div>

</div>


<div class="card">

🆕 Today New

<div class="number">
{{ stats["today"] }}
</div>

</div>


<div class="card">

🔥 Active 24h

<div class="number">
{{ stats["active_24"] }}
</div>

</div>


<div class="card">

📅 Active 7d

<div class="number">
{{ stats["active_7"] }}
</div>

</div>


<div class="card">

🟢 Active 30d

<div class="number">
{{ stats["active_30"] }}
</div>

</div>


<div class="card">

💤 Inactive 30d+

<div class="number">
{{ stats["inactive_30"] }}
</div>

</div>


<div class="card">

💤 Inactive 60d+

<div class="number">
{{ stats["inactive_60"] }}
</div>

</div>


<div class="card">

🗓️ This Month

<div class="number">
{{ stats["month"] }}
</div>

</div>


<div class="card">

💬 Messages

<div class="number">
{{ stats["messages"] }}
</div>

</div>


<div class="card">

⚡ Commands

<div class="number">
{{ stats["commands"] }}
</div>

</div>


</div>


<div class="users">


<h2>
👤 Recent Users
</h2>


<table>


<tr>

<th>Name</th>

<th>Username</th>

<th>User ID</th>

<th>First Seen</th>

<th>Last Activity</th>

<th>Messages</th>

</tr>


{% for user in users %}


<tr>

<td>
{{ user[2] or "Unknown" }}
</td>


<td>

{{ ("@"
