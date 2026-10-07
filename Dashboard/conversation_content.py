"""
Conversation & content story page: where each brand is talked about and posts content (Xiaohongshu, Reddit,
YouTube, Instagram, Facebook), who gets the attention, what the reaction looks like, and what people discuss.
Same pattern as Brand Health and Journey & barriers: what the data shows -> why it matters -> what insight it
supports -> coverage -> dig deeper.

Two kinds of items are kept apart because they mean different things to a marketer:
  * posts / videos  = content that exists on a channel. On YouTube, Instagram and Facebook much of it is the
    brands' own accounts, so it shows what brands say, not what people say.
  * comments (and Xiaohongshu posts, which are consumer posts) = reaction. Sentiment is read from these only.
"Official account" is a name match (the account name contains the brand name), so it is directional.

Attention is compared inside a channel only, because the unit differs: YouTube views, Instagram / Facebook /
Xiaohongshu likes, Reddit upvotes.
"""

import html

import pandas as pd
import streamlit as st

import brand_health
import charts
import ebi
import insights
import ui
from sg_common import xhs_attributed

CHANNELS = ["Xiaohongshu", "Reddit", "YouTube", "Instagram", "Facebook"]
OWNED_CHANNELS = ["YouTube", "Instagram", "Facebook"]       # brands run official accounts here
REACH_COL = {"YouTube": "view_count", "Instagram": "likes_count", "Facebook": "likes_count", "Reddit": "score"}
UNIT = {"Xiaohongshu": "likes", "Reddit": "upvotes", "YouTube": "views", "Instagram": "likes", "Facebook": "likes"}
NAME_KEYS = {"Acuvue": "acuvue", "Alcon": "alcon", "Bausch & Lomb": "bausch", "CooperVision": "coopervision", "Olens": "olens"}

# What a theme over- or under-index may suggest. Hypotheses to test, not conclusions.
THEME_HINTS = {
    "comfort": "Comfort dominates the talk: lead with all-day comfort proof.",
    "recommendation": "People ask for and give recommendations: creator and optometrist voices may carry weight.",
    "colour": "Colour and look drive cosmetic-lens talk: show colour clearly.",
    "value": "Value is weighed against price: test cost-per-day or trial framing.",
    "brand_comparison": "People compare brands directly: state a clear difference.",
    "vision_clarity": "Clarity resonates: lead with it.",
    "dryness": "Dryness is a pain point: add a comfort or care message.",
    "authenticity": "Authenticity doubts signal a trust issue: make authorised sellers easy to find.",
}


def _prune(key: str, options) -> None:
    cur = st.session_state.get(key)
    if cur is not None and cur not in options:
        del st.session_state[key]


def _pts(v: float) -> str:
    return f"{v:+.0f} pt{'' if round(abs(v)) == 1 else 's'}"


def _is_official(brand: str, account) -> bool:
    key = NAME_KEYS.get(brand)
    return bool(key) and key in str(account or "").lower().replace(" ", "")


def _url(u) -> str | None:
    if not isinstance(u, str) or not u:
        return None
    return "https://www.reddit.com" + u if u.startswith("/r/") else u


def content_frame(xhs: pd.DataFrame, posts: dict, brands: list) -> pd.DataFrame:
    """One row per post / video / thread: source, brand, account, official, attention, title, url, date.
    Xiaohongshu uses brand-attributed posts only (the same rule as Brand Health)."""
    parts = []
    if xhs is not None and not xhs.empty:
        a = xhs_attributed(xhs)
        a = a[a["brand_mentioned"].isin(brands)]
        parts.append(pd.DataFrame({
            "source": "Xiaohongshu", "brand": a["brand_mentioned"].values, "account": a["author"].values,
            "attention": pd.to_numeric(a["likes"], errors="coerce").fillna(0).values,
            "title": a["title"].fillna(a["content_en"]).values, "url": a["url"].values, "date": a["publish_date"].values,
        }))
    for src, df in posts.items():
        if df is None or df.empty:
            continue
        d = df[df["brand"].isin(brands)]
        parts.append(pd.DataFrame({
            "source": src, "brand": d["brand"].values, "account": d["channel_display"].values,
            "attention": pd.to_numeric(d[REACH_COL[src]], errors="coerce").fillna(0).values,
            "title": d["title_display"].values, "url": [_url(u) for u in d["url_display"]],
            "date": pd.to_datetime(d["date"], errors="coerce", utc=True).dt.tz_localize(None).values,
        }))
    if not parts:
        return pd.DataFrame(columns=["source", "brand", "account", "official", "attention", "title", "url", "date"])
    cf = pd.concat(parts, ignore_index=True)
    cf["official"] = [_is_official(b, a) for b, a in zip(cf["brand"], cf["account"])]
    return cf


def _share(cf: pd.DataFrame, brand: str, source: str, col: str = None) -> tuple:
    """(share %, base) of `brand` in `source`: by number of posts, or by summing `col`. Share is None under MIN_N rows."""
    d = cf[cf["source"] == source]
    if len(d) < ebi.MIN_N:
        return None, len(d)
    if col is None:
        return len(d[d["brand"] == brand]) / len(d) * 100, len(d)
    tot = d[col].sum()
    return (d.loc[d["brand"] == brand, col].sum() / tot * 100 if tot else None), len(d)


def _tone(frames: dict, brands: list, source: str) -> tuple:
    """(% positive or neutral, n, dominant brand or None) over the usable labelled items of `brands` in one channel.
    The dominant brand is named when it supplies 60%+ of the pooled items, so a pooled "peers" figure is not misread."""
    a = frames[source]["analysed"]
    a = a[a["brand"].isin(brands) & a["sentiment"].isin(insights.VALID)] if not a.empty else a
    if not len(a):
        return None, 0, None
    top = a["brand"].value_counts()
    dom = top.index[0] if len(brands) > 1 and top.iloc[0] / len(a) >= 0.6 else None
    return a["sentiment"].isin(["positive", "neutral"]).mean() * 100, len(a), dom


def _theme_rows(xhs: pd.DataFrame, focus: str, peers: list) -> pd.DataFrame:
    """Share of the focus brand's vs peers' Xiaohongshu posts that carry each theme (one post can carry several)."""
    a = xhs[xhs["brand_mentioned"].isin([focus] + peers)]
    f, p = a[a["brand_mentioned"] == focus], a[a["brand_mentioned"].isin(peers)]
    nf, npe = len(f), len(p)
    themes = sorted({t for lst in a["themes_list"] for t in lst}) if len(a) else []
    rows = []
    for t in themes:
        kf = int(f["themes_list"].map(lambda l, t=t: t in l).sum())
        kp = int(p["themes_list"].map(lambda l, t=t: t in l).sum())
        sf = kf / nf * 100 if nf >= ebi.MIN_N else float("nan")
        sp = kp / npe * 100 if npe >= ebi.MIN_N else float("nan")
        rows.append({"theme": t, "reason": t.replace("_", " ").capitalize(), "brand_k": kf, "peer_k": kp,
                     "brand_share": sf, "peer_share": sp,
                     "brand_text": f"{sf:.0f}% ({kf})" if nf >= ebi.MIN_N else f"{kf} of {nf}",
                     "peer_text": f"{sp:.0f}% ({kp})" if npe >= ebi.MIN_N else f"{kp} of {npe}",
                     "gap": sf - sp if nf >= ebi.MIN_N and npe >= ebi.MIN_N else float("nan")})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("brand_k", ascending=False).reset_index(drop=True)
    df.attrs["n_focus"], df.attrs["n_peers"] = nf, npe
    return df


def _attention_label(c: str, total: float, n: int) -> str:
    """Channel tick for the attention chart: name, sample size (amber if thin), then the attention total underneath."""
    tot = f"{total:,.0f} {UNIT[c]}" if total else f"no {UNIT[c]} recorded"
    return f'{charts.row_label(c, n)}<br><span style="font-size:10px;color:{charts.MUTED}">{tot}</span>'


def render(selected_brands: list, xhs: pd.DataFrame, posts: dict, social: dict) -> None:
    """posts: {"YouTube": videos_df, "Instagram": posts_df, "Facebook": posts_df, "Reddit": threads_df}
    social: {"Reddit"|"YouTube"|"Instagram"|"Facebook": (comments_df, module)}, as passed to Brand Health."""
    brands = charts.order_brands(selected_brands)
    if not brands:
        st.info("No brands selected.")
        return
    _prune("cc_focus", brands)
    default = insights.FOCAL if insights.FOCAL in brands else brands[0]
    focus = st.segmented_control("Focus brand", brands, default=default, key="cc_focus") or default
    peers = [b for b in brands if b != focus]

    cf = content_frame(xhs, posts, brands)
    frames = insights.build_frames(None, xhs, social)
    cov = insights.coverage(frames, brands)
    foc = cf[cf["brand"] == focus]

    # ---- Story: Pyramid (answer, arguments, action) ------------------------------------------
    fe = html.escape(focus)
    shares = {c: _share(cf, focus, c)[0] for c in CHANNELS}
    known = {c: s for c, s in shares.items() if s is not None}
    hi = max(known, key=known.get) if len(known) >= 2 else None
    lo = min(known, key=known.get) if len(known) >= 2 else None

    o_f = foc[foc["source"].isin(OWNED_CHANNELS)]
    o_p = cf[cf["brand"].isin(peers) & cf["source"].isin(OWNED_CHANNELS)]
    own_f = o_f["official"].mean() * 100 if len(o_f) >= ebi.MIN_N else None
    own_p = o_p["official"].mean() * 100 if len(o_p) >= ebi.MIN_N else None

    att = {}
    for c in CHANNELS:
        sp, sa = _share(cf, focus, c)[0], _share(cf, focus, c, "attention")[0]
        if sp is not None and sa is not None and cf.loc[cf["source"] == c, "attention"].sum():
            att[c] = (sa - sp, sp, sa)
    att_c = max(att, key=lambda k: abs(att[k][0])) if att else None

    tones = []
    for c in CHANNELS:
        tf, nf, _ = _tone(frames, [focus], c)
        tp, npe, dom = _tone(frames, peers, c)
        if tf is not None and tp is not None and nf >= ebi.MIN_N and npe >= ebi.MIN_N:
            tones.append((c, tf, nf, tp, npe, tf - tp, dom))
    gap_lo = min(tones, key=lambda t: t[5]) if tones else None     # where tone trails peers most
    gap_hi = max(tones, key=lambda t: t[5]) if tones else None     # where it leads most
    trail = gap_lo is not None and gap_lo[5] < -5
    lead = gap_hi is not None and gap_hi[5] > 5

    xa0 = xhs_attributed(xhs) if xhs is not None and not xhs.empty else pd.DataFrame()
    xa0 = xa0[xa0["brand_mentioned"].isin(brands)] if not xa0.empty else xa0
    th0 = _theme_rows(xa0, focus, peers) if not xa0.empty else pd.DataFrame()
    th_over = th_under = None
    if not th0.empty and th0.attrs["n_focus"] >= ebi.MIN_N and th0.attrs["n_peers"] >= ebi.MIN_N:
        g0 = th0.dropna(subset=["gap"]).sort_values("gap")
        if len(g0):
            th_over, th_under = g0.iloc[-1], g0.iloc[0]

    if not len(foc):
        answer = f"No {fe} posts collected."
    elif own_f is not None and own_f >= 50:
        answer = (f"{fe}'s social presence is largely brand-run ({own_f:.0f}% of its posts on YouTube, Instagram and Facebook), "
                  "so consumer perception has to be read from comments.")
        if trail:
            answer += f" The exposure is {gap_lo[0]}, where tone trails peers."
    elif trail:
        answer = f"The exposure is {gap_lo[0]}, where consumer tone trails peers."
    elif hi:
        answer = f"{fe} posts most on {hi} ({known[hi]:.0f}% of posts there)."
    else:
        answer = f"{fe} is {len(foc) / len(cf) * 100:.0f}% of all posts."

    args = []
    if len(foc):
        txt = (f"Posts most on {hi} ({known[hi]:.0f}%) and least on {lo} ({known[lo]:.0f}%)." if hi else
               f"{fe} is {len(foc) / len(cf) * 100:.0f}% of all posts.")
        if att_c:
            txt += f" On {att_c}: {att[att_c][1]:.0f}% of posts, {att[att_c][2]:.0f}% of {UNIT[att_c]}."
        brand_run = "Brand-run content dominates" + (f" (peers {own_p:.0f}%)" if own_p is not None else "") + ". " if own_f is not None and own_f >= 50 else ""
        args.append({"label": "Voice", "value": f"{own_f:.0f}% own" if own_f is not None else f"{len(foc):,} posts",
                     "text": f"{brand_run}{txt}", "tone": "watch" if own_f is not None and own_f >= 50 else "flat"})
    if tones:
        def _say(g):
            c, tf, nf, tp, npe, d, dom = g
            return (f"{'above' if d >= 0 else 'below'} peers on {c} ({tf:.0f}% vs {tp:.0f}%"
                    + (f", peers mostly {html.escape(dom)}" if dom else "") + ")")
        if trail and lead:
            r_txt, r_val, r_tone = f"Tone is uneven across channels: {_say(gap_lo)}, {_say(gap_hi)}.", f"{gap_lo[0]} {_pts(gap_lo[5]).replace('-', '−')}", "bad"
        elif trail:
            r_txt, r_val, r_tone = f"Tone trails on one channel: {_say(gap_lo)}.", f"{gap_lo[0]} {_pts(gap_lo[5]).replace('-', '−')}", "bad"
        elif lead:
            r_txt, r_val, r_tone = f"Tone leads on one channel: {_say(gap_hi)}.", f"{gap_hi[0]} {_pts(gap_hi[5])}", "good"
        else:
            r_txt, r_val, r_tone = "Tone is consistent across channels with enough comments.", "Within 5 pts", "flat"
        args.append({"label": "Reaction", "value": r_val, "text": r_txt, "tone": r_tone})
    else:
        args.append({"label": "Reaction", "value": "Too few", "text": "Too few comments to compare with peers.", "tone": "flat"})
    if th_over is not None:
        args.append({"label": "Themes", "value": th_over["reason"],
                     "text": (f"The talk differs on Xiaohongshu: over-indexes ({th_over['brand_share']:.0f}% vs {th_over['peer_share']:.0f}%), "
                              f"under-indexes on {th_under['reason'].lower()} ({th_under['brand_share']:.0f}% vs {th_under['peer_share']:.0f}%)."), "tone": "flat"})

    parts = []
    if own_f is not None and own_f >= 50:
        parts.append("Brand accounts dominate YouTube, Instagram and Facebook, so read comments and Xiaohongshu for consumer views. "
                     "Test creator or optometrist content where earned posts are scarce.")
    if trail:
        parts.append(f"Tone on {gap_lo[0]} trails peers: read those comments first.")
    insight_text = " ".join(parts) or "No clear gap to act on."
    ui.pyramid(answer, args, html.escape(insight_text))

    t_voice = ("Brand-run content dominates" if own_f is not None and own_f >= 50
               else f"{focus} posts most on {hi}" if hi else "Who posts, and who gets the attention")
    t_react = ("Tone is uneven across channels" if trail and lead
               else f"Tone trails on one channel: {gap_lo[0]}" if trail
               else f"Tone leads on one channel: {gap_hi[0]}" if lead
               else "Tone is consistent across channels")
    t_theme = (f"The talk differs on Xiaohongshu: {focus} over-indexes on {th_over['reason'].lower()}"
               if th_over is not None and th_over["gap"] > 0 else "What Xiaohongshu posts talk about")

    # ---- Who is posting, who gets the attention -----------------------------------------------
    ui.section(t_voice, "Share of posts (left) and of attention (right), by channel.",
               "1 · Voice", kind="fact")
    left, right = st.columns(2)
    with left:
        n_posts = cf.groupby("source").size().reindex(CHANNELS, fill_value=0).astype(int).to_dict()
        fig = charts.share_bars(cf.assign(value=1), CHANNELS, brands, height=420)
        p_sh = {c: _share(cf, focus, c)[0] for c in CHANNELS}
        p_sh = {c: s for c, s in p_sh.items() if s is not None}
        top = max(p_sh, key=p_sh.get) if p_sh else None
        ui.plot(fig, f"{focus}'s post share peaks on {top} ({p_sh[top]:.0f}%)." if top else "Share of posts by channel.",
                note="Counts inside bars. Hatched = under 30 items.", key="cc_sov_posts",
                bases=n_posts, noun="posts, videos and threads")
    with right:
        totals = {c: cf.loc[cf["source"] == c, "attention"].sum() for c in CHANNELS}
        labels = {c: _attention_label(c, totals[c], n_posts[c]) for c in CHANNELS}
        fig = charts.share_bars(cf.assign(value=cf["attention"]), CHANNELS, brands, labels=labels, count_text=False, height=420)
        deltas = {}
        for c in CHANNELS:
            sp, sa = _share(cf, focus, c)[0], _share(cf, focus, c, "attention")[0]
            if sp is not None and sa is not None and totals[c]:
                deltas[c] = (sa - sp, sp, sa)
        if deltas:
            c = max(deltas, key=lambda k: abs(deltas[k][0]))
            d, sp, sa = deltas[c]
            say = f"On {c}, {focus} has {sp:.0f}% of posts but {sa:.0f}% of {UNIT[c]}."
        else:
            say = "Share of attention by channel."
        ui.plot(fig, say, note="Attention = views (YouTube), likes (Instagram, Facebook, Xiaohongshu), upvotes (Reddit). Compare within a channel only.",
                key="cc_sov_attn", bases=n_posts, noun="posts behind the attention")
    missing = [f"{b} on {c}" for c in CHANNELS for b in brands if cf[(cf["source"] == c) & (cf["brand"] == b)].empty]
    if missing:
        st.caption("No posts for: " + "; ".join(missing) + " (none collected, or all off-brand or non-Singapore).")

    # ---- Owned vs everyone else ------------------------------------------------------------------
    ui.section(f"{own_f:.0f}% of {focus}'s posts on YouTube, Instagram and Facebook are its own" if own_f is not None else "Own accounts vs everyone else",
               "Official = account name contains the brand name.",
               "1 · Voice", kind="fact")
    rows = []
    for b in brands:
        r = {"Brand": b}
        for c in CHANNELS:
            d = cf[(cf["source"] == c) & (cf["brand"] == b)]
            r[c] = charts.NO_DATA if d.empty else (f"{int(d['official'].sum())} of {len(d)} official" if d["official"].any() else f"None of {len(d)} official")
        rows.append(r)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("A post is credited to the brand it discusses, so an account can appear under a rival it compares.")

    # ---- How people react --------------------------------------------------------------------------
    ui.section(t_react, "Comments; for Xiaohongshu, posts.",
               "2 · Reaction", kind="fact")
    grid = st.columns(2)
    for i, c in enumerate(CHANNELS):
        a = frames[c]["analysed"]
        a = a[a["brand"].isin(brands)] if not a.empty else a
        collected = {b: int(frames[c]["collected"].get(b, 0)) for b in brands}
        r = cov[(cov["brand"] == focus) & (cov["source"] == c)].iloc[0]
        noun = "posts" if c == "Xiaohongshu" else "comments"
        if r["status"] == "ok" and r["scored_n"] >= ebi.MIN_N:
            say = f"{c}: {r['pos_neu']:.0f}% positive or neutral for {focus}."
        elif r["collected"] == 0:
            say = f"{c}: {charts.NO_DATA.lower()} for {focus}."
        else:
            say = f"{c}: {charts.thin_label(int(r['scored_n']), int(r['collected'])).lower()} for {focus}."
        with grid[i % 2]:
            n_by = a.groupby("brand").size().reindex(brands, fill_value=0).astype(int).to_dict() if not a.empty else {b: 0 for b in brands}
            ui.plot(charts.sentiment_mix(a, "brand", brands, height=60 + 52 * len(brands), collected=collected), say,
                    note="Hatched = under 30 items.", key=f"cc_mix_{c}",
                    bases=n_by, noun=f"labelled {noun}")
            st.caption(insights.scope_note(cov[cov["source"] == c], [c]))

    # ---- What people talk about (XHS themes) ---------------------------------------------------------
    ui.section(t_theme, "Xiaohongshu is the only channel with themes; one post can carry several.",
               "3 · Themes", kind="fact")
    xa = xhs_attributed(xhs) if xhs is not None and not xhs.empty else pd.DataFrame()
    xa = xa[xa["brand_mentioned"].isin(brands)] if not xa.empty else xa
    th = _theme_rows(xa, focus, peers) if not xa.empty else pd.DataFrame()
    if th.empty:
        st.info("No themed Xiaohongshu posts for the current selection.")
    else:
        nf, npe = th.attrs["n_focus"], th.attrs["n_peers"]
        view = th.head(8).copy()
        view[["brand_share", "peer_share"]] = view[["brand_share", "peer_share"]].fillna(0)
        if nf >= ebi.MIN_N and npe >= ebi.MIN_N:
            g = th.dropna(subset=["gap"]).sort_values("gap")
            over, under = g.iloc[-1], g.iloc[0]
            say = (f"{focus} over-indexes on {over['reason'].lower()} ({over['brand_share']:.0f}% vs {over['peer_share']:.0f}%)"
                   f" and under-indexes on {under['reason'].lower()} ({under['brand_share']:.0f}% vs {under['peer_share']:.0f}%).")
            if over["gap"] <= 0 or under["gap"] >= 0:
                say = f"{focus} and peers discuss similar themes; widest gap: {g.iloc[g['gap'].abs().argmax()]['reason'].lower()}."
            ui.plot(charts.gap_bars(view, focus, axis_title="Share of posts carrying the theme", n_brand=nf, n_peers=npe), say,
                    note="Counts in brackets.", key="cc_themes",
                    bases={focus: nf, "Peers": npe}, noun="Xiaohongshu posts")
            hint = THEME_HINTS.get(th.iloc[0]["theme"])
            if hint:
                ui.takeaway(html.escape(hint), "dir")
        else:
            st.dataframe(view[["reason", "brand_text", "peer_text"]].rename(columns={
                "reason": "Theme", "brand_text": f"{focus} (count of {nf})", "peer_text": f"Peers (count of {npe})"}),
                hide_index=True, width="stretch")
            ui.n_strip({focus: nf, "Peers": npe}, noun="Xiaohongshu posts")
            st.caption(f"Under {ebi.MIN_N} items: counts only.")

    # ---- Coverage ---------------------------------------------------------------------------------------
    with st.expander("Coverage: analysed of collected, by brand and channel", expanded=False):
        st.caption(insights.scope_note(cov, CHANNELS))
        st.dataframe(brand_health._coverage_grid(cov, brands, CHANNELS), hide_index=True, width="stretch")
        st.caption("Off-brand, non-Singapore and off-topic items are removed first. "
                   f"“{charts.NO_DATA}” = nothing scraped. “Too few to score” = under {insights.MIN_SOURCE_N} labelled items.")

    # ---- Dig deeper ---------------------------------------------------------------------------------------
    with st.expander(f"Who is posting about {focus}: accounts", expanded=False):
        if foc.empty:
            st.info(f"No {focus} posts collected.")
        else:
            acc = (foc.groupby(["source", "account"], dropna=False)
                   .agg(Posts=("title", "size"), Attention=("attention", "sum"), Official=("official", "max")).reset_index())
            acc["Attention"] = [f"{v:,.0f} {UNIT[s]}" for v, s in zip(acc["Attention"], acc["source"])]
            acc["Official"] = acc["Official"].map({True: "Yes", False: "No"})
            acc["account"] = acc["account"].fillna("unknown")
            acc = acc.sort_values("Posts", ascending=False).head(25)
            st.dataframe(acc.rename(columns={"source": "Channel", "account": "Account / community"}), hide_index=True, width="stretch", height=320)
            st.caption("Top 25 by posts; Reddit shows the subreddit.")

    with st.expander(f"{focus}: most-attended posts", expanded=False):
        if foc.empty:
            st.info(f"No {focus} posts collected.")
        else:
            top = (foc.sort_values("attention", ascending=False).groupby("source").head(5)
                   .assign(Attention=lambda d: [f"{v:,.0f} {UNIT[s]}" for v, s in zip(d["attention"], d["source"])]))
            st.dataframe(top[["source", "account", "title", "Attention", "url"]].rename(columns={
                "source": "Channel", "account": "Account", "title": "Post", "url": "Link"}),
                hide_index=True, width="stretch", height=360,
                column_config={"Link": st.column_config.LinkColumn("Link", display_text="Open ↗")})
            st.caption("Top 5 per channel; compare within a channel only.")
