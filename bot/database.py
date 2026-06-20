import os
import sqlite3
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2


# ──────────────────────────────────────────────
#  Shared DictRow (works for both backends)
# ──────────────────────────────────────────────

class DictRow(dict):
    """Supports both key and integer-index access, like sqlite3.Row."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


# ──────────────────────────────────────────────
#  PostgreSQL backend
# ──────────────────────────────────────────────

class PGCursor:
    def __init__(self, raw_cur):
        self._cur = raw_cur
        self._lastrowid = None
        self._is_insert = False

    def execute(self, sql, params=None):
        sql_pg = sql.replace("?", "%s")
        self._is_insert = sql_pg.strip().upper().startswith("INSERT")
        if self._is_insert and "RETURNING" not in sql_pg.upper():
            sql_pg = sql_pg.rstrip().rstrip(";") + " RETURNING *"
        self._cur.execute(sql_pg, params or ())
        if self._is_insert:
            row = self._cur.fetchone()
            if row is not None and self._cur.description:
                cols = [d[0] for d in self._cur.description]
                self._lastrowid = row[cols.index("id")] if "id" in cols else None
            else:
                self._lastrowid = None
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


# ──────────────────────────────────────────────
#  SQLite backend (fallback)
# ──────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "zoneluck.db")


class SQLiteCursor:
    """Wraps sqlite3 cursor so rows are returned as DictRow."""
    def __init__(self, raw_cur):
        self._cur = raw_cur

    def execute(self, sql, params=None):
        self._cur.execute(sql, params or ())
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return DictRow(zip(row.keys(), tuple(row)))

    def fetchall(self):
        rows = self._cur.fetchall()
        return [DictRow(zip(r.keys(), tuple(r))) for r in rows]

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount


class SQLiteConnection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = SQLiteCursor(self._conn.cursor())
        return cur.execute(sql, params)

    def executescript(self, script):
        self._conn.executescript(script)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ──────────────────────────────────────────────
#  Unified db() context manager
# ──────────────────────────────────────────────

def get_connection():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        return PGConnection(conn)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return SQLiteConnection(conn)


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


# ──────────────────────────────────────────────
#  init_db — creates all tables on first run
# ──────────────────────────────────────────────

def init_db():
    if USE_POSTGRES:
        _init_postgres()
    else:
        _init_sqlite()


def _init_postgres():
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
            "INSERT INTO settings (key,value) VALUES ('trc20_address','') ON CONFLICT (key) DO NOTHING",
            "INSERT INTO settings (key,value) VALUES ('bep20_address','') ON CONFLICT (key) DO NOTHING",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'ar'",
        ]:
            conn.execute(stmt)


def _init_sqlite():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                balance REAL DEFAULT 0.0,
                referred_by INTEGER REFERENCES users(id),
                referral_rewarded INTEGER DEFAULT 0,
                language TEXT DEFAULT 'ar',
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount REAL NOT NULL,
                network TEXT NOT NULL,
                tx_hash TEXT,
                proof_file_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                amount REAL NOT NULL,
                wallet_address TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            );
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                match_id INTEGER NOT NULL REFERENCES matches(id),
                bet_type TEXT NOT NULL,
                entry_fee REAL NOT NULL,
                prediction TEXT NOT NULL,
                payout REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settled_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS lottery_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                ticket_number TEXT UNIQUE NOT NULL,
                draw_id INTEGER,
                prize_tier INTEGER,
                prize_amount REAL DEFAULT 0,
                status TEXT DEFAULT 'active',
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS lottery_draws (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_ticket TEXT,
                second_ticket TEXT,
                third_ticket TEXT,
                drawn_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            INSERT OR IGNORE INTO settings (key, value) VALUES ('trc20_address', '');
            INSERT OR IGNORE INTO settings (key, value) VALUES ('bep20_address', '');
        """)
        try:
            conn.execute("ALTER TABLE users ADD COLUMN language TEXT DEFAULT 'ar'")
        except Exception:
            pass
