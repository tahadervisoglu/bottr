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


def walk_back(exchange_id, symbol, pair, timeframe, earliest, want_since,
              max_rounds=60):
    """Page backwards from `earliest` toward `want_since`.

    Some venues refuse a `since` that predates the listing and answer with an
    empty list, which makes a single forward query look like "no history".
    Stepping back one page at a time finds the true start instead.
    """
    ex = client(exchange_id)
    step = config.TIMEFRAME_MS[timeframe]
    stored, cursor = 0, earliest

    for _ in range(max_rounds):
        if cursor <= want_since:
            break
        since = max(want_since, cursor - 1000 * step)
        batch = ex.fetch_ohlcv(pair, timeframe=timeframe, since=since, limit=1000)
        batch = [r for r in batch if r[0] < cursor]
        if not batch:
            break
        stored += store.save_candles(exchange_id, symbol, timeframe, batch)
        new_earliest = min(r[0] for r in batch)
        if new_earliest >= cursor:
            break
        cursor = new_earliest

    return stored


def update_asset(asset, timeframe, backfill_days=None):
    """Fetch missing history and any new candles. Returns the number stored."""
    symbol, exchange_id, pair = asset["symbol"], asset["exchange"], asset["pair"]
    step = config.TIMEFRAME_MS[timeframe]
    days = backfill_days if backfill_days is not None else config.BACKFILL_DAYS
    want_since = int(time.time() * 1000) - days * 86_400_000

    first, last = store.candle_bounds(exchange_id, symbol, timeframe)
    stored = 0

    if first is None:
        rows = fetch_range(exchange_id, pair, timeframe, want_since)
        if not rows:
            # The venue will not serve a `since` this old; take its latest page
            # and let walk_back find how far the history really goes.
            rows = fetch_latest(exchange_id, pair, timeframe)
        stored += store.save_candles(exchange_id, symbol, timeframe, rows)
        first, last = store.candle_bounds(exchange_id, symbol, timeframe)

    if first is not None and first > want_since + step:
        stored += walk_back(exchange_id, symbol, pair, timeframe, first, want_since)

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
