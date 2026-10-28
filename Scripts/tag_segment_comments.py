"""
tag_segment_comments.py

Runs the project's one tagger (tag_voice_items.py: same prompt, same eight themes, same journey stages, same model) over the
comments in the segment study pack (Handover/segment_study_2026-10/consumer_intel/social_comments.csv).

Kept apart on purpose: reads the pack, writes only Scripts/output/segment_items_sg.db and segment_tags_sg.db. It never touches
voice_items_sg.db or voice_tags_sg.db, so no brand-pool number moves. YouTube comments sit under videos that carry no Singapore
signal (the pack's strict rule), so these labels are for reading what non-wearers say, not for Singapore percentages.

Scope: YouTube and TikTok comments marked `substantive`, plus the strictly on-topic Singapore Reddit posts from
Handover/segment_study_2026-10/reddit/reddit_segment_posts.csv (a contact-lens or refractive-surgery term in the title or body). Instagram comments are fan and contest replies (pack NOTE) and chatter
is not worth a call; both stay out.

Usage:
  python tag_segment_comments.py --build                 # build segment_items_sg.db, print counts, no API call
  python tag_segment_comments.py --tag --limit 60        # pilot: tag 60 items, write nothing
  python tag_segment_comments.py --tag --confirm         # tag all, resumable, writes segment_tags_sg.db
  python tag_segment_comments.py --export                # CSV of the tagged comments for the persona work (Handover/segment_study_2026-10)
"""
import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd

import tag_voice_items as tv

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "output"
PACK = ROOT / "Handover" / "segment_study_2026-10" / "consumer_intel"
ITEMS_DB = OUT / "segment_items_sg.db"
TAGS_DB = OUT / "segment_tags_sg.db"
SOURCE = {"youtube": "YouTube (segment study)", "tiktok": "TikTok (segment study)"}
COUNTRY = {"youtube": "unknown", "tiktok": "Singapore (TikTok tag)"}
REDDIT = ROOT / "Handover" / "segment_study_2026-10" / "reddit" / "reddit_segment_posts.csv"
REDDIT_SEGMENT = {"glasses_only": "S1_glasses_only", "dropout": "S2_dropouts", "part_timer": "S3_part_timers", "surgery": "S4_surgery_choosers",
                  "student": "S5_students_teens", "over40": "S6_over_40", "sporty": "S7_sporty", "screen_pro": "S8_screen_heavy"}
# on topic = names contact lenses or refractive surgery; "glasses" alone, "progressive lenses" and "screen" do not count
ON_TOPIC = re.compile(r"contact\s*lens|\bcontacts\b|colou?red lens|circle lens|dailies|acuvue|air optix|biofinity|olens|bausch|coopervision|ortho-?k|myopia control|atropine|"
                      r"lasik|relex|\bsmile\b (eye|surgery|procedure)|smile/|/smile|\bicl\b(?! of)|implantable|eye surgery|laser eye|refractive", re.I)


def reddit_rows() -> pd.DataFrame:
    """Singapore Reddit posts that are strictly on topic, in the same columns as the comments (posts: the title goes in `title`)."""
    if not REDDIT.exists():
        return pd.DataFrame()
    r = pd.read_csv(REDDIT, dtype=str, encoding="utf-8-sig")
    r = r[(r["title"].fillna("") + " " + r["selftext"].fillna("")).map(lambda t: bool(ON_TOPIC.search(t)))].drop_duplicates("post_id")
    return pd.DataFrame({
        "item_id": "seg:reddit:" + r["post_id"], "source": "Reddit (segment study)", "unit": "post", "voice_type": "consumer",
        "brand_std": None, "retailer": None, "title": r["title"], "text_en": r["selftext"].fillna(""), "date": r["created_utc"].str[:10],
        "url": r["permalink"].map(lambda u: "https://www.reddit.com" + u if isinstance(u, str) and u.startswith("/r/") else u),
        "segment": r["segment"].map(REDDIT_SEGMENT), "purpose": "segment", "video_title": r["subreddit"].map(lambda x: f"r/{x}"),
        "post_scope": "found", "post_scope_reason": r["sg_reason"], "lens_relevant": 1, "brand_relevant": 0, "in_pool": 0, "is_contest": 0,
        "country": "Singapore"})


def reddit_comment_rows() -> pd.DataFrame:
    """Replies in strictly on-topic Singapore Reddit threads (same ON_TOPIC test as the posts), 25+ characters.
    A reply carries its thread's segment, not one of its own."""
    path = REDDIT.parent / "reddit_segment_comments.csv"
    if not REDDIT.exists() or not path.exists():
        return pd.DataFrame()
    p = pd.read_csv(REDDIT, dtype=str, encoding="utf-8-sig").drop_duplicates("post_id").set_index("post_id")
    ok = (p["title"].fillna("") + " " + p["selftext"].fillna("")).map(lambda t: bool(ON_TOPIC.search(t)))
    c = pd.read_csv(path, dtype=str, encoding="utf-8-sig").drop_duplicates("comment_id")
    c = c[c["post_id"].map(ok).fillna(False).astype(bool) & (c["body"].fillna("").str.strip().str.len() >= 25)]
    t = p.reindex(c["post_id"])
    return pd.DataFrame({
        "item_id": ("seg:reddit_comment:" + c["comment_id"]).to_numpy(), "source": "Reddit (segment study)", "unit": "comment",
        "voice_type": "consumer", "brand_std": None, "retailer": None, "title": None, "text_en": c["body"].str.strip().to_numpy(),
        "date": c["created_utc"].str[:10].to_numpy(),
        "url": t["permalink"].map(lambda u: "https://www.reddit.com" + u if isinstance(u, str) and u.startswith("/r/") else u).to_numpy(),
        "segment": c["segment"].map(REDDIT_SEGMENT).to_numpy(), "purpose": "segment", "video_title": c["subreddit"].map(lambda x: f"r/{x}").to_numpy(),
        "post_scope": "found", "post_scope_reason": t["sg_reason"].to_numpy(), "lens_relevant": 1, "brand_relevant": 0, "in_pool": 0,
        "is_contest": 0, "country": "Singapore"})


def stamp_added(ids: pd.Series, source: pd.Series) -> pd.Series:
    """When each item first entered this table (feeds the dashboard's 'added today' count). Kept across rebuilds; a new item gets now.
    Rows that predate the column keep no stamp, except Reddit, which was collected on 2026-10-28 (archive sweep logs)."""
    now = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    prev = {}
    if ITEMS_DB.exists():
        con = sqlite3.connect(ITEMS_DB)
        cols = [r[1] for r in con.execute("PRAGMA table_info(voice_items)")]
        rows = con.execute("SELECT item_id, " + ("added_at" if "added_at" in cols else "NULL") + " FROM voice_items").fetchall() if cols else []
        con.close()
        prev = dict(rows)
    def one(i, src):
        if i in prev:
            return prev[i] or ("2026-10-28 00:00" if src.startswith("Reddit") else None)
        return now
    return pd.Series([one(i, sr) for i, sr in zip(ids, source)], index=ids.index)


def build() -> pd.DataFrame:
    c = pd.read_csv(PACK / "social_comments.csv", dtype=str, encoding="utf-8-sig")
    p = pd.read_csv(PACK / "social_posts.csv", dtype=str, encoding="utf-8-sig")
    c = c[c["platform"].isin(SOURCE) & (c["signal"] == "substantive") & c["text"].notna()].copy()
    post = p.drop_duplicates(["platform", "post_id"]).set_index(["platform", "post_id"])[["url", "title", "scope_status", "scope_reason"]]
    j = post.reindex(pd.MultiIndex.from_frame(c[["platform", "post_id"]]))
    d = pd.DataFrame({
        "item_id": "seg:" + c["platform"] + ":" + c["comment_id"], "source": c["platform"].map(SOURCE), "unit": "comment",
        "voice_type": "consumer", "brand_std": None, "retailer": None, "title": None, "text_en": c["text"].str.strip(),
        "date": c["published_at"].str[:10], "url": j["url"].to_numpy(), "segment": c["segment"], "purpose": c["purpose"],
        "video_title": j["title"].to_numpy(), "post_scope": j["scope_status"].to_numpy(), "post_scope_reason": j["scope_reason"].to_numpy(),
        "lens_relevant": 1, "brand_relevant": 0, "in_pool": 0, "is_contest": 0,
    }).drop_duplicates("item_id")
    d["country"] = c["platform"].map(COUNTRY).to_numpy()
    d = pd.concat([d, reddit_rows(), reddit_comment_rows()], ignore_index=True).drop_duplicates("item_id")
    OUT.mkdir(exist_ok=True)
    d["added_at"] = stamp_added(d["item_id"], d["source"])
    con = sqlite3.connect(ITEMS_DB)
    d.to_sql("voice_items", con, if_exists="replace", index=False)
    con.close()
    return d


def export() -> None:
    """Tagged comments with the segment search that found them, for the persona work. Not Singapore evidence: say so in the file."""
    sys.path.insert(0, str(ROOT / "Dashboard"))
    import segment_data as sd
    d = sd.reference_all()
    sg = d["country"].astype(str).str.startswith("Singapore")
    d = d.assign(themes=d["themes"].map(", ".join), date=d["date"].dt.strftime("%Y-%m-%d"),
                 note=sg.map({True: "Singapore (Reddit Singapore subreddit or TikTok with a Singapore tag). Posts only; the segment is the search that found it, not who wrote it.",
                              False: "Reference voice: country unknown (YouTube video has no Singapore signal); the segment is the search that found it, not who wrote it. Not Singapore evidence."}))
    cols = ["segment_label", "readable", "country", "source", "date", "sentiment", "themes", "journey_stage", "content_type", "text", "video_title", "url", "post_scope", "note"]
    path = PACK.parent / "reference_voice_for_personas.csv"
    d.sort_values(["segment_label", "readable"], ascending=[True, False])[cols].rename(columns={"segment_label": "found_by_search_for", "readable": "worth_reading"})         .to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Wrote {len(d)} comments ({int(d['readable'].sum())} worth reading) to {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--tag", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="pilot: tag this many items and write nothing")
    ap.add_argument("--confirm", action="store_true", help="spend API budget and write segment_tags_sg.db")
    a = ap.parse_args()
    if a.build or not ITEMS_DB.exists():
        d = build()
        print(f"{len(d)} comments in {ITEMS_DB.name}")
        print(d.groupby(["source", "post_scope"], dropna=False).size().to_string())
    if a.export:
        export()
    if not a.tag:
        return
    tv.VOICE_DB, tv.TAG_DB = ITEMS_DB, TAGS_DB          # the tagger reads and writes these two, nothing else
    items = tv.load_items()
    if TAGS_DB.exists():
        con = tv.connect()
        done = {r[0] for r in con.execute("SELECT item_id FROM voice_tags WHERE taxonomy_version = ?", (tv.TAXONOMY_VERSION,))}
        con.close()
        items = items[~items["item_id"].isin(done)]
    if a.limit:
        items = items.sample(min(a.limit, len(items)), random_state=7)
    rows = items.to_dict("records")
    print(f"taxonomy {tv.TAXONOMY_VERSION}: {len(rows)} items, about ${tv.estimate(rows):.3f} on {tv.MODEL}.")
    if not a.limit and not a.confirm:
        sys.exit("Refusing to spend: add --confirm (or --limit N for a pilot).")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY not set (.env at the project root).")
    res, t_in, t_out = tv.run(tv.OpenAI(api_key=key), rows)
    print(f"tagged {len(res)} of {len(rows)}; {t_in:,} in / {t_out:,} out tokens, about ${t_in / 1e6 * tv.PRICE_IN + t_out / 1e6 * tv.PRICE_OUT:.3f}.")
    if a.limit:
        r = pd.DataFrame(res)
        r.assign(themes=r["themes"].map(str))[["item_id", "sentiment", "themes", "journey_stage", "content_type", "body"]] \
            .to_csv(OUT / "segment_tag_pilot.csv", index=False, encoding="utf-8-sig")
        print(r["sentiment"].value_counts().to_dict(), r["content_type"].value_counts().to_dict(), r["journey_stage"].value_counts().to_dict())
        print(f"Pilot only: nothing written to the tag database. Rows: {OUT / 'segment_tag_pilot.csv'}")
        return
    tv.save(res)
    print(f"Wrote {len(res)} rows to {TAGS_DB}")


if __name__ == "__main__":
    main()
