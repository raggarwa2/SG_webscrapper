"""Google Trends signals (SG) -- trends_interest / trends_related in trends_data_sg.db.

Search-demand-over-time per brand term. Values are Google's normalized 0-100
interest index (not search volume) and are only comparable within a batch, so
the charts use each term's value as a % of the "contact lens" anchor in its own
batch ("share of category interest"). That puts every term on one axis.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ebi
import ui
from sg_common import BRAND_COLORS, TRENDS_DB, normalize_brand, read_table

ANCHOR = "contact lens"
MUTED = "#999999"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


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


def _relative(df: pd.DataFrame) -> pd.DataFrame:
    """Each term as a % of its own batch's 'contact lens' value, same week."""
    anchor = (
        df[df["term"] == ANCHOR][["batch_key", "date", "value"]].rename(columns={"value": "anchor"})
    )
    out = df[df["term"] != ANCHOR].merge(anchor, on=["batch_key", "date"], how="left")
    out = out[out["anchor"] > 0].copy()
    out["share"] = out["value"] / out["anchor"] * 100
    return out


def _like_for_like(s: pd.DataFrame, col: str, year: int, last: pd.Timestamp) -> float:
    """Mean of col for `year`, Jan 1 up to the same day-of-year as `last`."""
    m = (s["date"].dt.year == year) & (s["date"].dt.dayofyear <= last.dayofyear)
    return float(s.loc[m, col].mean()) if m.any() else float("nan")


def _pct_change(new: float, old: float):
    if pd.isna(new) or pd.isna(old) or old == 0:
        return None
    return (new / old - 1) * 100


def _style(fig, height=360):
    fig.update_layout(
        height=height, margin=dict(l=0, r=0, t=10, b=0), hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0, title_text=""),
        xaxis=dict(showgrid=False, title=""), yaxis=dict(gridcolor="rgba(148,163,184,.25)", zeroline=False),
    )
    return fig


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
    rel = _relative(complete)
    nonzero = rel[rel["value"] > 0].groupby("term").size()
    charted = sorted(t for t in rel["term"].unique() if nonzero.get(t, 0) >= ebi.MIN_N)
    thin = sorted(set(rel["term"].unique()) - set(charted))
    if "Acuvue" not in charted:
        st.info("Not enough Acuvue search data to chart.")
        return

    last = complete["date"].max()
    y1, y0 = last.year, last.year - 1
    brand_terms = {"Acuvue": "Acuvue", "Olens": "Olens"}
    stats = {}
    for name, term in brand_terms.items():
        s = rel[rel["term"] == term]
        stats[name] = {
            "idx_now": _like_for_like(s, "value", y1, last),
            "idx_prev": _like_for_like(s, "value", y0, last),
            "share_now": _like_for_like(s, "share", y1, last),
            "share_prev": _like_for_like(s, "share", y0, last),
        }
    cat = complete[complete["term"] == ANCHOR].drop_duplicates("date")
    cat_chg = _pct_change(_like_for_like(cat, "value", y1, last), _like_for_like(cat, "value", y0, last))
    ac = rel[rel["term"] == "Acuvue"]
    peak = ac.loc[ac["value"].idxmax()]

    window = f"Jan to {last:%d %b}"
    # ---- headline tiles ---------------------------------------------------
    a, o = stats["Acuvue"], stats["Olens"]
    c1, c2, c3, c4 = st.columns(4)
    chg = _pct_change(a["idx_now"], a["idx_prev"])
    c1.metric(f"Acuvue interest, {y1}", f"{a['idx_now']:.0f}", f"{chg:+.0f}% vs {y0}" if chg is not None else None,
              help=f"Average 0-100 index, {window} each year.")
    c2.metric("Acuvue share of category", f"{a['share_now']:.0f}%", f"{a['share_now'] - a['share_prev']:+.0f} pts vs {y0}",
              help="Acuvue's index as a % of the 'contact lens' index in the same batch and week.")
    chg_o = _pct_change(o["idx_now"], o["idx_prev"])
    c3.metric(f"Olens interest, {y1}", f"{o['idx_now']:.0f}", f"{chg_o:+.0f}% vs {y0}" if chg_o is not None else None,
              help=f"Average 0-100 index, {window} each year.")
    c4.metric("Acuvue peak week", f"{peak['date']:%d %b %Y}", f"index {peak['value']:.0f}", delta_color="off")

    # ---- what it says -----------------------------------------------------
    lines = []
    if chg is not None:
        cat_txt = f" while the whole category moved {cat_chg:+.0f}%" if cat_chg is not None else ""
        lines.append(
            f"<b>Acuvue searches are {'up' if chg >= 0 else 'down'} {abs(chg):.0f}%</b> on {y0} "
            f"({window}){cat_txt}, so its share of category interest went from "
            f"<b>{a['share_prev']:.0f}%</b> to <b>{a['share_now']:.0f}%</b>."
        )
    if chg_o is not None:
        lines.append(f"<b>Olens is {'up' if chg_o >= 0 else 'down'} {abs(chg_o):.0f}%</b> over the same window.")
    for t in lines:
        ui.insight(t)

    # ---- chart 1: share of category over time ------------------------------
    ui.subheader("Share of category search interest", "Each brand's index as a % of 'contact lens' searches, 4-week average", "Trend")
    fig = go.Figure()
    for name, term in brand_terms.items():
        s = rel[rel["term"] == term].sort_values("date")
        s = s.assign(smooth=s["share"].rolling(4, min_periods=1).mean())
        fig.add_scatter(
            x=s["date"], y=s["smooth"], name=name, mode="lines",
            line=dict(color=BRAND_COLORS.get(name, MUTED), width=2),
            hovertemplate="%{y:.0f}% of category<extra>" + name + "</extra>",
        )
    pk = ac.sort_values("date").assign(smooth=lambda d: d["share"].rolling(4, min_periods=1).mean())
    pk = pk.loc[pk["smooth"].idxmax()]
    fig.add_scatter(
        x=[pk["date"]], y=[pk["smooth"]], mode="markers+text", showlegend=False,
        marker=dict(color=BRAND_COLORS["Acuvue"], size=10, line=dict(color="white", width=2)),
        text=[f"Acuvue peak, {pk['date']:%b %Y}"], textposition="top center", hoverinfo="skip",
    )
    fig.update_yaxes(ticksuffix="%")
    st.plotly_chart(_style(fig), width="stretch")
    st.caption(f"Google Trends, Singapore · {rel['date'].min():%b %Y} – {rel['date'].max():%b %Y} · weekly")

    # ---- chart 2: like-for-like by year -----------------------------------
    ui.subheader("Year on year, like for like", f"Average share of category interest, {window} of each year", "Growth")
    years = [y for y in range(last.year - 4, y1 + 1)]
    fig2 = go.Figure()
    for name, term in brand_terms.items():
        s = rel[rel["term"] == term]
        vals = [_like_for_like(s, "share", y, last) for y in years]
        fig2.add_bar(
            x=[str(y) for y in years], y=vals, name=name, marker_color=BRAND_COLORS.get(name, MUTED),
            hovertemplate="%{y:.1f}% of category<extra>" + name + "</extra>",
        )
    fig2.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08)
    fig2.update_yaxes(ticksuffix="%")
    st.plotly_chart(_style(fig2, 320), width="stretch")
    st.caption(f"Google Trends, Singapore · {rel['date'].min():%b %Y} – {rel['date'].max():%b %Y} · weekly")

    # ---- chart 3: seasonality heatmap -------------------------------------
    ui.subheader("When do people search?", "Average index by month and year (0-100, darker = more interest)", "Seasonality")
    pick = st.selectbox("Term", [t for t in ["Acuvue", "Olens", "Acuvue Oasys"] if t in charted] or charted, key="trends_heat_term")
    h = rel[rel["term"] == pick].copy()
    h["year"], h["month"] = h["date"].dt.year, h["date"].dt.month
    grid = h.pivot_table(index="year", columns="month", values="value", aggfunc="mean").reindex(columns=range(1, 13))
    color = BRAND_COLORS.get(normalize_brand("MyACUVUE" if "Acuvue" in pick else pick), "#178197")
    fig3 = go.Figure(go.Heatmap(
        z=grid.values, x=MONTHS, y=[str(y) for y in grid.index], colorscale=[[0, "#F8F8F8"], [1, color]],
        xgap=2, ygap=2, colorbar=dict(title="Index", thickness=10),
        hovertemplate="%{y} %{x}: %{z:.0f}<extra></extra>",
    ))
    fig3.update_yaxes(autorange="reversed", showgrid=False)
    fig3.update_xaxes(showgrid=False)
    fig3.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig3, width="stretch")
    st.caption(f"Google Trends, Singapore · {rel['date'].min():%b %Y} – {rel['date'].max():%b %Y} · weekly")
    st.caption("Grey cells have no data (the series starts 26 Sep 2021 and ends in the latest complete week).")

    # ---- evidence, table, limits ------------------------------------------
    n_weeks = int(rel["date"].nunique())
    st.caption(
        f"n = {n_weeks} complete weekly points per term ({rel['date'].min():%d %b %Y} to {last:%d %b %Y}); "
        "latest incomplete week excluded."
    )
    if thin:
        st.caption(f"Not charted (under {ebi.MIN_N} weeks with any searches, too little volume): " + ", ".join(thin) + ".")
    with st.expander("Table view"):
        tbl = rel[rel["term"].isin(charted)].pivot_table(index="date", columns="term", values="value").sort_index(ascending=False)
        st.dataframe(tbl, width="stretch", height=300)
    ebi.limits([
        "Google Trends shows relative interest, not number of searches; 'share of category' is a ratio of index values, not market share.",
        "Branded terms in Singapore are low volume, so weekly values are noisy and often zero; competitor product lines are too sparse to chart.",
        "Search interest is not purchase or registration; it needs internal data to link to MyACUVUE sign-ups.",
    ])
    st.caption(f"Latest pull: {df['pulled_at'].max()[:10]}")


if __name__ == "__main__":
    render()
