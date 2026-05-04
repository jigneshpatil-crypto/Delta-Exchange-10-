"""
BTC Global Elite Scalper V6 — Database Layer
Supabase PostgreSQL for trade persistence and bot state.
"""
import json, logging
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import RealDictCursor
import config

logger = logging.getLogger("Database")

class Database:
    def __init__(self):
        self.conn = None
        self._connect()
        self._create_tables()

    def _connect(self):
        if not config.DATABASE_URL:
            logger.error("DATABASE_URL not set!")
            return
        try:
            self.conn = psycopg2.connect(config.DATABASE_URL, sslmode="require", connect_timeout=10)
            self.conn.autocommit = True
            logger.info("Connected to Supabase PostgreSQL")
        except Exception as e:
            logger.error(f"DB connection failed: {e}")
            self.conn = None

    def _ensure_connection(self):
        if self.conn is None or self.conn.closed:
            self._connect()
        return self.conn is not None

    def _create_tables(self):
        if not self._ensure_connection():
            return
        try:
            cur = self.conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY, entry_time TIMESTAMPTZ, exit_time TIMESTAMPTZ,
                    side VARCHAR(10), entry_price FLOAT8, exit_price FLOAT8,
                    size INTEGER, pnl FLOAT8 DEFAULT 0, pnl_pct FLOAT8 DEFAULT 0,
                    status VARCHAR(20) DEFAULT 'open', close_reason VARCHAR(100),
                    order_id VARCHAR(50), partial_tp_done BOOLEAN DEFAULT FALSE,
                    breakeven_done BOOLEAN DEFAULT FALSE, peak_price FLOAT8,
                    data_json TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS bot_state (
                    id INTEGER PRIMARY KEY DEFAULT 1, is_locked BOOLEAN DEFAULT FALSE,
                    lock_until TIMESTAMPTZ, daily_start_balance FLOAT8,
                    last_reset_date VARCHAR(20), last_trade_was_loss BOOLEAN DEFAULT FALSE,
                    last_candle_time TIMESTAMPTZ, data_json TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                INSERT INTO bot_state (id, is_locked, daily_start_balance)
                VALUES (1, FALSE, 0) ON CONFLICT (id) DO NOTHING;
                CREATE TABLE IF NOT EXISTS trade_log (
                    id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT NOW(),
                    event_type VARCHAR(50), message TEXT, data_json TEXT
                );
            """)
            cur.close()
            logger.info("Database tables verified")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")

    def save_trade(self, td):
        if not self._ensure_connection(): return None
        try:
            cur = self.conn.cursor()
            cur.execute("""INSERT INTO trades (entry_time,side,entry_price,size,status,order_id,data_json)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id;""",
                (td.get("entry_time"),td.get("side"),td.get("entry_price"),
                 td.get("size"),td.get("status","open"),td.get("order_id"),json.dumps(td)))
            tid = cur.fetchone()[0]; cur.close(); return tid
        except Exception as e:
            logger.error(f"Failed to save trade: {e}"); return None

    def get_open_trade(self):
        if not self._ensure_connection(): return None
        try:
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM trades WHERE status='open' ORDER BY id DESC LIMIT 1;")
            t = cur.fetchone(); cur.close()
            return dict(t) if t else None
        except Exception as e:
            logger.error(f"Failed to get open trade: {e}"); return None

    def update_trade(self, data):
        if not self._ensure_connection(): return
        try:
            cur = self.conn.cursor()
            sets = [f"{k}=%s" for k in data.keys()]
            cur.execute(f"UPDATE trades SET {','.join(sets)} WHERE status='open' AND id=(SELECT id FROM trades WHERE status='open' ORDER BY id DESC LIMIT 1);", list(data.values()))
            cur.close()
        except Exception as e:
            logger.error(f"Failed to update trade: {e}")

    def get_today_trades(self):
        if not self._ensure_connection(): return []
        try:
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM trades WHERE DATE(entry_time)=%s ORDER BY id DESC;",
                (datetime.now(timezone.utc).strftime("%Y-%m-%d"),))
            t = cur.fetchall(); cur.close(); return [dict(r) for r in t]
        except Exception as e:
            logger.error(f"Failed: {e}"); return []

    def get_recent_trades(self, limit=20):
        if not self._ensure_connection(): return []
        try:
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM trades ORDER BY id DESC LIMIT %s;", (limit,))
            t = cur.fetchall(); cur.close(); return [dict(r) for r in t]
        except Exception as e:
            logger.error(f"Failed: {e}"); return []

    def get_bot_state(self):
        if not self._ensure_connection(): return None
        try:
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM bot_state WHERE id=1;")
            s = cur.fetchone(); cur.close()
            return dict(s) if s else None
        except Exception as e:
            logger.error(f"Failed: {e}"); return None

    def update_bot_state(self, data):
        if not self._ensure_connection(): return
        try:
            cur = self.conn.cursor()
            sets = [f"{k}=%s" for k in data.keys()]
            sets.append("updated_at=NOW()")
            cur.execute(f"UPDATE bot_state SET {','.join(sets)} WHERE id=1;", list(data.values()))
            cur.close()
        except Exception as e:
            logger.error(f"Failed: {e}")

    def set_last_candle_time(self, t):
        self.update_bot_state({"last_candle_time": t})

    def get_last_candle_time(self):
        s = self.get_bot_state()
        return s.get("last_candle_time") if s else None

    def log_event(self, event_type, message, data=None):
        if not self._ensure_connection(): return
        try:
            cur = self.conn.cursor()
            cur.execute("INSERT INTO trade_log (event_type,message,data_json) VALUES (%s,%s,%s);",
                (event_type, message, json.dumps(data) if data else None))
            cur.close()
        except Exception as e:
            logger.error(f"Failed to log: {e}")

    def get_recent_logs(self, limit=50):
        if not self._ensure_connection(): return []
        try:
            cur = self.conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT * FROM trade_log ORDER BY id DESC LIMIT %s;", (limit,))
            l = cur.fetchall(); cur.close(); return [dict(r) for r in l]
        except Exception as e:
            logger.error(f"Failed: {e}"); return []

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()
