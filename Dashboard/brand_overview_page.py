"""
Brand Overview: the first tab, laid out like the HK dashboard. A scorecard table (one row per brand: products, stores, weighted
rating, reviews, then how many comments or posts each channel holds), the rating chart under it, and the competitors and category
page below. Channel counts are the pooled items of voice_data, so they match every other page.
"""

import pandas as pd
import streamlit as st

import app_store_signals
import ebi
import market_competitors
import ui
import voice_data as vd

# Pool sources shown as one scorecard column each (posts and comments of a channel are added together).
SCORE_COLS = {
    "XHS": ["Xiaohongshu", "Xiaohongshu comments"],
    "Reddit": ["Reddit"],
    "YouTube": ["YouTube"],
    "Instagram": ["Instagram"],
    "Facebook": ["Facebook"],
    "KiasuParents": ["KiasuParents"],
}


def scorecard(products: pd.DataFrame, reviews: pd.DataFrame, pool: pd.DataFrame, brands: list, weighted_rating, d: pd.DataFrame) -> pd.DataFrame:
    """HK layout, SG data: per brand the items per channel, the social total, the thin retailer rating with its base,
    and the brand's own posts. No health score here (HK has none; it lives on Brand Health)."""
    own = vd.own_posts(d) if not d.empty else pd.DataFrame(columns=["brand_std"])
    rows = []
    for b in brands:
        bp = products[products["brand"] == b]
        n_rev = int(bp.loc[bp["total_reviews"] > 0, "total_reviews"].sum())
        rating = weighted_rating(bp) if n_rev >= ebi.MIN_N else float("nan")
        pb = pool[pool["brand_std"] == b]
        row = {"Brand": b}
        for col, sources in SCORE_COLS.items():
            row[col] = int(pb["source"].isin(sources).sum())
        row["Social signals"] = sum(v for k, v in row.items() if k in SCORE_COLS and k != "KiasuParents")
        row["Retailer rating (ratings)"] = f"{rating:.2f} ({n_rev})" if pd.notna(rating) else None
        row["Brand's own posts"] = int((own["brand_std"] == b).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def _source_strip(d: pd.DataFrame) -> None:
    """The sources that cannot be compared across brands, in one line of cards: the app (Acuvue only), Google Maps (stores, not brands)."""
    app, _ = app_store_signals.load_app_reviews()
    maps = vd.raw_by_source()
    maps_n = int(maps.loc[maps["source"] == "Google Maps", "collected"].sum())
    st.caption("**Also collected, not comparable across brands**")
    c1, c2, c3 = st.container(key="src-strip").columns(3)
    n_app = len(app) if app is not None else 0
    c1.metric("MyACUVUE app (Acuvue only)", f"{app['rating'].mean():.2f} / 5" if n_app >= ebi.MIN_N else "n/a", f"{n_app} store reviews", delta_color="off", delta_arrow="off")
    c2.metric("Google Maps (store experience)", f"{maps_n:,}", "reviews of lens retailers, not of brands", delta_color="off", delta_arrow="off")
    c3.metric("Retailer pages", "3 of 5 brands", "Acuvue, Alcon, Bausch & Lomb carry 15+ ratings", delta_color="off", delta_arrow="off")


def _scorecard_table(sc: pd.DataFrame) -> None:
    """HK-style HTML table: centred columns, grey header, Acuvue's row bold on a light tint, a dash where there is no rating."""
    cols = [c for c in sc.columns]
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = []
    for _, r in sc.iterrows():
        focal = r["Brand"] == "Acuvue"
        cells = "".join(
            f"<td>{'–' if pd.isna(r[c]) else (f'{r[c]:.0f}' if isinstance(r[c], float) else r[c])}</td>" for c in cols)
        body.append(f'<tr class="{"sc-focal" if focal else ""}">{cells}</tr>')
    st.markdown(
        """<style>
.sc-table {width:100%;border-collapse:collapse;font-size:13px;}
.sc-table th {background:var(--wash-2);color:var(--muted);font-weight:700;font-size:12px;padding:10px 14px;border-bottom:2px solid var(--line);text-align:center;}
.sc-table td {padding:9px 14px;border-bottom:1px solid var(--line);text-align:center;}
.sc-table tr.sc-focal td {font-weight:700;background:var(--wash);}
.sc-table tr:hover td {background:var(--wash-2);}
</style>"""
        f'<table class="sc-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>',
        unsafe_allow_html=True)


def render(products: pd.DataFrame, reviews: pd.DataFrame, d: pd.DataFrame, brands: list, weighted_rating,
           caption: str, story_frames) -> None:
    pool = vd.pool(d) if not d.empty else pd.DataFrame(columns=["brand_std", "source"])
    ui.part("Brand health scorecard")
    sc = scorecard(products, reviews, pool, brands, weighted_rating, d)
    if sc.empty:
        st.info("No brands selected.")
    else:
        _scorecard_table(sc)
        st.caption(f"Channel columns count the comments, posts and reviews that name the brand and are about lenses (brand pool). Social signals adds "
                   f"XHS, Reddit, YouTube, Instagram and Facebook (KiasuParents is not in the total). A dash means no source or under {ebi.MIN_N} ratings, not a low score. "
                   f"The blended sentiment score is on Brand Health.")
        _source_strip(d)
        g1, g2, g3, g4, _ = st.columns([1, 1, 1, 1, 1.5])
        with g1:
            ui.goto("Brand Health", key="bo_to_health")
        with g2:
            ui.goto("Social Signals", key="bo_to_social")
        with g3:
            ui.goto("Retail & Promotions", key="bo_to_retail")
        with g4:
            ui.goto("Journey & App", key="bo_to_app")
    ui.part("Category")
    market_competitors.render_category()

    ui.read_comments(pool[pool["brand_std"].isin(brands)], "Read the brand comments behind this page (brand pool)", key="bo_read")
