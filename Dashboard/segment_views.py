"""Segment study views (Consumer Intel pack): the new-wearer search direction and how AI engines describe each segment.

search_direction()  Demand Trends > Demand Signals, after the category search block.
ai_answers()        Demand Trends > AI Answers sub-tab.
Both read segment_data only; neither counts anything as consumer voice.
"""

import palette
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import ebi
import segment_data as sd
import ui
from sg_common import BRAND_COLORS

LINE = palette.FOCAL_COLOR


def _pct(x) -> str:
    return f"{x:+.0f}%"


def search_direction() -> None:
    """Which segments people search for, as a direction for new wearers. Only terms with MIN_N active weeks are drawn."""
    t = sd.term_table()
    if t.empty:
        return
    ok = t[t["Readable"]]
    thin = t[~t["Readable"]]
    st.divider()
    ui.part("New-wearer direction")
    st.markdown("**What people who are not yet wearers search for**")
    st.caption("Google Trends, Singapore, weekly, from the segment study (a separate request from the brand terms above, so its index is "
               "not comparable with them). Relative interest, not search volume, and interest is not buying.")
    if ok.empty:
        st.info(f"No segment term has searches in {ebi.MIN_N} or more weeks.")
    else:
        s = sd.search()
        fig = make_subplots(rows=1, cols=len(ok), subplot_titles=[f"{r.Term} ({r.Segment})" for r in ok.itertuples()], shared_yaxes=False)
        for i, r in enumerate(ok.itertuples(), start=1):
            m = s[s["term"] == r.Term].copy()
            m["month"] = m["date"].dt.to_period("M").dt.to_timestamp()
            m = m.groupby("month", as_index=False)["value"].mean()
            fig.add_trace(go.Scatter(x=m["month"], y=m["value"], mode="lines", line=dict(color=LINE, width=2), showlegend=False,
                                     hovertemplate="%{x|%b %Y}: %{y:.0f}<extra></extra>"), row=1, col=i)
            fig.update_yaxes(range=[0, 105], gridcolor="rgba(148,163,184,.25)", row=1, col=i)
            fig.update_xaxes(showgrid=False, row=1, col=i)
        fig.update_layout(margin=dict(t=40))   # room for the panel titles under the lead sentence
        rise = ok[ok["Change"] > 10]
        flat = ok[ok["Change"].abs() <= 10]
        parts = [f"{r.Term} searches are {_pct(r.Change)} on the year before" for r in rise.itertuples()]
        parts += [f"{r.Term} searches are steady ({_pct(r.Change)})" for r in flat.itertuples()]
        parts += [f"{r.Term} searches are down {_pct(r.Change)}" for r in ok[ok["Change"] < -10].itertuples()]
        ui.plot(fig, "; ".join(parts)[0].upper() + "; ".join(parts)[1:] + ".", "fact", height=300, key="seg_search",
                bases={r["Term"]: int(r["Weeks with searches"]) for _, r in ok.iterrows()}, noun="weeks with searches",
                note="Monthly average of weekly values; each panel is its own 0-100 scale. Last 52 weeks against the 52 before.")
        grow = [f"{r.Segment} ({r.Term})" for r in rise.itertuples()]
        if grow:
            ui.takeaway(f"Interest is growing among {', '.join(grow)}, the clearest pool of people who may start wearing lenses "
                        "(a multifocal trial and fitting message). " + (
                            f"Interest among {', '.join(f'{r.Segment} ({r.Term})' for r in flat.itertuples())} is steady, so it stays the "
                            "standing alternative to lenses." if len(flat) else ""), "dir")
    if len(thin):
        st.caption(f"{len(thin)} other segment search terms are under {ebi.MIN_N} weeks with searches ({', '.join(sorted(set(thin['Segment'])))}), "
                   "so they are not drawn: read them as no usable search signal in Singapore, not as no interest.")
    ui.show_data("Show the search terms and their change", t.assign(Change=t["Change"].map(lambda x: "" if pd.isna(x) else _pct(x)))
                 .drop(columns="Readable"))
    c1, c2 = st.columns(2)
    with c1:
        ui.goto("Social Signals", "New wearers: first-time buyers in reviews", key="seg_to_newwearers",
                sub="New Wearers", sub_key="social_subtabs")
    with c2:
        ui.goto("Demand Trends", "AI Answers: how AI engines describe each segment", key="seg_to_ai",
                sub="AI Answers", sub_key="trends_subtabs")


def ai_answers() -> None:
    """One row per segment: what the engines say first, and the pages they send readers to. Labelled as AI answers, not consumers."""
    a = sd.ai_answers()
    if a.empty:
        st.info("No AI answers loaded.")
        return
    ui.subheader("AI answers point readers to health portals, clinics and brand sites",
                 "ChatGPT search and Perplexity, Singapore, one brand-free question per segment, 2026-10-28. These are AI answers, not "
                 "consumers: they show how a person asking the question would be answered, and which pages they would be sent to.",
                 "AI answers by segment", kind="fact")
    dom = sd.domain_table(a)
    brand_sites = dom[dom["Domain"].str.contains("acuvue|coopervision|myalcon|bausch|olens", case=False)]
    top = dom.head(10).set_index("Domain")["Answers"]
    colour = [BRAND_COLORS["Acuvue"] if "acuvue" in d else palette.RULE for d in top.index]
    fig = go.Figure(go.Bar(x=top.values[::-1], y=top.index[::-1], orientation="h", marker_color=colour[::-1],
                           text=top.values[::-1], textposition="outside", cliponaxis=False))
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(autorange=True), bargap=0.35)
    n_ac = int(brand_sites.loc[brand_sites["Domain"].str.contains("acuvue", case=False), "Answers"].sum())
    n_oth = int(brand_sites["Answers"].sum() - n_ac)
    ui.plot(fig, f"Pages cited in {len(a)} answers: acuvue.com is cited {n_ac} times, other lens-brand sites {n_oth}; the other cited pages are mainly health "
            "portals, clinics and optical chains.", "fact", height=320, key="seg_ai_domains",
            bases={"ChatGPT search": int((a['engine'] == 'chatgpt_search').sum()), "Perplexity": int((a['engine'] == 'perplexity_web').sum())},
            noun="answers", note="The ten most-cited domains. Perplexity hides some sources behind a count, so citations are a floor.")
    _barriers(a)
    _brands()
    st.markdown("**What the engines say, by segment**")
    for seg, g in a.groupby("segment_label", sort=False):
        first = g.sort_values("engine").iloc[0]
        with st.container(border=True):
            st.markdown(f"**{seg}** · {len(g)} answers")
            st.caption(first["prompt"])
            st.write(first["answer"])
    ui.show_data("Show the cited domains", dom)
    ui.read_proof(a, "Read the AI answers behind this section", {"Segment": "segment_label", "Engine": "engine_label",
                                                                 "Question": "prompt", "Answer": "answer_text"}, key="seg_ai_proof", link="link")


def _barriers(a: pd.DataFrame) -> None:
    """Barrier labels the answers name per segment (hand-read, one barrier list). Product & look is set aside, as on the other barrier charts."""
    b = sd.barrier_table()
    if b.empty:
        return
    skip = ["Product experience", "Colour & look (cosmetic lenses)", "Other / unclear"]
    shown = b[~b["Barrier"].isin(skip)]
    aside = int(b[b["Barrier"].isin(skip[:2])]["Answers naming it"].sum())
    pv = shown.pivot_table(index="Segment", columns="Barrier", values="Answers naming it", aggfunc="sum").fillna(0).astype(int)
    pv = pv.reindex([s for s in sd.SEGMENTS.values() if s in pv.index])
    reads = b.groupby("Segment")["Answers read"].first()
    st.markdown("**What the answers name as the barrier**")
    st.caption(f"Read by hand from the {len(a)} answers and mapped to the one barrier list. Product & look is set aside here "
               f"({aside} mentions across segments); the table behind the click has every row.")
    order = list(pv.sum(axis=0).sort_values(ascending=False).index)
    fig = go.Figure()
    for k_, seg in enumerate(pv.index):
        v = [int(pv.loc[seg, b_]) for b_ in order]
        fig.add_bar(y=order, x=[x or None for x in v], orientation="h", name=seg, marker_color=palette.SERIES[list(sd.SEGMENTS.values()).index(seg) % len(palette.SERIES)],
                    marker_pattern_shape=["/" if 0 < x < 3 else "" for x in v],
                    text=[str(x) if x else "" for x in v], textposition="inside", textfont=dict(color=palette.WHITE, size=11),
                    hovertemplate="%{y} / " + seg + ": %{x} answers<extra></extra>")
    for b_ in order:
        fig.add_annotation(x=int(pv[b_].sum()), y=b_, text=f"<b>{int(pv[b_].sum())}</b>", showarrow=False, xanchor="left", xshift=6, font=dict(size=12))
    fig.update_xaxes(title="Answers naming the barrier", range=[0, int(pv.sum(axis=0).max()) * 1.15 + 1])
    fig.update_yaxes(autorange="reversed", title=None, categoryorder="array", categoryarray=order)
    fig.update_layout(barmode="stack", height=130 + 56 * len(order), legend=dict(orientation="h", y=-0.25, title_text=""))
    top = shown.sort_values("Answers naming it", ascending=False)
    lead = top.iloc[0]
    ui.plot(fig, f"{lead['Barrier']} is the most-named barrier: {int(lead['Answers naming it'])} of {int(lead['Answers read'])} answers "
            f"for {lead['Segment'].lower()}.", "fact", key="seg_ai_barriers",
            bases={k: int(v) for k, v in reads.items()}, noun="answers read",
            note="Counts of answers (each segment has six) that name the barrier, stacked by segment; hatched = under 3. A reference lens: AI engines summarising local sources, not consumers, and not added to the desk-research claims.")
    ui.show_data("Show every barrier row with its answer ids", b.drop(columns="Theme").assign(ids=b["ids"].map(", ".join)))


def _brands() -> None:
    """Where the engines name ACUVUE, and where a peer lens brand instead."""
    t = sd.acuvue_named()
    if t.empty:
        return
    t = t.sort_values("Acuvue", ascending=False)
    fig = go.Figure()
    fig.add_bar(y=t["Segment"], x=t["Acuvue"], name="Names ACUVUE", orientation="h", marker_color=BRAND_COLORS["Acuvue"])
    fig.add_bar(y=t["Segment"], x=t["Peer"], name="Names a peer lens brand", orientation="h", marker_color=palette.RULE)
    fig.update_layout(barmode="group", yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=1.12, x=0, title_text=""), height=340)
    none = t[t["Acuvue"] == 0]["Segment"].tolist()
    ui.plot(fig, f"ACUVUE is named in {int(t['Acuvue'].sum())} of {int(t['Answers'].sum())} answers, for " + ", ".join(t[t["Acuvue"] > 0]["Segment"].str.lower())
            + (f"; it is absent for {', '.join(s.lower() for s in none)}." if none else "."), "fact", key="seg_ai_brands",
            bases={r["Segment"]: int(r["Answers"]) for _, r in t.iterrows()}, noun="answers",
            note="Counted by name match (ACUVUE, MyACUVUE, Abiliti against Dailies, Air Optix, Precision1, MiSight, Clariti, MyDay, Proclear and the peer company names). The questions never name a brand.")


def reference_voice() -> None:
    """New Wearers: what viewers elsewhere ask and fear. A sixth lens, never pooled, never a rate, never a Singapore figure."""
    allc, d = sd.reference_all(), sd.reference_voice()
    allc = allc[~allc["source"].str.startswith("Reddit")]
    if d.empty:
        return
    st.divider()
    n_tt = int(d["source"].str.startswith("TikTok").sum())
    ui.subheader("Viewers elsewhere ask about handling, comfort and who will fit the lens", "YouTube and TikTok comments found by the segment "
                 "searches, tagged by the same model and themes. The YouTube videos carry no Singapore signal, so country is unknown"
                 + (f" ({n_tt} TikTok comments come from videos with a Singapore tag)" if n_tt else "")
                 + ". This is what people in similar situations ask and fear, not Singapore, and it is in no Singapore figure. Counts and quotes only.",
                 "Reference voice (not Singapore)", kind="fact")
    segs = [x for x in list(sd.SEGMENTS.values()) + ["No segment (brand search)"] if x in set(d["segment_label"])]
    pick = st.pills("Found by the search for", segs, selection_mode="multi", key="ref_seg") or segs
    d = d[d["segment_label"].isin(pick)]
    st.caption(f"{len(d)} of {int(allc['segment_label'].isin(pick).sum())} comments read: the rest have no theme or are chatter or off-topic. "
               "The segment is the search that found the comment, not who wrote it.")
    ex = d.explode("themes")
    ex["complaint"] = [p.get(t) in ("negative", "mixed") for p, t in zip(ex["pol"], ex["themes"])]
    tc = ex.groupby("themes").agg(total=("item_id", "size"), complaints=("complaint", "sum")).sort_values("total", ascending=False)
    drawn, small = tc[tc["total"] >= ebi.MIN_COUNT], tc[tc["total"] < ebi.MIN_COUNT]
    if len(drawn):
        fig = go.Figure()
        for name, vals, col in (("Complaint (negative or mixed)", drawn["complaints"], palette.NEG_COLOR), ("Praise or neutral", drawn["total"] - drawn["complaints"], palette.RULE)):
            fig.add_bar(y=drawn.index, x=vals, name=name, orientation="h", marker_color=col,
                        marker_pattern_shape=["/" if t < 30 else "" for t in drawn["total"]])
        fig.update_layout(barmode="stack", yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=1.12, x=0, title_text=""), height=320)
        top = drawn.index[0]
        ui.plot(fig, f"{top} is raised in {int(drawn.iloc[0]['total'])} of {len(d)} comments, {int(drawn.iloc[0]['complaints'])} of them as a complaint.",
                "fact", key="ref_themes", bases={"comments read": len(d)}, noun="comments",
                note=("Hatched = 10 to 29 comments (directional). " + (f"Under {ebi.MIN_COUNT}, not drawn: " + ", ".join(f"{k} ({int(v)})" for k, v in small["total"].items()) + "." if len(small) else "")))
    stage = d[d["journey_stage"].isin(sd.STAGES)]["journey_stage"].value_counts().reindex(sd.STAGES).fillna(0).astype(int)
    if stage.sum():
        fig = go.Figure(go.Bar(x=stage.index, y=stage.values, marker_color=palette.FOCAL_COLOR, text=stage.values, textposition="outside", cliponaxis=False))
        fig.update_layout(height=280, yaxis=dict(visible=False))
        ui.plot(fig, f"Where these viewers are: most name {stage.idxmax()} ({int(stage.max())} of {int(stage.sum())} that name a stage).", "fact",
                key="ref_stage", bases={"comments naming a stage": int(stage.sum())}, noun="comments",
                note=f"Stage is read from the comment text; {len(d) - int(stage.sum())} of {len(d)} name none. Counts, not rates.")
    tone = d["sentiment"].value_counts()
    st.caption("Tone of the comments read (counts): " + ", ".join(f"{k} {int(tone.get(k, 0))}" for k in ["negative", "mixed", "neutral", "positive"]) + ".")
    ui.read_proof(d.assign(Themes=d["themes"].map(", ".join), Date=d["date"].dt.strftime("%Y-%m-%d")), "Read the comments behind this section (not Singapore)",
                  {"Date": "Date", "Found by": "segment_label", "Source": "source", "Tone": "sentiment", "Themes": "Themes", "Stage": "journey_stage",
                   "Comment": "text", "Video": "video_title"}, key="ref_proof")
    _singapore_reddit(d)


def _theme_counts(d: pd.DataFrame) -> pd.DataFrame:
    ex = d.explode("themes").dropna(subset=["themes"])
    ex["complaint"] = [p.get(t) in ("negative", "mixed") for p, t in zip(ex["pol"], ex["themes"])]
    return ex.groupby("themes").agg(total=("item_id", "size"), complaints=("complaint", "sum")).sort_values("total", ascending=False)


def _singapore_reddit(ref: pd.DataFrame) -> None:
    """Singapore Reddit posts beside the reference themes: is what viewers elsewhere raise also raised in Singapore?"""
    sg = sd.singapore_posts()
    if sg.empty:
        return
    q = int((sg["content_type"] == "question").sum())
    tc = _theme_counts(sg[sg["themes"].map(len) > 0])
    st.markdown("**Seen in Singapore? Reddit posts on the same themes**")
    st.caption(f"{len(sg)} Singapore Reddit posts that name contact lenses or refractive surgery (askSingapore, NationalServiceSG, SGExams and others), "
               "last 24 months, posts only, partial export: comments and several eye-care subreddits are missing. Tagged by the same model.")
    drawn = tc[tc["total"] >= ebi.MIN_COUNT]
    if len(drawn):
        fig = go.Figure()
        for name, vals, col in (("Complaint (negative or mixed)", drawn["complaints"], palette.NEG_COLOR), ("Praise or neutral", drawn["total"] - drawn["complaints"], palette.RULE)):
            fig.add_bar(y=drawn.index, x=vals, name=name, orientation="h", marker_color=col,
                        marker_pattern_shape=["/" if t < 30 else "" for t in drawn["total"]])
        fig.update_layout(barmode="stack", yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=1.12, x=0, title_text=""), height=240)
        ui.plot(fig, f"Singapore Reddit raises {drawn.index[0]} most ({int(drawn.iloc[0]['total'])} of {len(sg)} posts); {q} of {len(sg)} posts are questions.",
                "fact", key="ref_sg_themes", bases={"Singapore Reddit posts": len(sg)}, noun="posts",
                note="Hatched = 10 to 29 (directional). Under " + str(ebi.MIN_COUNT) + " are in the table behind the click.")
    stage = sg[sg["journey_stage"].isin(sd.STAGES)]["journey_stage"].value_counts()
    if stage.sum():
        st.caption("Stage named in the post (counts): " + ", ".join(f"{k} {int(v)}" for k, v in stage.items()) + f"; {len(sg) - int(stage.sum())} name none.")
    both = pd.DataFrame({"Reference voice (not Singapore)": _theme_counts(ref)["total"], "Singapore Reddit posts": tc["total"]}).fillna(0).astype(int)
    both["Reading"] = [("Seen in Singapore" if sgn >= ebi.MIN_COUNT else f"Seen, but under {ebi.MIN_COUNT} posts" if sgn else "Not seen in Singapore posts yet")
                       if refn >= ebi.MIN_COUNT else "Too few to compare" for refn, sgn in zip(both.iloc[:, 0], both.iloc[:, 1])]
    ui.show_data("Show the themes side by side", both.reset_index().rename(columns={"index": "Theme", "themes": "Theme"}),
                 "Counts on different bases (comments vs posts): compare presence, not size.")
    ui.read_proof(sg.assign(Themes=sg["themes"].map(", ".join), Date=sg["date"].dt.strftime("%Y-%m-%d")), "Read the Singapore Reddit posts behind this",
                  {"Date": "Date", "Subreddit": "video_title", "Found by": "segment_label", "Tone": "sentiment", "Themes": "Themes", "Stage": "journey_stage", "Post": "text"},
                  key="ref_sg_proof")
