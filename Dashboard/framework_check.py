"""
Research check: the Category users and barrier framework (desk research, Research runs 1 to 4) laid over the
scraped comments, by journey stage. Section 4 of the Journey & barriers page.

The framework used to sit on its own in Positioning as three strips. Its stages are the dashboard's journey
stages and its barriers are the set-B barrier types (barrier_taxonomy.TYPES_B), so each research claim becomes a
cell (barrier x stage) that the scraped data can confirm or not. Each cell gets one verdict:
  Confirmed               the research names it and it carries SHARE_MIN% or more of that stage's flagged items
  Seen at <stage> instead the research names it, the data shows it at a different stage
  Not seen                the research names it, the stage has enough items, the data does not show it
  Too few items to test   the stage has under ebi.MIN_N flagged items
  Data only               the data shows it and no research row covers it
Scraped comments carry no persona tag, so the persona picker filters the research markers only.
The numbers behind the research markers come from the "Barriers by stage" tables in
analysis/4_persona_barrier_framework.md; levels follow the same rubric: 3 High, 2 Medium, 1 Low.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import barrier_taxonomy
import charts
import ebi
import insights
import ui
from sg_common import JOURNEY_STAGES

SHARE_MIN = 10     # % of a stage's flagged items a barrier needs to count as seen
LEVEL = {1: "Low", 2: "Medium", 3: "High"}
USERS = ["Existing wearers", "New wearers", "Active considerers"]
INK = "#051F4A"

# (category user, stage, set-B barrier, confidence level, what the research says, source IDs)
RESEARCH = [
    ("Existing wearers", "Engagement", "Registration / login friction", 2, "OTP, login and eligibility gating", "R4-C-03, C-04, C-05, C-15"),
    ("Existing wearers", "Consideration", "Price & channel cost", 2, "Compares cost across stores, online and Johor Bahru", "R4-C-06; R3-C-21"),
    ("Existing wearers", "Purchase", "Loyalty & rewards", 2, "Points earned only at the chosen store; other purchases earn nothing", "R4-C-11, C-12"),
    ("Existing wearers", "Repeat/Retention", "Product experience", 2, "Dryness and discomfort", "R1-C-24"),
    ("Existing wearers", "Repeat/Retention", "Loyalty & rewards", 2, "Store-binding and points freezing", "R4-C-13"),
    ("Existing wearers", "Repeat/Retention", "App utility & support", 1, "App seen as a points tracker", "R4-C-14"),
    ("Existing wearers", "Repeat/Retention", "Price & channel cost", 1, "Price-driven re-use of dailies", "R3-C-09, C-10"),
    ("New wearers", "Consideration", "Fear / handling difficulty", 2, "Fear of infection; lens rolling behind the eye", "R4-C-08; R1-C-06"),
    ("New wearers", "Trial", "Fear / handling difficulty", 2, "Handling and orientation difficulty after teaching", "R4-C-08"),
    ("New wearers", "Trial", "Lack of professional guidance", 1, "Thin fitting; free teaching tied to a 2-box minimum", "R4-C-09, C-10; R3-C-02"),
    ("New wearers", "Purchase", "Price & channel cost", 2, "Own-brand clear lenses about S$1 against about S$2.03 for ACUVUE 1-Day Moist", "R3-C-01, C-04"),
    ("New wearers", "Purchase", "Loyalty & rewards", 2, "Welcome rewards range from S$20 to S$60", "R2-C-13"),
    ("New wearers", "Repeat/Retention", "Product experience", 2, "First-year dropout: vision, discomfort (non-SG)", "R1-C-14"),
    ("New wearers", "Repeat/Retention", "Fear / handling difficulty", 2, "Handling is 15% to 25% of dropout reasons (non-SG)", "R1-C-14"),
    ("Active considerers", "Awareness", "Lack of professional guidance", 2, "Few are told they are candidates; information comes from providers", "R1-C-02; R4-C-07"),
    ("Active considerers", "Consideration", "Fear / handling difficulty", 2, "Fear of touching the eye; handling anxiety", "R1-C-06, C-07; R4-C-08"),
    ("Active considerers", "Consideration", "Lack of professional guidance", 2, "No ECP prompt; ECPs default to spectacles", "R1-C-09, C-10, C-11"),
    ("Active considerers", "Consideration", "Availability & where to buy", 2, "Cosmetic lenses listed widely and cheaply outside ECPs", "SC-PRD; R3-C-20"),
    ("Active considerers", "Consideration", "Price & channel cost", 2, "Myopia-control cost (parents)", "R3-C-20"),
    ("Active considerers", "Purchase", "Availability & where to buy", 1, "Cosmetic buying outside the ECP channel (S$5 to S$36 per listing)", "SC-PRD"),
]


def tally(jf_all: pd.DataFrame, skip_sources: set) -> tuple:
    """Flagged items per stage (the base) and per barrier x stage. An item counts once per stage it is tagged and
    once per barrier it carries, so a row can overlap with another. The MyACUVUE app is included: the framework's
    registration and loyalty barriers are about that app."""
    d = jf_all[(jf_all["is_barrier"] == 1) & ~jf_all["source"].isin(skip_sources)]
    d = d.drop_duplicates(["source", "brand", "text", "journey_stage"])
    base = d.groupby("journey_stage").size().reindex(JOURNEY_STAGES, fill_value=0)
    ex = d.assign(barrier=d["text"].map(barrier_taxonomy.classify_b)).explode("barrier").reset_index(drop=True)
    k = pd.crosstab(ex["barrier"], ex["journey_stage"]).reindex(columns=JOURNEY_STAGES, fill_value=0)
    return base, k, int((d["source"] == insights.APP_SOURCE).sum())


def _count(k: pd.DataFrame, barrier: str, stage: str) -> int:
    return int(k.at[barrier, stage]) if barrier in k.index else 0


def _seen(base: pd.Series, k: pd.DataFrame, barrier: str, stage: str) -> bool:
    return base[stage] >= ebi.MIN_N and _count(k, barrier, stage) / base[stage] * 100 >= SHARE_MIN


def _verdict(base, k, barrier: str, stage: str) -> str:
    if base[stage] < ebi.MIN_N:
        return "Too few items to test"
    if _seen(base, k, barrier, stage):
        return "Confirmed"
    elsewhere = [s for s in JOURNEY_STAGES if s != stage and _seen(base, k, barrier, s)]
    return f"Seen at {elsewhere[0]} instead" if elsewhere else "Not seen"


def summary(jf_all: pd.DataFrame, skip_sources: set) -> dict:
    """Counts for the page summary: all categories of user, so the number does not move with the picker."""
    base, k, _ = tally(jf_all, skip_sources)
    cells = {(b, s) for _, s, b, *_ in RESEARCH}
    testable = [c for c in cells if base[c[1]] >= ebi.MIN_N]
    confirmed = [c for c in testable if _seen(base, k, *c)]
    thin = [s for s in JOURNEY_STAGES if base[s] < ebi.MIN_N and any(c[1] == s for c in cells)]
    return {"confirmed": len(confirmed), "testable": len(testable), "untested": len(cells) - len(testable), "thin_stages": thin}


def _pick_cells(users: list) -> dict:
    cells: dict = {}
    for u, s, b, lvl, note, ids in RESEARCH:
        if u in users:
            cells.setdefault((b, s), []).append((u, lvl, note, ids))
    return cells


def _heat(base: pd.Series, k: pd.DataFrame, rows: list, cells: dict) -> go.Figure:
    stages = JOURNEY_STAGES
    thin = [base[s] < ebi.MIN_N for s in stages]
    n_r = len(rows)
    z, text, hover = [], [], []
    for b in reversed(rows):
        zr, tr, hr = [], [], []
        for j, s in enumerate(stages):
            kk = _count(k, b, s)
            zr.append(None if thin[j] else kk / base[s] * 100)
            tr.append(str(kk) if kk else "")
            share = "" if thin[j] or not base[s] else f" ({kk / base[s] * 100:.0f}% of the stage's flagged items)"
            hr.append(f"{b}<br>{s}: {kk} of {int(base[s])} flagged items{share}")
        z.append(zr); text.append(tr); hover.append(hr)
    fig = go.Figure(go.Heatmap(
        z=z, x=list(range(len(stages))), y=list(range(n_r)), customdata=hover,
        hovertemplate="%{customdata}<extra></extra>", xgap=3, ygap=3, zmin=0, zmax=max([30.0] + [v for r in z for v in r if v is not None]),
        colorscale=["#F8F8F8", "#178197", INK], colorbar=dict(title="% of stage", thickness=10, len=0.6),
    ))
    for yi, tr in enumerate(text):                     # counts as annotations so the colour can follow the cell shade
        for j, t in enumerate(tr):
            if t:
                dark = z[yi][j] is not None and z[yi][j] >= 22
                fig.add_annotation(x=j, y=yi, text=t, showarrow=False, font=dict(size=12, color="white" if dark else "#191919"))
    for j, t in enumerate(thin):                       # stages under MIN_N: counts only, shaded amber
        if t:
            fig.add_shape(type="rect", x0=j - 0.5, x1=j + 0.5, y0=-0.5, y1=n_r - 0.5, fillcolor="rgba(183,121,31,0.08)",
                          line_width=0, layer="below")
    for lvl, symbol, size, fill in ((3, "diamond", 17, INK), (2, "diamond", 14, INK), (1, "diamond", 14, "white")):
        xs, ys, tips = [], [], []
        for r, b in enumerate(rows):
            for j, s in enumerate(stages):
                ent = cells.get((b, s))
                if ent and max(e[1] for e in ent) == lvl:
                    xs.append(j - 0.33); ys.append(n_r - 1 - r + 0.3)
                    tips.append(f"<b>Research · {b} · {s}</b><br>" + "<br>".join(f"{u} ({LEVEL[l]}): {n}" for u, l, n, _ in ent))
        if xs:
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", name=f"Research: {LEVEL[lvl]} confidence", customdata=tips,
                                     hovertemplate="%{customdata}<extra></extra>",
                                     marker=dict(symbol=symbol, size=size, color=fill, line=dict(width=1.6, color=INK if fill == "white" else "white"))))
    fig.update_xaxes(tickmode="array", tickvals=list(range(len(stages))), side="top", range=[-0.5, len(stages) - 0.5],
                     ticktext=[charts.row_label(s_, int(base[s_])) for s_ in stages], showgrid=False, automargin=True)
    fig.update_yaxes(tickmode="array", tickvals=list(range(n_r)), ticktext=list(reversed(rows)), range=[-0.5, n_r - 0.5],
                     showgrid=False, automargin=True)
    fig.update_layout(height=max(340, 54 * n_r + 110), showlegend=True, legend=dict(y=-0.04))
    return fig


def render(jf_all: pd.DataFrame, skip_sources: set) -> None:
    base, k, n_app = tally(jf_all, skip_sources)
    s = summary(jf_all, skip_sources)
    ui.section(f"{s['confirmed']} of {s['testable']} testable barriers from the research show up in scraped comments",
               "The desk-research framework (Category users) laid over the scraped comments, by journey stage.",
               "4 · Research check", kind="fact")
    pick = st.segmented_control("Category user", ["All users"] + USERS, default="All users", key="fe_persona") or "All users"
    users = USERS if pick == "All users" else [pick]
    cells = _pick_cells(users)

    all_cells = {(b, s_) for _, s_, b, *_ in RESEARCH}
    in_data = {b for b in k.index if b != barrier_taxonomy.OTHER and any(_seen(base, k, b, st_) for st_ in JOURNEY_STAGES)}
    rows = [b for b in barrier_taxonomy.TYPES_B if b in {c[0] for c in all_cells} | in_data]

    cell_v = {c: _verdict(base, k, *c) for c in cells}
    n_ok = sum(v == "Confirmed" for v in cell_v.values())
    n_test = sum(v != "Too few items to test" for v in cell_v.values())
    thin_names = [st_ for st_ in JOURNEY_STAGES if base[st_] < ebi.MIN_N]
    lead = (f"{n_ok} of {n_test} testable research barriers for {pick.lower()} show up in the data"
            + (f"; {', '.join(thin_names)} have too few flagged items to test." if thin_names else "."))
    ui.plot(_heat(base, k, rows, cells), lead, key="fe_heat",
            note=("Colour = share of the stage's flagged items carrying that barrier; number = items. Diamond = research names it "
                  f"(hover for the claim). Shaded stage = under {ebi.MIN_N} flagged items, counts only. "
                  f"Includes {n_app} MyACUVUE app reviews (ACUVUE only). Comments carry no persona tag: the picker filters the diamonds only."),
            bases={st_: int(base[st_]) for st_ in JOURNEY_STAGES}, noun="flagged items")

    rows_t = []
    for (b, st_), ent in sorted(cells.items(), key=lambda kv: (JOURNEY_STAGES.index(kv[0][1]), kv[0][0])):
        kk = _count(k, b, st_)
        rows_t.append({"Stage": st_, "Barrier": b, "Research": "; ".join(f"{u} ({LEVEL[l]})" for u, l, _, _ in ent),
                       "Scraped": ebi.share(kk, int(base[st_])), "Verdict": cell_v[(b, st_)]})
    data_only = []
    if pick == "All users":
        moved = {(b, v.removeprefix("Seen at ").removesuffix(" instead")) for (b, _), v in cell_v.items() if v.startswith("Seen at ")}
        for b in k.index:
            for st_ in JOURNEY_STAGES:
                if b != barrier_taxonomy.OTHER and _seen(base, k, b, st_) and (b, st_) not in all_cells and (b, st_) not in moved:
                    data_only.append((_count(k, b, st_) / base[st_] * 100, b, st_))
                    rows_t.append({"Stage": st_, "Barrier": b, "Research": "No research row", "Scraped": ebi.share(_count(k, b, st_), int(base[st_])),
                                   "Verdict": "Data only"})
    if data_only:
        pct, b, st_ = max(data_only)
        where = ", ".join(sorted({c[1] for c in all_cells if c[0] == b}, key=JOURNEY_STAGES.index)) or "no stage"
        ui.takeaway(f"{b} is the biggest barrier in the data ({pct:.0f}% of flagged items at {st_}); the research places it at {where} only.", "fact")
    if rows_t:
        st.dataframe(pd.DataFrame(rows_t), hide_index=True, width="stretch")
        st.caption(f"Seen = {SHARE_MIN}% or more of the stage's flagged items. Not seen means not in public comments, not that the barrier is absent: "
                   "in-store and in-app experiences are thinly posted.")

    with st.expander("What the research says, cell by cell (source IDs)", expanded=False):
        st.dataframe(pd.DataFrame([{"Category user": u, "Stage": s_, "Barrier": b, "Confidence": LEVEL[l], "Claim": n, "Source IDs": i}
                                   for u, s_, b, l, n, i in RESEARCH if u in users]), hide_index=True, width="stretch")
        st.caption("Source IDs resolve in Positioning > Sources. The profiles, needs and language are in Positioning > Category users.")
