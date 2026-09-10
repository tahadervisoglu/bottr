"""Configuration for the paper trading bot.

Total simulated capital is 10,000 USD split across four assets by risk grade,
then split evenly between the 5m and 15m timeframes for each asset.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data.db"

TOTAL_CAPITAL = 10_000.0

TIMEFRAMES = ["5m", "15m"]

TIMEFRAME_MS = {"5m": 5 * 60 * 1000, "15m": 15 * 60 * 1000}

# Maximum number of candles to hold a position before closing at market.
MAX_HOLD_BARS = {"5m": 48, "15m": 32}

# Assets. `alloc` is the fraction of TOTAL_CAPITAL, `risk_pct` is the fraction
# of that asset's own balance risked on a single trade, `slippage` is the
# adverse price move applied on both entry and exit.
ASSETS = [
    {
        "symbol": "XRP",
        "name": "XRP",
        "exchange": "binance",
        "pair": "XRP/USDT",
        "risk_grade": "dusuk",
        "alloc": 0.50,
        "risk_pct": 0.020,
        "slippage": 0.0005,
    },
    {
        "symbol": "DEBIT",
        "name": "Teller",
        "exchange": "kucoin",
        "pair": "DEBIT/USDT",
        "risk_grade": "orta",
        "alloc": 0.25,
        "risk_pct": 0.015,
        "slippage": 0.0020,
    },
    {
        "symbol": "ROBIN",
        "name": "Robin the Frog",
        "exchange": "mexc",
        "pair": "ROBIN/USDT",
        "risk_grade": "yuksek",
        "alloc": 0.15,
        "risk_pct": 0.010,
        "slippage": 0.0020,
    },
    {
        "symbol": "TRA",
        "name": "Trabzonspor Fan Token",
        "exchange": "okx",
        "pair": "TRA/USDT",
        "risk_grade": "cok_yuksek",
        "alloc": 0.10,
        "risk_pct": 0.010,
        "slippage": 0.0020,
    },
]

ASSET_BY_SYMBOL = {a["symbol"]: a for a in ASSETS}

# Trading costs and sizing limits.
FEE_RATE = 0.001            # 0.1% per side
MIN_TRADE_USD = 5.0

# Spot trading has no leverage, so a position cannot exceed the balance. With a
# stop under about 1% away, this cap binds before `risk_pct` does and the real
# risk per trade falls well below it. Effective risk is therefore
#   min(risk_pct, MAX_POSITION_FRACTION * stop_distance_pct)
# and the dashboard reports the realised figure per trade.
MAX_POSITION_FRACTION = 0.5

# Strategy parameters.
EMA_FAST, EMA_MID, EMA_SLOW = 9, 21, 50
RSI_PERIOD = 14
RSI_ENTRY_MAX = 45
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
BB_PERIOD, BB_STD = 20, 2.0
ATR_PERIOD = 14
ATR_SL_MULT = 1.5
MIN_STOP_PCT = 0.006   # a stop is never closer than 0.6% to the entry
RISK_REWARD = 2.0
VOLUME_MIN_RATIO = 0.5       # candle volume vs. 20-bar average
MACD_CROSS_LOOKBACK = 3
TREND_LOOKBACK = 10

# Discretionary exits, in addition to stop-loss, target and the time limit.
USE_BEAR_PATTERN_EXIT = True
USE_MACD_EXIT = False        # closes winners early on 5m/15m crypto

# Runtime.
POLL_SECONDS = 15
BACKFILL_DAYS = 30
CALC_WINDOW = 300            # candles fed to the indicator pipeline

# On its very first run the live wallet replays this many days of recent
# candles, so the dashboard opens with real trades instead of an empty table.
LIVE_WARMUP_DAYS = 3


def strategy_id(symbol: str, timeframe: str) -> str:
    return f"{symbol}_{timeframe}"


def starting_balance(symbol: str) -> float:
    """Balance for one strategy: the asset's allocation split across timeframes."""
    return TOTAL_CAPITAL * ASSET_BY_SYMBOL[symbol]["alloc"] / len(TIMEFRAMES)


def all_strategies():
    """Yield (asset dict, timeframe, strategy_id) for every strategy instance."""
    for asset in ASSETS:
        for tf in TIMEFRAMES:
            yield asset, tf, strategy_id(asset["symbol"], tf)
