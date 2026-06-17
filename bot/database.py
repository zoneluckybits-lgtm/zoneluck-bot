import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "zoneluck.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                full_name TEXT,
                balance REAL DEFAULT 0.0,
                referred_by INTEGER REFERENCES users(id),
                referral_rewarded INTEGER DEFAULT 0,
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
