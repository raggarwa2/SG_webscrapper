"""Google Trends signals (SG) -- trends_interest / trends_related in trends_data_sg.db.

Search-demand-over-time per brand term. Values are Google's normalized 0-100
interest index (not search volume) and are only comparable within a batch, so
the "vs. 'contact lens'" view divides each term by its own batch's anchor.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

import ebi
from sg_common import BRAND_COLORS, TRENDS_DB, normalize_brand, read_table

ANCHOR = "contact lens"


def load() -> pd.DataFrame:
    df = read_table(
        TRENDS_DB,
        "SELECT term, brand, date, value, is_partial, batch_key, pulled_at FROM trends_interest",
    )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["brand"] = df["brand"].map(normalize_brand)
    return df


def _anchor_scaled(df: pd.DataFrame) -> pd.DataFrame:
    anchor = (
        df[df["term"] == ANCHOR][["batch_key", "date", "value"]]
        .rename(columns={"value": "anchor"})
    )
    out = df[df["term"] != ANCHOR].merge(anchor, on=["batch_key", "date"], how="left")
    out = out[out["anchor"] > 0].copy()
    out["value"] = out["value"] / out["anchor"] * 100
    return out


def render():
    ebi.page_header(
        "Is search demand for our brands growing, and how does it compare with competitors?",
        ["dir"],
        "Google Trends, Singapore, weekly, last 5 years. Normalized 0-100 interest index, not search volume.",
    )
    df = load()
    if df.empty:
        st.info("No Google Trends data loaded (run Scripts/google_trends_sg.py).")
        return

    complete = df[df["is_partial"] == 0]
    terms = complete[complete["term"] != ANCHOR]
    nonzero_weeks = terms[terms["value"] > 0].groupby("term").size()
    charted = sorted(t for t in terms["term"].unique() if nonzero_weeks.get(t, 0) >= ebi.MIN_N)
    thin = sorted(set(terms["term"].unique()) - set(charted))

    view = st.radio(
        "View",
        ["Index (0-100, within batch)", "Relative to 'contact lens' searches"],
        horizontal=True,
        key="trends_view",
    )
    plot_df = _anchor_scaled(complete) if view.startswith("Relative") else terms
    plot_df = plot_df[plot_df["term"].isin(charted)]
    if plot_df.empty:
        st.info("No term has enough non-zero weeks to chart.")
        return

    # 4-week rolling mean smooths the weekly noise of low-volume terms.
    plot_df = plot_df.sort_values("date").copy()
    plot_df["smoothed"] = plot_df.groupby("term")["value"].transform(lambda s: s.rolling(4, min_periods=1).mean())
    fig = px.line(
        plot_df, x="date", y="smoothed", color="brand", line_dash="term",
        color_discrete_map=BRAND_COLORS,
        labels={"smoothed": "Interest (4-week avg)", "date": "", "brand": "Brand", "term": "Search term"},
    )
    fig.update_layout(legend_title_text="", margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, width="stretch")

    n_weeks = int(plot_df["date"].nunique())
    st.caption(
        f"n = {n_weeks} weekly points per term ({plot_df['date'].min():%d %b %Y} to {plot_df['date'].max():%d %b %Y}); "
        "latest incomplete week excluded."
    )
    if thin:
        st.caption(
            f"Not charted (under {ebi.MIN_N} weeks with any searches, too little volume): " + ", ".join(thin) + "."
        )

    ebi.limits([
        "Google Trends shows relative interest, not number of searches; terms are only comparable within one batch "
        "(use the 'relative to contact lens' view across batches).",
        "Branded terms in Singapore are low volume, so weekly values are noisy and often zero.",
        "Search interest is not purchase or registration; it needs internal data to link to MyACUVUE sign-ups.",
    ])
    st.caption(f"Latest pull: {df['pulled_at'].max()[:10]}")


if __name__ == "__main__":
    render()
