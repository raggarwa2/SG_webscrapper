"""
tag_journey_stage.py

Second pass that answers one question for each friction item: at which step of the consumer journey does the problem happen?

Why a separate pass: tag_voice_items.py reads stage as "where the author is in the buying journey" and answers None when the text
gives no signal. That leaves 62% of friction items without a stage (app reviews 76 of 78, store reviews 83 of 116), because an app
or shop complaint rarely says it. Here the stage is where the FRICTION happens, with rules for app, store and consumer text. Sentiment
and themes are NOT touched, so no other number in the dashboard moves.

Friction item = a complaint as the dashboard defines it (negative or mixed on a theme group, per-theme polarity), or overall
sentiment negative or mixed with at least one theme, in the latest tag version of voice_tags_sg.db.
Sources combined: consumer comments and posts (brand-named pool and category voice), retail reviews, MyACUVUE app reviews.
Brand posts and ads are not friction and are left out.

Stage rule agreed 2026-10-08: app sign-up, registration, login, OTP and date-of-birth entry sit at Trial.

Usage:
  python tag_journey_stage.py                      # pilot: 150 friction items (50 app, 50 retail, 50 consumer), writes only the CSV
  python tag_journey_stage.py --mode full --confirm   # every friction item, writes table journey_stage in journey_stage_sg.db
Input : Scripts/output/voice_items_sg.db and voice_tags_sg.db (read-only).
Output: Scripts/output/journey_stage_pilot.csv (pilot) or Scripts/output/journey_stage_sg.db (full). voice_tags_sg.db is never written.
"""
from __future__ import annotations

import argparse
import json
import os
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

import tag_voice_items as tv   # reuses the item loader, the category rule and the connection defaults

OUT = tv.OUT
PILOT_CSV = OUT / "journey_stage_pilot.csv"
STAGE_DB = OUT / "journey_stage_sg.db"
MODEL = tv.MODEL
BATCH = 15
MAX_CHARS = 600
STAGES = ("Awareness", "Engagement", "Consideration", "Trial", "Purchase", "Repeat/Retention", "None")
STAGE_VERSION = "stage-v4"
Stage = Literal[STAGES]
Conf = Literal["high", "low"]


class ItemOut(BaseModel):
    id: int
    stage: Stage
    confidence: Conf
    reason: str


class BatchOut(BaseModel):
    items: list[ItemOut]


SYSTEM = (
    "Each numbered item is a complaint or problem about contact lenses, a lens retailer or the MyACUVUE app in Singapore (some text is "
    "Chinese; read it as it is). Each item shows [brand or retailer | source | who is speaking | unit]. For each item return the step of "
    "the consumer journey AT WHICH THE PROBLEM HAPPENS, not where the author is in general.\n\n"
    "Stages:\n"
    "- Awareness: first hearing of or noticing the brand or product (ads, social posts, news, word of mouth). Problem: misleading or "
    "irrelevant information, not knowing lenses are an option.\n"
    "- Engagement: ONLINE only: following, reacting to or asking about brand and creator content before deciding. Problem: content "
    "that is unhelpful, promotional or unanswered. A store visit, a store wait or store staff is NEVER Engagement.\n"
    "- Consideration: comparing brands, products or prices, deciding where to buy, finding a store, or enquiring before an eye test or "
    "purchase. Problem: unclear choice, price comparison, no stock information, advice that steers the choice.\n"
    "- Trial: the first use of a lens or of the app. This covers the eye test and fitting, trial lenses, first-wear comfort and handling "
    "(insertion, dryness, irritation, wrong prescription), AND the app's sign-up, registration, login, OTP or verification code, "
    "date-of-birth entry and first launch. Registration and login problems are always Trial.\n"
    "- Purchase: buying and paying. Price paid, checkout, delivery, stock and availability, the sale at a store counter, packaging, "
    "authenticity of what was sold, a prescription demanded at the point of sale.\n"
    "- Repeat/Retention: using or reordering after the first time. Reordering, switching brand, comfort over weeks or years, loyalty "
    "points, rewards and vouchers, app problems that appear once an account exists (update loop, crash, points not showing), unsubscribe "
    "and marketing messages, after-sales and refunds.\n"
    "- None: use only when the text gives no signal about the step even after applying the rules below.\n\n"
    "Rules by source:\n"
    "- App review (MyACUVUE app): follow this fixed mapping. Trial = every problem with getting into or operating the app: login, OTP, "
    "verification, sign-up, registration, date of birth, NRIC or FIN request, freezing, hanging, will not open, crash, blank or welcome "
    "screen, update loop or 'not working after the update', server or connection error, download trouble, hard-to-use screens, "
    "missing buttons or search, and a generic 'does not work' or 'bad app' (confidence low for the generic ones). "
    "Repeat/Retention = loyalty and ongoing relationship: points, rewards, redeem, vouchers, points not logging or reset, the "
    "one-retailer lock, unsubscribe, spam, notifications, advertising or privacy, and complaints that the app does not let you order "
    "lenses or that the developer ignores feedback. None only for text that is not about the app's function at all.\n"
    "- Store review (Google Maps, retailer page): a visit has steps, so name the step where it went wrong. Waiting for or being refused "
    "an eye test or fitting, an absent optometrist, a wrong prescription, trial lenses, an eye test that hurt = Trial. Stock, price, "
    "payment, upselling, a declined freebie, refusing to sell, a purchase that was paid for but not delivered or only part delivered = "
    "Purchase. Booking or attending an eye test, the optometrist, a prescription or fitting is Trial even when staff are rude or "
    "advice is wrong. Consideration in a store review ONLY when the customer says they were just asking, enquiring or browsing, or "
    "relied on a website or phone answer before going, and had not yet started an eye test or a purchase. "
    "Refunds, returns, a lens problem after weeks or years of wear, or reordering = Repeat/Retention. Being a regular customer does "
    "NOT make a complaint Repeat/Retention: judge the step of the problem itself. If the review does not say what the visit was for or "
    "which step failed ('rude staff', 'worst shop') = None, confidence low.\n"
    "- Lens feels bad (dry, red, uncomfortable, painful): Trial when it is the first pair, first wear or first days; "
    "Repeat/Retention when the text says weeks, months or years of use or a change over time; None, confidence low, when nothing "
    "says which.\n"
    "- Forum, social or video comment: read the problem. Choosing between brands, price comparison, asking which to buy = "
    "Consideration; first-wear discomfort or handling = Trial; long-term wear, switching or reordering = Repeat/Retention; "
    "price paid or where it was bought = Purchase.\n\n"
    "confidence: high when the text states or clearly implies the step; low when you are inferring it from the source or the topic. "
    "reason: at most 12 words naming the clue. Return every id you were given."
)


def friction_items() -> pd.DataFrame:
    """Every friction item with its source type, the old stage and the old tags. One row per item_id."""
    d = tv.load_items()
    con = sqlite3.connect(f"file:{tv.TAG_DB.as_posix()}?mode=ro", uri=True)
    t = pd.read_sql_query("SELECT item_id, sentiment, themes, theme_polarity, journey_stage, taxonomy_version, tagged_at FROM voice_tags", con)
    con.close()
    latest = t.loc[t["tagged_at"].idxmax(), "taxonomy_version"]
    t = t[t["taxonomy_version"] == latest].rename(columns={"sentiment": "tag_sentiment", "journey_stage": "old_stage"})
    d = d.merge(t, on="item_id", how="inner")
    d["n_themes"] = d["themes"].map(lambda s: len(json.loads(s)) if isinstance(s, str) else 0)
    # the dashboard's complaint (voice_data.complaints): negative or mixed on a theme group. Items whose overall sentiment is
    # negative or mixed and that carry a theme are included as well, so the set only ever grows.
    pol_bad = d["theme_polarity"].map(lambda s: any(v in ("negative", "mixed") for v in json.loads(s).values()) if isinstance(s, str) else False)
    friction = pol_bad | (d["tag_sentiment"].isin(["negative", "mixed"]) & (d["n_themes"] > 0))

    def bucket(r) -> str:
        if r["source"] == "MyACUVUE app":
            return "App"
        if r["lens"] == "retail_experience" or r["source"] in ("Google Maps", "Facebook retailer reviews"):
            return "Retail reviews"
        if r["voice_type"] == "consumer" and r["in_pool"] == 1:
            return "Consumer, brand-named"
        if r["category_item"]:
            return "Consumer, no brand"
        return "other"

    d["bucket"] = d.apply(bucket, axis=1)
    return d[friction & (d["bucket"] != "other") & (d["body"].str.len() > 0)].copy()


def pilot_sample(d: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for names, n in ((["App"], 50), (["Retail reviews"], 50), (["Consumer, brand-named", "Consumer, no brand"], 50)):
        s = d[d["bucket"].isin(names)]
        parts.append(s.sample(min(n, len(s)), random_state=11))
    return pd.concat(parts)


def tag_batch(client: OpenAI, rows: list[dict], model: str | None = None) -> tuple[dict, int, int]:
    user = "\n".join(f"{i}. [{tv.ctx(r)}] {r['body'][:MAX_CHARS]!r}" for i, r in enumerate(rows))
    resp = client.beta.chat.completions.parse(
        model=model or MODEL, temperature=0,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        response_format=BatchOut,
    )
    out = {it.id: {"stage": it.stage, "confidence": it.confidence, "reason": it.reason}
           for it in resp.choices[0].message.parsed.items if 0 <= it.id < len(rows)}
    return out, resp.usage.prompt_tokens, resp.usage.completion_tokens


def run(client: OpenAI, rows: list[dict], model: str | None = None) -> tuple[list[dict], int, int]:
    results, t_in, t_out, n = [], 0, 0, len(rows)
    for s in range(0, n, BATCH):
        chunk = rows[s:s + BATCH]
        for attempt in range(3):
            try:
                tags, a, b = tag_batch(client, chunk, model)
                break
            except Exception as e:  # noqa: BLE001 - retry on any API or parse error
                print(f"  batch {s // BATCH}: {type(e).__name__}: {e}")
                time.sleep(2 * (attempt + 1))
        else:
            continue
        t_in += a
        t_out += b
        results += [{**r, **tags[i]} for i, r in enumerate(chunk) if i in tags]
        print(f"  {min(s + BATCH, n)}/{n}", flush=True)
    return results, t_in, t_out


def report(res: pd.DataFrame) -> None:
    pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_colwidth", 100)
    order = list(STAGES)
    print("\n== NEW stage by source type (friction items) ==")
    print(pd.crosstab(res["bucket"], res["stage"]).reindex(columns=[c for c in order if c in set(res["stage"])], fill_value=0).to_string())
    print("\n== OLD stage by source type (same items) ==")
    old = res["old_stage"].fillna("None")
    print(pd.crosstab(res["bucket"], old).to_string())
    print("\n== share with a stage: old vs new ==")
    print(pd.DataFrame({"old": (old != "None").groupby(res["bucket"]).mean().round(2),
                        "new": (res["stage"] != "None").groupby(res["bucket"]).mean().round(2),
                        "new, high confidence": ((res["stage"] != "None") & (res["confidence"] == "high")).groupby(res["bucket"]).mean().round(2)}).to_string())
    both = res[(old != "None") & (res["stage"] != "None")]
    if len(both):
        agree = (both["old_stage"] == both["stage"])
        print(f"\n== where both name a stage: {agree.mean():.0%} agree on {len(both)} items ==")
        print(pd.crosstab(both["old_stage"], both["stage"], rownames=["old"], colnames=["new"]).to_string())
    print("\n== sample to hand-check (new stage | confidence | reason) ==")
    for b in ("App", "Retail reviews", "Consumer, brand-named"):
        print(f"\n-- {b}")
        for r in res[res["bucket"] == b].sample(min(8, int((res['bucket'] == b).sum())), random_state=4).itertuples():
            print(f"  [{r.stage} | {r.confidence} | was {r.old_stage}] {r.body[:140]!r}\n      why: {r.reason}")


def save(results: list[dict]) -> None:
    con = sqlite3.connect(STAGE_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS journey_stage(
        item_id TEXT PRIMARY KEY, stage TEXT, confidence TEXT, reason TEXT, stage_version TEXT, model TEXT, tagged_at TEXT)""")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.executemany("INSERT OR REPLACE INTO journey_stage VALUES (?,?,?,?,?,?,?)",
                    [(r["item_id"], r["stage"], r["confidence"], r["reason"], STAGE_VERSION, r.get("model", MODEL), now) for r in results])
    con.commit()
    con.close()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["pilot", "full"], default="pilot")
    ap.add_argument("--confirm", action="store_true", help="required with --mode full: spends API budget and writes journey_stage_sg.db")
    ap.add_argument("--model", default=MODEL, help="OpenAI model; the spend estimate assumes gpt-4o-mini prices")
    ap.add_argument("--tag", default="", help="suffix for the pilot CSV name, to keep runs side by side")
    args = ap.parse_args()

    d = friction_items()
    print("friction items by source type:", d["bucket"].value_counts().to_dict())
    if args.mode == "pilot":
        q = pilot_sample(d)
    else:   # resumable: items already staged under this version are kept and skipped
        q = d
        if STAGE_DB.exists():
            con = sqlite3.connect(STAGE_DB)
            done = {r[0] for r in con.execute("SELECT item_id FROM journey_stage WHERE stage_version = ?", (STAGE_VERSION,))}
            con.close()
            q = d[~d["item_id"].isin(done)]
        print(f"{len(d) - len(q)} already staged under {STAGE_VERSION}, {len(q)} to do.")
    rows = q.to_dict("records")
    n = len(rows)
    est_tokens = sum(min(len(r["body"]), MAX_CHARS) // 3 + 30 for r in rows) + (-(-n // BATCH)) * (len(SYSTEM) // 3)
    print(f"{STAGE_VERSION}: {n} items in {-(-n // BATCH)} calls, about ${est_tokens / 1e6 * tv.PRICE_IN + n * 40 / 1e6 * tv.PRICE_OUT:.3f} on {MODEL}.")
    if args.mode == "full" and not args.confirm:
        sys.exit("Refusing to spend: add --confirm.")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY not set (.env at the project root).")
    results, t_in, t_out = run(OpenAI(api_key=key), rows, args.model)
    print(f"tagged {len(results)} of {n}; {t_in:,} in / {t_out:,} out tokens, about ${t_in / 1e6 * tv.PRICE_IN + t_out / 1e6 * tv.PRICE_OUT:.3f}.")
    res = pd.DataFrame(results)
    if args.mode == "pilot":
        out = PILOT_CSV.with_name(f"journey_stage_pilot{args.tag}.csv")
        res[["item_id", "source", "bucket", "brand_std", "old_stage", "stage", "confidence", "reason", "body"]].to_csv(
            out, index=False, encoding="utf-8-sig")
        report(res)
        print(f"\nPilot only: nothing written to any database. Rows for hand-checking: {out}")
        return
    save([{**r, "model": args.model} for r in results])
    report(res)
    print(f"Wrote {len(results)} rows to {STAGE_DB}")


if __name__ == "__main__":
    main()
