"""Live paper trading loop.

Run in its own terminal:  python runner.py
State lives in SQLite, so the loop resumes cleanly after a restart.
"""

import json

import pandas as pd
import time
import traceback

import config
import engine
import fetcher
import lock
import signals as sig
import store

MODE = "live"


def restore_book(asset, timeframe, sid):
    """Rebuild a wallet from the trade history."""
    start = config.starting_balance(asset["symbol"])
    rows = store.query(
        "SELECT * FROM trades WHERE strategy_id=? AND mode=?", (sid, MODE))
    balance = start
    if not rows.empty:
        balance -= rows["fee"].fillna(0).sum()
        balance += rows.loc[rows["status"] == "closed", "pnl"].fillna(0).sum()

    book = engine.Book(sid, asset["symbol"], timeframe, balance,
                       asset["slippage"], asset["risk_pct"], MODE)

    open_rows = rows[rows["status"] == "open"] if not rows.empty else rows
    if not open_rows.empty:
        r = open_rows.iloc[-1]
        book.position = engine.Position(
            strategy_id=sid, symbol=asset["symbol"], timeframe=timeframe,
            mode=MODE, entry_ts=int(r["entry_ts"]), entry_price=float(r["entry_price"]),
            qty=float(r["qty"]), sl=float(r["sl"]), tp=float(r["tp"]),
            reason_entry=r["reason_entry"], trade_id=int(r["id"]),
            leverage=int(r["leverage"] or 1),
            margin=float(r["margin"] or 0.0),
            liq=float(r["liq_price"]) if pd.notna(r["liq_price"]) else None)
    return book


def process(book, asset, timeframe, sid):
    """Run every newly closed candle through the engine."""
    df = store.load_candles(asset["symbol"], timeframe, limit=config.CALC_WINDOW)
    if len(df) < 60:
        return 0

    df = sig.prepare(df)

    key = f"last_ts:{sid}"
    marker = store.get_state(key)
    if marker is None:
        # First run: replay the warm-up window so the dashboard has content.
        last_done = store.now_ms() - config.LIVE_WARMUP_DAYS * 86_400_000
    else:
        last_done = int(marker)
    processed = 0

    for i in range(len(df)):
        ts = int(df["ts"].iat[i])
        if ts <= last_done or not fetcher.is_closed(ts, timeframe):
            continue
        event = engine.step(book, df, i)
        store.set_state(f"last_ts:{sid}", ts)
        processed += 1
        if event:
            store.log("TRADE", f"{sid} {event} @ {df['close'].iat[i]}")

    last = df.iloc[-1]
    book.snapshot(store.now_ms(), float(last["close"]))
    store.set_state(f"status:{sid}", json.dumps({
        "fiyat": float(last["close"]),
        "mum_ts": int(last["ts"]),
        "rsi": round(float(last["rsi"]), 1),
        "trend": ("yukselis" if bool(last["trend_up"])
                  else "dusus" if bool(last["trend_down"]) else "yatay"),
        "rejim_yukari": bool(last["regime_up"]),
        "ema_long": float(last["ema_long"]),
        "islenen_mum_ts": int(last["ts"]),
        "macd_uzeri": bool(last["macd"] > last["macd_signal"]),
        "hacim_orani": round(float(last["volume"] / last["vol_avg"]), 2)
                       if last["vol_avg"] and last["vol_avg"] > 0 else 0.0,
        "boga_formasyon": sig.pattern_names(last, "bull"),
        "ayi_formasyon": sig.pattern_names(last, "bear"),
        "pozisyon": book.position is not None,
    }))
    return processed


def bootstrap():
    """Fetch history and replay the warm-up window. Returns the wallets."""
    store.init_db()
    if not lock.acquire():
        raise SystemExit(lock.wait_message())
    store.log("INFO", "runner basliyor, gecmis veri cekiliyor")

    total, errors = fetcher.update_all()
    store.log("INFO", f"ilk yukleme: {total} mum, hatali: {errors or 'yok'}")

    books = {sid: restore_book(a, tf, sid) for a, tf, sid in config.all_strategies()}
    for asset, tf, sid in config.all_strategies():
        try:
            process(books[sid], asset, tf, sid)
        except Exception as exc:  # noqa: BLE001
            store.log("ERROR", f"warmup {sid}: {exc}")
        b = books[sid]
        store.log("INFO",
                  f"{sid} bakiye={b.balance:.2f} "
                  f"pozisyon={'var' if b.position else 'yok'}")
    store.set_state("heartbeat", store.now_ms())
    return books


def heartbeat_line(books):
    """One line saying the loop is alive and why nothing is happening.

    Without it the terminal shows nothing between trades, and a quiet hour
    looks identical to a crashed process.
    """
    total = start = 0.0
    open_count = 0
    blocked = []
    for asset, tf, sid in config.all_strategies():
        book = books[sid]
        start += config.starting_balance(asset["symbol"])
        total += book.balance

        raw = store.get_state(f"status:{sid}")
        price = json.loads(raw)["fiyat"] if raw else None
        if raw and not json.loads(raw).get("rejim_yukari", True):
            blocked.append(sid)

        if book.position is not None:
            open_count += 1
            if price:
                total += book.position.unrealized(price)

    pct = (total / start - 1) * 100 if start else 0.0
    note = (f"rejim kapali: {', '.join(blocked)}" if blocked
            else "tum rejimler acik, formasyon bekleniyor")
    print(f"[{time.strftime('%H:%M:%S')}] izliyor | deger {total:.2f} "
          f"({pct:+.2f}%) | acik pozisyon {open_count} | {note}", flush=True)


def loop(books=None):
    """Poll forever. Safe to call after bootstrap()."""
    if books is None:
        if not lock.acquire():
            raise SystemExit(lock.wait_message())
        books = {sid: restore_book(a, tf, sid)
                 for a, tf, sid in config.all_strategies()}

    last_beat = 0.0
    while True:
        cycle_start = time.time()
        try:
            fetcher.update_all()
            for asset, tf, sid in config.all_strategies():
                try:
                    process(books[sid], asset, tf, sid)
                except Exception as exc:  # noqa: BLE001
                    store.log("ERROR", f"process {sid}: {exc}\n{traceback.format_exc()}")
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            store.log("ERROR", f"dongu: {exc}")

        store.set_state("heartbeat", store.now_ms())
        lock.refresh()

        if time.time() - last_beat >= config.STATUS_LINE_SECONDS:
            heartbeat_line(books)
            last_beat = time.time()

        elapsed = time.time() - cycle_start
        time.sleep(max(5, config.POLL_SECONDS - elapsed))


def main():
    loop(bootstrap())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        store.log("INFO", "runner durduruldu")
    finally:
        lock.release()
