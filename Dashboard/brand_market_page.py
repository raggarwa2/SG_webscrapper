"""
Brand & market: how does Acuvue stand against its peers, and what is the market talking about?

One page for what used to be Brand Health, Conversation & content and Themes & channels. Everything reads voice_data (one item
table, one tagger), so every channel is on the same scale. Only the consumer-voice lens compares brands; category voice, brands'
own posts and search demand are read beside it, never pooled with it.

Order (Pyramid Principle): the answer card, then 1 Position, 2 Channels, 3 Themes, 4 Brand voice, 5 Demand, then collapsed
supporting data. Charts are shown; tables and verbatims sit behind a click.
"""

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import charts
import ebi
import market_competitors
import method_page
import trends_signals
import ui
import voice_data as vd
from sg_common import BRAND_COLORS, SENTIMENT_COLORS

FOCAL = vd.FOCAL
PEER_GREY = "#9AA5B1"
CAT_COLOR = "#6B7A90"
CONTENT_ORDER = ["promo", "education_news", "giveaway_spam", "experience", "opinion", "question", "other"]
CONTENT_LABEL = {"promo": "Promotion", "education_news": "Education / news", "giveaway_spam": "Giveaway / spam",
                 "experience": "Own experience", "opinion": "Opinion", "question": "Question", "other": "Other"}
CONTENT_COLOR = {"promo": "#B7791F", "education_news": "#59A5D7", "giveaway_spam": "#9AA5B1", "experience": "#168012",
                 "opinion": "#0B3556", "question": "#7048E8", "other": "#D5DBE1"}


def _pts(v) -> str:
    return f"{v:+.0f}"


@st.cache_data(ttl=600, show_spinner=False, max_entries=2)
def _facts(m_items: float, m_tags: float) -> dict:
    return _build_facts(vd.load())


def facts(d: pd.DataFrame) -> dict:
    """Numbers the page, the Answer card and the header strip share, so they can never disagree (cached on the table timestamps)."""
    return _facts(vd.VOICE_DB.stat().st_mtime, vd.TAG_DB.stat().st_mtime) if len(d) else _build_facts(d)


def _build_facts(d: pd.DataFrame) -> dict:
    p = vd.pool(d)
    f_all, o_all = p[p["brand_std"] == FOCAL], p[p["brand_std"] != FOCAL]
    out = {"pool": p, "n_f": len(f_all), "n_p": len(o_all)}
    out["pooled_gap"] = vd.gap(f_all["sentiment"], o_all["sentiment"]) if len(f_all) and len(o_all) else {}
    out["std"] = vd.standardised(p)
    g = out["std"] or out["pooled_gap"]
    out["read"] = g
    if g:
        out["verdict"] = "level with peers" if g["lo"] <= 0 <= g["hi"] else ("ahead of peers" if g["gap"] > 0 else "behind peers")
    else:
        out["verdict"] = "not readable"
    out["channels"] = vd.channel_gaps(p)
    out["groups"] = vd.group_table(p)
    out["category"] = vd.category(d)
    out["own"] = vd.own_posts(d)
    return out


def _net_dots(bn: pd.DataFrame, ref: float | None) -> go.Figure:
    fig = go.Figure()
    labels = {r.brand: charts.row_label(r.brand, int(r.n)) for r in bn.itertuples()}
    for r in bn.itertuples():
        col = BRAND_COLORS.get(r.brand, "#178197")
        if r.net is None or pd.isna(r.net):
            continue
        fig.add_trace(go.Scatter(x=[r.lo, r.hi], y=[labels[r.brand]] * 2, mode="lines", line=dict(color=col, width=7), opacity=0.35,
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[r.net], y=[labels[r.brand]], mode="markers", marker=dict(size=14, color=col), showlegend=False,
                                 customdata=[[r.brand]],
                                 hovertemplate=f"{r.brand}: net %{{x:+.0f}} (95% interval {r.lo:+.0f} to {r.hi:+.0f}, n={int(r.n)})<extra></extra>"))
        fig.add_trace(go.Scatter(x=[r.hi], y=[labels[r.brand]], mode="text", text=[f"<b>{r.net:+.0f}</b>"], textposition="middle right",
                                 textfont=dict(size=12, color="#191919"), showlegend=False, hoverinfo="skip"))
    if ref is not None:
        fig.add_vline(x=ref, line=dict(color="#64748B", width=1.5, dash="dash"))
    fig.update_xaxes(zeroline=True, zerolinecolor="#CBD5E1", range=[min(-5, bn["lo"].min() - 8 if bn["lo"].notna().any() else -5), 100],
                     title="Net sentiment (% positive minus % negative), all channels pooled, 95% interval"
                           + (f"<br><span style='font-size:11px;color:#64748B'>dashed line = peers pooled ({ref:+.0f})</span>" if ref is not None else ""))
    fig.update_yaxes(title="", categoryorder="array", categoryarray=[labels[b] for b in bn["brand"]], range=[len(bn) - 0.5, -0.5])
    fig.update_layout(height=120 + 52 * len(bn))
    return fig


def channel_phrase(clear: pd.DataFrame) -> str:
    """Every channel whose gap passes the checks, behind first: 'behind on KiasuParents (-48) and YouTube (-36), ahead on Xiaohongshu comments (+31)'."""
    def names(df):
        items = [f"{r.channel} ({_pts(r.gap)})" for r in df.sort_values("gap").itertuples()]
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    behind, ahead = clear[clear["gap"] < 0], clear[clear["gap"] > 0]
    parts = ([f"behind on {names(behind)}"] if len(behind) else []) + ([f"ahead on {names(ahead)}"] if len(ahead) else [])
    return ", ".join(parts)


def _tile(label: str, value: str, text: str, tone: str = "flat", stat: str = "") -> dict:
    return {"label": label, "value": value, "text": text, "tone": tone, "stat": stat}


def render(d: pd.DataFrame) -> None:
    if d.empty:
        st.info("Run Scripts/build_voice_items.py and Scripts/tag_voice_items.py to build the tables this page reads.")
        return
    F = facts(d)
    p, g, cg, gt, cat, own = F["pool"], F["read"], F["channels"], F["groups"], F["category"], F["own"]
    bn = vd.brand_net(p)
    tf, mf = trends_signals.facts(), market_competitors.trade_facts()
    n_f, n_p = F["n_f"], F["n_p"]

    # ---- numbers behind the answer card ------------------------------------------------------------------------
    clear = cg[cg["ok"] & cg["lo"].notna() & ((cg["lo"] > 0) | (cg["hi"] < 0))] if len(cg) else cg
    readable = gt[gt["grade"] != "Not readable"]
    top_g = gt.sort_values("share_f", ascending=False).iloc[0] if len(gt) and gt["share_f"].notna().any() else None
    own_f = own[own["owner_brand"] == FOCAL]
    promo = (own_f["content_type"] == "promo").mean() * 100 if len(own_f) >= ebi.MIN_N else None

    if g:
        bottom = f"{FOCAL} is {F['verdict']} on net sentiment ({_pts(g['net_f'])} vs {_pts(g['net_p'])}; gap {_pts(g['gap'])})"
        if len(clear):
            bottom += f"; by channel it is {channel_phrase(clear)}"
        bottom += "."
    else:
        bottom = f"{FOCAL} cannot yet be read against peers: the pool is too thin."
    tiles = []
    if g:
        std = F["std"]
        tiles.append(_tile("Position", f"{_pts(g['net_f'])} vs {_pts(g['net_p'])}", (f"{F['verdict'].capitalize()} at one channel mix" if std else F["verdict"].capitalize()),
                           "flat" if F["verdict"] == "level with peers" else ("good" if g["gap"] > 0 else "bad"), stat=f"Net sentiment, {FOCAL} vs peers"))
    if len(clear):
        n_ok = int(cg["ok"].sum())
        tiles.append(_tile("Channels", f"{len(clear)} of {n_ok} differ", html.escape(channel_phrase(clear)[:1].upper() + channel_phrase(clear)[1:]),
                           "bad" if (clear["gap"] < 0).any() else "good",
                           stat=f"Channels with 15+ items per side where {FOCAL} differs from peers"))
    else:
        tiles.append(_tile("Channels", "No clear gap", "No channel with 15+ items on both sides shows a real gap", "flat",
                           stat="Net-sentiment gap by channel"))
    if top_g is not None:
        gline = (f"net {_pts(top_g['net_f'])} vs {_pts(top_g['net_p'])}, {vd.GRADE_PHRASE[top_g['grade']].split(',')[0]}"
                 if top_g["net_f"] is not None else "too few peer items")
        tiles.append(_tile("Themes", f"{len(readable)} of {len(vd.GROUP_LIST)} groups",
                           f"{html.escape(top_g['group'])} is {top_g['share_f']:.0f}% of {FOCAL} items; {gline}", "watch" if len(readable) < 3 else "flat",
                           stat="Topic groups with enough items to compare"))
    if promo is not None:
        comfort_cons = gt.set_index("group").loc["Product & look", "share_f"] if "Product & look" in set(gt["group"]) else None
        tiles.append(_tile("Brand voice", f"{promo:.0f}% promo", (f"Consumers raise product and look in {comfort_cons:.0f}% of items" if comfort_cons is not None else ""),
                           "watch", stat=f"Share of {FOCAL}'s own posts that are promotion"))
    if tf and mf:
        tiles.append(_tile("Demand", f"{tf['idx_chg']:+.0f}% searches", f"Lens imports {mf['units']:+.0f}% in units, {mf['first']} to {mf['last']}: the signals disagree",
                           "watch", stat=f"Change in {FOCAL} search interest vs {tf['prev']}"))
    trail = gt[(gt["grade"].isin(["B · one channel", "A · corroborated"])) & (gt["gap"] < 0)] if len(gt) else gt
    parts = []
    if F["verdict"] == "level with peers":
        parts.append("Sentiment is level, so the registration gap is not a brand problem.")
    elif F["verdict"] == "behind peers":
        parts.append("Overall sentiment trails peers: fix the brand story before the registration journey.")
    if len(trail):
        t0 = trail.iloc[0]
        parts.append(f"{FOCAL} trails on {t0['group']} (net {_pts(t0['net_f'])} vs {_pts(t0['net_p'])}), "
                     f"{'only in ' + ', '.join(t0['where']) if t0['where'] else 'in one channel'}: test proof there first.")
    else:
        parts.append("Lead with proof on product and look, where people talk most.")
    if tf and mf and (tf["idx_chg"] > 0) != (mf["units"] > 0):
        parts.append("Treat demand as unsettled until internal sales data settles imports vs searches.")
    implication = " ".join(parts)
    ui.pyramid(bottom, tiles, implication)

    ui.nav(["1 · Position", "2 · Channels", "3 · Themes", "4 · Brand voice", "5 · Demand"])
    t_pos, t_chan, t_theme, t_voice, t_dem = (st.container() for _ in range(5))

    # ---- 1. Position ----------------------------------------------------------------------------------------------
    with t_pos:
        ui.section(f"{FOCAL} is {F['verdict']} on sentiment" if g else "Sentiment position",
                   f"{len(p):,} brand-named items from {p['source'].nunique()} channels; giveaways removed.",
                   "1 · Position", kind="fact")
        ref = vd.net(p.loc[p["brand_std"] != FOCAL, "sentiment"])[0] if n_p >= ebi.MIN_N else None
        note = ""
        if F["std"]:
            s = F["std"]
            note = (f"At one channel mix: {FOCAL} {_pts(s['net_f'])} vs peers {_pts(s['net_p'])}, gap {_pts(s['gap'])} ({_pts(s['lo'])} to {_pts(s['hi'])})"
                    + ("; some cells under 15, so directional" if s["thin"] else "") + ". Brands differ in channel mix: read the gap here, not from the dots.")
        ui.plot(_net_dots(bn, ref), (f"{FOCAL} {_pts(g['net_f'])} vs peers {_pts(g['net_p'])} at one channel mix: the gap {'could be chance' if F['verdict'] == 'level with peers' else 'is real'}." if g else "Net sentiment by brand."),
                key="bm_pos", note=note, bases={r.brand: int(r.n) for r in bn.itertuples()}, noun="pooled items")
        tbl = pd.DataFrame({"Brand": bn["brand"], "Items": bn["n"],
                            **{charts.SENTIMENT_LABELS[k].replace("Positive", "% positive").replace("Neutral", "% neutral").replace("Mixed", "% mixed").replace("Negative", "% negative"):
                               bn[k].round(0).astype(int) for k in vd.SENT},
                            "Net sentiment": [f"{v:+.0f}" if pd.notna(v) else "n<15" for v in bn["net"]],
                            "95% interval": [f"{lo:+.0f} to {hi:+.0f}" if pd.notna(lo) else "-" for lo, hi in zip(bn["lo"], bn["hi"])]})
        ui.show_data("Show the sentiment mix behind the dots", tbl, "Net sentiment = % positive minus % negative; neutral and mixed stay in the base.")

    # ---- 2. Channels ----------------------------------------------------------------------------------------------
    with t_chan:
        ui.section((f"The gap sits in one channel: {clear.iloc[0]['channel']}" if len(clear) == 1 else
                    (f"{len(clear)} channels differ: {channel_phrase(clear)}" if len(clear) else "No channel shows a gap the data can separate from chance")),
                   "Acuvue vs peers pooled. Hatched under 15 items; not drawn under 10.",
                   "2 · Channels", kind="fact")
        shown = cg[(cg["n_f"] >= ebi.MIN_COUNT) | (cg["n_p"] >= ebi.MIN_COUNT)] if len(cg) else cg
        if len(shown):
            rows = [(r.channel, f"{r.channel}<br><span style='font-size:10px;color:{charts.MUTED if r.ok else charts.AMBER}'>n={r.n_f} vs {r.n_p}"
                     + ("" if r.ok else " · directional") + "</span>", r.n_f,
                     vd.net(p[(p['source'] == r.channel) & (p['brand_std'] == FOCAL)]['sentiment'])[0] if r.n_f else None, r.n_p,
                     vd.net(p[(p['source'] == r.channel) & (p['brand_std'] != FOCAL)]['sentiment'])[0] if r.n_p else None) for r in shown.itertuples()]
            fig = charts.pair_bars(rows, "Net sentiment (% positive minus % negative)", as_net=True)
            peer_note = ""
            for r in clear.itertuples():
                if r.peer_top_share >= 60:
                    peer_note += f"Peers on {r.channel} are {r.peer_top_share:.0f}% {r.peer_top}: that is {FOCAL} against {r.peer_top}, not the field. "
            ev = ui.plot(fig, (f"{FOCAL} is {channel_phrase(clear)}." if len(clear)
                               else "No channel with 15+ items on both sides shows a gap."), key="bm_chan", select=True,
                         note=peer_note + "Click a bar for the items.", bases={r.channel: int(r.n_f + r.n_p) for r in shown.itertuples()}, noun="items")
            pk = ui.picked(ev)
            if pk:
                ch, side = pk[0]
                sel = p[(p["source"] == ch) & ((p["brand_std"] == FOCAL) if side == "focus" else (p["brand_std"] != FOCAL))]
                ui.items_panel(vd.view(sel), f"{ch}: {FOCAL if side == 'focus' else 'peer'} items")
            tcg = pd.DataFrame({"Channel": cg["channel"], f"{FOCAL} items": cg["n_f"], "Peer items": cg["n_p"],
                                f"{FOCAL} net": [f"{v:+.0f}" if pd.notna(v) and n >= ebi.MIN_N else f"n={n}" for v, n in zip(cg["net_f"], cg["n_f"])],
                                "Peers net": [f"{v:+.0f}" if pd.notna(v) and n >= ebi.MIN_N else f"n={n}" for v, n in zip(cg["net_p"], cg["n_p"])],
                                "Gap (95% interval)": [f"{a:+.0f} ({lo:+.0f} to {hi:+.0f})" if pd.notna(a) and ok else "-" for a, lo, hi, ok in zip(cg["gap"], cg["lo"], cg["hi"], cg["ok"])],
                                "Peers are mostly": [f"{b} ({s:.0f}%)" if b else "-" for b, s in zip(cg["peer_top"], cg["peer_top_share"])]})
            ui.show_data("Show the channel table", tcg, "Gaps are shown only where both sides have 15+ items.")
        else:
            st.caption("No channel has enough items on either side.")

    # ---- 3. Themes ------------------------------------------------------------------------------------------------
    with t_theme:
        top_txt = f"{top_g['group']} leads what people say about {FOCAL}" if top_g is not None else "What people talk about"
        ui.section(f"{top_txt}; {len(readable)} of {len(vd.GROUP_LIST)} topic groups can be compared with peers",
                   "Eight themes in four decision groups. An item can touch two.", "3 · Themes", kind="fact")
        drawn = gt[(gt["n_f"] >= ebi.MIN_COUNT) | (gt["n_p"] >= ebi.MIN_COUNT)]
        left = gt[~gt["group"].isin(drawn["group"])]
        cat_share = vd.group_share(cat) if len(cat) else None
        c1, c2 = st.columns(2)
        with c1:
            rows = [(r.group, r.group, r.n_f, r.share_f, r.n_p, r.share_p) for r in drawn.itertuples()]
            third = ([(r.group, r.group, sum(r.group in gs for gs in cat["groups"]), cat_share[r.group]) for r in drawn.itertuples()]
                     if cat_share and cat_share["n"] >= ebi.MIN_N else None)
            fig = charts.pair_bars(rows, "% of each side's items that touch the group", third=third)
            ui.plot(fig, "What people talk about, by group.", key="bm_topics",
                    bases={FOCAL: n_f, "Peers": n_p, **({"Category voice": cat_share["n"]} if third else {})}, noun="items")
        with c2:
            rows = [(r.group, f"{r.group}<br><span style='font-size:10px;color:{charts.MUTED if min(r.n_f, r.n_p) >= ebi.MIN_N else charts.AMBER}'>"
                     f"{r.grade.split(' ·')[0].lower()} · n={r.n_f} vs {r.n_p}</span>", r.n_f,
                     vd.net(vd.group_labels(p[p['brand_std'] == FOCAL], r.group))[0] if r.n_f else None, r.n_p,
                     vd.net(vd.group_labels(p[p['brand_std'] != FOCAL], r.group))[0] if r.n_p else None) for r in drawn.itertuples()]
            fig = charts.pair_bars(rows, "Net sentiment on the group", as_net=True)
            ev = ui.plot(fig, "How people feel about each group.", key="bm_topics_net", select=True,
                         note="Click a bar for the items.", bases={FOCAL: n_f, "Peers": n_p}, noun="items")
        pk = ui.picked(ev)
        if pk:
            grp, side = pk[0]
            sel = p[p["groups"].map(lambda gs: grp in gs) & ((p["brand_std"] == FOCAL) if side == "focus" else (p["brand_std"] != FOCAL))]
            ui.items_panel(vd.view(sel), f"{grp}: {FOCAL if side == 'focus' else 'peer'} items")
        # ---- every brand on the same topic groups ------------------------------------------------------------------
        ui.section("Every brand on the same topic groups",
                   "Each brand on its own. Cells under 15 items show the count only.",
                   "3 · Themes", kind="fact")
        keys = [g for g in vd.GROUP_LIST if max((c["n"] for (b_, k_), c in vd.brand_cells(p, [g]).items()), default=0) >= ebi.MIN_COUNT]
        cells = vd.brand_cells(p, keys)
        view = st.segmented_control("Show", ["Net sentiment", "Share of items"], default="Net sentiment", key="bm_grid_view",
                                    help="Net sentiment = % positive minus % negative on the group. Share = % of the brand's items that touch the group.")
        mode = "share" if view == "Share of items" else "net"
        readable_cells = [(b_, k_) for (b_, k_), c in cells.items() if c["n"] >= ebi.MIN_N]
        best = max(((c["net"], b_, k_) for (b_, k_), c in cells.items() if c["net"] is not None), default=None)
        worst = min(((c["net"], b_, k_) for (b_, k_), c in cells.items() if c["net"] is not None), default=None)
        say = (f"{len(readable_cells)} of {len(cells)} cells have 15+ items; net runs from {worst[0]:+.0f} to {best[0]:+.0f}."
               if best and worst else f"{len(readable_cells)} of {len(cells)} cells have 15+ items.")
        ui.plot(charts.brand_topic_heat(cells, [b_ for b_ in charts.BRAND_ORDER if (b_ in set(p["brand_std"]))], keys, mode), say, key="bm_brand_grid",
                note=("Net sentiment on the group: green above zero, red below. " if mode == "net" else "% of the brand's items on the group, with count. ")
                + "Loyalty & app has too few consumer items; its evidence is the app (Barriers & journey).",
                bases={b_: int((p["brand_std"] == b_).sum()) for b_ in charts.BRAND_ORDER if (p["brand_std"] == b_).any()}, noun="pooled items")
        with st.expander("Show every brand on the eight themes", expanded=False, on_change="rerun", key="bm_brand_theme_grid") as ex:
            if ex.open:
                tkeys = [t for t in vd.THEMES if max((c["n"] for c in vd.brand_cells(p, [t], "theme").values()), default=0) >= ebi.MIN_COUNT]
                tcells = vd.brand_cells(p, tkeys, "theme")
                st.caption("One level down. Most cells are under 15 items: counts only.")
                st.plotly_chart(charts.brand_topic_heat(tcells, [b_ for b_ in charts.BRAND_ORDER if (b_ in set(p["brand_std"]))], tkeys, mode),
                                width="stretch", key="bm_brand_theme_heat")
        notes = []
        if len(left):
            notes.append("Not drawn (under 10 on both sides): " + ", ".join(f"{r.group} ({r.n_f} vs {r.n_p})" for r in left.itertuples()) + ".")
        if cat_share and cat_share["n"] >= ebi.MIN_N:
            notes.append(f"Category voice = {cat_share['n']} lens comments naming no brand (mostly YouTube how-tos): topics only.")
        notes.append("Evidence: Level = could be chance; B = real gap in one channel; A = real gap in two channels with 15+ items each.")
        st.caption(" ".join(notes))
        tg = pd.DataFrame({"Group": gt["group"], f"{FOCAL} items": gt["n_f"], "Peer items": gt["n_p"],
                           f"{FOCAL} net": [f"{v:+.0f}" if v is not None and pd.notna(v) else "n<15" for v in gt["net_f"]],
                           "Peers net": [f"{v:+.0f}" if v is not None and pd.notna(v) else "n<15" for v in gt["net_p"]],
                           "Gap (95% interval)": [f"{a:+.0f} ({lo:+.0f} to {hi:+.0f})" if a is not None and pd.notna(a) else "-" for a, lo, hi in zip(gt["gap"], gt["lo"], gt["hi"])],
                           "Evidence": gt["grade"]})
        ui.show_data("Show the group table", tg)
        with st.expander("Show the eight themes under the groups", expanded=False, on_change="rerun", key="bm_theme_tbl") as ex:
            if ex.open:
                tt = vd.theme_table(p)
                th = pd.DataFrame({"Theme": tt["theme"], "Group": tt["group"], f"{FOCAL} items": tt["n_f"], "Peer items": tt["n_p"],
                                   f"{FOCAL} net": [f"{v:+.0f}" if v is not None and pd.notna(v) else "n<15" for v in tt["net_f"]],
                                   "Peers net": [f"{v:+.0f}" if v is not None and pd.notna(v) else "n<15" for v in tt["net_p"]], "Evidence": tt["grade"]})
                st.caption("The same read one level down. Most single themes are under 15 items on a side.")
                st.dataframe(th, hide_index=True, width="stretch")

    # ---- 4. Brand voice -------------------------------------------------------------------------------------------
    with t_voice:
        ui.section((f"{FOCAL}'s own posts are {promo:.0f}% promotion; consumers talk about product and look" if promo is not None and promo >= 50
                    else "What brands post and what people say"),
                   "Own posts by content type, and the topics posted vs the topics consumers raise.",
                   "4 · Brand voice", kind="fact")
        brands_own = [b for b in charts.BRAND_ORDER if (own["owner_brand"] == b).sum() >= ebi.MIN_N]
        c1, c2 = st.columns(2)
        with c1:
            if brands_own:
                fv = go.Figure()
                for ct in CONTENT_ORDER:
                    fv.add_bar(y=[charts.row_label(b, int((own["owner_brand"] == b).sum())) for b in brands_own],
                               x=[(own[own["owner_brand"] == b]["content_type"] == ct).mean() * 100 for b in brands_own], orientation="h",
                               name=CONTENT_LABEL[ct], marker_color=CONTENT_COLOR[ct])
                fv.update_layout(barmode="stack", height=90 + 60 * len(brands_own), legend=dict(orientation="h", y=-0.35, traceorder="normal"),
                                 xaxis=dict(range=[0, 100], title="% of posts"))
                fv.update_yaxes(autorange="reversed")
                small = [b for b in charts.BRAND_ORDER if 0 < (own["owner_brand"] == b).sum() < ebi.MIN_N]
                ui.plot(fv, (f"{promo:.0f}% of {FOCAL}'s own posts are promotions." if promo is not None else "Content type of brands' own posts."), key="bm_voice",
                        note=("Under 15 posts, left out: " + ", ".join(f"{b} ({int((own['owner_brand'] == b).sum())})" for b in small) + ".") if small else "",
                        bases={b: int((own["owner_brand"] == b).sum()) for b in brands_own}, noun="own posts")
        with c2:
            cons_f = p[p["brand_std"] == FOCAL]
            if len(own_f) >= ebi.MIN_N and len(cons_f) >= ebi.MIN_N:
                os_, cs_ = vd.group_share(own_f), vd.group_share(cons_f)
                keys = vd.GROUP_LIST + [vd.NO_THEME]
                fm = go.Figure()
                fm.add_bar(y=keys, x=[os_[k] for k in keys], orientation="h", name=f"{FOCAL} own posts", marker_color="#B7791F",
                           text=[f"{os_[k]:.0f}%" for k in keys], textposition="outside", cliponaxis=False)
                fm.add_bar(y=keys, x=[cs_[k] for k in keys], orientation="h", name=f"Consumers on {FOCAL}", marker_color=BRAND_COLORS[FOCAL],
                           text=[f"{cs_[k]:.0f}%" for k in keys], textposition="outside", cliponaxis=False)
                fm.update_layout(barmode="group", height=350, xaxis_title="% of items that touch the group", legend=dict(orientation="h", y=-0.3, traceorder="normal"))
                fm.update_xaxes(range=[0, max(max(os_[k] for k in keys), max(cs_[k] for k in keys)) * 1.25])
                fm.update_yaxes(autorange="reversed")
                ui.plot(fm, "The topics Acuvue posts about are not the ones consumers raise.", key="bm_gap",
                        note="Promo posts carry no theme: this shows what is posted, not a missed message.",
                        bases={f"{FOCAL} own posts": len(own_f), f"Consumers on {FOCAL}": len(cons_f)}, noun="items")

    # ---- 5. Demand ------------------------------------------------------------------------------------------------
    with t_dem:
        if tf or mf:
            opp = tf and mf and (tf["idx_chg"] > 0) != (mf["units"] > 0)
            ui.section("Search interest and imports point opposite ways: demand is unsettled" if opp else "Demand signals",
                       "Google Trends searches and UN Comtrade imports. Neither is sales.",
                       "5 · Demand", kind="fact")
            cols = st.columns(4)
            if tf:
                cols[0].metric(f"{FOCAL} search interest, {tf['year']}", f"{tf['idx_chg']:+.0f}%", f"vs {tf['prev']}, {tf['window']}", delta_color="off", delta_arrow="off",
                               help="Average Google Trends index, Jan to the latest complete week, against the same days last year.")
                cols[1].metric(f"{FOCAL} share of category searches", f"{tf['share_now']:.0f}%", f"{tf['share_now'] - tf['share_prev']:+.0f} pts vs {tf['prev']}", delta_color="off", delta_arrow="off",
                               help="Acuvue's index as a % of the 'contact lens' index in the same batch and week; a ratio of index values, not market share.")
                cols[2].metric("Category search interest", f"{tf['cat_chg']:+.0f}%" if tf["cat_chg"] is not None else "-", f"vs {tf['prev']}", delta_color="off", delta_arrow="off")
            if mf:
                cols[3].metric("Lens imports (units)", f"{mf['units']:+.0f}%", f"{mf['first']} to {mf['last']}", delta_color="off", delta_arrow="off",
                               help="UN Comtrade, HS 9001.30, Singapore. Singapore also re-exports, so imports only roughly proxy local demand.")
            sc = trends_signals.share_chart()
            if sc:
                fig, weeks = sc
                ui.plot(fig, f"{FOCAL}'s share of category searches has risen since {tf['prev']}." if tf and tf["share_now"] > tf["share_prev"] else f"{FOCAL}'s share of category searches over time.",
                        key="bm_trends", note="4-week average of the brand index as a % of the 'contact lens' index. Imports include re-exports.",
                        bases=f"Google Trends index, no search count disclosed · {weeks} weekly points per term")
            with st.expander("Search demand detail: year-on-year, seasonality, related terms", expanded=False, on_change="rerun", key="bm_trends_detail") as ex:
                if ex.open:
                    trends_signals.render()
        else:
            st.caption("No search or import data is loaded.")

    # ---- Supporting data ------------------------------------------------------------------------------------------
    with st.expander("Supporting data: coverage and method", expanded=False, on_change="rerun", key="bm_support") as ex:
        if ex.open:
            fig, bases, thin = method_page.coverage_figure(p)
            ui.plot(fig, "Brands are heard on different channels: compare only where both sides have 15+ items.", key="bm_cov",
                    note=f"{thin} cells hold 1 to 29 items. Full coverage and label standard: Data & method.",
                    bases=bases, noun="analysed items")
