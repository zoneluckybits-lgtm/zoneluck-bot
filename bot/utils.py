import random
import string
from database import db


def generate_ticket_number():
    chars = string.ascii_uppercase + string.digits
    while True:
        ticket = "ZL-" + "".join(random.choices(chars, k=8))
        with db() as conn:
            exists = conn.execute(
                "SELECT id FROM lottery_tickets WHERE ticket_number = ?", (ticket,)
            ).fetchone()
        if not exists:
            return ticket


def get_setting(key):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else ""


def set_setting(key, value):
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )


def get_user_by_telegram_id(telegram_id):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()


def get_user_by_id(user_id):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_lang(telegram_id):
    with db() as conn:
        row = conn.execute(
            "SELECT language FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if row and row["language"] in ("ar", "en"):
            return row["language"]
        return "ar"


def set_user_lang(telegram_id, lang):
    with db() as conn:
        conn.execute(
            "UPDATE users SET language = ? WHERE telegram_id = ?", (lang, telegram_id)
        )


def register_user(telegram_id, username, full_name, referred_by_telegram_id=None):
    with db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if existing:
            return existing["id"]

        referrer_id = None
        if referred_by_telegram_id:
            ref = conn.execute(
                "SELECT id FROM users WHERE telegram_id = ?", (referred_by_telegram_id,)
            ).fetchone()
            if ref:
                referrer_id = ref["id"]

        cursor = conn.execute(
            "INSERT INTO users (telegram_id, username, full_name, referred_by) VALUES (?, ?, ?, ?)",
            (telegram_id, username, full_name, referrer_id),
        )
        return cursor.lastrowid


def get_referral_tree(user_id):
    with db() as conn:
        referrer = conn.execute(
            """SELECT u.id, u.telegram_id, u.username, u.full_name
               FROM users u
               JOIN users child ON child.referred_by = u.id
               WHERE child.id = ?""",
            (user_id,),
        ).fetchone()

        downline = conn.execute(
            """SELECT id, telegram_id, username, full_name
               FROM users WHERE referred_by = ?""",
            (user_id,),
        ).fetchall()

        return referrer, list(downline)


def format_user_name(user):
    if user["username"]:
        return f"@{user['username']}"
    return user["full_name"] or f"User#{user['telegram_id']}"
