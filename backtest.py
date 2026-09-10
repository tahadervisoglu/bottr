"""Replay the same strategy over stored history.

    python backtest.py --days 30

Uses engine.step, so results reflect exactly the rules the live runner applies.
"""

import argparse

import config
import engine
import fetcher
import signals as sig
import store

MODE = "backtest"


def run_one(asset, timeframe, sid, days):
    df = store.load_candles(asset["symbol"], timeframe)
    if len(df) < 80:
        return None

    cutoff = store.now_ms() - days * 86_400_000
    df = sig.prepare(df)
    warmup = 60

    book = engine.Book(sid, asset["symbol"], timeframe,
                       config.starting_balance(asset["symbol"]),
                       asset["slippage"], asset["risk_pct"], MODE)

    for i in range(warmup, len(df)):
        if int(df["ts"].iat[i]) < cutoff:
            continue
        engine.step(book, df, i, record_signals=False)

    if book.position is not None:
        book.close(int(df["ts"].iloc[-1]), float(df["close"].iloc[-1]), "test sonu")

    book.snapshot(int(df["ts"].iloc[-1]), float(df["close"].iloc[-1]))
    return book


def summarize(sid, book):
    t = store.query(
        "SELECT * FROM trades WHERE strategy_id=? AND mode=? AND status='closed'",
        (sid, MODE))
    start = config.starting_balance(sid.rsplit("_", 1)[0])
    out = {"islem": len(t), "kazanma_pct": 0.0,
           "getiri_pct": round((book.balance - start) / start * 100, 2)}
    if not t.empty:
        out["kazanma_pct"] = round((t["pnl"] > 0).sum() / len(t) * 100, 1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=config.BACKFILL_DAYS)
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args()

    store.init_db()
    if not args.skip_fetch:
        store.log("INFO", "backtest icin veri cekiliyor")
        fetcher.update_all(backfill_days=args.days)

    store.clear_mode(MODE)
    for asset, tf, sid in config.all_strategies():
        book = run_one(asset, tf, sid, args.days)
        if book is None:
            print(f"{sid:14s} yetersiz veri")
            continue
        s = summarize(sid, book)
        start = config.starting_balance(asset["symbol"])
        print(f"{sid:14s} baslangic={start:8.2f}  bakiye={book.balance:9.2f}  "
              f"islem={s['islem']:3d}  getiri={s['getiri_pct']:+7.2f}%  "
              f"kazanma={s['kazanma_pct']:5.1f}%")


if __name__ == "__main__":
    main()
