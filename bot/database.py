import os
from contextlib import contextmanager
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "")


class DictRow(dict):
    """Mimics sqlite3.Row — supports both key and integer index access."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class PGCursor:
    """Wraps a psycopg2 cursor with a sqlite3-compatible interface.

    Key behaviours:
    - Converts '?' placeholders to '%s' automatically.
    - Appends 'RETURNING id' to INSERT statements so that .lastrowid works.
    - Returns DictRow objects from fetchone/fetchall.
    """

    def __init__(self, raw_cur):
        self._cur = raw_cur
        self._lastrowid = None
        self._is_insert = False

    def execute(self, sql, params=None):
        sql_pg = sql.replace("?", "%s")
        self._is_insert = sql_pg.strip().upper().startswith("INSERT")

        if self._is_insert and "RETURNING" not in sql_pg.upper():
            sql_pg = sql_pg.rstrip().rstrip(";") + " RETURNING id"

        self._cur.execute(sql_pg, params or ())

        if self._is_insert:
            row = self._cur.fetchone()
            self._lastrowid = row[0] if row else None

        return self

    def fetchone(self):
        if self._is_insert:
            return None
        row = self._cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return DictRow(zip(cols, row))

    def fetchall(self):
        if self._is_insert:
            return []
        rows = self._cur.fetchall()
        if not rows:
            return []
        cols = [d[0] for d in self._cur.description]
        return [DictRow(zip(cols, row)) for row in rows]

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount


class PGConnection:
    """Wraps a psycopg2 connection with a sqlite3-compatible interface."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = PGCursor(self._conn.cursor())
        return cur.execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return PGConnection(conn)


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        for stmt in [
            """CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                balance DOUBLE PRECISION DEFAULT 0.0,
                referred_by INTEGER REFERENCES users(id),
                referral_rewarded INTEGER DEFAULT 0,
                language TEXT DEFAULT 'ar',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS deposits (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount DOUBLE PRECISION NOT NULL,
                network TEXT NOT NULL,
                tx_hash TEXT,
                proof_file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS withdrawals (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount DOUBLE PRECISION NOT NULL,
                wallet_address TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS matches (
                id SERIAL PRIMARY KEY,
                team_home TEXT NOT NULL,
                team_away TEXT NOT NULL,
                match_time TIMESTAMP NOT NULL,
                status TEXT DEFAULT 'upcoming',
                result_home INTEGER,
                result_away INTEGER,
                yellow_card_players TEXT DEFAULT '',
                red_card_players TEXT DEFAULT '',
                penalty_score_home INTEGER,
                penalty_score_away INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS bets (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                bet_type TEXT NOT NULL,
                entry_fee DOUBLE PRECISION NOT NULL,
                prediction TEXT NOT NULL,
                payout DOUBLE PRECISION NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settled_at TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS lottery_tickets (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticket_number TEXT UNIQUE NOT NULL,
                draw_id INTEGER,
                prize_tier INTEGER,
                prize_amount DOUBLE PRECISION DEFAULT 0,
                status TEXT DEFAULT 'active',
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS lottery_draws (
                id SERIAL PRIMARY KEY,
                first_ticket TEXT,
                second_ticket TEXT,
                third_ticket TEXT,
                drawn_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )""",
            "INSERT INTO settings (key, value) VALUES ('trc20_address', '') ON CONFLICT (key) DO NOTHING",
            "INSERT INTO settings (key, value) VALUES ('bep20_address', '') ON CONFLICT (key) DO NOTHING",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'ar'",
        ]:
            conn.execute(stmt)
