"""
Coverage and method: what is behind every number, in one place.

Shows the channel passport (what each channel is, how much was collected and analysed, which brands it can compare), the
brand x channel coverage matrix and the label standard (one sentiment scale, eight themes in four decision groups, one
definition of a complaint). The story pages show only a small sample-size strip; the detail lives here.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import ebi
import theme_tags
import ui
import voice_data as vd

GROUP_OWNER = {
    "Product & look": ("Marketing, product", "Comfort and look proof, how the lens performs"),
    "Price, access & trust": ("Trade, brand protection", "Price, where to buy, genuine product"),
    "Guidance & service": ("ECP and retailer field team", "Fitting, handling, store service"),
    "Loyalty & app": ("CRM and WhatsApp", "Points, the app, registration, messages"),
}


def passport(d: pd.DataFrame) -> pd.DataFrame:
    """One row per channel and unit: lens, items collected, items analysed in the brand pool, brands it can compare, journey role."""
    raw = vd.raw_by_source()
    p = vd.pool(d)
    cov = vd.coverage_matrix(p)
    rows = []
    for r in raw.itertuples():
        brands = ""
        if r.lens == "consumer_voice" and r.source in cov.columns and r.pooled:
            ok = [b for b in charts.BRAND_ORDER if cov.loc[b, r.source] >= ebi.MIN_N]
            brands = ", ".join(ok) if ok else "none reaches 15"
        role = vd.CHANNEL_ROLE.get(r.source, ("", ""))
        unit = {"comment": "comments", "post": "posts", "review": "reviews", "thread": "threads", "ad": "ads"}.get(r.unit, r.unit)
        rows.append({"Lens": vd.LENS_LABEL.get(r.lens, r.lens), "Channel": r.source, "Unit": unit, "Collected": int(r.collected),
                     "In the brand pool": int(r.pooled or 0) if r.lens == "consumer_voice" else None,
                     "Giveaway entries removed": int(r.giveaway) if r.giveaway else None,
                     "Brands it can compare (15+ items)": brands, "Journey role": role[0]})
    out = pd.DataFrame(rows)
    order = list(vd.LENS_LABEL.values())
    out["_o"] = out["Lens"].map(lambda x: order.index(x) if x in order else 9)
    return out.sort_values(["_o", "Collected"], ascending=[True, False]).drop(columns="_o")


LENS_BAR = {"Consumer voice": "#178197", "Category voice": "#59A5D7", "Owned experience": "#7048E8", "Retail experience": "#B7791F",
            "Brand broadcast": "#9AA5B1"}


def passport_figure(pp: pd.DataFrame) -> go.Figure:
    """Items collected per channel (pale) and, for consumer voice, how many reached the brand pool (solid). Grouped by lens."""
    pp = pp.reset_index(drop=True)
    labels = [pp["Lens"].tolist(), [c if c.lower().endswith(u) else f"{c} {u}" for c, u in zip(pp["Channel"], pp["Unit"])]]
    fig = go.Figure()
    fig.add_bar(y=labels, x=pp["Collected"], orientation="h", name="Collected", marker_color="#D5DBE1", text=pp["Collected"].map("{:,}".format),
                textposition="outside", cliponaxis=False,
                customdata=pp[["Giveaway entries removed"]].fillna(0).astype(int).values,
                hovertemplate="%{y}: %{x:,} collected<br>%{customdata[0]} giveaway entries removed<extra></extra>")
    fig.add_bar(y=labels, x=pp["In the brand pool"], orientation="h", name="In the brand pool", marker_color="#178197",
                hovertemplate="%{y}: %{x:,} in the brand pool<extra></extra>")
    fig.update_layout(barmode="overlay", height=90 + 30 * len(pp), legend=dict(orientation="h", y=-0.08), xaxis_title="Items", margin=dict(l=10, r=40))
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(range=[0, float(pp["Collected"].max()) * 1.15])
    return fig


def coverage_figure(p: pd.DataFrame) -> tuple:
    """Brand x channel grid of analysed items: where each brand has a voice. Cells under 15 are amber, empty cells say none."""
    cov = vd.coverage_matrix(p)
    cols = [c for c in cov.columns if cov[c].sum() > 0]
    z, txt = [], []
    for b in cov.index:
        z.append([min(v, 100) if v >= ebi.MIN_N else (0 if v == 0 else None) for v in cov.loc[b, cols]])
        txt.append([f"{v}" if v else "none" for v in cov.loc[b, cols]])
    fig = go.Figure(go.Heatmap(z=z, x=[c.replace(" ", "<br>") for c in cols], y=list(cov.index), text=txt, texttemplate="%{text}",
                               colorscale=[[0, "#F1F5F9"], [1, "#5FB0C0"]], zmin=0, zmax=100, xgap=3, ygap=3, showscale=False,
                               hovertemplate="%{y} · %{x}: %{text} items<extra></extra>", textfont=dict(size=11, color="#191919")))
    fig.update_xaxes(side="top", tickangle=0, title=None)
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_layout(height=100 + 50 * len(cov), plot_bgcolor="#F1F5F9", margin=dict(t=60, l=10, r=10, b=10))
    thin = int(((cov.values > 0) & (cov.values < ebi.MIN_N)).sum())
    return fig, {b: int(cov.loc[b].sum()) for b in cov.index}, thin


def render(d: pd.DataFrame) -> None:
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables the pages read.")
        return
    p = vd.pool(d)
    ui.section("Every number comes from one table and one tagger", "One item = one post, comment or review, labelled by the same prompt.",
               "Coverage", kind="fact")
    pp = passport(d)
    ui.plot(passport_figure(pp), f"{int(pp['Collected'].sum()):,} items collected; only consumer voice reaches the brand pool.", key="mt_passport",
            note="Brand pool = names a brand, relevant, no giveaways. Only consumer voice compares brands.",
            bases=f"{len(pp)} channel and unit pairs, {int(pp['Collected'].sum()):,} items collected")
    ui.show_data("Show the channel table", pp, "Includes the brands each channel can compare (15+ items) and its journey role.")

    ui.section("Brands are heard on different channels", "Analysed items per brand and channel. Compared only where both sides have 15+.",
               "Coverage", kind="fact")
    fig, bases, thin = coverage_figure(p)
    ui.plot(fig, "Olens is heard on YouTube, Acuvue on Xiaohongshu and YouTube; most cells are thin.", key="mt_cov",
            note=f"{thin} cells hold 1 to 29 items (directional). Empty = nothing passed the pool rules.",
            bases=bases, noun="analysed items")

    ui.section("Label standard", "What the labels mean on every page.", "Method", kind="fact")
    versions = ", ".join(sorted(set(d["taxonomy_version"])))
    n_tagged = len(d)
    agree = p[p["sentiment_native"].isin(vd.SENT)]
    ag = (agree["sentiment"] == agree["sentiment_native"]).mean() * 100 if len(agree) else None
    stage_share = (p["journey_stage"] != "None").mean() * 100
    ui.group_cards([(g, list(ts), GROUP_OWNER[g][0], GROUP_OWNER[g][1]) for g, ts in theme_tags.GROUPS.items()])
    st.markdown(
        "- **Sentiment:** positive, neutral, mixed or negative toward the brand named first, from one model prompt "
        "(`gpt-4o-mini`, tag version " + versions + f", {n_tagged:,} items). **Net sentiment** = % positive minus % negative.\n"
        "- **Themes:** 0 to 2 of eight per item, each with its own polarity. Headlines use the four groups above.\n"
        "- **Complaint:** a negative or mixed item on a theme group, on every page.\n"
        f"- **Journey stage:** each channel's role (context.md), not a per-item label: only {stage_share:.0f}% of items name one.\n"
        "- **Lenses:** consumer voice compares brands. Category voice, the app, retail reviews and brands' own posts are read alone.\n"
        "- **Limits:** under 15 items a rate becomes a count. A brand gap needs 15 items across both groups and an interval that excludes zero. "
        "Comments cluster under a few videos."
        + (f"\n- **Older labels:** the new sentiment agrees on {ag:.0f}% of {len(agree):,} pool items and reads stricter on promo and off-topic items, "
           "so net sentiment is lower." if ag is not None else ""))
