"""SQLite persistence layer.

The runner writes, the Streamlit dashboard reads. WAL mode keeps the two
processes from blocking each other.
"""

import sqlite3
import time
from contextlib import contextmanager

import pandas as pd

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    exchange TEXT, symbol TEXT, timeframe TEXT, ts INTEGER,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (exchange, symbol, timeframe, ts)
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT, symbol TEXT, timeframe TEXT, mode TEXT,
    entry_ts INTEGER, entry_price REAL,
    exit_ts INTEGER, exit_price REAL,
    qty REAL, sl REAL, tp REAL,
    pnl REAL, pnl_pct REAL, fee REAL,
    risk_usd REAL, risk_pct_real REAL,
    reason_entry TEXT, reason_exit TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    ts INTEGER, strategy_id TEXT, symbol TEXT, timeframe TEXT,
    rule TEXT, direction TEXT, price REAL, acted INTEGER, note TEXT
);

CREATE TABLE IF NOT EXISTS equity (
    ts INTEGER, strategy_id TEXT, mode TEXT,
    balance REAL, unrealized REAL, total REAL
);

CREATE TABLE IF NOT EXISTS logs (
    ts INTEGER, level TEXT, message TEXT
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY, value TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_strat ON trades (strategy_id, mode);
CREATE INDEX IF NOT EXISTS idx_equity_strat ON equity (strategy_id, mode, ts);
CREATE INDEX IF NOT EXISTS idx_signals_strat ON signals (strategy_id, ts);
"""


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with cursor() as conn:
        conn.executescript(SCHEMA)
        # Add columns introduced after a database was first created.
        have = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
        for col in ("risk_usd", "risk_pct_real"):
            if col not in have:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col} REAL")


def now_ms() -> int:
    return int(time.time() * 1000)


# --- candles ---------------------------------------------------------------

def save_candles(exchange, symbol, timeframe, rows):
    """rows: iterable of [ts, open, high, low, close, volume]."""
    if not rows:
        return 0
    payload = [(exchange, symbol, timeframe, int(r[0]), *[float(x) for x in r[1:6]])
               for r in rows]
    with cursor() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?)", payload)
    return len(payload)


def candle_bounds(exchange, symbol, timeframe):
    """Return (earliest ts, latest ts) held for this series, or (None, None)."""
    with cursor() as conn:
        row = conn.execute(
            "SELECT MIN(ts) AS lo, MAX(ts) AS hi FROM candles "
            "WHERE exchange=? AND symbol=? AND timeframe=?",
            (exchange, symbol, timeframe)).fetchone()
    return row["lo"], row["hi"]


def last_candle_ts(exchange, symbol, timeframe):
    return candle_bounds(exchange, symbol, timeframe)[1]


def load_candles(symbol, timeframe, limit=None) -> pd.DataFrame:
    sql = ("SELECT ts, open, high, low, close, volume FROM candles "
           "WHERE symbol=? AND timeframe=? ORDER BY ts")
    params = [symbol, timeframe]
    with cursor() as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    if limit and len(df) > limit:
        df = df.iloc[-limit:].reset_index(drop=True)
    return df


# --- generic helpers -------------------------------------------------------

def insert(table, **fields):
    cols = ",".join(fields)
    marks = ",".join("?" * len(fields))
    with cursor() as conn:
        cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})",
                           tuple(fields.values()))
        return cur.lastrowid


def update(table, row_id, **fields):
    sets = ",".join(f"{k}=?" for k in fields)
    with cursor() as conn:
        conn.execute(f"UPDATE {table} SET {sets} WHERE id=?",
                     (*fields.values(), row_id))


def query(sql, params=()) -> pd.DataFrame:
    with cursor() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def log(level, message):
    insert("logs", ts=now_ms(), level=level, message=str(message)[:2000])
    print(f"[{level}] {message}", flush=True)


def clear_mode(mode):
    """Wipe trades and equity for one mode ('live' or 'backtest')."""
    with cursor() as conn:
        conn.execute("DELETE FROM trades WHERE mode=?", (mode,))
        conn.execute("DELETE FROM equity WHERE mode=?", (mode,))


def open_trades(mode="live") -> pd.DataFrame:
    return query("SELECT * FROM trades WHERE status='open' AND mode=?", (mode,))


def get_state(key, default=None):
    with cursor() as conn:
        row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(key, value):
    with cursor() as conn:
        conn.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, str(value)))
