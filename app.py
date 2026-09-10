"""Streamlit dashboard.  Run with:  streamlit run app.py"""

import json
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import bot_thread
import config
import fetcher
import gate
import signals as sig
import store

st.set_page_config(page_title="Paper Trade Bot", layout="wide",
                   initial_sidebar_state="expanded")
store.init_db()

if not gate.check():
    st.stop()

READ_ONLY = gate.read_only()


@st.cache_resource
def _bot():
    """Start the trading loop once per process (hosted deployments only)."""
    return bot_thread.start()


BOT_MODE = _bot()

GREEN, RED, BLUE, GREY = "#16a34a", "#dc2626", "#2563eb", "#6b7280"


def money(x):
    return f"${x:,.2f}"


def fmt_ts(series):
    return pd.to_datetime(series, unit="ms").dt.strftime("%d.%m %H:%M")


def ago(ms):
    if not ms:
        return "hic"
    s = int((store.now_ms() - int(ms)) / 1000)
    if s < 60:
        return f"{s} saniye once"
    if s < 3600:
        return f"{s // 60} dakika once"
    return f"{s // 3600} saat once"


def last_price(symbol, timeframe):
    df = store.load_candles(symbol, timeframe, limit=1)
    return float(df["close"].iloc[-1]) if not df.empty else None


def status_of(sid):
    raw = store.get_state(f"status:{sid}")
    return json.loads(raw) if raw else None


@st.cache_data(ttl=30)
def regime_now(symbol, timeframe):
    """Regime state straight from the candles, for runners predating it."""
    df = store.load_candles(symbol, timeframe, limit=config.CALC_WINDOW)
    if len(df) < config.TREND_EMA:
        return True, 0.0
    ema = df["close"].ewm(span=config.TREND_EMA, adjust=False).mean().iloc[-1]
    return bool(df["close"].iloc[-1] > ema), float(ema)


def wallet(sid, symbol, timeframe, mode):
    """Balance, open P&L and trade stats rebuilt from the trade log."""
    start = config.starting_balance(symbol)
    t = store.query("SELECT * FROM trades WHERE strategy_id=? AND mode=?",
                    (sid, mode))
    closed = t[t["status"] == "closed"] if not t.empty else t
    open_t = t[t["status"] == "open"] if not t.empty else t

    realized = closed["pnl"].fillna(0).sum() if not closed.empty else 0.0
    fees = t["fee"].fillna(0).sum() if not t.empty else 0.0
    balance = start + realized - fees

    unreal, open_row = 0.0, None
    if not open_t.empty:
        open_row = open_t.iloc[-1]
        px = last_price(symbol, timeframe)
        if px:
            unreal = (px - float(open_row["entry_price"])) * float(open_row["qty"])

    n = len(closed)
    wins = int((closed["pnl"] > 0).sum()) if n else 0
    return {
        "start": start, "balance": balance, "unrealized": unreal,
        "total": balance + unreal, "trades": n, "wins": wins,
        "win_pct": round(wins / n * 100, 1) if n else 0.0,
        "open_row": open_row,
    }


def summary_frame(mode):
    rows = []
    for asset, tf, sid in config.all_strategies():
        w = wallet(sid, asset["symbol"], tf, mode)
        rows.append({
            "Coin": asset["symbol"], "Zaman": tf, "_sid": sid,
            "Risk": asset["risk_grade"].replace("_", " "),
            "Baslangic": w["start"], "Su anki deger": w["total"],
            "Kar/Zarar": w["total"] - w["start"],
            "Getiri %": round((w["total"] - w["start"]) / w["start"] * 100, 2),
            "Islem": w["trades"], "Kazanma %": w["win_pct"],
            "Pozisyon": "ACIK" if w["open_row"] is not None else "-",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- sidebar ---

REFRESH_SECONDS = 5

PAGES = {
    "Su an ne oluyor": "Canli durum, acik pozisyonlar, son hareketler",
    "Ozet": "Sekiz strateji yan yana, 5m ve 15m karsilastirmasi",
    "Grafik": "Mum grafigi uzerinde botun aldigi ve sattigi noktalar",
    "Islem gecmisi": "Tamamlanmis islemler ve neden kapandiklari",
    "Sinyal logu": "Gordugu her formasyon, islem acti mi acmadi mi",
    "Backtest (kisa test)": "Ayni kurallarin son 30 gundeki sonucu",
    "Backtest (uzun test)": "Ayni kurallarin son 180 gundeki sonucu",
}

with st.sidebar:
    st.markdown("## Paper Trade Bot")

    # A radio, not tabs: the choice survives the auto-refresh rerun.
    page = st.radio("Menu", list(PAGES), label_visibility="collapsed", key="page")
    st.caption(PAGES[page])

    st.divider()

    hb_side = store.get_state("heartbeat")
    if hb_side and (store.now_ms() - int(hb_side)) < 180_000:
        st.markdown(f":green[● Bot calisiyor] · {ago(hb_side)}")
    elif BOT_MODE == "calisiyor":
        st.markdown(":orange[● Bot yeni basladi, veri cekiyor]")
    else:
        st.markdown(":red[● Bot durdu]")
    st.caption(f"Sayfa {REFRESH_SECONDS} saniyede bir kendini yeniler. "
               f"Bot borsadan {config.POLL_SECONDS} saniyede bir veri ceker.")

    st.divider()

    with st.expander("Bu nedir?"):
        st.write(
            "Sanal 10.000 dolarla islem yapan bir bot. Gercek para yok, gercek "
            "emir yok. Amaci, PDF'lerdeki mum formasyonu kurallarinin gercekten "
            "para kazandirip kazandirmadigini olcmek.")

    with st.expander("Para nasil bolundu?"):
        st.dataframe(pd.DataFrame([{
            "Coin": a["symbol"],
            "Risk": a["risk_grade"].replace("_", " "),
            "Pay": f"%{int(a['alloc'] * 100)}",
            "Tutar": money(config.TOTAL_CAPITAL * a["alloc"]),
        } for a in config.ASSETS]), hide_index=True, use_container_width=True)
        st.caption("Risk arttikca pay kuculur. Her coin kendi payini 5 dakikalik "
                   "ve 15 dakikalik strateji arasinda ikiye boler.")

    with st.expander("Kurallar"):
        st.write(
            f"- Komisyon her yonde %{config.FEE_RATE * 100:.2f}\n"
            f"- Hedef, riskin {config.RISK_REWARD:.0f} kati\n"
            f"- Stop en az %{config.MIN_STOP_PCT * 100:.1f} uzakta\n"
            f"- Ayi formasyonunda cikis: "
            f"{'acik' if config.USE_BEAR_PATTERN_EXIT else 'kapali'}\n"
            f"- MACD cikisinda cikis: "
            f"{'acik' if config.USE_MACD_EXIT else 'kapali'}\n"
            f"- Duz alim (EMA {config.TREND_EMA} alti): "
            f"{config.LEVERAGE_PLAIN}x\n"
            f"- Teyitli alim (EMA {config.TREND_EMA} ustu): "
            f"{config.LEVERAGE_CONFIRMED}x\n"
            "- Sadece alis yapar, acik satis yoktur")
        if config.LEVERAGE_CONFIRMED > 1:
            liq = (1 / config.LEVERAGE_CONFIRMED
                   - config.MAINTENANCE_MARGIN_RATE) * 100
            if liq <= config.MIN_STOP_PCT * 100:
                st.error(
                    f"{config.LEVERAGE_CONFIRMED}x kaldiracta tasfiye "
                    f"%{liq:.2f} dususte gelir, stop ise en az "
                    f"%{config.MIN_STOP_PCT * 100:.1f} uzakta. Stop hic "
                    "calisamaz, her kaybeden islem teminatin tamamini goturur.")
            else:
                st.caption(
                    f"{config.LEVERAGE_CONFIRMED}x kaldiracta tasfiye yaklasik "
                    f"%{liq:.1f} dususte gelir. Stop %"
                    f"{config.MIN_STOP_PCT * 100:.1f} uzakta oldugu icin once "
                    "stop calisir.")


# ------------------------------------------------------------------ body ---

@st.fragment(run_every=REFRESH_SECONDS)
def body():
    """Only this part reloads on a timer, so the sidebar stays responsive."""
    page = st.session_state.page

    # ----------------------------------------------------------------- header ---

    st.title(page)

    hb = store.get_state("heartbeat")
    alive = hb and (store.now_ms() - int(hb)) < 180_000
    if alive:
        st.success(f"Bot calisiyor. Son kontrol: {ago(hb)}. Her dakika yeni mumlara bakar.")
    else:
        st.error(
            "Bot su an calismiyor. Islem acilmaz, veriler guncellenmez. "
            "Ayri bir terminal ac ve calistir:  `python runner.py`"
            + (f"  (son calisma: {ago(hb)})" if hb else ""))

    df_live = summary_frame("live")
    total_now = df_live["Su anki deger"].sum()
    delta = total_now - config.TOTAL_CAPITAL
    open_count = int((df_live["Pozisyon"] == "ACIK").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Baslangic parasi", money(config.TOTAL_CAPITAL))
    c2.metric("Su anki deger", money(total_now),
              f"{delta:+,.2f} $  ({delta / config.TOTAL_CAPITAL * 100:+.2f}%)")
    c3.metric("Kapanan islem", int(df_live["Islem"].sum()))
    c4.metric("Acik pozisyon", open_count)
    st.caption(
        "Su anki deger = nakit + acik pozisyonlarin guncel degeri. Yesilse kardasin, "
        "kirmiziysa zarardasin. Kapanan islem, alip sattigi tamamlanmis islem sayisi.")


    # ------------------------------------------------------- page: live status ---

    if page == "Su an ne oluyor":
        st.subheader("Her strateji su an ne yapiyor?")
        st.write(
            "Bot almak icin dort sart arar. Fiyat 200 mumluk ortalamanin ustunde "
            "olmali (rejim), kisa vadede bir boga mum formasyonu cikmali, RSI 45 "
            "altinda olmali ya da MACD yukari kesmeli, ve hacim yeterli olmali. "
            "Dordu birden tutmadan almaz. Asagidaki son sutun, o anda hangisinin "
            "tutmadigini soyler.")

        last_trade = store.query(
            "SELECT strategy_id, MAX(entry_ts) e FROM trades WHERE mode='live' "
            "GROUP BY strategy_id")
        last_trade = dict(zip(last_trade["strategy_id"], last_trade["e"])) \
            if not last_trade.empty else {}

        rows = []
        for asset, tf, sid in config.all_strategies():
            s = status_of(sid)
            w = wallet(sid, asset["symbol"], tf, "live")
            if s is None:
                rows.append({"Strateji": f"{asset['symbol']} {tf}",
                             "Durum": "veri bekleniyor", "Fiyat": "-",
                             "Rejim": "-", "Trend": "-", "RSI": "-", "Hacim": "-",
                             "Formasyon": "-", "Son islem": "-",
                             "Neden almiyor": "bot henuz bu seriyi islemedi"})
                continue

            if "rejim_yukari" in s:
                regime_ok, ema_long = s["rejim_yukari"], s.get("ema_long", 0.0)
            else:
                # An older runner is still writing status rows without the
                # regime fields; derive them here so the page stays accurate.
                regime_ok, ema_long = regime_now(asset["symbol"], tf)
            if w["open_row"] is not None:
                r = w["open_row"]
                what = (f"POZISYONDA. {float(r['entry_price']):.6g} alindi, "
                        f"hedef {float(r['tp']):.6g}, stop {float(r['sl']):.6g}. "
                        f"Su an {w['unrealized']:+.2f} $")
            elif not regime_ok:
                what = (f"REJIM KAPALI. Fiyat 200 mumluk ortalamanin "
                        f"({ema_long:.6g}) altinda. Bu seride hic islem "
                        "acilmaz, formasyon ciksa bile.")
            elif s["boga_formasyon"]:
                what = f"formasyon var ({s['boga_formasyon']}) ama teyit/hacim tutmadi"
            else:
                what = "rejim uygun, boga formasyonu bekliyor"

            lt = last_trade.get(sid)
            rows.append({
                "Strateji": f"{asset['symbol']} {tf}",
                "Durum": "pozisyonda" if w["open_row"] is not None else "bekliyor",
                "Fiyat": f"{s['fiyat']:.6f}".rstrip("0").rstrip("."),
                "Rejim": "acik" if regime_ok else "KAPALI",
                "Son islem": ago(lt) if lt else "hic",
                "Trend": s["trend"],
                "RSI": s["rsi"],
                "Hacim": f"{s['hacim_orani']}x",
                "Formasyon": s["boga_formasyon"] or s["ayi_formasyon"] or "-",
                "Neden almiyor": what,
            })
        frame = pd.DataFrame(rows)
        st.dataframe(frame, hide_index=True, use_container_width=True)

        kapali = frame[frame["Rejim"] == "KAPALI"]["Strateji"].tolist()
        if kapali:
            pay = sum(a["alloc"] for a in config.ASSETS
                      if any(s.startswith(a["symbol"] + " ") for s in kapali)) * 100
            st.warning(
                f"Su an {len(kapali)} stratejide rejim kapali: {', '.join(kapali)}. "
                f"Bu coinlerin fiyati 200 mumluk ortalamanin altinda, yani uzun "
                f"vadeli trend asagi. Trend filtresi bu durumda hic islem acmaz. "
                f"Portfoyun yaklasik %{pay:.0f}'i bekleme modunda. "
                "Bu bir ariza degil, kuralin calismasi. Fiyat ortalamanin ustune "
                "cikinca kendiliginden islem acmaya baslar.")

        st.caption(
            "Rejim: fiyat 200 mumluk ortalamanin ustunde mi. Kapaliysa o seride "
            "hicbir sart islem actiramaz. Trend: fiyatin 21 mumluk ortalamaya gore "
            "kisa vadeli yonu. RSI 30 altinda asiri satim, 70 ustunde asiri alim. "
            "Hacim, son 20 mumun ortalamasina gore oran; 0.5x altinda bot islem "
            "acmaz. Son islem: bu strateji en son ne zaman alim yapti.")

        st.divider()
        st.subheader("Acik pozisyonlar")
        op = store.query("SELECT * FROM trades WHERE status='open' AND mode='live'")
        if op.empty:
            st.info("Su an acik pozisyon yok. Bot kural tutan bir mum bekliyor.")
        else:
            rows = []
            for _, r in op.iterrows():
                px = last_price(r["symbol"], r["timeframe"]) or r["entry_price"]
                pnl = (px - r["entry_price"]) * r["qty"]
                mesafe_tp = (r["tp"] / px - 1) * 100
                mesafe_sl = (r["sl"] / px - 1) * 100
                rows.append({
                    "Strateji": r["strategy_id"],
                    "Ne zaman alindi": fmt_ts(pd.Series([r["entry_ts"]]))[0],
                    "Alis fiyati": r["entry_price"], "Guncel fiyat": px,
                    "Kar/Zarar $": round(pnl, 2),
                    "Kar/Zarar %": round((px / r["entry_price"] - 1) * 100, 2),
                    "Hedefe kalan %": round(mesafe_tp, 2),
                    "Stopa kalan %": round(mesafe_sl, 2),
                    "Kaldirac": f"{int(r['leverage'] or 1)}x",
                    "Tasfiye fiyati": (round(float(r["liq_price"]), 8)
                                       if pd.notna(r.get("liq_price")) else "-"),
                    "Tasfiyeye kalan %": (
                        round((float(r["liq_price"]) / px - 1) * 100, 2)
                        if pd.notna(r.get("liq_price")) else "-"),
                    "Riske attigi $": round((r["entry_price"] - r["sl"]) * r["qty"], 2),
                    "Risk %": round(r["risk_pct_real"], 2)
                              if pd.notna(r.get("risk_pct_real")) else None,
                    "Neden aldi": r["reason_entry"],
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.caption(
                "Hedefe kalan: fiyatin kar al seviyesine ulasmasi icin gereken yuzde. "
                "Stopa kalan: zarar kes seviyesine dusmesi icin gereken yuzde. "
                "Riske attigi: stop calisirsa kaybedilecek tutar. Kaldirac 1x "
                "ise tasfiye yoktur. Kaldiracli pozisyonda fiyat tasfiye "
                "seviyesine inerse pozisyon zorla kapanir ve teminatin tamami "
                "gider; stop tasfiyeden uzaktaysa hic calisamaz.")

        st.divider()
        st.subheader("Son hareketler")
        recent = store.query(
            "SELECT * FROM trades WHERE mode='live' ORDER BY entry_ts DESC LIMIT 12")
        if recent.empty:
            st.info("Henuz islem yok.")
        else:
            for _, r in recent.iterrows():
                when = fmt_ts(pd.Series([r["entry_ts"]]))[0]
                if r["status"] == "open":
                    st.markdown(
                        f"- **{when}** · {r['strategy_id']} · **ALDI** "
                        f"{money(r['entry_price'])} · sebep: `{r['reason_entry']}` · "
                        f"pozisyon hala acik")
                else:
                    sign = "kar" if r["pnl"] > 0 else "zarar"
                    color = GREEN if r["pnl"] > 0 else RED
                    st.markdown(
                        f"- **{when}** · {r['strategy_id']} · ALDI "
                        f"{money(r['entry_price'])} → SATTI {money(r['exit_price'])} · "
                        f"<span style='color:{color}'><b>{r['pnl']:+.2f} $ {sign}</b></span> · "
                        f"cikis sebebi: `{r['reason_exit']}`", unsafe_allow_html=True)


    # --------------------------------------------------------------- tab: ozet ---

    def equity_chart(mode):
        df = store.query("SELECT * FROM equity WHERE mode=? ORDER BY ts", (mode,))
        if df.empty:
            st.info("Henuz kayit yok.")
            return
        if df["ts"].nunique() < 3:
            # A backtest writes one snapshot at the end, so there is no curve.
            st.caption("Gecmis test tek bir kapanis degeri yazar, egri olusmaz. "
                       "Zaman icindeki degisimi canli simulasyonda gorursun.")
            return
        df["zaman"] = pd.to_datetime(df["ts"], unit="ms")
        fig = go.Figure()
        for sid, g in df.groupby("strategy_id"):
            fig.add_trace(go.Scatter(x=g["zaman"], y=g["total"], name=sid, mode="lines"))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=30, b=10),
                          yaxis_title="Strateji degeri (USD)")
        st.plotly_chart(fig, use_container_width=True)


    if page == "Ozet":
        st.subheader("Strateji karsilastirmasi")
        show = df_live.drop(columns=["_sid"])
        st.dataframe(
            show.style.format({
                "Baslangic": "{:,.2f}", "Su anki deger": "{:,.2f}",
                "Kar/Zarar": "{:+,.2f}", "Getiri %": "{:+.2f}",
            }).map(lambda v: f"color:{GREEN if v > 0 else RED if v < 0 else GREY}",
                   subset=["Kar/Zarar", "Getiri %"]),
            hide_index=True, use_container_width=True)
        st.caption(
            "Ayni kurallar iki farkli zaman diliminde calisiyor. 5m, bes dakikalik "
            "mumlara bakar ve cok islem acar. 15m daha az ama daha guvenilir sinyal "
            "uretir. Hangisinin daha iyi oldugunu bu tablodan gorursun.")

        g5 = df_live[df_live["Zaman"] == "5m"]
        g15 = df_live[df_live["Zaman"] == "15m"]
        a, b = st.columns(2)
        a.metric("5 dakikalik gruplar toplami", money(g5["Su anki deger"].sum()),
                 f"{g5['Kar/Zarar'].sum():+,.2f} $")
        b.metric("15 dakikalik gruplar toplami", money(g15["Su anki deger"].sum()),
                 f"{g15['Kar/Zarar'].sum():+,.2f} $")

        st.subheader("Paranin zaman icinde degisimi")
        equity_chart("live")
        st.caption("Her cizgi bir strateji. Yukari giden kazaniyor, asagi giden kaybediyor.")


    # -------------------------------------------------------------- tab: chart ---

    if page == "Grafik":
        c1, c2, c3 = st.columns([2, 1, 1])
        symbol = c1.selectbox("Coin", [a["symbol"] for a in config.ASSETS])
        timeframe = c2.selectbox("Zaman dilimi", config.TIMEFRAMES)
        bars = c3.slider("Kac mum gosterilsin", 100, 600, 250, step=50)

        df = store.load_candles(symbol, timeframe, limit=bars)
        if df.empty:
            st.warning("Bu coin icin veri yok. Bot calisiyor mu?")
        else:
            df = sig.prepare(df)
            df["zaman"] = pd.to_datetime(df["ts"], unit="ms")

            fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                                row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.04,
                                subplot_titles=("Fiyat ve formasyonlar", "RSI", "MACD"))
            fig.add_trace(go.Candlestick(
                x=df["zaman"], open=df["open"], high=df["high"],
                low=df["low"], close=df["close"], name="Fiyat"), row=1, col=1)
            for col, name in [("ema_fast", "EMA 9"), ("ema_mid", "EMA 21"),
                              ("ema_slow", "EMA 50")]:
                fig.add_trace(go.Scatter(x=df["zaman"], y=df[col], name=name,
                                         line=dict(width=1)), row=1, col=1)

            bulls, bears = df[df["bull_signal"]], df[df["bear_signal"]]
            if not bulls.empty:
                fig.add_trace(go.Scatter(
                    x=bulls["zaman"], y=bulls["low"] * 0.995, mode="markers",
                    marker=dict(symbol="triangle-up", size=12, color=GREEN),
                    name="Boga formasyonu",
                    hovertext=[sig.pattern_names(r, "bull") for _, r in bulls.iterrows()]),
                    row=1, col=1)
            if not bears.empty:
                fig.add_trace(go.Scatter(
                    x=bears["zaman"], y=bears["high"] * 1.005, mode="markers",
                    marker=dict(symbol="triangle-down", size=12, color=RED),
                    name="Ayi formasyonu",
                    hovertext=[sig.pattern_names(r, "bear") for _, r in bears.iterrows()]),
                    row=1, col=1)

            sid = config.strategy_id(symbol, timeframe)
            window_start = int(df["ts"].iloc[0])
            tr = store.query(
                "SELECT * FROM trades WHERE strategy_id=? AND mode='live' AND entry_ts>=?",
                (sid, window_start))

            if tr.empty:
                st.info("Bu pencerede bot hic islem yapmadi. Mum sayisini artir ya da "
                        "baska bir strateji sec.")
            else:
                first = True
                for _, r in tr.iterrows():
                    x0 = pd.to_datetime(r["entry_ts"], unit="ms")
                    y0 = float(r["entry_price"])
                    won = pd.notna(r["pnl"]) and r["pnl"] > 0
                    colour = GREEN if won else RED if pd.notna(r["pnl"]) else BLUE

                    # Buy marker with a price label underneath.
                    fig.add_trace(go.Scatter(
                        x=[x0], y=[y0], mode="markers+text",
                        marker=dict(symbol="triangle-up", size=18, color=BLUE,
                                    line=dict(width=2, color="white")),
                        text=[f"AL {y0:.5g}"], textposition="bottom center",
                        textfont=dict(size=11, color=BLUE),
                        name="BOT ALDI", legendgroup="al", showlegend=first,
                        hovertemplate=(f"<b>ALDI</b><br>{x0:%d.%m %H:%M}<br>"
                                       f"fiyat {y0:.6g}<br>sebep {r['reason_entry']}"
                                       "<extra></extra>")), row=1, col=1)

                    if pd.notna(r["exit_ts"]):
                        x1 = pd.to_datetime(r["exit_ts"], unit="ms")
                        y1 = float(r["exit_price"])
                        # Line from buy to sell, coloured by the outcome.
                        fig.add_trace(go.Scatter(
                            x=[x0, x1], y=[y0, y1], mode="lines",
                            line=dict(color=colour, width=3),
                            name="Kazanan islem" if won else "Kaybeden islem",
                            legendgroup="kar" if won else "zarar", showlegend=first,
                            hoverinfo="skip"), row=1, col=1)
                        fig.add_trace(go.Scatter(
                            x=[x1], y=[y1], mode="markers+text",
                            marker=dict(symbol="triangle-down", size=18, color=colour,
                                        line=dict(width=2, color="white")),
                            text=[f"SAT {y1:.5g} ({r['pnl']:+.2f}$)"],
                            textposition="top center",
                            textfont=dict(size=11, color=colour),
                            name="BOT SATTI", legendgroup="sat", showlegend=first,
                            hovertemplate=(f"<b>SATTI</b><br>{x1:%d.%m %H:%M}<br>"
                                           f"fiyat {y1:.6g}<br>"
                                           f"sonuc {r['pnl']:+.2f} $<br>"
                                           f"sebep {r['reason_exit']}"
                                           "<extra></extra>")), row=1, col=1)
                    else:
                        # Position still open: show the stop and target as guides.
                        x_end = df["zaman"].iloc[-1]
                        for lvl, lab, col in [(float(r["tp"]), "HEDEF", GREEN),
                                              (float(r["sl"]), "STOP", RED)]:
                            fig.add_trace(go.Scatter(
                                x=[x0, x_end], y=[lvl, lvl], mode="lines",
                                line=dict(color=col, width=2, dash="dash"),
                                name=lab, showlegend=first, hoverinfo="skip"),
                                row=1, col=1)
                        fig.add_annotation(x=x_end, y=float(r["tp"]), text="HEDEF",
                                           showarrow=False, xanchor="right",
                                           yshift=10, font=dict(color=GREEN, size=11),
                                           row=1, col=1)
                        fig.add_annotation(x=x_end, y=float(r["sl"]), text="STOP",
                                           showarrow=False, xanchor="right",
                                           yshift=-10, font=dict(color=RED, size=11),
                                           row=1, col=1)
                    first = False

            fig.add_trace(go.Scatter(x=df["zaman"], y=df["rsi"], name="RSI",
                                     line=dict(color=BLUE)), row=2, col=1)
            fig.add_hline(y=70, line=dict(dash="dot", width=1, color=RED), row=2, col=1)
            fig.add_hline(y=30, line=dict(dash="dot", width=1, color=GREEN), row=2, col=1)
            fig.add_trace(go.Scatter(x=df["zaman"], y=df["macd"], name="MACD"), row=3, col=1)
            fig.add_trace(go.Scatter(x=df["zaman"], y=df["macd_signal"], name="Sinyal"),
                          row=3, col=1)
            fig.update_layout(height=780, xaxis_rangeslider_visible=False,
                              margin=dict(l=10, r=10, t=40, b=10),
                              legend=dict(orientation="h", y=1.06))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Kucuk yesil ucgen: botun tanidigi yukselis formasyonu. Kucuk kirmizi "
                "ucgen: dusus formasyonu. Bu isaretler sadece formasyonu gosterir, "
                "botun aldigi anlamina gelmez. Buyuk mavi ucgen ve **AL** yazisi botun "
                "gercekten aldigi yer. Ondan cikan kalin cizgi satisa kadar uzanir, "
                "yesilse kar etti kirmiziysa zarar etti. Acik pozisyonda kesik yesil "
                "cizgi hedefi, kesik kirmizi cizgi stop seviyesini gosterir.")

            if not tr.empty:
                st.subheader("Grafikte gorunen islemler")
                tbl = pd.DataFrame({
                    "Alis zamani": fmt_ts(tr["entry_ts"]),
                    "Alis fiyati": tr["entry_price"],
                    "Satis zamani": fmt_ts(tr["exit_ts"]),
                    "Satis fiyati": tr["exit_price"],
                    "Sonuc $": tr["pnl"].round(2),
                    "Sonuc %": tr["pnl_pct"].round(2),
                    "Neden aldi": tr["reason_entry"],
                    "Neden satti": tr["reason_exit"],
                })
                st.dataframe(tbl.sort_values("Alis zamani", ascending=False),
                             hide_index=True, use_container_width=True)


    # ------------------------------------------------------------ tab: history ---

    if page == "Islem gecmisi":
        tr = store.query(
            "SELECT * FROM trades WHERE mode='live' ORDER BY entry_ts DESC LIMIT 500")
        if tr.empty:
            st.info("Henuz islem yok.")
        else:
            closed = tr[tr["status"] == "closed"]
            if not closed.empty:
                a, b, c, d = st.columns(4)
                a.metric("Toplam islem", len(closed))
                a.caption("Alinip satilmis, tamamlanmis islem sayisi")
                b.metric("Kazanan", int((closed["pnl"] > 0).sum()))
                b.caption("Karla kapanan islem")
                c.metric("Kaybeden", int((closed["pnl"] <= 0).sum()))
                c.caption("Zararla kapanan islem")
                d.metric("Net sonuc", money(closed["pnl"].sum()))
                d.caption("Tum islemlerin toplam kar zarari")

                st.subheader("Islemler neden kapandi?")
                why = closed.groupby("reason_exit").agg(
                    Adet=("pnl", "size"), Toplam=("pnl", "sum")).reset_index()
                why.columns = ["Cikis sebebi", "Adet", "Toplam kar/zarar $"]
                why["Toplam kar/zarar $"] = why["Toplam kar/zarar $"].round(2)
                st.dataframe(why.sort_values("Adet", ascending=False),
                             hide_index=True, use_container_width=True)
                st.caption(
                    "stop-loss: zarar kes seviyesine dustu. take-profit: hedefe ulasti. "
                    "ayi formasyonu: dusus isareti gorunce cikti. "
                    "sure limiti: cok bekledi, kapatti.")

            st.subheader("Tum islemler")
            out = pd.DataFrame({
                "Strateji": tr["strategy_id"],
                "Alis zamani": fmt_ts(tr["entry_ts"]),
                "Alis": tr["entry_price"],
                "Satis zamani": fmt_ts(tr["exit_ts"]),
                "Satis": tr["exit_price"],
                "Kar/Zarar $": tr["pnl"].round(2),
                "Kar/Zarar %": tr["pnl_pct"].round(2),
                "Alis sebebi": tr["reason_entry"],
                "Satis sebebi": tr["reason_exit"],
                "Durum": tr["status"].map({"open": "acik", "closed": "kapandi"}),
            })
            st.dataframe(out, hide_index=True, use_container_width=True)


    # ------------------------------------------------------------ tab: signals ---

    if page == "Sinyal logu":
        st.write(
            "Bot bir formasyon gordugu her an buraya yazar. Bazilarinda islem acar, "
            "bazilarinda teyit ya da hacim tutmadigi icin acmaz. Neden acmadigini "
            "son sutunda gorursun.")
        sg = store.query("SELECT * FROM signals ORDER BY ts DESC LIMIT 400")
        if sg.empty:
            st.info("Henuz sinyal yok. Bot formasyon bekliyor.")
        else:
            out = pd.DataFrame({
                "Zaman": fmt_ts(sg["ts"]),
                "Strateji": sg["strategy_id"],
                "Gordugu formasyon": sg["rule"],
                "Fiyat": sg["price"],
                "Islem acti mi": sg["acted"].map({1: "EVET", 0: "hayir"}),
                "Acmadiysa neden": sg["note"],
            })
            st.dataframe(out, hide_index=True, use_container_width=True)


    # ----------------------------------------------------------- tab: backtest ---

    if page.startswith("Backtest"):
        mode = "backtest_long" if "uzun" in page else "backtest"
        cmd = ("python backtest.py --long" if mode == "backtest_long"
               else "python backtest.py --days 30")
        days = store.get_state(f"{mode}:days")
        ran = store.get_state(f"{mode}:ran_at")

        if mode == "backtest_long":
            st.write(
                f"Uzun test, ayni kurallari {days or config.LONG_TEST_DAYS} gunluk "
                "veri uzerinde calistirir. Kisa test tek bir piyasa donemini olcer "
                "ve o donem yukselisse sonuc yaniltici cikar. Uzun test hem yukselis "
                "hem dusus icerdigi icin kuralin gercekten calisip calismadigini "
                "gosterir. Sadece XRP'de tam gecmis var; DEBIT ve ROBIN yeni "
                "listelendigi icin kendi yaslari kadar veri katiyor.")
        else:
            st.write(
                f"Kisa test, ayni kurallari son {days or config.BACKFILL_DAYS} gunun "
                "verisi uzerinde calistirir. Canli simulasyondan bagimsizdir. Tek "
                "donemi olctugu icin uzun testle birlikte okunmalidir.")

        if ran:
            st.caption(f"Son calistirma: {ago(ran)}")

        window = config.LONG_TEST_DAYS if mode == "backtest_long" else 30
        if READ_ONLY:
            st.caption("Bu panel salt okunur yayinlaniyor. Testi panelin sahibi "
                       "terminalden calistirir.")
        elif st.button(f"Testi simdi calistir ({window} gun)", key=f"run_{mode}",
                       type="primary"):
            import backtest
            with st.status(f"{window} gunluk test calisiyor", expanded=True) as s:
                st.write("Veri cekiliyor...")
                fetcher.update_all(backfill_days=window)
                st.write("Kurallar gecmis uzerinde calistiriliyor...")
                store.clear_mode(mode)
                store.set_state(f"{mode}:days", window)
                store.set_state(f"{mode}:ran_at", store.now_ms())
                for asset, tf, sid in config.all_strategies():
                    st.write(f"  {sid}")
                    backtest.run_one(asset, tf, sid, window, mode)
                s.update(label="Test bitti", state="complete", expanded=False)
            st.rerun()

        bt = summary_frame(mode)
        if bt["Islem"].sum() == 0:
            st.info(
                "Sonuc yok. Yukaridaki dugmeye bas, ya da terminalden calistir:  "
                f"`{cmd}`\n\nBulutta acilan sayfa kendi veritabanini sifirdan "
                "kurar. Senin bilgisayarindaki sonuclar buraya gelmez, cunku "
                "veritabani dosyasi depoya dahil degildir.")
        else:
            bh = {}
            for asset, tf, sid in config.all_strategies():
                d = store.load_candles(asset["symbol"], tf)
                cut = store.now_ms() - int(days or config.BACKFILL_DAYS) * 86_400_000
                d = d[d["ts"] >= cut]
                bh[sid] = ((d["close"].iloc[-1] / d["close"].iloc[0] - 1) * 100
                           if len(d) > 1 else 0.0)
                bh[sid + "_gun"] = ((d["ts"].iloc[-1] - d["ts"].iloc[0]) / 86_400_000
                                    if len(d) > 1 else 0.0)

            show = bt.drop(columns=["Pozisyon"]).copy()
            show["Al-tut %"] = show["_sid"].map(bh).round(2)
            show["Fark"] = (show["Getiri %"] - show["Al-tut %"]).round(2)
            show["Veri gun"] = show["_sid"].map(
                {k[:-4]: v for k, v in bh.items() if k.endswith("_gun")}).round(1)
            show = show.drop(columns=["_sid"])
            st.dataframe(
                show.style.format({
                    "Baslangic": "{:,.2f}", "Su anki deger": "{:,.2f}",
                    "Kar/Zarar": "{:+,.2f}", "Getiri %": "{:+.2f}",
                    "Al-tut %": "{:+.2f}", "Fark": "{:+.2f}",
                }).map(lambda v: f"color:{GREEN if v > 0 else RED if v < 0 else GREY}",
                       subset=["Kar/Zarar", "Getiri %", "Fark"]),
                hide_index=True, use_container_width=True)
            st.caption(
                "Al-tut: ayni parayi o coine yatirip hic dokunmasaydin ne olurdu. "
                "Fark: botun bu referansa gore ne kadar iyi ya da kotu oldugu. "
                "Fark eksiyse bot, hicbir sey yapmamaktan daha kotu calismis.")

            total_start = bt["Baslangic"].sum()
            total_end = bt["Su anki deger"].sum()
            a, b, c = st.columns(3)
            a.metric("Toplam sonuc", money(total_end),
                     f"{(total_end - total_start) / total_start * 100:+.2f}%")
            g5, g15 = bt[bt["Zaman"] == "5m"], bt[bt["Zaman"] == "15m"]
            b.metric("5 dakikalik toplam", money(g5["Su anki deger"].sum()),
                     f"{g5['Kar/Zarar'].sum():+,.2f} $")
            c.metric("15 dakikalik toplam", money(g15["Su anki deger"].sum()),
                     f"{g15['Kar/Zarar'].sum():+,.2f} $")

            t = store.query(
                "SELECT * FROM trades WHERE mode=? AND status='closed'", (mode,))
            if not t.empty:
                gross = (t["pnl"] + t["fee"]).sum()
                risk = t["risk_pct_real"].dropna()
                d1, d2, d3 = st.columns(3)
                d1.metric("Komisyon oncesi brut", money(gross))
                d1.caption("Sinyalin ham sonucu, maliyet dusulmeden")
                d2.metric("Odenen komisyon", money(t["fee"].sum() * 2))
                d2.caption("Brut sonuctan buyukse maliyet kenari yiyor demektir")
                d3.metric("Islem basina gercek risk",
                          f"%{risk.mean():.2f}" if len(risk) else "-")
                d3.caption("Config'de hedeflenen ile karsilastir")

            equity_chart(mode)




body()
