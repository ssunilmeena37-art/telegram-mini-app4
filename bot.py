import os, sqlite3, threading
from datetime import datetime, timedelta
from flask import Flask
import telebot

ADMIN_ID = 914679628
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
app = Flask(__name__)

DB = sqlite3.connect("users.db", check_same_thread=False)
LOCK = threading.Lock()

with LOCK:
    DB.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        first_seen TEXT NOT NULL,
        last_activity TEXT NOT NULL,
        messages INTEGER DEFAULT 0,
        subscribed INTEGER DEFAULT 0,
        subscribed_until TEXT,
        muted INTEGER DEFAULT 0,
        deleted INTEGER DEFAULT 0
    )""")

    DB.execute("""CREATE TABLE IF NOT EXISTS chats (
        chat_id INTEGER PRIMARY KEY,
        chat_type TEXT,
        title TEXT,
        first_seen TEXT NOT NULL,
        last_activity TEXT NOT NULL
    )""")

    DB.commit()


def now():
    return datetime.utcnow()


def stamp():
    return now().strftime("%Y-%m-%d %H:%M:%S")


def admin(message):
    return message.from_user.id == ADMIN_ID


def need_admin(message):
    if not admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return False
    return True


def register(message):
    user = message.from_user
    chat = message.chat
    current = stamp()

    with LOCK:
        row = DB.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (user.id,)
        ).fetchone()

        if row:
            DB.execute("""
                UPDATE users
                SET username=?,
                    first_name=?,
                    last_activity=?,
                    messages=messages+1
                WHERE user_id=?
            """, (
                user.username,
                user.first_name or "",
                current,
                user.id
            ))
        else:
            DB.execute("""
                INSERT INTO users
                (user_id, username, first_name,
                 first_seen, last_activity, messages)
                VALUES (?, ?, ?, ?, ?, 1)
            """, (
                user.id,
                user.username,
                user.first_name or "",
                current,
                current
            ))

        if chat.type in ("group", "supergroup", "channel"):
            DB.execute("""
                INSERT INTO chats
                (chat_id, chat_type, title,
                 first_seen, last_activity)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                chat_type=excluded.chat_type,
                title=excluded.title,
                last_activity=excluded.last_activity
            """, (
                chat.id,
                chat.type,
                getattr(chat, "title", "") or "",
                current,
                current
            ))

        DB.commit()


def active_sub(until):
    if not until:
        return False

    try:
        return datetime.strptime(
            until,
            "%Y-%m-%d %H:%M:%S"
        ) >= now()
    except ValueError:
        return False


def status(subscribed, until, muted, deleted):

    if deleted:
        return "🔴 Deleted"

    if muted:
        return "🔇 Muted"

    if subscribed and active_sub(until):
        return "🟢 Active"

    return "⚪ Not subscribed"


def find_id(message, usage):

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(
            message,
            f"Usage: <code>{usage}</code>"
        )
        return None

    return int(parts[1])


# =========================
# START
# =========================

@bot.message_handler(commands=["start"])
def start(message):

    register(message)

    bot.reply_to(
        message,
        "👋 <b>Welcome!</b>\n\n"
        "You have been successfully registered.\n\n"
        "Use /help to see commands."
    )


# =========================
# HELP
# =========================

@bot.message_handler(commands=["help"])
def help_command(message):

    register(message)

    if admin(message):

        text = (
            "🛠 <b>ADMIN COMMANDS</b>\n\n"

            "/stats — Dashboard\n"
            "/users — Recent users\n"
            "/subscribers — Subscribers\n"
            "/user ID — User details\n\n"

            "/subscribe ID DAYS — Subscribe\n"
            "/unsubscribe ID — Unsubscribe\n"
            "/mute ID — Mute\n"
            "/unmute ID — Unmute\n"
            "/delete ID — Mark deleted\n"
            "/restore ID — Restore\n\n"

            "/broadcast TEXT — Broadcast"
        )

    else:

        text = (
            "ℹ️ <b>Commands</b>\n\n"
            "/start — Register\n"
            "/help — Help"
        )

    bot.reply_to(message, text)


# =========================
# DASHBOARD / STATS
# =========================

@bot.message_handler(commands=["stats"])
def stats(message):

    if not need_admin(message):
        return

    register(message)

    with LOCK:

        total = DB.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        active = DB.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE subscribed=1
            AND muted=0
            AND deleted=0
            AND subscribed_until>=?
        """, (stamp(),)).fetchone()[0]

        muted = DB.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE muted=1
            AND deleted=0
        """).fetchone()[0]

        deleted = DB.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE deleted=1
        """).fetchone()[0]

        subscribers = DB.execute("""
            SELECT COUNT(*)
            FROM users
            WHERE subscribed=1
        """).fetchone()[0]

        groups = DB.execute("""
            SELECT COUNT(*)
            FROM chats
            WHERE chat_type IN ('group', 'supergroup')
        """).fetchone()[0]

        messages = DB.execute("""
            SELECT COALESCE(SUM(messages), 0)
            FROM users
        """).fetchone()[0]

    bot.reply_to(
        message,

        "📊 <b>BOT DASHBOARD</b>\n\n"

        "@bot\n\n"

        f"🟢 Active Users: <b>{active}</b>\n"
        f"🔇 Muted: <b>{muted}</b>\n"
        f"🔴 Deleted: <b>{deleted}</b>\n"
        f"⭐ Subscribers: <b>{subscribers}</b>\n"
        f"👥 Total Users: <b>{total}</b>\n"
        f"👨‍👩‍👧‍👦 Group Chats: <b>{groups}</b>\n"
        f"💬 Total Messages: <b>{messages}</b>"
    )


# =========================
# USERS
# =========================

@bot.message_handler(commands=["users"])
def users(message):

    if not need_admin(message):
        return

    register(message)

    with LOCK:

        rows = DB.execute("""
            SELECT
                user_id,
                username,
                first_name,
                last_activity,
                messages,
                subscribed,
                subscribed_until,
                muted,
                deleted

            FROM users

            ORDER BY last_activity DESC

            LIMIT 50
        """).fetchall()

    if not rows:

        bot.reply_to(
            message,
            "No users registered yet."
        )

        return

    output = [
        "👥 <b>RECENT USERS (50)</b>",
        ""
    ]

    for row in rows:

        (
            uid,
            username,
            name,
            last,
            msg,
            subscribed,
            until,
            muted,
            deleted
        ) = row

        output.append(
            f"• <b>{name or 'Unknown'}</b> | "
            f"<code>{uid}</code>\n"
            f"  @{username or 'NoUsername'} | "
            f"{status(subscribed, until, muted, deleted)} | "
            f"Msg: {msg} | Last: {last}"
        )

    bot.reply_to(
        message,
        "\n".join(output)
    )


# =========================
# SUBSCRIBERS
# =========================

@bot.message_handler(commands=["subscribers"])
def subscribers(message):

    if not need_admin(message):
        return

    register(message)

    with LOCK:

        rows = DB.execute("""
            SELECT
                user_id,
                username,
                first_name,
                subscribed_until

            FROM users

            WHERE subscribed=1
            AND deleted=0

            ORDER BY subscribed_until DESC
        """).fetchall()

    if not rows:

        bot.reply_to(
            message,
            "⭐ No subscribers found."
        )

        return

    output = [
        "⭐ <b>SUBSCRIBERS</b>",
        ""
    ]

    for uid, username, name, until in rows:

        state = (
            "🟢 Active"
            if active_sub(until)
            else "⚪ Expired"
        )

        output.append(
            f"• {name or 'Unknown'} | "
            f"<code>{uid}</code>\n"
            f"  @{username or 'None'} | "
            f"{state} | Until: {until or 'N/A'}"
        )

    bot.reply_to(
        message,
        "\n".join(output)
    )


# =========================
# USER DETAILS
# =========================

@bot.message_handler(commands=["user"])
def user_details(message):

    if not need_admin(message):
        return

    register(message)

    uid = find_id(
        message,
        "/user USER_ID"
    )

    if uid is None:
        return

    with LOCK:

        row = DB.execute("""
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

            WHERE user_id=?
        """, (uid,)).fetchone()

    if not row:

        bot.reply_to(
            message,
            "❌ User not found."
        )

        return

    (
        uid,
        username,
        name,
        first_seen,
        last_activity,
        messages,
        subscribed,
        until,
        muted,
        deleted
    ) = row

    bot.reply_to(
        message,

        "👤 <b>USER DETAILS</b>\n\n"

        f"Name: <b>{name or 'Unknown'}</b>\n"
        f"Username: @{username or 'None'}\n"
        f"ID: <code>{uid}</code>\n"
        f"First Seen: {first_seen}\n"
        f"Last Activity: {last_activity}\n"
        f"Messages: {messages}\n"
        f"Status: "
        f"{status(subscribed, until, muted, deleted)}\n"
        f"Subscribed Until: {until or 'N/A'}"
    )


# =========================
# SUBSCRIBE
# =========================

@bot.message_handler(commands=["subscribe"])
def subscribe(message):

    if not need_admin(message):
        return

    register(message)

    parts = message.text.split()

    if (
        len(parts) != 3
        or not parts[1].isdigit()
        or not parts[2].isdigit()
        or int(parts[2]) <= 0
    ):

        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/subscribe USER_ID DAYS</code>"
        )

        return

    uid = int(parts[1])
    days = int(parts[2])

    with LOCK:

        row = DB.execute(
            """
            SELECT subscribed_until
            FROM users
            WHERE user_id=?
            """,
            (uid,)
        ).fetchone()

        if not row:

            bot.reply_to(
                message,
                "❌ User not found."
            )

            return

        base = now()

        if row[0]:

            try:

                old_date = datetime.strptime(
                    row[0],
                    "%Y-%m-%d %H:%M:%S"
                )

                if old_date > base:
                    base = old_date

            except ValueError:
                pass

        until = (
            base + timedelta(days=days)
        ).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        DB.execute(
            """
            UPDATE users
            SET subscribed=1,
                subscribed_until=?,
                deleted=0
            WHERE user_id=?
            """,
            (until, uid)
        )

        DB.commit()

    bot.reply_to(
        message,

        "✅ <b>Subscribed</b>\n\n"
        f"User: <code>{uid}</code>\n"
        f"Added: <b>{days} days</b>\n"
        f"Until: <b>{until} UTC</b>"
    )


# =========================
# UNSUBSCRIBE
# =========================

@bot.message_handler(commands=["unsubscribe"])
def unsubscribe(message):

    if not need_admin(message):
        return

    register(message)

    uid = find_id(
        message,
        "/unsubscribe USER_ID"
    )

    if uid is None:
        return

    with LOCK:

        changed = DB.execute(
            """
            UPDATE users
            SET subscribed=0,
                subscribed_until=NULL
            WHERE user_id=?
            """,
            (uid,)
        ).rowcount

        DB.commit()

    bot.reply_to(
        message,
        "✅ Unsubscribed."
        if changed
        else "❌ User not found."
    )


# =========================
# FLAG HELPER
# =========================

def set_flag(message, column, value, label, command):

    if not need_admin(message):
        return

    register(message)

    uid = find_id(
        message,
        f"/{command} USER_ID"
    )

    if uid is None:
        return

    with LOCK:

        changed = DB.execute(
            f"""
            UPDATE users
            SET {column}=?
            WHERE user_id=?
            """,
            (value, uid)
        ).rowcount

        DB.commit()

    if changed:

        bot.reply_to(
            message,
            f"✅ {label} updated for "
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
def mute(message):
    set_flag(
        message,
        "muted",
        1,
        "Muted",
        "mute"
    )


# =========================
# UNMUTE
# =========================

@bot.message_handler(commands=["unmute"])
def unmute(message):
    set_flag(
        message,
        "muted",
        0,
        "Unmuted",
        "unmute"
    )


# =========================
# DELETE
# =========================

@bot.message_handler(commands=["delete"])
def delete_user(message):
    set_flag(
        message,
        "deleted",
        1,
        "Deleted",
        "delete"
    )


# =========================
# RESTORE
# =========================

@bot.message_handler(commands=["restore"])
def restore(message):
    set_flag(
        message,
        "deleted",
        0,
        "Restored",
        "restore"
    )


# =========================
# BROADCAST
# =========================

@bot.message_handler(commands=["broadcast"])
def broadcast(message):

    if not need_admin(message):
        return

    register(message)

    text = (
        message.text
        .partition(" ")[2]
        .strip()
    )

    if not text:

        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/broadcast Your message here</code>"
        )

        return

    with LOCK:

        user_ids = [
            row[0]
            for row in DB.execute("""
                SELECT user_id
                FROM users
                WHERE deleted=0
                AND muted=0
            """).fetchall()
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
def normal_text(message):

    if not message.text.startswith("/"):
        register(message)


# =========================
# FLASK
# =========================

@app.route("/")
def home():

    return (
        "Telegram bot is running",
        200
    )


@app.route("/health")
def health():

    return (
        "OK",
        200
    )


# =========================
# TELEGRAM POLLING
# =========================

def run_bot():

    bot.remove_webhook()

    bot.infinity_polling(
        timeout=30,
        long_polling_timeout=30,
        skip_pending=True,
        allowed_updates=["message"]
    )


# =========================
# START
# =========================

if __name__ == "__main__":

    threading.Thread(
        target=run_bot,
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                "10000"
            )
        )
  )
