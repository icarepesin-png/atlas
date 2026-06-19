"""Dashboard Streamlit.

Run:  streamlit run atlas/dashboard/app.py
Onglets: Watchlist, Signaux, Portefeuille, Heatmap secteurs, Backtests, Risque.
Theme: config dans .streamlit/config.toml + CSS ci-dessous (presentation
uniquement, aucune logique metier ici).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Streamlit execute ce fichier comme un script: si le cwd du lanceur contient
# un dossier homonyme du package (ex: C:\bot trading\atlas vu comme namespace
# package), l'import de `atlas` se resout mal. On epingle la racine du projet
# en tete de sys.path pour etre independant du repertoire de lancement.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from datetime import datetime

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Hebergement cloud (Streamlit Community Cloud): l'URL de la base Postgres est
# fournie via les "secrets" Streamlit. On la bascule en variable d'environnement
# pour que la config ATLAS la lise, avant tout acces a la base.
_secret_seen = False
try:
    if "DATABASE_URL" in st.secrets:
        os.environ["DATABASE_URL"] = str(st.secrets["DATABASE_URL"])
        _secret_seen = True
except Exception:
    pass

from atlas.config import get_settings
get_settings.cache_clear()  # relire DATABASE_URL apres l'avoir positionne
from atlas.data.store import load_ohlcv, read_table_raw

try:
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo("America/New_York")
    _PARIS = ZoneInfo("Europe/Paris")
except Exception:
    _NY = None
    _PARIS = None


def now_paris() -> datetime:
    """Heure de Paris (le serveur cloud tourne en UTC: on affiche l'heure
    locale de l'utilisateur, pas celle du serveur)."""
    return datetime.now(_PARIS) if _PARIS else datetime.now()

# ----------------------------------------------------------------- palette ---

NAVY = "#0b1220"
CARD = "#121b2e"
BORDER = "#24314d"
GRID = "#1d2940"
TEXT_DIM = "#93a4c3"
AMBER = "#e3aa4e"
EMERALD = "#4fd1a5"
CRIMSON = "#e35d6a"
PIE_PALETTE = ["#e3aa4e", "#4fd1a5", "#5b8def", "#b07ce8", "#e35d6a",
               "#53c4dd", "#9aa55b", "#d97f4e", "#7f8ca6", "#c75b9b"]

st.set_page_config(page_title="ATLAS", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
/* ---- fond et typographie ---- */
.stApp { background: radial-gradient(1200px 600px at 20% -10%, #13203a 0%, #0b1220 55%) fixed; }
h1, h2, h3 { letter-spacing: .4px; }

/* ---- masquer le chrome Streamlit ---- */
#MainMenu, footer { visibility: hidden; height: 0; }
.stAppDeployButton, [data-testid="stToolbar"], [data-testid="stDecoration"] { display: none; }
header[data-testid="stHeader"] { background: transparent; }

/* ---- en-tete ATLAS ---- */
.atlas-header { padding: 6px 0 2px 0; }
.atlas-logo {
  font-size: 44px; font-weight: 800; letter-spacing: 6px;
  background: linear-gradient(90deg, #f0c879, #e3aa4e 45%, #b8843a);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.atlas-sub { color: #93a4c3; font-size: 15px; letter-spacing: 2.5px;
  text-transform: uppercase; margin-left: 18px; }
.atlas-rule { height: 1px; margin: 10px 0 4px 0;
  background: linear-gradient(90deg, #e3aa4e55, #24314d 40%, transparent); }

/* ---- cartes de metriques ---- */
[data-testid="stMetric"] {
  background: #121b2e; border: 1px solid #24314d; border-radius: 12px;
  padding: 14px 18px 12px 18px;
  box-shadow: 0 2px 10px rgba(0,0,0,.25);
}
[data-testid="stMetricLabel"] { color: #93a4c3; }
[data-testid="stMetricValue"] { color: #e6edf3; }

/* ---- onglets ---- */
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid #24314d; }
.stTabs [data-baseweb="tab"] {
  background: transparent; border-radius: 9px 9px 0 0;
  padding: 9px 20px; color: #93a4c3;
}
.stTabs [aria-selected="true"] {
  background: #121b2e; color: #e3aa4e !important;
  border: 1px solid #24314d; border-bottom: none;
}

/* ---- bandeaux d'etat ---- */
[data-testid="stAlert"] { border-radius: 10px; }

/* ---- tableaux ---- */
[data-testid="stDataFrame"] { border: 1px solid #24314d; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<div class="atlas-header"><span class="atlas-logo">ATLAS</span>'
    '<span class="atlas-sub">Global Equity Quant Platform</span></div>'
    '<div class="atlas-rule"></div>',
    unsafe_allow_html=True,
)

# Bandeau de sante du run nocturne. En local: lit health.json. Sur le cloud
# (pas de health.json), repli sur la date du dernier scan presente en base.
def _health_banner():
    try:
        from atlas.monitoring.healthcheck import HEALTH_FILE, check
        if HEALTH_FILE.exists():
            ok, msg = check()
            (st.success if ok else st.error)(msg)
            return
    except Exception:
        pass
    s = read_table_raw("scores")
    if not s.empty:
        st.info(f"Donnees du dernier scan: {s['as_of_date'].max()} "
                f"({len(s[s['as_of_date'] == s['as_of_date'].max()])} titres).")
    else:
        st.warning("Aucune donnee disponible pour le moment.")


_health_banner()


@st.cache_data(ttl=300)
def load(table: str) -> pd.DataFrame:
    # Lecture sans DDL: fonctionne aussi bien en local (SQLite) que sur le
    # dashboard cloud (Postgres peuple par la synchro). Table absente -> vide.
    return read_table_raw(table)


def clean_nan(df: pd.DataFrame, placeholder: str = "n/d") -> pd.DataFrame:
    """Remplace les NaN des colonnes TEXTE par un placeholder lisible.
    Sans ca, le tableau JavaScript affiche 'undefined'. Les colonnes
    numeriques gardent leurs NaN (rendus en case vide, ce qui est correct)."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].where(out[c].notna(), placeholder)
    return out


def us_market_open() -> bool:
    """Heures US (9h30-16h ET, lun-ven). Indicateur, ignore les jours feries."""
    if _NY is None:
        return False
    now = datetime.now(_NY)
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= hm <= 16 * 60


@st.cache_data(ttl=240)
def live_prices_usd(tickers: tuple) -> dict:
    """Cours differes (~15 min) des positions, convertis en USD.

    Ne touche a aucune decision: revalorisation d'AFFICHAGE uniquement.
    Repli sur le dernier cours de cloture en cache si l'API ne repond pas."""
    import yfinance as yf

    from atlas.data.fx import currency_of, get_usd_rates, to_usd

    rates = get_usd_rates()
    out, intraday = {}, {}
    # Un seul appel groupe (barres 1 min du jour) pour tous les titres
    try:
        data = yf.download(list(tickers), period="1d", interval="1m",
                           progress=False, group_by="ticker", threads=True)
        for t in tickers:
            try:
                col = data[t]["Close"] if len(tickers) > 1 else data["Close"]
                series = col.dropna()
                if len(series):
                    intraday[t] = float(series.iloc[-1])
            except Exception:
                pass
    except Exception:
        pass
    for t in tickers:
        px = intraday.get(t)
        if not px:  # marche ferme ou pas d'intraday: dernier cours de cloture
            df = load_ohlcv(t)
            if not df.empty:
                px = float(df["close"].iloc[-1])
        if px:
            out[t] = to_usd(px, currency_of(t), rates)
    return out


@st.cache_data(ttl=240)
def paper_cash() -> float:
    # Sur le cloud: lit la table paper_account synchronisee (pas de DDL).
    acct = read_table_raw("paper_account")
    if not acct.empty and "cash" in acct.columns:
        return float(acct["cash"].iloc[0])
    try:  # repli local
        from atlas.execution.paper import PaperBroker
        return PaperBroker().get_cash()
    except Exception:
        return 0.0


@st.cache_data(ttl=600)
def company_names(tickers: tuple) -> dict:
    from atlas.data.names import get_company_names
    return get_company_names(tickers)


def style_fig(fig, height: int = 380):
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_DIM),
        margin=dict(l=10, r=10, t=45, b=10),
        title_font=dict(color="#e6edf3", size=15),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, linecolor=BORDER)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=BORDER)
    # Sans texte de titre, Plotly affiche "undefined" des qu'une police de
    # titre est definie: on force une chaine vide pour les graphes sans titre.
    if fig.layout.title.text is None:
        fig.update_layout(title_text="")
    return fig


SCORE_COL = lambda label: st.column_config.ProgressColumn(
    label, min_value=0, max_value=100, format="%.1f")
MONEY = lambda label: st.column_config.NumberColumn(label, format="%.2f")

tab_watch, tab_signals, tab_pf, tab_sectors, tab_bt, tab_risk = st.tabs(
    ["Watchlist", "Signaux", "Portefeuille", "Secteurs", "Backtests", "Risque"]
)

scores = load("scores")
latest_scores = pd.DataFrame()
if not scores.empty:
    latest_scores = scores[scores["as_of_date"] == scores["as_of_date"].max()]

with tab_watch:
    st.subheader("Watchlist dynamique (scores composites)")
    if latest_scores.empty:
        st.info("Aucun score. Lancer: python -m atlas.pipelines.daily_scan --limit 100")
    else:
        st.caption(f"Date du scan: {scores['as_of_date'].max()}  |  "
                   f"{len(latest_scores)} titres analyses")
        min_score = st.slider("Score composite minimum", 0, 100, 70)
        view = latest_scores[latest_scores["composite"] >= min_score].copy()
        names = company_names(tuple(view["ticker"]))
        view.insert(1, "societe", view["ticker"].map(names))
        # Remplacer les valeurs manquantes (sinon le tableau affiche "undefined")
        view["societe"] = view["societe"].fillna(view["ticker"])
        for _c in ("sector_name", "country"):
            if _c in view.columns:
                view[_c] = view[_c].fillna("n/d")
        st.dataframe(
            view.sort_values("composite", ascending=False)[
                ["ticker", "societe", "composite", "fundamental", "technical",
                 "sector", "sentiment", "sector_name", "country"]
            ],
            use_container_width=True, hide_index=True, height=520,
            column_config={
                "ticker": st.column_config.TextColumn("Titre"),
                "societe": st.column_config.TextColumn("Societe", width="medium"),
                "composite": SCORE_COL("Composite"),
                "fundamental": SCORE_COL("Fondamental"),
                "technical": SCORE_COL("Technique"),
                "sector": SCORE_COL("Secteur"),
                "sentiment": st.column_config.NumberColumn("Sentiment", format="%.0f"),
                "sector_name": st.column_config.TextColumn("Industrie"),
                "country": st.column_config.TextColumn("Pays"),
            },
        )

with tab_signals:
    st.subheader("Signaux")
    signals = load("signals")
    if signals.empty:
        st.info("Aucun signal genere pour le moment.")
    else:
        st.dataframe(
            signals.sort_values("created_at", ascending=False)[
                ["as_of_date", "ticker", "side", "entry", "stop",
                 "tp1", "tp2", "tp3", "composite_score", "confidence", "status"]
            ],
            use_container_width=True, hide_index=True,
            column_config={
                "as_of_date": st.column_config.TextColumn("Date"),
                "ticker": st.column_config.TextColumn("Titre"),
                "side": st.column_config.TextColumn("Sens"),
                "entry": MONEY("Entree"), "stop": MONEY("Stop"),
                "tp1": MONEY("TP1"), "tp2": MONEY("TP2"), "tp3": MONEY("TP3"),
                "composite_score": SCORE_COL("Score"),
                "confidence": st.column_config.TextColumn("Confiance"),
                "status": st.column_config.TextColumn("Statut"),
            },
        )

with tab_pf:
    st.subheader("Portefeuille (paper)")
    positions = load("positions")
    trades = load("trades")
    try:
        equity_hist = load("paper_equity")
    except Exception:
        equity_hist = pd.DataFrame()
    col1, col2, col3, col4, col5 = st.columns(5)
    last_equity = float(equity_hist["equity"].iloc[-1]) if not equity_hist.empty else None
    delta = f"{last_equity - 100_000:+,.0f}" if last_equity else None
    col1.metric("Equity (USD)", f"{last_equity:,.0f}" if last_equity else "n/a",
                delta=delta)
    col2.metric("Positions ouvertes", len(positions))
    realized = float(trades["pnl"].sum()) if not trades.empty else 0.0
    col3.metric("PnL realise", f"{realized:,.0f}",
                delta=f"{realized:+,.0f}" if realized else None)
    n_closed = len(trades)
    col4.metric("Trades clotures", n_closed)
    # Taux de reussite = part des trades clotures gagnants (pnl > 0)
    n_wins = int((trades["pnl"] > 0).sum()) if not trades.empty else 0
    win_rate = (100 * n_wins / n_closed) if n_closed else 0.0
    col5.metric("Taux de reussite", f"{win_rate:.0f}%" if n_closed else "n/a",
                delta=f"{n_wins}/{n_closed} gagnants" if n_closed else None,
                delta_color="off")
    st.caption("Valeurs ci-dessus: figees au dernier run nocturne (23h)."
               + ("" if n_closed >= 20 else
                  f" Taux de reussite peu significatif ({n_closed} trades, "
                  "fiable a partir de ~20)."))

    # --- Valorisation en direct (rafraichissement auto, affichage seulement) ---
    st.divider()
    st.markdown("#### Valorisation en direct")

    @st.fragment(run_every="300s")
    def live_valuation():
        pos = read_table_raw("positions")  # lecture fraiche a chaque cycle
        if pos.empty:
            st.info("Aucune position ouverte a valoriser.")
            return
        bcol, _ = st.columns([1, 4])
        if bcol.button("Rafraichir maintenant", key="refresh_live",
                       help="Force la recuperation immediate des derniers cours "
                       "(sans attendre le rafraichissement auto de 5 min)"):
            live_prices_usd.clear()
            paper_cash.clear()
        with st.spinner("Recuperation des cours..."):
            prices = live_prices_usd(tuple(pos["ticker"]))
        names = company_names(tuple(pos["ticker"]))
        cash = paper_cash()
        rows, mkt_value = [], 0.0
        for _, p in pos.iterrows():
            fx = float(p.get("fx_entry") or 1.0)
            entry_usd = float(p["avg_price"]) * fx
            last_usd = prices.get(p["ticker"], entry_usd)
            qty = float(p["qty"])
            value = qty * last_usd                    # valeur actuelle en USD
            mkt_value += value
            pnl = (last_usd - entry_usd) * qty
            # PnL assure: gain verrouille si le stop effectif (stop ou trailing,
            # le plus haut) est passe AU-DESSUS du prix d'entree. Sinon vide.
            eff_stop_usd = max(float(p.get("stop") or 0),
                               float(p.get("trailing_stop") or 0)) * fx
            secured = (eff_stop_usd - entry_usd) * qty
            rows.append({
                "Titre": p["ticker"], "Societe": names.get(p["ticker"], p["ticker"]),
                "Qte": qty,
                "Prix entree (USD)": round(entry_usd, 2),
                "Cours actuel (USD)": round(last_usd, 2),
                "Valeur (USD)": round(value, 2),
                "P&L latent (USD)": round(pnl, 2),
                "PnL assure (USD)": round(secured, 2) if eff_stop_usd > entry_usd else None,
                "P&L %": round((last_usd / entry_usd - 1) * 100, 2) if entry_usd else 0.0,
            })
        live_equity = cash + mkt_value
        # Poids de chaque position en % du portefeuille total (cash inclus)
        for r in rows:
            r["Poids %"] = round(100 * r["Valeur (USD)"] / live_equity, 1) if live_equity else 0.0
        latent = sum(r["P&L latent (USD)"] for r in rows)
        is_open = us_market_open()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Equity en direct (USD)", f"{live_equity:,.0f}",
                  delta=f"{live_equity - 100_000:+,.0f}")
        c2.metric("Investi (USD)", f"{mkt_value:,.0f}",
                  delta=f"{100 * mkt_value / live_equity:.0f}% du portefeuille"
                  if live_equity else None, delta_color="off")
        c3.metric("P&L latent (USD)", f"{latent:+,.0f}")
        c4.metric("Marche US", "ouvert" if is_open else "ferme")
        col_order = ["Titre", "Societe", "Qte", "Prix entree (USD)",
                     "Cours actuel (USD)", "Valeur (USD)", "Poids %",
                     "P&L latent (USD)", "PnL assure (USD)", "P&L %"]
        st.dataframe(
            pd.DataFrame(rows)[col_order], use_container_width=True, hide_index=True,
            column_config={
                "Societe": st.column_config.TextColumn("Societe", width="medium"),
                "Qte": st.column_config.NumberColumn(format="%.0f"),
                "Valeur (USD)": st.column_config.NumberColumn(format="$%.0f"),
                "Poids %": st.column_config.ProgressColumn(
                    "Poids %", min_value=0, max_value=10, format="%.1f%%"),
                "P&L latent (USD)": st.column_config.NumberColumn(format="%.2f"),
                "PnL assure (USD)": st.column_config.NumberColumn(
                    "PnL assure (USD)", format="%.2f",
                    help="Gain verrouille par le trailing stop: ce que la "
                    "position rapporte au minimum meme si elle redescend "
                    "jusqu'au stop. Vide tant que le stop est sous le prix "
                    "d'entree."),
                "P&L %": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        n_secured = sum(1 for r in rows if r["PnL assure (USD)"] is not None)
        total_secured = sum(r["PnL assure (USD)"] or 0 for r in rows)
        if n_secured:
            st.caption(f"PnL assure: {n_secured} position(s) ont verrouille un "
                       f"profit via leur trailing stop (total {total_secured:+,.0f} "
                       "USD garanti meme en cas de repli).")
        cash_pct = 100 * cash / live_equity if live_equity else 0.0
        tail = ("" if is_open
                else "  Marche ferme: les cours ne bougeront qu'a la prochaine seance.")
        st.caption(f"Cash disponible: {cash:,.0f} USD ({cash_pct:.0f}% du portefeuille). "
                   f"Cours differes (~15 min), actualise a "
                   f"{now_paris().strftime('%H:%M:%S')} (Paris), "
                   f"auto toutes les 5 min.{tail}")

    live_valuation()

    st.divider()
    if not equity_hist.empty and len(equity_hist) > 1:
        eq = equity_hist.set_index("date")["equity"]
        fig_eq = go.Figure(go.Scatter(
            x=eq.index, y=eq.values, name="equity", mode="lines",
            line=dict(color=EMERALD, width=2.2),
            fill="tozeroy", fillcolor="rgba(79,209,165,0.07)"))
        fig_eq.update_yaxes(range=[min(eq.min() * 0.995, 99_000),
                                   max(eq.max() * 1.005, 101_000)])
        st.plotly_chart(style_fig(fig_eq, 300), use_container_width=True)
    elif not equity_hist.empty:
        st.caption("La courbe de capital apparaitra a partir du deuxieme "
                   "jour de donnees.")
    if not positions.empty:
        cols = [c for c in ["ticker", "qty", "avg_price", "currency",
                            "stop", "trailing_stop", "opened_at"]
                if c in positions.columns]
        view = positions[cols].copy()
        if "opened_at" in view.columns:
            view["opened_at"] = view["opened_at"].astype(str).str[:10]
        if "currency" in view.columns:
            view["currency"] = view["currency"].fillna("USD")
        st.dataframe(
            clean_nan(view), use_container_width=True, hide_index=True,
            column_config={
                "ticker": st.column_config.TextColumn("Titre"),
                "qty": st.column_config.NumberColumn("Quantite", format="%.0f"),
                "avg_price": MONEY("Prix moyen"),
                "currency": st.column_config.TextColumn("Devise"),
                "stop": MONEY("Stop"),
                "trailing_stop": MONEY("Stop suiveur"),
                "opened_at": st.column_config.TextColumn("Ouverte le"),
            },
        )
    if not trades.empty:
        st.subheader("Journal des trades")
        tcols = [c for c in ["ticker", "qty", "entry_price", "exit_price",
                             "pnl", "exit_reason", "closed_at"]
                 if c in trades.columns]
        tview = trades.sort_values("closed_at", ascending=False)[tcols].copy()
        if "closed_at" in tview.columns:
            tview["closed_at"] = tview["closed_at"].astype(str).str[:10]
        st.dataframe(
            clean_nan(tview), use_container_width=True, hide_index=True,
            column_config={
                "ticker": st.column_config.TextColumn("Titre"),
                "qty": st.column_config.NumberColumn("Quantite", format="%.0f"),
                "entry_price": MONEY("Prix entree"),
                "exit_price": MONEY("Prix sortie"),
                "pnl": st.column_config.NumberColumn("P&L (USD)", format="%.2f"),
                "exit_reason": st.column_config.TextColumn("Motif sortie"),
                "closed_at": st.column_config.TextColumn("Cloture le"),
            },
        )

with tab_sectors:
    st.subheader("Heatmap sectorielle")
    if latest_scores.empty or "sector_name" not in latest_scores.columns:
        st.info("Pas de donnees sectorielles.")
    else:
        st.caption("Taille = nombre de titres dans l'univers. "
                   "Couleur = score composite moyen des titres du secteur.")
        agg = (latest_scores.dropna(subset=["sector_name"])
               .groupby("sector_name")
               .agg(score=("composite", "mean"), n=("ticker", "count"))
               .reset_index())
        # px.Constant nomme la racine du treemap (sinon Plotly l'affiche
        # "undefined"). On exclut aussi tout secteur vide/inconnu.
        agg = agg[agg["sector_name"].astype(str).str.strip().ne("")]
        fig = px.treemap(agg, path=[px.Constant("Tous secteurs"), "sector_name"],
                         values="n", color="score",
                         color_continuous_scale="RdYlGn", range_color=[30, 90])
        fig.update_traces(marker=dict(cornerradius=6),
                          textfont=dict(size=14))
        st.plotly_chart(style_fig(fig, 480), use_container_width=True)

with tab_bt:
    st.subheader("Backtests")
    bts = load("backtests")
    if bts.empty:
        st.info("Lancer: python -m atlas.pipelines.run_backtest --limit 100 --validate")
    else:
        names = bts.apply(lambda r: f"#{r['id']} {r['name']} ({r['created_at'][:10]})", axis=1)
        choice = st.selectbox("Backtest", names)
        row = bts.iloc[list(names).index(choice)]
        metrics = json.loads(row["metrics"]) if row["metrics"] else {}
        flat = metrics.get("metrics", metrics)
        shown = [("CAGR", "cagr", "{:.1%}"), ("Sharpe", "sharpe", "{:.2f}"),
                 ("Max DD", "max_drawdown", "{:.1%}"),
                 ("Alpha", "alpha", "{:.1%}"), ("Beta", "beta", "{:.2f}")]
        cols = st.columns(len(shown))
        for col, (label, key, fmt) in zip(cols, shown):
            v = flat.get(key)
            col.metric(label, fmt.format(v) if isinstance(v, (int, float)) else "n/a")
        with st.expander("Toutes les metriques et validations"):
            st.json(metrics)
        eq = pd.Series(json.loads(row["equity_curve"]))
        eq.index = pd.to_datetime(eq.index)
        fig = go.Figure(go.Scatter(x=eq.index, y=eq.values, name="equity",
                                   line=dict(color=AMBER, width=2)))
        fig.update_layout(title="Courbe de capital")
        st.plotly_chart(style_fig(fig, 380), use_container_width=True)
        dd = (1 - eq / eq.cummax()) * -100
        fig2 = go.Figure(go.Scatter(
            x=eq.index, y=dd.values, fill="tozeroy", name="drawdown",
            line=dict(color=CRIMSON, width=1.5),
            fillcolor="rgba(227,93,106,0.15)"))
        fig2.update_layout(title="Drawdown (%)")
        st.plotly_chart(style_fig(fig2, 240), use_container_width=True)

with tab_risk:
    st.subheader("Risque en temps reel")
    positions = load("positions")
    if positions.empty:
        st.info("Aucune position ouverte, rien a surveiller.")
    else:
        if not latest_scores.empty:
            merged = positions.merge(
                latest_scores[["ticker", "sector_name", "country"]],
                on="ticker", how="left")
            fx = merged.get("fx_entry", pd.Series(1.0, index=merged.index)).fillna(1.0)
            value = merged["qty"] * merged["avg_price"] * fx
            c1, c2 = st.columns(2)
            sector_w = value.groupby(merged["sector_name"].fillna("Unknown")).sum()
            fig = px.pie(values=sector_w.values, names=sector_w.index,
                         title="Exposition sectorielle", hole=0.45,
                         color_discrete_sequence=PIE_PALETTE)
            c1.plotly_chart(style_fig(fig, 360), use_container_width=True)
            country_w = value.groupby(merged["country"].fillna("Unknown")).sum()
            fig2 = px.pie(values=country_w.values, names=country_w.index,
                          title="Exposition geographique", hole=0.45,
                          color_discrete_sequence=PIE_PALETTE[::-1])
            c2.plotly_chart(style_fig(fig2, 360), use_container_width=True)
        rcols = [c for c in ["ticker", "qty", "avg_price", "currency",
                             "stop", "trailing_stop"] if c in positions.columns]
        st.dataframe(clean_nan(positions[rcols].copy()),
                     use_container_width=True, hide_index=True,
                     column_config={
                         "ticker": st.column_config.TextColumn("Titre"),
                         "qty": st.column_config.NumberColumn("Quantite", format="%.0f"),
                         "avg_price": MONEY("Prix moyen"),
                         "currency": st.column_config.TextColumn("Devise"),
                         "stop": MONEY("Stop"),
                         "trailing_stop": MONEY("Stop suiveur"),
                     })
