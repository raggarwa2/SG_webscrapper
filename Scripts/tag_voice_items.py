"""
tag_voice_items.py

Phase 2 of the common-taxonomy plan: one model pass that labels every voice item in voice_items_sg.db the same way, whatever
the channel. Same prompt, same lists, same model for all rows, so the labels are comparable across sources.

Per item (all from one call):
  sentiment     positive | neutral | mixed | negative       the author's attitude to the product or service
  themes        0 to 2 of the eight THEMES (Dashboard/theme_tags.py), each with its own polarity, so a mixed item
                ("love the comfort, price is crazy") scores each theme separately
  journey_stage Awareness | Engagement | Consideration | Trial | Purchase | Repeat/Retention | None   (read from the text)
  content_type  experience | opinion | question | promo | giveaway_spam | education_news | other

Input : Scripts/output/voice_items_sg.db (build_voice_items.py). Read-only.
Output: Scripts/output/voice_tags_sg.db, table voice_tags(item_id PK, ...). Resumable: items already tagged under the same
        taxonomy_version are skipped. Separate from theme_tags_sg.db (theme_tag_sg.py), which is left untouched.

Usage:
  python tag_voice_items.py                          # pilot: ~100 items across every source, writes only voice_tag_pilot.csv
  python tag_voice_items.py --mode full --scope pool --confirm      # the 1,079 Brand Health pool items
  python tag_voice_items.py --mode full --scope lenses --confirm    # pool + owned posts, app, ads, contact-lens retailer rows
  python tag_voice_items.py --mode full --scope all --confirm       # every row with text (includes ~5k spectacle-heavy Maps rows)
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

try:
    from openai import OpenAI
    from pydantic import BaseModel
except ImportError:
    sys.exit("Missing dependency. Run: pip install openai pydantic")

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "output"
VOICE_DB = OUT / "voice_items_sg.db"
TAG_DB = OUT / "voice_tags_sg.db"
OLD_TAG_DB = OUT / "theme_tags_sg.db"
PILOT_CSV = OUT / "voice_tag_pilot.csv"
MODEL = "gpt-4o-mini"
BATCH = 20
MAX_CHARS = 600
PRICE_IN, PRICE_OUT = 0.15, 0.60     # per 1M tokens, only for the spend estimate


def _themes() -> dict:
    """THEMES from Dashboard/theme_tags.py without importing streamlit: read the dict literal."""
    src = (ROOT / "Dashboard" / "theme_tags.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "THEMES":
            return ast.literal_eval(node.value)
    raise SystemExit("THEMES not found in Dashboard/theme_tags.py")


THEMES = _themes()
THEME_NAMES = tuple(THEMES)
SENT = ("positive", "neutral", "mixed", "negative")
STAGES = ("Awareness", "Engagement", "Consideration", "Trial", "Purchase", "Repeat/Retention", "None")
CONTENT = ("experience", "opinion", "question", "promo", "giveaway_spam", "education_news", "other")

ThemeName = Literal[THEME_NAMES]
Sentiment = Literal[SENT]
Stage = Literal[STAGES]
Content = Literal[CONTENT]


class ThemePol(BaseModel):
    theme: ThemeName
    polarity: Sentiment


class ItemOut(BaseModel):
    id: int
    sentiment: Sentiment
    themes: list[ThemePol]
    journey_stage: Stage
    content_type: Content


class BatchOut(BaseModel):
    items: list[ItemOut]


SYSTEM = (
    "You label text about contact lenses in Singapore: consumer comments and reviews, posts, store reviews, app reviews and ads. "
    "Some text is Chinese; read it as it is. Each numbered item shows [brand or retailer | source | who is speaking | unit]. "
    "For each item return:\n\n"
    "sentiment: the author's attitude toward the brand, retailer or app named first in the brackets (when it says 'no brand', toward the "
    "product or store discussed): positive, neutral, mixed (both) or negative. Judge the words, not the star rating. When the text compares "
    "that brand with another, score it from the named brand's side: preferring a competitor, or saying a competitor is better, is negative "
    "or mixed for the named brand even if the author is happy overall; praise for the named brand is positive even if a competitor is "
    "criticised. Theme polarity follows the same rule. Text written by a brand, retailer or advertiser (who is speaking = brand_owned, paid_ad, retailer_owned) is "
    "neutral unless it addresses a problem; promotion is not praise.\n\n"
    "themes: 0 to 2 themes the item is about, most important first, each with a polarity (positive, neutral, mixed or negative) for "
    "that theme alone. Use only these names, spelled exactly:\n"
    + "\n".join(f"- {k}: {v}" for k, v in THEMES.items())
    + "\nA brand or ad post that offers points, vouchers, a redeem deal or the app is Loyalty & app. A review about how the app itself "
    "behaves (hangs, will not open, update loop, date-of-birth entry, OTP) is Loyalty & app, never Service.\n"
    "Return an empty list when the item has no clear theme (greeting, joke, tag or emoji only, off-topic, a contest entry).\n\n"
    "journey_stage: where the author is in the buying journey, read from the text: Awareness (just noticing or learning the brand exists), "
    "Engagement (following, interacting, reacting), Consideration (comparing, asking, weighing options), Trial (first use, trial lenses, "
    "fitting), Purchase (buying, price paid, delivery), Repeat/Retention (reordering, switching, loyalty, points, long-term use), or "
    "None when the text gives no signal.\n\n"
    "content_type: experience (the author used or bought it and says so), opinion (a view without personal use), question, promo (brand, "
    "retailer or ad copy selling something), giveaway_spam (contest entries, tag-a-friend, spam), education_news (eye-care tips, news, "
    "explainers), other.\n\n"
    "Return every id you were given."
)
TAXONOMY_VERSION = "v1-" + hashlib.sha1((json.dumps(THEMES, sort_keys=True) + SYSTEM).encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------- selecting items
def load_items() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{VOICE_DB.as_posix()}?mode=ro", uri=True)
    d = pd.read_sql_query("SELECT * FROM voice_items", con)
    con.close()
    d["body"] = [" ".join(x for x in (t, b) if x) for t, b in
                 zip(d["title"].fillna(""), d["text_en"].fillna(""))]
    # the model reads the original when there is no English version
    d["body"] = d["body"].str.strip()
    d["category_item"] = category_mask(d)
    return d[d["body"].str.len() > 0]


def category_mask(d: pd.DataFrame) -> pd.Series:
    """Category voice: lens-relevant consumer comments that name no tracked brand (how-to, first-time wearer, handling talk).
    They are not in the brand pool; the dashboard reads them on themes only, never against a brand."""
    return ((d["voice_type"] == "consumer") & (d["unit"] == "comment") & (d["lens_relevant"] == 1)
            & (d["brand_relevant"] == 0) & (d["in_pool"] != 1) & (d["is_contest"] != 1))


def scope_mask(d: pd.DataFrame, scope: str) -> pd.Series:
    if scope == "all":
        return pd.Series(True, index=d.index)
    if scope == "category":
        return category_mask(d)
    pool = d["in_pool"] == 1
    if scope == "pool":
        return pool
    lens_ok = d["lens_relevant"].fillna(1) != 0                       # contact-lens (or unknown) rows only
    other = ((d["source"] == "MyACUVUE app")
             | ((d["source"].isin(["Google Maps", "Facebook retailer reviews", "Facebook retailer posts"])) & (d["lens_relevant"] == 1))
             | (d["voice_type"].isin(["brand_owned", "paid_ad"]) & lens_ok)
             | ((d["unit"] == "post") & (d["voice_type"] == "consumer") & (d["brand_relevant"].fillna(1) != 0) & lens_ok))
    return pool | other


PILOT_QUOTA = [  # (source, unit, extra filter, n)
    ("Lazada reviews", None, "in_pool", 6), ("KiasuParents", None, "in_pool", 6), ("Xiaohongshu", "post", "in_pool", 8),
    ("Xiaohongshu comments", None, "in_pool", 6), ("Reddit", "comment", "in_pool", 6), ("YouTube", "comment", "in_pool", 8),
    ("Instagram", "comment", "in_pool", 8), ("Facebook", "comment", "in_pool", 6),
    ("MyACUVUE app", None, None, 10), ("Google Maps", None, "lens", 10), ("Facebook retailer reviews", None, "lens", 5),
    ("Instagram", "post", "owned", 4), ("Facebook", "post", "owned", 4), ("YouTube", "post", "owned", 4),
    ("Facebook ads", None, None, 5), ("Facebook retailer posts", None, "lens", 4),
]


def pilot_sample(d: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for source, unit, f, n in PILOT_QUOTA:
        s = d[d["source"] == source]
        if unit:
            s = s[s["unit"] == unit]
        if f == "in_pool":
            s = s[s["in_pool"] == 1]
        elif f == "lens":
            s = s[s["lens_relevant"] == 1]
        elif f == "owned":
            s = s[s["voice_type"] == "brand_owned"]
        parts.append(s.sample(min(n, len(s)), random_state=3))
    return pd.concat(parts)


# ---------------------------------------------------------------- tagging
def ctx(r) -> str:
    if r.get("category_item"):      # filed under a brand by the search, but the text names none: score the product or store discussed
        who = "no brand"
    else:
        who = r["brand_std"] if isinstance(r["brand_std"], str) else (f"retailer {r['retailer']}" if isinstance(r["retailer"], str) else "no brand")
    bits = [who, r["source"], r["voice_type"], r["unit"]]
    return " | ".join(str(b) for b in bits)


def tag_batch(client: OpenAI, rows: list[dict]) -> tuple[dict, int, int]:
    user = "\n".join(f"{i}. [{ctx(r)}] {r['body'][:MAX_CHARS]!r}" for i, r in enumerate(rows))
    resp = client.beta.chat.completions.parse(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        response_format=BatchOut,
    )
    out = {}
    for it in resp.choices[0].message.parsed.items:
        if 0 <= it.id < len(rows):
            seen, themes = set(), []
            for t in it.themes:
                if t.theme not in seen and len(themes) < 2:
                    seen.add(t.theme)
                    themes.append({"theme": t.theme, "polarity": t.polarity})
            out[it.id] = {"sentiment": it.sentiment, "themes": themes, "journey_stage": it.journey_stage,
                          "content_type": it.content_type}
    return out, resp.usage.prompt_tokens, resp.usage.completion_tokens


def run(client: OpenAI, rows: list[dict]) -> tuple[list[dict], int, int]:
    results, t_in, t_out, n = [], 0, 0, len(rows)
    for s in range(0, n, BATCH):
        chunk = rows[s:s + BATCH]
        for attempt in range(3):
            try:
                tags, a, b = tag_batch(client, chunk)
                break
            except Exception as e:  # noqa: BLE001 - retry on any API/parse error
                print(f"  batch {s // BATCH}: {type(e).__name__}: {e}")
                time.sleep(2 * (attempt + 1))
        else:
            continue
        t_in += a
        t_out += b
        results += [{**r, **tags[i]} for i, r in enumerate(chunk) if i in tags]
        print(f"  {min(s + BATCH, n)}/{n}", flush=True)
    return results, t_in, t_out


def estimate(rows: list[dict]) -> float:
    n = len(rows)
    chars = sum(min(len(r["body"]), MAX_CHARS) for r in rows)
    est_in = chars / 3.5 + n * 14 + (n / BATCH + 1) * 1400
    return est_in / 1e6 * PRICE_IN + n * 45 / 1e6 * PRICE_OUT


# ---------------------------------------------------------------- storage
def connect() -> sqlite3.Connection:
    con = sqlite3.connect(TAG_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS voice_tags (
        item_id TEXT PRIMARY KEY, source TEXT, brand_std TEXT, sentiment TEXT, themes TEXT, theme_polarity TEXT,
        journey_stage TEXT, content_type TEXT, taxonomy_version TEXT, model TEXT, tagged_at TEXT)""")
    return con


def save(results: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    con = connect()
    con.executemany(
        "INSERT OR REPLACE INTO voice_tags VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(r["item_id"], r["source"], r["brand_std"] if isinstance(r["brand_std"], str) else None, r["sentiment"],
          json.dumps([t["theme"] for t in r["themes"]]), json.dumps({t["theme"]: t["polarity"] for t in r["themes"]}),
          r["journey_stage"], r["content_type"], TAXONOMY_VERSION, MODEL, now) for r in results])
    con.commit()
    con.close()


# ---------------------------------------------------------------- pilot checks
def _old_key(brand, text) -> str:
    return hashlib.sha1(f"{brand}|{re.sub(r'\s+', ' ', str(text or '')).strip().lower()}".encode("utf-8")).hexdigest()[:16]


def pilot_report(res: pd.DataFrame) -> None:
    pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_colwidth", 90)
    res = res.copy()
    res["theme_list"] = res["themes"].map(lambda t: [x["theme"] for x in t])
    res["first_theme"] = res["theme_list"].map(lambda t: t[0] if t else "(none)")
    print("\n== themes assigned (first theme) ==")
    print(res["first_theme"].value_counts().to_string())
    print("\n== sentiment by source ==")
    print(res.pivot_table(index="source", columns="sentiment", values="item_id", aggfunc="count", fill_value=0).to_string())
    print("\n== content_type by source ==")
    print(res.pivot_table(index="source", columns="content_type", values="item_id", aggfunc="count", fill_value=0).to_string())
    print("\n== journey_stage by source ==")
    print(res.pivot_table(index="source", columns="journey_stage", values="item_id", aggfunc="count", fill_value=0).to_string())

    sent = res[res["sentiment_native"].isin(SENT)]
    if len(sent):
        agree = (sent["sentiment"] == sent["sentiment_native"])
        print(f"\n== sentiment vs the existing label: {agree.mean():.0%} agree on {len(sent)} items ==")
        print(sent.assign(agree=agree).groupby("source")["agree"].agg(["mean", "size"]).round(2).to_string())
        print(pd.crosstab(sent["sentiment_native"], sent["sentiment"], rownames=["existing"], colnames=["new"]).to_string())
    try:
        con = sqlite3.connect(f"file:{OLD_TAG_DB.as_posix()}?mode=ro", uri=True)
        old = {k: json.loads(v) for k, v in con.execute("SELECT key, themes FROM theme_tags")}
        con.close()
    except Exception as exc:
        old = {}
        print("  (old theme tags not readable:", exc, ")")
    pool = res[res["in_pool"] == 1].copy()
    pool["old"] = [old.get(_old_key(b, t)) for b, t in zip(pool["brand_std"], pool["text_en"])]
    both = pool[pool["old"].notna()]
    if len(both):
        first = [(o[0] if o else "(none)") == n for o, n in zip(both["old"], both["first_theme"])]
        anyov = [bool(set(o) & set(n)) or (not o and not n) for o, n in zip(both["old"], both["theme_list"])]
        print(f"\n== themes vs the existing theme tags (pool items only, {len(both)} matched of {len(pool)}) ==")
        print(f"  first theme identical: {sum(first) / len(both):.0%}   any theme in common (or both empty): {sum(anyov) / len(both):.0%}")
    print("\n== sample: 30 items to read ==")
    for r in res.sample(min(30, len(res)), random_state=5).itertuples():
        th = ", ".join(f"{t['theme']} ({t['polarity']})" for t in r.themes) or "-"
        print(f"- [{r.source} | {r.voice_type}] {r.body[:110]!r}\n    -> {r.sentiment} | {th} | {r.journey_stage} | {r.content_type}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    ap.add_argument("--scope", choices=["pool", "lenses", "category", "all"], default="pool")
    ap.add_argument("--confirm", action="store_true", help="required with --mode full to spend API budget and write the DB")
    args = ap.parse_args()

    d = load_items()
    if args.mode == "pilot":
        q = pilot_sample(d)
    else:
        q = d[scope_mask(d, args.scope)]
        if TAG_DB.exists():
            con = connect()
            done = {r[0] for r in con.execute("SELECT item_id FROM voice_tags WHERE taxonomy_version = ?", (TAXONOMY_VERSION,))}
            con.close()
            q = q[~q["item_id"].isin(done)]
    rows = q.to_dict("records")
    n = len(rows)
    print(f"taxonomy {TAXONOMY_VERSION}: {n} items in {-(-n // BATCH)} calls, about ${estimate(rows):.2f} on {MODEL}.")
    if args.mode == "full" and not args.confirm:
        sys.exit("Refusing to spend: add --confirm.")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY not set (.env at the project root).")
    results, t_in, t_out = run(OpenAI(api_key=key), rows)
    cost = t_in / 1e6 * PRICE_IN + t_out / 1e6 * PRICE_OUT
    print(f"tagged {len(results)} of {n}; {t_in:,} in / {t_out:,} out tokens, about ${cost:.3f}.")
    if args.mode == "pilot":
        res = pd.DataFrame(results)
        out = res.assign(themes=res["themes"].map(json.dumps))[
            ["item_id", "source", "unit", "voice_type", "brand_std", "sentiment_native", "sentiment", "themes",
             "journey_stage", "content_type", "body"]]
        out.to_csv(PILOT_CSV, index=False, encoding="utf-8-sig")
        pilot_report(res)
        print(f"\nPilot only: nothing written to the tag database. Rows for hand-checking: {PILOT_CSV}")
        return
    save(results)
    print(f"Wrote {len(results)} rows to {TAG_DB}")


if __name__ == "__main__":
    main()
