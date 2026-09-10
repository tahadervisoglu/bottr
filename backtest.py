"""Replay the same strategy over stored history.

    python backtest.py                 30 gunluk test
    python backtest.py --long          180 gunluk test, ayri kaydedilir
    python backtest.py --days 90       istedigin pencere

Uses engine.step, so results reflect exactly the rules the live runner applies.
The short and long runs are stored under different modes, so the dashboard can
show them side by side instead of one overwriting the other.
"""

import argparse

import config
import engine
import fetcher
import signals as sig
import store

WARMUP_BARS = 220   # enough history for the 200-period regime EMA


def run_one(asset, timeframe, sid, days, mode):
    df = store.load_candles(asset["symbol"], timeframe)
    if len(df) < WARMUP_BARS + 40:
        return None

    cutoff = store.now_ms() - days * 86_400_000
    df = sig.prepare(df)

    book = engine.Book(sid, asset["symbol"], timeframe,
                       config.starting_balance(asset["symbol"]),
                       asset["slippage"], asset["risk_pct"], mode)

    for i in range(WARMUP_BARS, len(df)):
        if int(df["ts"].iat[i]) < cutoff:
            continue
        engine.step(book, df, i, record_signals=False)

    if book.position is not None:
        book.close(int(df["ts"].iloc[-1]), float(df["close"].iloc[-1]), "test sonu")

    book.snapshot(int(df["ts"].iloc[-1]), float(df["close"].iloc[-1]))
    return book


def buy_and_hold(asset, timeframe, days):
    """Benchmark: what the same money would have done untouched."""
    df = store.load_candles(asset["symbol"], timeframe)
    cutoff = store.now_ms() - days * 86_400_000
    df = df[df["ts"] >= cutoff]
    if len(df) < 2:
        return None, 0.0
    pct = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
    span = (df["ts"].iloc[-1] - df["ts"].iloc[0]) / 86_400_000
    return pct, span


def summarize(sid, book, mode):
    t = store.query(
        "SELECT * FROM trades WHERE strategy_id=? AND mode=? AND status='closed'",
        (sid, mode))
    start = config.starting_balance(sid.rsplit("_", 1)[0])
    out = {"islem": len(t), "kazanma_pct": 0.0, "ort_risk": 0.0,
           "getiri_pct": round((book.balance - start) / start * 100, 2)}
    if not t.empty:
        out["kazanma_pct"] = round((t["pnl"] > 0).sum() / len(t) * 100, 1)
        out["ort_risk"] = round(t["risk_pct_real"].dropna().mean() or 0, 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--long", action="store_true",
                    help=f"{config.LONG_TEST_DAYS} gunluk test, mode=backtest_long")
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args()

    if args.long:
        days, mode, label = config.LONG_TEST_DAYS, "backtest_long", "UZUN"
    else:
        days = args.days or config.BACKFILL_DAYS
        mode, label = "backtest", "KISA"

    store.init_db()
    if not args.skip_fetch:
        print(f"{days} gunluk veri cekiliyor...")
        fetcher.update_all(backfill_days=days)

    store.clear_mode(mode)
    store.set_state(f"{mode}:days", days)
    store.set_state(f"{mode}:ran_at", store.now_ms())

    print(f"\n=== {label} TEST · {days} gun · "
          f"trend filtresi {'acik' if config.USE_TREND_FILTER else 'kapali'} ===")
    print(f"{'strateji':14s} {'baslangic':>10s} {'bitis':>10s} {'getiri':>8s} "
          f"{'al-tut':>8s} {'islem':>6s} {'kazanma':>8s} {'gun':>6s}")

    tot_start = tot_end = 0.0
    for asset, tf, sid in config.all_strategies():
        book = run_one(asset, tf, sid, days, mode)
        start = config.starting_balance(asset["symbol"])
        bh, span = buy_and_hold(asset, tf, days)
        if book is None:
            print(f"{sid:14s} yetersiz veri")
            continue
        s = summarize(sid, book, mode)
        tot_start += start
        tot_end += book.balance
        print(f"{sid:14s} {start:10.2f} {book.balance:10.2f} "
              f"{s['getiri_pct']:+7.2f}% {bh:+7.2f}% {s['islem']:6d} "
              f"{s['kazanma_pct']:7.1f}% {span:6.1f}")

    if tot_start:
        print(f"\n{'TOPLAM':14s} {tot_start:10.2f} {tot_end:10.2f} "
              f"{(tot_end / tot_start - 1) * 100:+7.2f}%")

    t = store.query(
        "SELECT * FROM trades WHERE mode=? AND status='closed'", (mode,))
    if not t.empty:
        risk = t["risk_pct_real"].dropna()
        print(f"\nislem basina gercek risk: ortalama %{risk.mean():.2f} "
              f"(hedef %1.0-2.0)")
        print(f"odenen komisyon: {t['fee'].sum() * 2:.2f} $, "
              f"komisyon oncesi brut: {(t['pnl'] + t['fee']).sum():+.2f} $")


if __name__ == "__main__":
    main()
