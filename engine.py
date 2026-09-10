"""Paper trading engine: position sizing, entry and exit rules, book-keeping.

The same functions drive both the live runner and the backtest, so the two
always share identical logic.
"""

from dataclasses import dataclass, asdict

import config
import signals as sig
import store


@dataclass
class Position:
    strategy_id: str
    symbol: str
    timeframe: str
    mode: str
    entry_ts: int
    entry_price: float
    qty: float
    sl: float
    tp: float
    reason_entry: str
    bars_held: int = 0
    trade_id: int = None

    def value(self, price):
        return self.qty * price

    def unrealized(self, price):
        return (price - self.entry_price) * self.qty


class Book:
    """One virtual wallet per strategy."""

    def __init__(self, strategy_id, symbol, timeframe, balance, slippage,
                 risk_pct, mode="live"):
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.balance = balance
        self.slippage = slippage
        self.risk_pct = risk_pct
        self.mode = mode
        self.position = None

    # --- sizing ---

    def size(self, entry, sl, candle_volume=None):
        """Quantity implied by the risk budget, capped by balance and liquidity."""
        risk_per_unit = entry - sl
        if risk_per_unit <= 0:
            return 0.0
        qty = (self.balance * self.risk_pct) / risk_per_unit
        qty = min(qty, (self.balance * config.MAX_POSITION_FRACTION) / entry)
        if candle_volume and candle_volume > 0:
            qty = min(qty, candle_volume * config.MAX_VOLUME_SHARE)
        return qty

    # --- trade lifecycle ---

    def open(self, ts, raw_price, sl, tp, reason, candle_volume=None):
        entry = raw_price * (1 + self.slippage)
        sl_adj = min(sl, entry * 0.999)
        qty = self.size(entry, sl_adj, candle_volume)
        if qty <= 0 or qty * entry < config.MIN_TRADE_USD:
            return None
        fee = qty * entry * config.FEE_RATE
        self.balance -= fee
        risk_usd = (entry - sl_adj) * qty
        self.position = Position(
            strategy_id=self.strategy_id, symbol=self.symbol,
            timeframe=self.timeframe, mode=self.mode, entry_ts=ts,
            entry_price=entry, qty=qty, sl=sl_adj, tp=tp, reason_entry=reason)
        self.position.trade_id = store.insert(
            "trades", strategy_id=self.strategy_id, symbol=self.symbol,
            timeframe=self.timeframe, mode=self.mode, entry_ts=ts,
            entry_price=entry, qty=qty, sl=sl_adj, tp=tp, fee=fee,
            risk_usd=risk_usd, risk_pct_real=risk_usd / self.balance * 100,
            reason_entry=reason, status="open")
        return self.position

    def close(self, ts, raw_price, reason):
        pos = self.position
        if pos is None:
            return None
        exit_price = raw_price * (1 - self.slippage)
        gross = (exit_price - pos.entry_price) * pos.qty
        fee = pos.qty * exit_price * config.FEE_RATE
        pnl = gross - fee
        self.balance += pnl
        pnl_pct = (exit_price / pos.entry_price - 1) * 100
        store.update("trades", pos.trade_id, exit_ts=ts, exit_price=exit_price,
                     pnl=pnl, pnl_pct=pnl_pct, reason_exit=reason, status="closed")
        self.position = None
        return pnl

    def snapshot(self, ts, price):
        unreal = self.position.unrealized(price) if self.position else 0.0
        store.insert("equity", ts=ts, strategy_id=self.strategy_id, mode=self.mode,
                     balance=self.balance, unrealized=unreal,
                     total=self.balance + unreal)


# --- rules ------------------------------------------------------------------

def entry_signal(df, i):
    """Return (ok, reason, note). `note` explains a rejection."""
    row = df.iloc[i]
    if not bool(row["bull_signal"]):
        return False, None, None

    names = sig.pattern_names(row, "bull")

    if config.USE_TREND_FILTER and not bool(row["regime_up"]):
        return False, names, f"uzun trend asagi (EMA {config.TREND_EMA} alti)"

    vol_avg = row["vol_avg"]
    if vol_avg and vol_avg > 0:
        if row["volume"] < config.VOLUME_MIN_RATIO * vol_avg:
            return False, names, "hacim filtresi"
    elif row["volume"] <= 0:
        return False, names, "hacim sifir"

    rsi_ok = row["rsi"] < config.RSI_ENTRY_MAX
    macd_ok = sig.macd_crossed_up(df, i)
    if not (rsi_ok or macd_ok):
        return False, names, "teyit yok (RSI/MACD)"

    confirm = "RSI" if rsi_ok else "MACD"
    return True, f"{names}|{confirm}", None


def stop_and_target(df, i, entry):
    """Stop is the wider of the formation low and an ATR-based stop.

    Position sizing already caps the dollar risk at `risk_pct` of the balance,
    so a wider stop shrinks the quantity instead of raising the risk. Giving
    the trade room beyond one ATR keeps ordinary noise from closing it.
    """
    row = df.iloc[i]
    atr = float(row["atr"] or 0)
    atr_stop = entry - config.ATR_SL_MULT * atr
    pattern_stop = float(row["pattern_low"])
    sl = min(atr_stop, pattern_stop)

    floor = entry * (1 - config.MIN_STOP_PCT)
    sl = min(sl, floor)
    if sl >= entry:
        sl = floor
    tp = entry + config.RISK_REWARD * (entry - sl)
    return sl, tp


def exit_signal(df, i, pos, max_bars):
    """Check exits against one candle. Stop wins ties with the target."""
    row = df.iloc[i]
    if row["low"] <= pos.sl:
        return pos.sl, "stop-loss"
    if row["high"] >= pos.tp:
        return pos.tp, "take-profit"
    if config.USE_BEAR_PATTERN_EXIT and bool(row["bear_signal"]):
        return float(row["close"]), f"ayi formasyonu:{sig.pattern_names(row, 'bear')}"
    if config.USE_MACD_EXIT and sig.macd_crossed_down(df, i):
        return float(row["close"]), "MACD asagi kesisim"
    if pos.bars_held >= max_bars:
        return float(row["close"]), "sure limiti"
    return None, None


def step(book, df, i, record_signals=True):
    """Advance one candle for one strategy. Returns a short event label."""
    row = df.iloc[i]
    ts, close = int(row["ts"]), float(row["close"])
    max_bars = config.MAX_HOLD_BARS[book.timeframe]
    event = None

    if book.position is not None:
        book.position.bars_held += 1
        price, reason = exit_signal(df, i, book.position, max_bars)
        if price is not None:
            book.close(ts, price, reason)
            event = f"cikis:{reason}"
    else:
        ok, reason, note = entry_signal(df, i)
        if reason and record_signals:
            store.insert("signals", ts=ts, strategy_id=book.strategy_id,
                         symbol=book.symbol, timeframe=book.timeframe,
                         rule=reason, direction="bull", price=close,
                         acted=int(ok), note=note or "")
        if ok:
            sl, tp = stop_and_target(df, i, close)
            if book.open(ts, close, sl, tp, reason, float(row["volume"])):
                event = f"giris:{reason}"

    return event
