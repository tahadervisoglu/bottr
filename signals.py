"""Indicators and candlestick patterns.

Indicators follow the training material: EMA 9/21/50, RSI 14 with 30/70
thresholds, MACD 12/26/9, Bollinger 20/2. ATR 14 is added for stop sizing.
Patterns are the seven two-candle formations from the candlestick document.
"""

import numpy as np
import pandas as pd

import config

BULL_PATTERNS = ["bullish_harami", "bullish_harami_cross",
                 "bullish_doji_star", "hammer"]
BEAR_PATTERNS = ["bearish_harami", "bearish_engulfing", "dark_cloud_cover"]


# --- indicators ------------------------------------------------------------

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    close, high, low = df["close"], df["high"], df["low"]

    df["ema_fast"] = close.ewm(span=config.EMA_FAST, adjust=False).mean()
    df["ema_mid"] = close.ewm(span=config.EMA_MID, adjust=False).mean()
    df["ema_slow"] = close.ewm(span=config.EMA_SLOW, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / config.RSI_PERIOD, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / config.RSI_PERIOD, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = (100 - 100 / (1 + rs)).fillna(50)

    ema_f = close.ewm(span=config.MACD_FAST, adjust=False).mean()
    ema_s = close.ewm(span=config.MACD_SLOW, adjust=False).mean()
    df["macd"] = ema_f - ema_s
    df["macd_signal"] = df["macd"].ewm(span=config.MACD_SIGNAL, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    mid = close.rolling(config.BB_PERIOD).mean()
    std = close.rolling(config.BB_PERIOD).std()
    df["bb_mid"] = mid
    df["bb_upper"] = mid + config.BB_STD * std
    df["bb_lower"] = mid - config.BB_STD * std

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / config.ATR_PERIOD, adjust=False).mean()

    df["vol_avg"] = df["volume"].rolling(20).mean()

    # Short-term context: majority of the last N closes relative to EMA 21.
    above = (close > df["ema_mid"]).rolling(config.TREND_LOOKBACK).mean()
    df["trend_up"] = above >= 0.6
    df["trend_down"] = above <= 0.4

    # Long-term regime. Until the long EMA has enough history it is NaN, and
    # `regime_up` stays False, so no trade is taken on an unformed trend.
    df["ema_long"] = close.ewm(span=config.TREND_EMA, adjust=False).mean()
    enough = df.index >= config.TREND_EMA
    df["regime_up"] = (close > df["ema_long"]) & enough
    return df


# --- candlestick patterns --------------------------------------------------

def add_patterns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]

    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    avg_body = body.rolling(20).mean()
    green, red = c > o, c < o
    doji = body <= 0.10 * rng

    top = df[["open", "close"]].max(axis=1)
    bottom = df[["open", "close"]].min(axis=1)
    upper_wick = h - top
    lower_wick = bottom - l

    p_o, p_c, p_h, p_l = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    p_body = body.shift(1)
    p_green, p_red = green.shift(1, fill_value=False), red.shift(1, fill_value=False)
    p_top, p_bottom = top.shift(1), bottom.shift(1)
    p_big = p_body >= 1.2 * avg_body.shift(1)
    p_small = p_body <= avg_body.shift(1)

    inside = (top <= p_top) & (bottom >= p_bottom)
    down, up = df["trend_down"], df["trend_up"]

    df["bullish_harami"] = down & p_red & p_big & green & inside & ~doji
    df["bullish_harami_cross"] = down & p_red & p_big & doji & inside
    df["bullish_doji_star"] = down & p_red & doji & (o < p_c)
    df["hammer"] = (down & (lower_wick >= 2 * body) & (upper_wick < body)
                    & (bottom >= l + 0.7 * (h - l).replace(0, np.nan)))

    df["bearish_harami"] = up & p_green & p_big & red & inside
    df["bearish_engulfing"] = (up & p_green & p_small & red
                               & (top >= p_top) & (bottom <= p_bottom))
    df["dark_cloud_cover"] = (up & p_green & red & (o > p_h)
                              & (c < (p_o + p_c) / 2) & (c > p_o))

    for col in BULL_PATTERNS + BEAR_PATTERNS:
        df[col] = df[col].fillna(False).astype(bool)

    df["bull_signal"] = df[BULL_PATTERNS].any(axis=1)
    df["bear_signal"] = df[BEAR_PATTERNS].any(axis=1)

    # Confirmation and stop levels taken from the two-candle formation.
    df["pattern_high"] = pd.concat([h, p_h], axis=1).max(axis=1)
    df["pattern_low"] = pd.concat([l, p_l], axis=1).min(axis=1)
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Full pipeline: indicators, then patterns."""
    if df.empty:
        return df
    return add_patterns(add_indicators(df))


def pattern_names(row, kind="bull"):
    cols = BULL_PATTERNS if kind == "bull" else BEAR_PATTERNS
    return "+".join(c for c in cols if bool(row.get(c)))


def macd_crossed_up(df, i, lookback=None):
    lookback = lookback or config.MACD_CROSS_LOOKBACK
    start = max(1, i - lookback + 1)
    for j in range(start, i + 1):
        if df["macd"].iat[j] > df["macd_signal"].iat[j] and \
           df["macd"].iat[j - 1] <= df["macd_signal"].iat[j - 1]:
            return True
    return False


def macd_crossed_down(df, i):
    if i < 1:
        return False
    return (df["macd"].iat[i] < df["macd_signal"].iat[i]
            and df["macd"].iat[i - 1] >= df["macd_signal"].iat[i - 1])
