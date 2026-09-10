"""Access gate for the dashboard when it is served over a public tunnel.

The tunnel proxies one port and nothing else, so the machine itself is not
reachable. This module adds the second layer: who may look at the page, and
what a viewer is allowed to make the server do.

Set APP_PASSWORD in the environment to require a password. Leave it unset and
the page is open to anyone holding the link, which is fine on localhost and a
deliberate choice on a tunnel.
"""

import hmac
import os

import streamlit as st


def password_required() -> bool:
    return bool(os.environ.get("APP_PASSWORD", "").strip())


def read_only() -> bool:
    """True when viewers must not be able to start server-side work.

    Buttons that kick off a long backtest are a way for a stranger with the
    link to pin the machine's CPU. They stay hidden unless the operator opts in
    with ALLOW_ACTIONS=1, or no password is configured and we are on localhost.
    """
    if os.environ.get("ALLOW_ACTIONS", "").strip() in ("1", "true", "True"):
        return False
    return bool(os.environ.get("PUBLIC_TUNNEL", "").strip()) or password_required()


def check() -> bool:
    """Render the password prompt. Returns True when the viewer may continue."""
    if not password_required():
        return True
    if st.session_state.get("_authed"):
        return True

    st.title("Paper Trade Bot")
    st.write("Bu panel parola ile korunuyor.")
    with st.form("giris"):
        entered = st.text_input("Parola", type="password")
        ok = st.form_submit_button("Gir")
    if ok:
        # compare_digest keeps the check from leaking length through timing.
        if hmac.compare_digest(entered, os.environ["APP_PASSWORD"]):
            st.session_state["_authed"] = True
            st.rerun()
        else:
            st.error("Parola yanlis.")
    st.caption("Parolayi panelin sahibi belirler. Kaybolursa APP_PASSWORD "
               "degiskenini degistirip uygulamayi yeniden baslatmak yeter.")
    return False
