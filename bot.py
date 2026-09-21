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
                username,
                first_name,
                now,
                now,
                1,
                chat_type
            ))

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


def subscription_active(until):

    if not until:
        return False

    try:

        return datetime.strptime(
            until,
            "%Y-%m-%d %H:%M:%S"
        ) >= datetime.utcnow()

    except ValueError:

        return False


# =========================
# START
# =========================

@bot.message_handler(commands=["start"])
def start(message):

    register_user(message)
    record_command()

    bot.reply_to(
        message,
        "👋 <b>Welcome!</b>\n\n"
        "You have been successfully registered."
    )


# =========================
# HELP
# =========================

@bot.message_handler(commands=["help"])
def help_command(message):

    register_user(message)
    record_command()

    if is_admin(message):

        text = (
            "🛠 <b>Admin Commands</b>\n\n"

            "/stats - Bot statistics\n"
            "/users - Recent users\n"
            "/user ID - User details\n\n"

            "/subscribe ID DAYS - Add subscription\n"
            "/unsubscribe ID - Remove subscription\n\n"

            "/mute ID - Mute user\n"
            "/unmute ID - Unmute user\n"

            "/delete ID - Mark user deleted\n"
            "/restore ID - Restore user\n\n"

            "/broadcast TEXT - Send message to users\n"

            "/help - Show this help"
        )

    else:

        text = (
            "ℹ️ <b>Commands</b>\n\n"
            "/start - Register\n"
            "/help - Help"
        )

    bot.reply_to(message, text)


# =========================
# STATS
# =========================

@bot.message_handler(commands=["stats"])
def stats(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    with db_lock:

        # Total users
        total_users = cursor.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE chat_type = 'private'
        """).fetchone()[0]


        # Active subscribers
        active = cursor.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE subscribed = 1
            AND muted = 0
            AND deleted = 0
            AND (
                subscribed_until IS NULL
                OR subscribed_until >= ?
            )
        """, (
            now_text(),
        )).fetchone()[0]


        # Muted
        muted = cursor.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE muted = 1
            AND deleted = 0
        """).fetchone()[0]


        # Deleted
        deleted = cursor.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE deleted = 1
        """).fetchone()[0]


        # Groups
        group_chats = cursor.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE chat_type IN (
                'group',
                'supergroup'
            )
        """).fetchone()[0]


    bot.reply_to(
        message,

        "📊 <b>Bot Statistics</b>\n\n"

        "@bot\n"

        f"Active: <b>{active}</b>\n"
        f"Muted: <b>{muted}</b>\n"
        f"Deleted: <b>{deleted}</b>\n"
        f"Total Users: <b>{total_users}</b>\n"
        f"Group Chats: <b>{group_chats}</b>"
    )


# =========================
# USERS
# =========================

@bot.message_handler(commands=["users"])
def users(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    with db_lock:

        rows = cursor.execute("""
            SELECT
                user_id,
                username,
                first_name,
                first_seen,
                last_activity,
                messages,
                subscribed,
                subscribed_until,
                muted,
                deleted

            FROM users

            ORDER BY last_activity DESC

            LIMIT 30
        """).fetchall()


    if not rows:

        bot.reply_to(
            message,
            "No users registered yet."
        )

        return


    lines = [
        "👥 <b>Recent Users</b>\n"
    ]


    for row in rows:

        (
            uid,
            username,
            first_name,
            first_seen,
            last_activity,
            messages,
            subscribed,
            subscribed_until,
            muted,
            deleted
        ) = row


        name = first_name or "Unknown"

        uname = (
            f"@{username}"
            if username
            else "No username"
        )


        if deleted:

            status = "🔴 Deleted"

        elif muted:

            status = "🔇 Muted"

        elif subscribed and subscription_active(
            subscribed_until
        ):

            status = "🟢 Active"

        else:

            status = "⚪ Not subscribed"


        lines.append(
            f"• <b>{name}</b>\n"
            f"  Username: {uname}\n"
            f"  ID: <code>{uid}</code>\n"
            f"  Messages: {messages}\n"
            f"  Status: {status}\n"
            f"  First: {first_seen}\n"
            f"  Last: {last_activity}\n"
        )


    bot.reply_to(
        message,
        "\n".join(lines)
    )


# =========================
# USER DETAILS
# =========================

@bot.message_handler(commands=["user"])
def user_details(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split(
        maxsplit=1
    )


    if (
        len(parts) != 2
        or not parts[1].strip().isdigit()
    ):

        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/user 123456789</code>"
        )

        return


    uid = int(
        parts[1].strip()
    )


    with db_lock:

        row = cursor.execute("""
            SELECT
                user_id,
                username,
                first_name,
                first_seen,
                last_activity,
                messages,
                subscribed,
                subscribed_until,
                muted,
                deleted

            FROM users

            WHERE user_id = ?
        """, (
            uid,
        )).fetchone()


    if not row:

        bot.reply_to(
            message,
            "❌ User not found."
        )

        return


    (
        uid,
        username,
        first_name,
        first_seen,
        last_activity,
        messages,
        subscribed,
        subscribed_until,
        muted,
        deleted
    ) = row


    if deleted:

        status = "🔴 Deleted"

    elif muted:

        status = "🔇 Muted"

    elif subscribed and subscription_active(
        subscribed_until
    ):

        status = "🟢 Active"

    else:

        status = "⚪ Not subscribed"


    bot.reply_to(
        message,

        "👤 <b>User Details</b>\n\n"

        f"Name: <b>{first_name or 'Unknown'}</b>\n"

        f"Username: "
        f"@{username if username else 'None'}\n"

        f"ID: <code>{uid}</code>\n"

        f"First Seen: {first_seen}\n"

        f"Last Activity: {last_activity}\n"

        f"Messages: {messages}\n"

        f"Subscription: {status}\n"

        f"Until: "
        f"{subscribed_until or 'N/A'}\n"

        f"Muted: "
        f"{'Yes' if muted else 'No'}\n"

        f"Deleted: "
        f"{'Yes' if deleted else 'No'}"
    )


# =========================
# SUBSCRIBE
# =========================

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

            "<code>"
            "/subscribe USER_ID DAYS"
            "</code>\n\n"

            "Example:\n"

            "<code>"
            "/subscribe 123456789 30"
            "</code>"
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

        row = cursor.execute(
            """
            SELECT subscribed_until
            FROM users
            WHERE user_id = ?
            """,
            (uid,)
        ).fetchone()


        if not row:

            bot.reply_to(
                message,
                "❌ User not found."
            )

            return


        current_until = row[0]

        base = datetime.utcnow()


        if current_until:

            try:

                old_date = datetime.strptime(
                    current_until,
                    "%Y-%m-%d %H:%M:%S"
                )

                if old_date > base:

                    base = old_date

            except ValueError:

                pass


        new_until = (
            base +
            timedelta(days=days)
        )


        new_until_text = (
            new_until.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )


        cursor.execute(
            """
            UPDATE users

            SET subscribed = 1,
                subscribed_until = ?,
                deleted = 0

            WHERE user_id = ?
            """,

            (
                new_until_text,
                uid
            )
        )


        conn.commit()


    bot.reply_to(
        message,

        "✅ <b>Subscription updated</b>\n\n"

        f"User ID: <code>{uid}</code>\n"

        f"Added: <b>{days} days</b>\n"

        f"Valid until: "
        f"<b>{new_until_text} UTC</b>"
    )


# =========================
# UNSUBSCRIBE
# =========================

@bot.message_handler(commands=["unsubscribe"])
def unsubscribe(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split()


    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        bot.reply_to(
            message,

            "Usage:\n"
            "<code>"
            "/unsubscribe USER_ID"
            "</code>"
        )

        return


    uid = int(parts[1])


    with db_lock:

        cursor.execute(
            """
            UPDATE users

            SET subscribed = 0,
                subscribed_until = NULL

            WHERE user_id = ?
            """,

            (uid,)
        )


        changed = cursor.rowcount

        conn.commit()


    if changed:

        bot.reply_to(
            message,

            "✅ Subscription removed for "
            f"<code>{uid}</code>."
        )

    else:

        bot.reply_to(
            message,
            "❌ User not found."
        )


# =========================
# MUTE
# =========================

@bot.message_handler(commands=["mute"])
def mute_user(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split()


    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        bot.reply_to(
            message,

            "Usage:\n"
            "<code>/mute USER_ID</code>"
        )

        return


    uid = int(parts[1])


    with db_lock:

        cursor.execute(
            """
            UPDATE users

            SET muted = 1

            WHERE user_id = ?
            """,

            (uid,)
        )


        changed = cursor.rowcount

        conn.commit()


    if changed:

        bot.reply_to(
            message,
            "🔇 User muted."
        )

    else:

        bot.reply_to(
            message,
            "❌ User not found."
        )


# =========================
# UNMUTE
# =========================

@bot.message_handler(commands=["unmute"])
def unmute_user(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split()


    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        bot.reply_to(
            message,

            "Usage:\n"
            "<code>/unmute USER_ID</code>"
        )

        return


    uid = int(parts[1])


    with db_lock:

        cursor.execute(
            """
            UPDATE users

            SET muted = 0

            WHERE user_id = ?
            """,

            (uid,)
        )


        changed = cursor.rowcount

        conn.commit()


    if changed:

        bot.reply_to(
            message,
            "🔊 User unmuted."
        )

    else:

        bot.reply_to(
            message,
            "❌ User not found."
        )


# =========================
# DELETE
# =========================

@bot.message_handler(commands=["delete"])
def delete_user(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split()


    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        bot.reply_to(
            message,

            "Usage:\n"
            "<code>/delete USER_ID</code>"
        )

        return


    uid = int(parts[1])


    with db_lock:

        cursor.execute(
            """
            UPDATE users

            SET deleted = 1

            WHERE user_id = ?
            """,

            (uid,)
        )


        changed = cursor.rowcount

        conn.commit()


    if changed:

        bot.reply_to(
            message,
            "🗑 User marked as deleted."
        )

    else:

        bot.reply_to(
            message,
            "❌ User not found."
        )


# =========================
# RESTORE
# =========================

@bot.message_handler(commands=["restore"])
def restore_user(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    parts = message.text.split()


    if (
        len(parts) != 2
        or not parts[1].isdigit()
    ):

        bot.reply_to(
            message,

            "Usage:\n"
            "<code>/restore USER_ID</code>"
        )

        return


    uid = int(parts[1])


    with db_lock:

        cursor.execute(
            """
            UPDATE users

            SET deleted = 0

            WHERE user_id = ?
            """,

            (uid,)
        )


        changed = cursor.rowcount

        conn.commit()


    if changed:

        bot.reply_to(
            message,
            "♻️ User restored."
        )

    else:

        bot.reply_to(
            message,
            "❌ User not found."
        )


# =========================
# BROADCAST
# =========================

@bot.message_handler(commands=["broadcast"])
def broadcast(message):

    if not admin_only(message):
        return

    register_user(message)
    record_command()

    text = (
        message.text
        .partition(" ")[2]
        .strip()
    )


    if not text:

        bot.reply_to(
            message,

            "Usage:\n"

            "<code>"
            "/broadcast Your message here"
            "</code>"
        )

        return


    with db_lock:

        user_ids = [
            row[0]

            for row in cursor.execute(
                """
                SELECT user_id

                FROM users

                WHERE deleted = 0
                AND muted = 0
                AND chat_type = 'private'
                """
            ).fetchall()
        ]


    sent = 0
    failed = 0


    for uid in user_ids:

        try:

            bot.send_message(
                uid,
                text
            )

            sent += 1

        except Exception:

            failed += 1


    bot.reply_to(
        message,

        "📢 <b>Broadcast complete</b>\n\n"

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


# =========================
# FLASK
# =========================

@app.route("/")
def home():

    return (
       
