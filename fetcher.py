"""OHLCV retrieval via ccxt REST polling."""

import time

import ccxt

import config
import store

_clients = {}


def client(exchange_id):
    if exchange_id not in _clients:
        _clients[exchange_id] = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    return _clients[exchange_id]


def fetch_range(exchange_id, pair, timeframe, since_ms, until_ms=None):
    """Page through fetch_ohlcv from since_ms up to now."""
    ex = client(exchange_id)
    step = config.TIMEFRAME_MS[timeframe]
    until = until_ms or int(time.time() * 1000)
    out, cursor = [], since_ms
    while cursor < until:
        batch = ex.fetch_ohlcv(pair, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        out.extend(batch)
        new_cursor = batch[-1][0] + step
        if new_cursor <= cursor:
            break
        cursor = new_cursor
        if len(batch) < 2:
            break
    return out


def fetch_latest(exchange_id, pair, timeframe, limit=1000):
    """Most recent candles, for assets listed too recently to honour `since`."""
    return client(exchange_id).fetch_ohlcv(pair, timeframe=timeframe, limit=limit)


def update_asset(asset, timeframe, backfill_days=None):
    """Fetch missing history and any new candles. Returns the number stored."""
    symbol, exchange_id, pair = asset["symbol"], asset["exchange"], asset["pair"]
    step = config.TIMEFRAME_MS[timeframe]
    days = backfill_days if backfill_days is not None else config.BACKFILL_DAYS
    want_since = int(time.time() * 1000) - days * 86_400_000

    first, last = store.candle_bounds(exchange_id, symbol, timeframe)
    stored = 0

    # Backfill older history when the stored series does not reach far enough.
    if first is None or first > want_since + step:
        rows = fetch_range(exchange_id, pair, timeframe, want_since,
                           until_ms=first)
        if not rows:
            # The pair has no data that far back; take whatever the venue has.
            rows = fetch_latest(exchange_id, pair, timeframe)
        stored += store.save_candles(exchange_id, symbol, timeframe, rows)

    # Forward update from the newest stored candle.
    _, last = store.candle_bounds(exchange_id, symbol, timeframe)
    if last is not None:
        rows = fetch_range(exchange_id, pair, timeframe, last + 1)
        stored += store.save_candles(exchange_id, symbol, timeframe, rows)

    return stored


def update_all(backfill_days=None):
    """Refresh every asset/timeframe pair, isolating per-asset failures."""
    total, errors = 0, []
    for asset, tf, sid in config.all_strategies():
        try:
            total += update_asset(asset, tf, backfill_days)
        except Exception as exc:  # noqa: BLE001 - one asset must not stop the loop
            errors.append(sid)
            store.log("ERROR", f"fetch {sid}: {type(exc).__name__}: {exc}")
    return total, errors


def is_closed(ts, timeframe):
    """True when the candle starting at ts has finished."""
    return ts + config.TIMEFRAME_MS[timeframe] <= int(time.time() * 1000)
