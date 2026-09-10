"""Single-writer lock for the trading loop.

Two loops against one wallet open the same candle twice: duplicate positions,
double fees, a balance that no longer matches reality. The lock lets exactly one
process own the wallet. It lives in the state table rather than a lock file, so
a machine that loses power leaves a stale entry that simply expires instead of a
file nobody can clear.
"""

import os
import time

import store

KEY = "runner_lock"
STALE_SECONDS = 90


def _parse(raw):
    try:
        pid, ts = raw.split(":", 1)
        return int(pid), int(ts)
    except (ValueError, AttributeError):
        return None, 0


def holder():
    """Return (pid, age_seconds) of a live lock, or (None, 0)."""
    pid, ts = _parse(store.get_state(KEY))
    if not pid:
        return None, 0
    age = (store.now_ms() - ts) / 1000
    if age > STALE_SECONDS:
        return None, age
    return pid, age


def acquire():
    """Take the lock. Returns True on success, False if another loop holds it."""
    pid, age = holder()
    if pid and pid != os.getpid():
        return False
    refresh()
    return True


def refresh():
    store.set_state(KEY, f"{os.getpid()}:{store.now_ms()}")


def release():
    pid, _ = _parse(store.get_state(KEY))
    if pid == os.getpid():
        store.set_state(KEY, "")


def wait_message():
    pid, age = holder()
    if not pid:
        return ""
    return (f"Baska bir runner zaten calisiyor (PID {pid}, {age:.0f} saniye once "
            "haber verdi). Iki runner ayni cuzdana yazarsa her islem iki kere "
            "acilir. Once digerini kapat, ya da o zaten kapaliysa "
            f"{STALE_SECONDS} saniye bekle, kilit kendiliginden duser.")
