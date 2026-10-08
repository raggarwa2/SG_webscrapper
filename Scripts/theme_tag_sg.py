"""
theme_tag_sg.py

Tags every consumer item the dashboard counts with (1) 1 or 2 themes and (2) 0 to 2 barrier labels, from two fixed lists, so
brands and barriers read on the same lists across Xiaohongshu, Lazada, KiasuParents, Reddit, YouTube, Instagram, Facebook and
the MyACUVUE app. Only four of those sources carry a theme field of their own, each with its own vocabulary, and the old
keyword barrier list was a regex draft.
  themes   = what the item is about (Dashboard/theme_tags.py THEMES)
  barriers = the obstacle it expresses about buying, registering, using or staying (Dashboard/barrier_taxonomy.py DEFINITIONS;
             each label rolls up to a theme through THEME_OF). Empty for praise or when no obstacle is stated.

Input : Scripts/output/theme_tag_queue.csv, written by the dashboard (theme_tags.queue) with the items that still need tags
        (columns brand, source, text, key). Open Brand Health and Journey & barriers once to refresh it.
Output: Scripts/output/theme_tags_sg.db, table theme_tags(key, brand, source, themes JSON, text_key, barriers JSON, model,
        tagged_at, text). Resumable: rows without barriers (tagged by the first, themes-only run) are tagged again.

Same idiom as extract_sentiment_sg.py (OpenAI gpt-4o-mini, structured output, pilot / --confirm spend gate). Sentiment is not
produced here: it is already on each item.

Usage:
  python theme_tag_sg.py                        # pilot: 24 items, prints the tags, writes nothing
  python theme_tag_sg.py --mode full --confirm  # tags the whole queue and writes theme_tags_sg.db
  python theme_tag_sg.py --check 50             # prints 50 random tagged items to hand-check (no API call)
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("Missing dependency. Run: pip install openai")
    sys.exit(1)
try:
    from pydantic import BaseModel
except ImportError:
    print("Missing dependency. Run: pip install pydantic")
    sys.exit(1)

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "Dashboard"))
import barrier_taxonomy  # noqa: E402  (stdlib only, so it imports without streamlit)

OUT = Path(__file__).resolve().parent / "output"
QUEUE = OUT / "theme_tag_queue.csv"
TAG_DB = OUT / "theme_tags_sg.db"
MODEL = "gpt-4o-mini"
RUN = "gpt-4o-mini/ctx3"      # stored in the model column; rows from an older prompt are tagged again
BATCH = 20
MAX_CHARS = 600
# gpt-4o-mini list price per 1M tokens (input, output); used only for the spend estimate
PRICE_IN, PRICE_OUT = 0.15, 0.60


def _themes() -> dict:
    """THEMES from Dashboard/theme_tags.py without importing streamlit: read the dict literal."""
    src = (ROOT / "Dashboard" / "theme_tags.py").read_text(encoding="utf-8")
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "THEMES":
            return ast.literal_eval(node.value)
    raise SystemExit("THEMES not found in Dashboard/theme_tags.py")


THEMES = _themes()
BARRIERS = barrier_taxonomy.DEFINITIONS


class ItemTags(BaseModel):
    id: int
    themes: list[str]          # 0 to 2 names from the theme list; empty = off-topic or no theme
    barriers: list[str]        # 0 to 2 names from the barrier list; empty = no obstacle stated


class BatchTags(BaseModel):
    items: list[ItemTags]


SYSTEM = (
    "You label consumer comments and reviews about contact lenses in Singapore. For each numbered item return two lists.\n\n"
    "themes: 0 to 2 themes the item is about, most important first, whether praised or criticised. Use only these names, spelled exactly:\n"
    + "\n".join(f"- {k}: {v}" for k, v in THEMES.items())
    + "\nReturn an empty list when the item has no clear theme (greeting, joke, off-topic, only a tag or emoji).\n\n"
    "barriers: 0 to 2 obstacles the item expresses about buying, registering, using or staying with lenses (a complaint, worry, "
    "friction or reason not to buy). Use only these names, spelled exactly:\n"
    + "\n".join(f"- {k}: {v}" for k, v in BARRIERS.items())
    + "\nEach item shows its source, sentiment and, when set, 'flagged as barrier' (an earlier step judged it a reason not to buy). "
    "For a negative or flagged item, choose the closest barrier label even when the text is short or vague (for example an app review "
    "saying 'doesn't work' or 'trouble downloading' is Registration / login friction or App utility & support; a forum summary comparing "
    "price is Price & channel cost). Use an empty list for praise, neutral questions, or a negative item that fits no label. "
    "Never invent an obstacle for a positive item. Return every id you were given."
)


def tag_batch(client: OpenAI, rows: list[dict]) -> tuple[dict, int, int]:
    def ctx(r):
        bits = [str(r["brand"]), str(r.get("source", ""))]
        if isinstance(r.get("sentiment"), str):
            bits.append(r["sentiment"])
        if r.get("is_barrier") == 1:
            bits.append("flagged as barrier")
        return " | ".join(bits)

    user = "\n".join(f"{i}. [{ctx(r)}] {str(r['text'])[:MAX_CHARS]!r}" for i, r in enumerate(rows))
    resp = client.beta.chat.completions.parse(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        response_format=BatchTags,
    )
    parsed = resp.choices[0].message.parsed
    out = {}
    for it in parsed.items:
        if 0 <= it.id < len(rows):
            out[it.id] = ([t for t in it.themes if t in THEMES][:2], [b for b in it.barriers if b in BARRIERS][:2])
    return out, resp.usage.prompt_tokens, resp.usage.completion_tokens


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(TAG_DB)
    con.execute("CREATE TABLE IF NOT EXISTS theme_tags (key TEXT PRIMARY KEY, brand TEXT, source TEXT, themes TEXT, model TEXT, tagged_at TEXT)")
    cols = {r[1] for r in con.execute("PRAGMA table_info(theme_tags)")}
    for col in ("text_key", "barriers", "text"):
        if col not in cols:
            con.execute(f"ALTER TABLE theme_tags ADD COLUMN {col} TEXT")
    return con


def check(n: int) -> None:
    """Print n random tagged items with their labels for a hand check."""
    con = _connect()
    rows = con.execute("SELECT text, brand, source, themes, barriers FROM theme_tags WHERE barriers IS NOT NULL").fetchall()
    con.close()
    import random
    random.seed(7)
    for text, brand, source, themes, barriers in random.sample(rows, min(n, len(rows))):
        print(f"- [{brand} / {source}] {str(text)[:230]!r}\n    themes={json.loads(themes)}  barriers={json.loads(barriers)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    ap.add_argument("--confirm", action="store_true", help="required with --mode full to spend API budget and write the DB")
    ap.add_argument("--check", type=int, default=0, help="print N random tagged items to hand-check; no API call")
    args = ap.parse_args()
    if args.check:
        return check(args.check)

    if not QUEUE.exists():
        sys.exit(f"No queue at {QUEUE}. Open the dashboard's Brand Health tab once to write it.")
    q = pd.read_csv(QUEUE, encoding="utf-8").dropna(subset=["text"]).drop_duplicates("key")
    if TAG_DB.exists():
        con = _connect()
        done = {r[0] for r in con.execute("SELECT key FROM theme_tags WHERE barriers IS NOT NULL AND model = ?", (RUN,))}
        con.close()
        q = q[~q["key"].isin(done)]
    if args.mode == "pilot":
        q = q.sample(min(24, len(q)), random_state=1)
    n = len(q)
    chars = int(q["text"].astype(str).str.slice(0, MAX_CHARS).str.len().sum())
    est_in = chars / 3.5 + n * 12 + (n / BATCH + 1) * 900
    est_cost = est_in / 1e6 * PRICE_IN + n * 22 / 1e6 * PRICE_OUT
    print(f"{n} items to tag in {-(-n // BATCH)} calls, about ${est_cost:.2f} on {MODEL}.")
    if args.mode == "full" and not args.confirm:
        sys.exit("Refusing to spend: add --confirm.")
    key_ = os.environ.get("OPENAI_API_KEY")
    if not key_:
        sys.exit("OPENAI_API_KEY not set (.env at the project root).")
    client = OpenAI(api_key=key_)

    rows = q.to_dict("records")
    results, t_in, t_out = [], 0, 0
    for s in range(0, len(rows), BATCH):
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
        for i, r in enumerate(chunk):
            if i in tags:
                results.append({**r, "themes": tags[i][0], "barriers": tags[i][1]})
        print(f"  {min(s + BATCH, n)}/{n}")
    cost = t_in / 1e6 * PRICE_IN + t_out / 1e6 * PRICE_OUT
    print(f"tagged {len(results)} of {n}; {t_in:,} in / {t_out:,} out tokens, about ${cost:.3f}.")

    if args.mode == "pilot":
        for r in results[:24]:
            print(f"- [{r['brand']} | {r.get('sentiment')} | flag={r.get('is_barrier')}] {str(r['text'])[:100]!r} -> themes={r['themes']} barriers={r['barriers']}")
        print("Pilot only: nothing written.")
        return
    con = _connect()
    now = datetime.now().isoformat(timespec="seconds")
    con.executemany("INSERT OR REPLACE INTO theme_tags (key, brand, source, themes, text_key, barriers, model, tagged_at, text) VALUES (?,?,?,?,?,?,?,?,?)",
                    [(r["key"], r["brand"], r["source"], json.dumps(r["themes"]), barrier_taxonomy.text_key(r["text"]),
                      json.dumps(r["barriers"]), RUN, now, str(r["text"])) for r in results])
    con.commit()
    con.close()
    print(f"wrote {len(results)} rows to {TAG_DB}")


if __name__ == "__main__":
    main()
