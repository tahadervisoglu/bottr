"""Run the trading loop inside the Streamlit process.

Streamlit Community Cloud starts only `app.py`, so `runner.py` cannot run as a
separate process there. On a hosted deployment the dashboard therefore starts
the same loop in a daemon thread.

Locally the loop stays off by default, because `python runner.py` is expected to
be running in its own terminal and two loops writing the same wallet would
double every trade. Set RUN_BOT_IN_APP=1 to force it on, or 0 to force it off.
"""

import os
import threading


def _looks_like_cloud() -> bool:
    if os.path.isdir("/mount/src"):          # Streamlit Community Cloud
        return True
    return bool(os.environ.get("DYNO")       # Heroku
                or os.environ.get("RENDER")  # Render
                or os.environ.get("K_SERVICE"))  # Cloud Run


def should_run() -> bool:
    flag = os.environ.get("RUN_BOT_IN_APP")
    if flag is not None:
        return flag.strip() not in ("", "0", "false", "False")
    return _looks_like_cloud()


def _seed_backtest():
    """Produce a short backtest once, so a fresh deployment is not empty.

    Only app.py runs on a hosted deployment, so `python backtest.py` never
    executes there and the backtest pages would stay blank forever.
    """
    import backtest
    import config
    import store

    if store.get_state("backtest:ran_at"):
        return
    try:
        store.clear_mode("backtest")
        store.set_state("backtest:days", 30)
        for asset, tf, sid in config.all_strategies():
            backtest.run_one(asset, tf, sid, 30, "backtest")
        store.set_state("backtest:ran_at", store.now_ms())
        store.log("INFO", "ilk backtest hazir")
    except Exception as exc:  # noqa: BLE001 - a failed seed must not stop the bot
        store.log("ERROR", f"backtest seed: {exc}")


def _boot():
    import runner

    runner.bootstrap()      # fetch history, replay the warm-up window
    _seed_backtest()        # then fill the backtest page from the same data
    runner.loop()


def start():
    """Start the loop once. Returns a label describing what happened."""
    if not should_run():
        return "kapali"

    thread = threading.Thread(target=_boot, name="bot-loop", daemon=True)
    thread.start()
    return "calisiyor"
