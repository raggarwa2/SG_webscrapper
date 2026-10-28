"""Segment study (Consumer Intel pack, 2026-10-27/28): the two sources that carry signal for new wearers.

  search interest  weekly Google Trends points for segment terms (Singapore, 5 years). Only a term with MIN_N active weeks is
                   read; of the segment terms that is LASIK (surgery choosers) and presbyopia (over-40s).
  AI answers       what ChatGPT search and Perplexity say to one brand-free question per segment, with the pages they cite.
                   They are a reference lens, not consumers, and are never counted as voice.

The pack's posts and comments are not read here: no segment reaches 15 Singapore items on any item-based source (its NOTE.md),
so they appear only as a count on Data Notes. Read-only; the CSVs stay as the tool exported them.
"""

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

import barrier_taxonomy
import ebi

PACK = Path(__file__).resolve().parent.parent / "Handover" / "segment_study_2026-10" / "consumer_intel"

SEGMENTS = {
    "S1_glasses_only": "Glasses-only", "S2_dropouts": "Dropouts", "S3_part_timers": "Part-timers",
    "S4_surgery_choosers": "Surgery choosers", "S5_students_teens": "Students & teens", "S6_over_40": "Over-40s",
    "S7_sporty": "Sporty", "S8_screen_heavy": "Screen-heavy",
}
# The Chinese anchor term is carried in every request and is the same series under each segment: it is not segment evidence.
ANCHOR = "隐形眼镜"
ENGINES = {"chatgpt_search": "ChatGPT search", "perplexity_web": "Perplexity"}


def available() -> bool:
    return (PACK / "search_interest.csv").exists() and (PACK / "ai_search.csv").exists()


@st.cache_data(ttl=600, show_spinner=False)
def search() -> pd.DataFrame:
    """Segment search terms, complete weeks only (the anchor term is dropped)."""
    if not available():
        return pd.DataFrame()
    s = pd.read_csv(PACK / "search_interest.csv", dtype=str, encoding="utf-8-sig")
    s = s[s["segment"].notna() & (s["term"] != ANCHOR) & (s["is_partial"].astype(str).str.lower().isin(["0", "false"]))].copy()
    s["date"] = pd.to_datetime(s["date"])
    s["value"] = pd.to_numeric(s["value"], errors="coerce")
    s["segment_label"] = s["segment"].map(SEGMENTS)
    return s[["segment", "segment_label", "term", "date", "value"]].sort_values("date").reset_index(drop=True)


def term_table() -> pd.DataFrame:
    """One row per segment term: weeks with searches, the last 52 weeks against the 52 before, and whether it is readable."""
    s = search()
    rows = []
    for (seg, label, term), g in s.groupby(["segment", "segment_label", "term"]):
        v = g.set_index("date")["value"]
        last, prev = v.iloc[-52:].mean(), v.iloc[-104:-52].mean()
        rows.append({"Segment": label, "Term": term, "Weeks with searches": int((v > 0).sum()),
                     "Last 52 weeks": round(last, 1), "Year before": round(prev, 1),
                     "Change": (last / prev - 1) * 100 if prev else None,
                     "Readable": int((v > 0).sum()) >= ebi.MIN_N})
    return pd.DataFrame(rows)


def readable() -> pd.DataFrame:
    t = term_table()
    return t[t["Readable"]].reset_index(drop=True) if len(t) else t


@st.cache_data(ttl=600, show_spinner=False)
def ai_answers() -> pd.DataFrame:
    if not available():
        return pd.DataFrame()
    a = pd.read_csv(PACK / "ai_search.csv", dtype=str, encoding="utf-8-sig")
    a["segment_label"] = a["segment"].map(SEGMENTS)
    a["engine_label"] = a["engine"].map(ENGINES)

    def cites(x):
        try:
            return json.loads(x)
        except (TypeError, ValueError):
            return []
    a["cited"] = a["citations"].map(cites)
    a["domains"] = a["cited"].map(lambda c: sorted({r.get("domain") for r in c if r.get("domain")}))
    a["link"] = a["cited"].map(lambda c: c[0].get("url") if c else None)
    a["answer"] = a["answer_text"].map(_lead)
    return a


def _lead(text, n: int = 2) -> str:
    """First sentence or two of the answer, without the engine's source-chip lines ('healthhub', '+2')."""
    lines = [ln.strip() for ln in str(text or "").splitlines()]
    para = next((ln for ln in lines if len(ln) > 60), "")
    parts = para.replace("”", "” ").split(". ")
    out = ". ".join(parts[:n]).strip()
    return out if out.endswith(".") else out + "."


def domain_table(a: pd.DataFrame) -> pd.DataFrame:
    """How often each page's domain is cited across the answers, with the segments it appears under."""
    rows = a[["segment_label", "domains"]].explode("domains").dropna()
    t = rows.groupby("domains").agg(Answers=("segment_label", "size"), Segments=("segment_label", lambda s: ", ".join(sorted(set(s)))))
    return t.sort_values("Answers", ascending=False).reset_index().rename(columns={"domains": "Domain"})


def coverage() -> pd.DataFrame:
    """Per segment: items that count on each item-based source (on-topic and Singapore-signalled, in the 24-month window), AI answers
    and readable search terms. Instagram and brand-query rows carry no segment, so they cannot lift a segment."""
    if not available():
        return pd.DataFrame()
    p = pd.read_csv(PACK / "social_posts.csv", dtype=str, encoding="utf-8-sig")
    f = p[(p["scope_status"] == "found") & (p["purpose"] == "segment") & p["segment"].notna()]
    n = f.groupby(["segment", "platform"]).size().unstack(fill_value=0)
    forum = pd.read_csv(PACK / "forum_threads.csv", dtype=str, encoding="utf-8-sig")
    forum = forum[forum["scope_status"] == "found"].groupby("segment").size()
    ai = ai_answers().groupby("segment").size()
    ok = readable()
    rows = []
    for seg, label in SEGMENTS.items():
        yt, tt = (int(n[c].get(seg, 0)) if c in n else 0 for c in ("youtube", "tiktok"))
        rows.append({"Segment": label, "YouTube videos": yt, "TikTok videos": tt, "KiasuParents threads": int(forum.get(seg, 0)),
                     "AI answers": int(ai.get(seg, 0)), "Readable search terms": int((ok["Segment"] == label).sum())})
    t = pd.DataFrame(rows)
    t["Items that count"] = t[["YouTube videos", "TikTok videos", "KiasuParents threads"]].sum(axis=1)
    return t


# What the AI answers name as the barrier, per segment: read by hand from the 47 answers and mapped to the one barrier list
# (barrier_taxonomy.TYPES). A keyword pass hit nearly every label on every answer, so it could not tell segments apart.
# (segment, barrier label, what the answers say, ids of the answers that say it = first 8 characters of raw_sha)
BARRIERS = [
    ('Glasses-only', 'Fear / handling difficulty', 'Fear of touching the eye or scratching it; insertion, removal and clean hands feel like a chore', ['e5efff81', '25e8a71d', 'acd1905c']),
    ('Glasses-only', 'Product experience', 'Dryness and discomfort in air-conditioned offices and long screen hours', ['e5efff81', '96d4cd0e', '25e8a71d', '5d156761', 'acd1905c']),
    ('Glasses-only', 'Price & channel cost', 'Recurring lens cost against a one-off pair of glasses', ['25e8a71d', '5d156761', 'acd1905c']),
    ('Glasses-only', 'Lack of professional guidance', 'A separate fitting and prescription is needed first', ['96d4cd0e', 'acd1905c']),
    ('Glasses-only', 'Other / unclear', 'Low perceived need: glasses are comfortable and good enough', ['e5efff81', '96d4cd0e', '25e8a71d', '5d156761']),
    ('Dropouts', 'Product experience', 'Dryness, irritation, allergies and blurred vision lead the reasons for stopping', ['ab4996ad', '756523a2', 'eedb8b13', '55ed4ade', '83ee89cc', '368c8ee5']),
    ('Dropouts', 'Fear / handling difficulty', 'Handling difficulty, hygiene burden and fear of infection; nervous about re-inserting', ['ab4996ad', 'eedb8b13', '55ed4ade', '83ee89cc', '368c8ee5']),
    ('Dropouts', 'Price & channel cost', 'Cost and hassle of dailies, solutions, fittings and follow-ups', ['ab4996ad', 'eedb8b13', '83ee89cc']),
    ('Dropouts', 'Lack of professional guidance', 'Past quitters may have had the wrong lens type or fit', ['55ed4ade']),
    ('Dropouts', 'Other / unclear', 'Heat, humidity and convenience make glasses the simpler daily choice', ['ab4996ad', '756523a2']),
    ('Part-timers', 'Colour & look (cosmetic lenses)', 'Wear for events, dates and photos; subtle tints or coloured dailies', ['18206f46', '118726f5']),
    ('Part-timers', 'Product experience', 'Comfort in air-conditioned rooms and long nights out', ['81e3638c', '687d2815', '118726f5']),
    ('Part-timers', 'Price & channel cost', 'Maintaining reusable lenses costs more than it is worth for a few wears a month', ['118726f5', '7da462f5']),
    ('Part-timers', 'Fear / handling difficulty', 'Hygiene and infection risk of reusable lenses left in storage', ['118726f5', 'cae37269']),
    ('Surgery choosers', 'Product experience', 'Dry eyes drive people to surgery, and fear of post-surgery dry eye keeps others in lenses', ['1fc7d0e0', 'a22b6b0b', '28dbad89', 'cc0b410a', 'e6ac90a6']),
    ('Surgery choosers', 'Fear / handling difficulty', 'Infection risk of lenses against the permanence and risk of surgery', ['a22b6b0b', 'cc0b410a', 'e6ac90a6']),
    ('Surgery choosers', 'Price & channel cost', 'Surgery costs less than lenses over the long run; upfront cost keeps others in lenses', ['a22b6b0b', 'cc0b410a', 'e6ac90a6']),
    ('Surgery choosers', 'Lack of professional guidance', 'Eye assessment (cornea, prescription, dry eye) decides what is offered', ['1fc7d0e0', '28dbad89', 'e6ac90a6']),
    ('Surgery choosers', 'Other / unclear', 'Freedom and convenience are what people say they want', ['6e4ab976', 'cc0b410a']),
    ('Students & teens', 'Lack of professional guidance', 'Prescription and fitting by a registered optometrist come first', ['42a67c53', 'dcc13c07', '2898bca7', '1fba122e', '2c97391f']),
    ('Students & teens', 'Fear / handling difficulty', 'Parents judge readiness: hygiene, insertion and removal, stopping when eyes are irritated', ['42a67c53', 'dcc13c07', '12cde787', '1fba122e']),
    ('Students & teens', 'Price & channel cost', 'Cost is weighed beside safety', ['42a67c53', 'dcc13c07']),
    ('Students & teens', 'Product experience', 'Tear film and dryness are checked before fitting', ['dcc13c07', '2898bca7']),
    ('Over-40s', 'Product experience', 'Multifocals can bring halos, glare and softer near vision', ['21731560', '9acf9203', 'eb4ea2f9', 'ecb49cb8']),
    ('Over-40s', 'Price & channel cost', 'Reading glasses are simpler and cheaper', ['0489ad25', '9acf9203', 'ecb49cb8']),
    ('Over-40s', 'Lack of professional guidance', 'Fitting and an adaptation period are needed', ['9acf9203', 'eb4ea2f9', 'ecb49cb8']),
    ('Over-40s', 'Fear / handling difficulty', 'Ongoing lens care and maintenance', ['9acf9203', 'ecb49cb8']),
    ('Over-40s', 'Other / unclear', 'Glasses remain the usual choice; no Singapore survey compares them with multifocals', ['5c956028', '0489ad25']),
    ('Sporty', 'Fear / handling difficulty', 'Water and infection risk: do not swim in lenses (Acanthamoeba keratitis)', ['db6aa49a', '22e1f9ac', '9b9dee86']),
    ('Sporty', 'Product experience', 'Comfort in heat and sweat; dailies recommended', ['db6aa49a', 'b6702afd', '3aad4fc4']),
    ('Screen-heavy', 'Product experience', 'Dryness from reduced blinking and air-conditioning', ['efcff4da', '846202c8', '4b5b726a', '408b549b', 'c8572aa6']),
    ('Screen-heavy', 'Lack of professional guidance', 'Check fit and wear time; examination if symptoms persist', ['4b5b726a', '408b549b', 'bb8321b8', 'c8572aa6']),
    ('Screen-heavy', 'Fear / handling difficulty', 'Strict lens hygiene', ['c8572aa6']),
    ('Screen-heavy', 'Other / unclear', 'Coping habits: 20-20-20 rule, drops, shorter wear', ['efcff4da', '846202c8', '408b549b', 'c8572aa6']),
]


def barrier_table() -> pd.DataFrame:
    """One row per segment and barrier, with how many of that segment's answers name it and the ids behind the count."""
    a = ai_answers()
    if a.empty:
        return pd.DataFrame()
    a = a.assign(sid=a["raw_sha"].str[:8])
    totals = a.groupby("segment_label").size()
    rows = []
    for seg, label, claim, ids in BARRIERS:
        have = set(a.loc[a["segment_label"] == seg, "sid"])
        ids = [i for i in ids if i in have]
        rows.append({"Segment": seg, "Barrier": label, "Theme": barrier_taxonomy.THEME_OF.get(label, ""), "What the answers say": claim,
                     "Answers naming it": len(ids), "Answers read": int(totals.get(seg, 0)), "ids": ids})
    return pd.DataFrame(rows)


def acuvue_named() -> pd.DataFrame:
    """Per segment, how many answers name ACUVUE / MyACUVUE / Abiliti, and how many name a peer lens brand."""
    a = ai_answers()
    ac = a["answer_text"].str.contains(r"acuvue|abiliti", case=False, regex=True)
    peer = a["answer_text"].str.contains(r"dailies|air optix|precision1|biofinity|misight|clariti|myday|proclear|coopervision|alcon|bausch|olens", case=False, regex=True)
    return a.assign(Acuvue=ac, Peer=peer).groupby("segment_label", sort=False).agg(Answers=("Acuvue", "size"), Acuvue=("Acuvue", "sum"), Peer=("Peer", "sum")).reset_index().rename(columns={"segment_label": "Segment"})


# ---- Reference voice: comments found by the segment searches, tagged with the project tagger (Scripts/tag_segment_comments.py).
# A sixth lens, kept outside voice_items: YouTube videos carry no Singapore signal, so these are what viewers elsewhere ask and fear.
SCRIPTS_OUT = Path(__file__).resolve().parent.parent / "Scripts" / "output"
ITEMS_DB, TAGS_DB = SCRIPTS_OUT / "segment_items_sg.db", SCRIPTS_OUT / "segment_tags_sg.db"
STAGES = ["Awareness", "Engagement", "Consideration", "Trial", "Purchase", "Repeat/Retention"]
READ_TYPES = ["experience", "opinion", "question"]


def reference_available() -> bool:
    return ITEMS_DB.exists() and TAGS_DB.exists()


@st.cache_data(ttl=600, show_spinner=False)
def reference_all() -> pd.DataFrame:
    """Every tagged segment-study comment, one row each (latest taxonomy version only)."""
    if not reference_available():
        return pd.DataFrame()
    i = pd.read_sql_query("SELECT item_id, source, unit, country, segment, date, title, video_title, url, text_en AS text, post_scope FROM voice_items",
                          sqlite3.connect(f"file:{ITEMS_DB.as_posix()}?mode=ro", uri=True))
    t = pd.read_sql_query("SELECT item_id, sentiment, themes, theme_polarity, journey_stage, content_type, taxonomy_version, tagged_at FROM voice_tags",
                          sqlite3.connect(f"file:{TAGS_DB.as_posix()}?mode=ro", uri=True))
    if len(t):
        t = t[t["taxonomy_version"] == t.loc[t["tagged_at"].idxmax(), "taxonomy_version"]]
    d = i.merge(t, on="item_id")
    d["themes"] = d["themes"].map(json.loads)
    d["pol"] = d["theme_polarity"].map(json.loads)
    d["text"] = (d["title"].fillna("") + " " + d["text"].fillna("")).str.strip()
    d["segment_label"] = d["segment"].map(SEGMENTS).fillna("No segment (brand search)")
    d["date"] = pd.to_datetime(d["date"], errors="coerce")
    d["readable"] = d["themes"].map(len).gt(0) & d["content_type"].isin(READ_TYPES)
    return d.drop(columns=["theme_polarity"])


def reference_voice() -> pd.DataFrame:
    """Comments that carry a theme and are an experience, opinion or question: the ones worth reading. Reddit posts are Singapore and
    are read apart (singapore_posts), so this is the not-Singapore side only."""
    d = reference_all()
    return d[d["readable"] & ~d["source"].str.startswith("Reddit")].reset_index(drop=True) if len(d) else d


def singapore_posts() -> pd.DataFrame:
    """Strictly on-topic Singapore Reddit posts (contact lenses or refractive surgery), tagged by the same model; all of them, readable or not."""
    d = reference_all()
    return d[d["source"].str.startswith("Reddit") & (d["unit"] == "post")].reset_index(drop=True) if len(d) else d
