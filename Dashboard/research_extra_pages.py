"""
Two Research & Triangulation sections built on the shared brand pool, the SG counterparts of HK's "Share of Voice" and
"-ve and +ve Tail": who gets talked about in each channel, and what the complaints are about.
"""

import palette
import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import charts
import ebi
import ui
import voice_data as vd
from sg_common import BRAND_COLORS, DB_DIR, SG_DB, read_table


def _pool(d: pd.DataFrame, brands: list) -> pd.DataFrame:
    p = vd.pool(d)
    p = p[p["brand_std"].isin(brands)].copy()
    p["channel"] = p["source"].replace({"Xiaohongshu comments": "Xiaohongshu"})
    return p


def share_of_voice(d: pd.DataFrame, brands: list) -> None:
    st.subheader("Share of voice: items per brand, by channel")
    p = _pool(d, brands)
    if p.empty:
        st.info("No brand-named items for the selected brands.")
        return
    st.caption(f"Channels with fewer than {ebi.MIN_N} brand-named items are left out. Share of voice is volume of talk, not approval.")
    ui.goto("Brand Health", "Sentiment is on Brand Health", key="rx_to_brand_health")
    n = p.groupby("channel").size()
    keep = [c for c in n.index if n[c] >= ebi.MIN_N]
    left = [f"{c} ({n[c]})" for c in n.index if c not in keep]
    allrow = p.assign(channel="All channels")
    t = pd.concat([allrow, p[p["channel"].isin(keep)]]).groupby(["channel", "brand_std"]).size().rename("items").reset_index()
    t["share"] = t["items"] / t.groupby("channel")["items"].transform("sum") * 100
    order = ["All channels"] + sorted(keep, key=lambda c: -n[c])
    fig = px.bar(t, x="share", y="channel", color="brand_std", orientation="h", color_discrete_map=BRAND_COLORS,
                 category_orders={"channel": order, "brand_std": charts.BRAND_ORDER}, hover_data=["items"])
    fig.update_layout(barmode="stack", height=120 + 44 * len(order), margin=dict(l=10, r=10, t=10, b=10), legend_title_text="",
                      xaxis=dict(title="Share of brand-named items (%)", range=[0, 100]), yaxis=dict(title="", autorange="reversed"))
    ui.chart(fig)
    ui.n_strip({"All channels": len(p), **{c: int(n[c]) for c in keep}}, "items", attached=True)
    if left:
        st.caption("Under the floor, not drawn: " + ", ".join(left) + ".")
    ui.show_data("Table: items by channel and brand · brand pool", t.pivot_table(index="channel", columns="brand_std", values="items", fill_value=0).astype(int))


def complaint_tail(d: pd.DataFrame, brands: list) -> None:
    head = st.empty()
    head.subheader("Negative Tail: what the complaints are about")
    p = _pool(d, brands)
    # a complaint is an item negative or mixed on a theme, the same rule as vd.complaints but at the eight-theme level
    hits = [(r.item_id, t) for r in p.itertuples() for t, pol in r.pol.items() if t in r.themes and pol in ("negative", "mixed")]
    comp = pd.DataFrame(hits, columns=["item_id", "theme"]).join(p.set_index("item_id")[["brand_std"]], on="item_id")
    if comp.empty:
        st.info("No complaints found for the selected brands.")
        return
    st.caption("Complaint = negative or mixed on that theme. Share = complaint items on the theme as a % of the brand's items; "
               f"a brand needs {ebi.MIN_N}+ items, a bar {ebi.MIN_COUNT}+ complaints (hatched under 30).")
    n_b = p.groupby("brand_std").size()
    shown = [b for b in charts.order_brands(p["brand_std"].unique()) if n_b[b] >= ebi.MIN_N]
    thin = [f"{b} ({n_b[b]})" for b in charts.order_brands(p["brand_std"].unique()) if n_b[b] < ebi.MIN_N]
    if not shown:
        st.info("No brand reaches the minimum number of items.")
        return
    cnt = comp.groupby(["brand_std", "theme"]).size()
    rows = [{"Brand": b, "Theme": t, "Complaints": int(cnt.get((b, t), 0)), "Items": int(n_b[b]),
             "Share": cnt.get((b, t), 0) / n_b[b] * 100} for b in shown for t in vd.THEMES]
    t = pd.DataFrame(rows)
    _top = {b: t[(t["Brand"] == b)].sort_values("Complaints", ascending=False).iloc[0] for b in shown}
    _same = {r["Theme"] for r in _top.values()}
    if len(_same) == 1 and len(shown) > 1:
        head.subheader(f"{next(iter(_same))} is the top complaint theme for all {len(shown)} brands with {ebi.MIN_N}+ items: it is a category issue, not an Acuvue one")
    elif vd.FOCAL in _top:
        _f = _top[vd.FOCAL]
        head.subheader(f"{_f['Theme']} is Acuvue's top complaint theme ({_f['Share']:.0f}% of its items)")
    ncol = 3
    nrow = -(-len(shown) // ncol)
    fig = make_subplots(rows=nrow, cols=ncol, subplot_titles=[f"{b} (n={n_b[b]})" for b in shown], shared_yaxes=True,
                        vertical_spacing=0.34 / nrow, horizontal_spacing=0.04)
    for i, b in enumerate(shown):
        s = t[(t["Brand"] == b) & (t["Complaints"] >= ebi.MIN_COUNT)]
        fig.add_trace(go.Bar(x=s["Theme"], y=s["Share"], name=b, showlegend=False, marker_color=BRAND_COLORS.get(b),
                             marker_pattern_shape=["/" if c < 30 else "" for c in s["Complaints"]], customdata=s[["Complaints"]],
                             text=[f"{v:.0f}%" for v in s["Share"]], textposition="outside",
                             hovertemplate="%{x}<br>%{y:.1f}% of items (%{customdata[0]} complaints)<extra>" + b + "</extra>"),
                      row=i // ncol + 1, col=i % ncol + 1)
    fig.update_xaxes(categoryorder="array", categoryarray=vd.THEMES, tickangle=-35, tickfont=dict(size=11))
    fig.update_yaxes(ticksuffix="%", rangemode="tozero")
    for r in range(1, nrow + 1):
        fig.update_yaxes(title_text="% of brand's items", row=r, col=1)
    fig.update_layout(height=330 * nrow + 80, margin=dict(l=10, r=10, t=40, b=10))
    ui.chart(fig)
    ui.n_strip({b: int(n_b[b]) for b in shown}, "brand-named items", attached=True)
    notes = []
    under = t[(t["Complaints"] > 0) & (t["Complaints"] < ebi.MIN_COUNT)]
    if not under.empty:
        notes.append("Under " + str(ebi.MIN_COUNT) + " complaints, not drawn: " + "; ".join(
            f"{b}: " + ", ".join(f"{r.Theme} ({r.Complaints})" for r in g.itertuples()) for b, g in under.groupby("Brand", sort=False)) + ".")
    if thin:
        notes.append(f"Under {ebi.MIN_N} items, left out: " + ", ".join(thin) + ".")
    if notes:
        st.caption(" ".join(notes))
    ui.show_data("Table: complaint share by brand and theme group · brand pool", t.pivot_table(index="Brand", columns="Theme", values="Share", sort=False).round(0).reindex(columns=vd.THEMES))
    pick = st.selectbox("Read the complaints on", vd.THEMES, key="rt_tail_group")
    ids = comp.loc[comp["theme"] == pick, "item_id"].unique()
    ui.items_panel(vd.view(p[p["item_id"].isin(ids)]), title=f"Complaints on {pick}")


# ---------------------------------------------------------------- distribution gap
# Where the desk research says each brand is sold (distribution_sg.csv, transcribed from the retail/ECP research file with
# its claim ids) against what we scraped per retailer. "Not listed" is not "not sold": the research names retailers it found.
DIST_CSV = os.path.normpath(os.path.join(DB_DIR, "..", "data", "research", "distribution_sg.csv"))
_STATUS_Z = {"Present": 2, "Solutions only": 1, "Unverified": 0.5}
_STATUS_SHOW = {"Present": "Yes", "Solutions only": "Solutions", "Unverified": "?"}
# research retailer name -> the names the scrapers use (listings come from the store name, reviews from the Maps chain)
_LISTING_STORES = {"Lenskart": ["Lenskart Singapore"], "Watsons Singapore": ["Watsons Singapore"]}


def _scraped_by_retailer(d: pd.DataFrame, names: list) -> dict:
    """Google Maps reviews per chain plus product listings for the two stores scraped as listings: the same counts as
    Channel Coverage, so a retailer carries one number on both pages."""
    maps = d[d["source"] == "Google Maps"].groupby("retailer").size() if "retailer" in d else pd.Series(dtype=int)
    listings = read_table(SG_DB, "SELECT store_name, COUNT(*) AS n FROM products GROUP BY store_name")
    lst = dict(zip(listings["store_name"], listings["n"])) if not listings.empty else {}
    out = {n: int(maps.get(n, 0)) for n in names}
    for r, stores in _LISTING_STORES.items():
        if r in out:
            out[r] += sum(int(lst.get(s, 0)) for s in stores)
    if "Third-party online sellers" in out:
        out["Third-party online sellers"] = int(sum(lst.values())) - sum(int(lst.get(s, 0)) for ss in _LISTING_STORES.values() for s in ss)
    return out


def distribution_gap(d: pd.DataFrame) -> None:
    head = st.empty()
    head.subheader("Distribution Gap: where brands are sold vs where we scraped")
    if not os.path.exists(DIST_CSV):
        st.info("No distribution list found (Scripts/data/research/distribution_sg.csv).")
        return
    dist = pd.read_csv(DIST_CSV)
    brands = [b for b in charts.BRAND_ORDER if b in set(dist["brand"])]
    n_present = dist[dist["status"] == "Present"].groupby("retailer")["brand"].nunique()
    names = list(dict.fromkeys(dist["retailer"]))
    scraped = _scraped_by_retailer(d, names)
    _carry = [r for r in names if n_present.get(r, 0) > 0]
    _blind = [r for r in _carry if scraped[r] == 0]
    head.subheader(f"{len(_blind)} of {len(_carry)} retailers that carry lenses have no scraped data" + (f" ({', '.join(_blind)})" if _blind else ""))
    names.sort(key=lambda r: (-int(n_present.get(r, 0)), -scraped[r], r))
    cell = {(r.retailer, r.brand): r for r in dist.itertuples()}
    z = [[_STATUS_Z.get(cell[(r, b)].status) if (r, b) in cell else None for b in brands] for r in names]
    txt = [[_STATUS_SHOW.get(cell[(r, b)].status, "") if (r, b) in cell else "" for b in brands] for r in names]
    hov = [[(f"{cell[(r, b)].status} ({cell[(r, b)].evidence_ids}): {cell[(r, b)].source_note}" if (r, b) in cell else "Not listed in the research")
            for b in brands] for r in names]
    ylab = [charts.row_label(r, scraped[r], note="not scraped") for r in names]
    fig = go.Figure(go.Heatmap(z=z, x=brands, y=ylab, text=txt, texttemplate="%{text}", customdata=hov, hovertemplate="%{y} · %{x}<br>%{customdata}<extra></extra>",
                               zmin=0, zmax=2, xgap=3, ygap=3, showscale=False,
                               colorscale=[[0, palette.BAND], [0.25, palette.BAND], [0.26, palette.SEQ_MID], [0.5, palette.SEQ_MID], [0.51, palette.FOCAL_COLOR], [1, palette.FOCAL_COLOR]]))
    fig.update_layout(height=120 + 46 * len(names), margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(autorange="reversed"), xaxis=dict(side="top"))
    sold = [r for r in names if n_present.get(r, 0) or (dist[(dist["retailer"] == r)]["status"] == "Solutions only").any()]
    missing = [r for r in sold if scraped[r] == 0]
    st.caption("Dark = brand found there; light blue = solutions only; grey ? = seller claim not verified; empty = not listed. "
               "Count under each retailer = items scraped there.")
    ui.plot(fig, (f"{len(missing)} of {len(sold)} retailers that carry lenses have no scraped data: {', '.join(missing)}." if missing
                  else "Every retailer the research names has scraped data."), "fact",
            "Desk research (claim ids C-04 to C-20) · not listed is not the same as not sold",
            height=fig.layout.height, bases=f"Desk research: {len(sold)} retailers carrying lenses, {len(brands)} brands · scraped counts as on Channel Coverage",
            key="dist_gap")
    ui.show_data("Table: retailer stocking · desk research", dist.rename(columns={"brand": "Brand", "retailer": "Retailer", "status": "Status",
                                                                              "evidence_ids": "Claim ids", "source_note": "Note"}))


# ---------------------------------------------------------------- attribute quadrant
# HK plots importance against performance of product attributes. SG uses the shared eight themes (not a private attribute list):
# importance = share of a side's items that touch the theme, performance = net sentiment of the polarity the model gave that theme.
# Acuvue and the peers are drawn on the same axes; the cut lines are the pool's own average share and overall themed net.
_QUADRANT = {(True, True): "Key drivers", (False, True): "Potential differentiators", (True, False): "Fix first", (False, False): "Low importance"}


def _theme_cell(s: pd.DataFrame, theme: str) -> dict:
    labs = [pl[theme] for pl, th in zip(s["pol"], s["themes"]) if theme in th]
    r = vd.net(labs) if len(labs) >= ebi.MIN_N else None
    return {"n": len(labs), "share": len(labs) / len(s) * 100 if len(s) else 0.0, "net": r[0] if r else None}


def attribute_quadrant(d: pd.DataFrame, brands: list) -> None:
    head = st.empty()
    head.subheader("Attribute Quadrant: how much each theme is talked about vs how well it is spoken of")
    p = _pool(d, brands)
    f, o = p[p["brand_std"] == vd.FOCAL], p[p["brand_std"] != vd.FOCAL]
    if f.empty or o.empty:
        st.info(f"Needs {vd.FOCAL} and at least one peer in the selection.")
        return
    themes = list(vd.THEMES)
    cells = {"f": {t: _theme_cell(f, t) for t in themes}, "o": {t: _theme_cell(o, t) for t in themes}, "p": {t: _theme_cell(p, t) for t in themes}}
    all_labs = [pl[t] for pl, th in zip(p["pol"], p["themes"]) for t in th]
    cut_y = vd.net(all_labs)[0] if all_labs else 0.0
    cut_x = sum(c["share"] for c in cells["p"].values()) / len(themes)
    fig = go.Figure()
    for key, name, color, size in (("o", "Peers", palette.PEER_GREY, 11), ("f", vd.FOCAL, BRAND_COLORS[vd.FOCAL], 15)):
        pts = [(t, c) for t, c in cells[key].items() if c["net"] is not None]
        fig.add_trace(go.Scatter(
            x=[c["share"] for _, c in pts], y=[c["net"] for _, c in pts], mode="markers+text" if key == "f" else "markers", name=name,
            text=[f"<b>{t}</b>" for t, _ in pts] if key == "f" else None, textposition="top center",
            marker=dict(color=color, size=size, line=dict(color="white", width=1)),
            customdata=[[t, c["n"]] for t, c in pts],
            hovertemplate=f"{name} · %{{customdata[0]}}<br>%{{x:.0f}}% of items · net %{{y:+.0f}} · n=%{{customdata[1]}}<extra></extra>"))
    fig.add_vline(x=cut_x, line=dict(color=palette.RULE, dash="dot"))
    fig.add_hline(y=cut_y, line=dict(color=palette.RULE, dash="dot"))
    fig.update_layout(height=430, xaxis=dict(title="Importance: % of items that touch the theme"),
                      yaxis=dict(title="Performance: net sentiment on the theme"), legend=dict(orientation="h", y=1.08))
    drawn = {t for key in ("f", "o") for t, c in cells[key].items() if c["net"] is not None}
    fc = cells["f"]
    key_f = [t for t in themes if fc[t]["net"] is not None]
    fix = [t for t in key_f if fc[t]["share"] >= cut_x and fc[t]["net"] < cut_y]
    head.subheader((f"{', '.join(fix)}: talked about most and scored below the pool, but " if fix else "No theme is both talked about most and scored below the pool; ")
                    + f"{vd.FOCAL} is readable on only {len(key_f)} of {len(themes)} themes")
    say = (f"{vd.FOCAL} is readable on {len(key_f)} of {len(themes)} themes"
           + (f"; {', '.join(fix)} is talked about most and sits under the pool's net (a position, not a tested gap)." if fix else "; none sits in the fix-first quadrant."))
    ui.plot(fig, "", "fact",
            f"Cut lines: pool average share ({cut_x:.0f}%) and pool net on all themed mentions ({cut_y:+.0f}). Top right = key drivers, bottom right = fix first, "
            f"top left = potential differentiators, bottom left = low importance. A theme with under {ebi.MIN_N} items on a side is not plotted for that side. "
            "Themes are model-tagged.",
            bases={vd.FOCAL: len(f), "Peers": len(o)}, noun="pooled items", key="attr_quad")
    thin = [t for t in themes if t not in drawn]
    if thin:
        st.caption("Under 15 items on both sides, not plotted: " + ", ".join(f"{t} ({cells['p'][t]['n']})" for t in thin) + ".")
    rows = []
    for t in themes:
        r = {"Theme": t}
        for key, nm in (("f", vd.FOCAL), ("o", "Peers")):
            c = cells[key][t]
            r[f"{nm} items"] = c["n"]
            r[f"{nm} share"] = f"{c['share']:.0f}%"
            r[f"{nm} net"] = ebi.sgn(c["net"]) if c["net"] is not None else "-"
            if key == "f":
                r["Quadrant"] = _QUADRANT[(c["share"] >= cut_x, c["net"] >= cut_y)] if c["net"] is not None else "-"
        rows.append(r)
    ui.show_data("Table: attribute scores by brand · desk research", pd.DataFrame(rows))
