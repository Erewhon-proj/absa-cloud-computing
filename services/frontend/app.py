"""Frontend Streamlit (Tier 1).

Due schede:
  - Invia recensione: POST all'API, poi polling fino al risultato.
  - Dashboard: sentiment aggregato per aspetto (GET /stats) + ultime
    recensioni con i loro aspetti (GET /reviews).
"""
import os
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://api:8000")

# Banche note (stesse di scripts/load_test.py); "Altra..." abilita input libero.
BANKS = ["Fineco", "Revolut", "BBVA", "Intesa", "Unicredit", "N26"]

# Colori fissi per i tre sentiment: gli stessi in chip, grafici e legenda.
SENTIMENT_COLORS = {
    "Positive": "#3FB68B",
    "Negative": "#E4604E",
    "Neutral": "#8A93A6",
}

st.set_page_config(page_title="ABSA Banking", page_icon="🏦", layout="wide")

# Ritocchi estetici: chip colorate per gli aspetti e header piu' compatto.
st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; }
      h1 { letter-spacing: -0.02em; }
      .chip {
        display: inline-block;
        padding: 0.25rem 0.7rem;
        margin: 0.15rem 0.3rem 0.15rem 0;
        border-radius: 999px;
        font-size: 0.85rem;
        font-weight: 600;
        color: #fff;
      }
      .chip small { opacity: 0.75; font-weight: 400; }
      .review-meta { color: #8A93A6; font-size: 0.85rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏦 ABSA Banking")
st.caption(
    "Aspect-Based Sentiment Analysis di recensioni bancarie — "
    f"API: {API_URL}"
)


def sentiment_chip(aspect: str, sentiment: str, confidence: float | None) -> str:
    """HTML di una chip colorata 'aspetto · sentiment (confidenza)'."""
    color = SENTIMENT_COLORS.get(sentiment, "#8A93A6")
    conf = f" <small>{confidence:.0%}</small>" if confidence is not None else ""
    return f'<span class="chip" style="background:{color}">{aspect}{conf}</span>'


def chips_row(aspects: list[dict]) -> str:
    return "".join(
        sentiment_chip(a["aspect"], a["sentiment"], a.get("confidence"))
        for a in aspects
    )


def fetch_json(path: str, params: dict | None = None):
    """GET all'API; None se non raggiungibile (l'errore lo mostra il chiamante)."""
    try:
        return requests.get(f"{API_URL}{path}", params=params, timeout=10).json()
    except requests.RequestException as exc:
        st.error(f"API non raggiungibile: {exc}")
        return None


tab_send, tab_dash = st.tabs(["✍️ Invia recensione", "📊 Dashboard"])


# ---------------------------------------------------------------- invio
with tab_send:
    col_form, col_result = st.columns([1, 1], gap="large")

    with col_form:
        # st.form: si invia col pulsante o con Ctrl+Enter dalla textarea.
        with st.form("review_form"):
            bank_choice = st.selectbox("Banca", BANKS + ["Altra..."])
            other_bank = ""
            if bank_choice == "Altra...":
                other_bank = st.text_input("Nome banca")
            text = st.text_area(
                "Recensione",
                height=150,
                placeholder="Es. L'app e' comoda ma l'assistenza e' lentissima...",
            )
            submitted = st.form_submit_button("Invia recensione", type="primary")
            st.caption("Invia con il pulsante o con Ctrl+Enter (⌘+Enter su Mac).")

    with col_result:
        if submitted:
            bank = other_bank.strip() if bank_choice == "Altra..." else bank_choice
            if not text.strip():
                st.warning("Inserisci una recensione.")
            else:
                try:
                    resp = requests.post(
                        f"{API_URL}/reviews",
                        json={"text": text, "bank": bank or None},
                        timeout=10,
                    )
                except requests.RequestException as exc:
                    st.error(f"API non raggiungibile: {exc}")
                    resp = None

                if resp is not None and resp.status_code == 202:
                    review_id = resp.json()["id"]
                    result = None
                    with st.status("In coda, elaborazione in corso...", expanded=False) as status:
                        for _ in range(30):
                            time.sleep(1)
                            try:
                                res = requests.get(
                                    f"{API_URL}/reviews/{review_id}", timeout=10
                                ).json()
                            except requests.RequestException:
                                continue
                            if res["status"] == "done":
                                result = res
                                status.update(label="Analisi completata", state="complete")
                                break
                            if res["status"] == "error":
                                status.update(label="Errore in elaborazione", state="error")
                                break
                        else:
                            status.update(label="Timeout: riprova piu' tardi", state="error")
                    if result:
                        st.subheader("Aspetti rilevati")
                        if result["aspects"]:
                            st.markdown(chips_row(result["aspects"]), unsafe_allow_html=True)
                        else:
                            st.info("Nessun aspetto rilevato in questa recensione.")
                elif resp is not None:
                    st.error(f"Errore API: {resp.status_code}")
        else:
            st.info(
                "Scrivi una recensione: l'API la accoda (202 Accepted) e il worker "
                "estrae gli aspetti e il loro sentiment in modo asincrono."
            )


# ---------------------------------------------------------------- dashboard
with tab_dash:
    col_bank, col_aspects, col_btn = st.columns([1, 2, 1], vertical_alignment="bottom")
    with col_bank:
        bank_filter = st.selectbox("Banca", ["Tutte"] + BANKS)
    with col_btn:
        st.button("🔄 Aggiorna", use_container_width=True)

    params = {} if bank_filter == "Tutte" else {"bank": bank_filter}
    stats = fetch_json("/stats", params)
    data = stats["data"] if stats else []

    if not data:
        st.info("Nessun dato ancora. Invia qualche recensione dalla prima scheda.")
    else:
        df = pd.DataFrame(data)

        with col_aspects:
            all_aspects = sorted(df["aspect"].unique())
            chosen = st.multiselect("Aspetti (vuoto = tutti)", all_aspects)
        if chosen:
            df = df[df["aspect"].isin(chosen)]

        # metriche di sintesi
        total = int(df["count"].sum())
        positive = int(df.loc[df["sentiment"] == "Positive", "count"].sum())
        negatives = (
            df[df["sentiment"] == "Negative"].groupby("aspect")["count"].sum()
        )
        worst = negatives.idxmax() if not negatives.empty else "—"
        m1, m2, m3 = st.columns(3)
        m1.metric("Menzioni totali", total)
        m2.metric("Positive", f"{positive / total:.0%}" if total else "—")
        m3.metric("Aspetto piu' criticato", worst)

        st.divider()
        col_bar, col_pie = st.columns([2, 1])
        with col_bar:
            st.subheader("Sentiment per aspetto")
            fig = px.bar(
                df,
                x="count",
                y="aspect",
                color="sentiment",
                orientation="h",
                color_discrete_map=SENTIMENT_COLORS,
                labels={"count": "menzioni", "aspect": "", "sentiment": ""},
            )
            fig.update_layout(legend_orientation="h", margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        with col_pie:
            st.subheader("Distribuzione")
            totals = df.groupby("sentiment", as_index=False)["count"].sum()
            fig = px.pie(
                totals,
                names="sentiment",
                values="count",
                hole=0.55,
                color="sentiment",
                color_discrete_map=SENTIMENT_COLORS,
            )
            fig.update_layout(showlegend=False, margin=dict(t=10, b=10))
            fig.update_traces(textinfo="label+percent")
            st.plotly_chart(fig, use_container_width=True)

        st.divider()
        st.subheader("Ultime recensioni")
        reviews = fetch_json("/reviews", {**params, "limit": 20}) or []
        for r in reviews:
            with st.container(border=True):
                bank_label = r["bank"] or "banca non indicata"
                date = r["created_at"][:16].replace("T", " ")
                st.markdown(
                    f'<div class="review-meta">🏦 <b>{bank_label}</b> · {date}</div>',
                    unsafe_allow_html=True,
                )
                st.write(r["text"])
                if r["aspects"]:
                    st.markdown(chips_row(r["aspects"]), unsafe_allow_html=True)
                elif r["status"] != "done":
                    st.caption(f"Stato: {r['status']}")
