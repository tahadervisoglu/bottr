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


def start():
    """Start the loop once. Returns a label describing what happened."""
    if not should_run():
        return "kapali"

    import runner  # imported lazily so local dashboards stay light

    thread = threading.Thread(target=runner.main, name="bot-loop", daemon=True)
    thread.start()
    return "calisiyor"
