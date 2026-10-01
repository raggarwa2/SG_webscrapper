#!/usr/bin/env python3
"""
translate_reviews_th.py — English translation for Boots TH product reviews.
Standalone script, sibling to pipeline_th.py. Fills product_reviews.review_text_en
for every row where review_text is present but not yet translated. Batches rows
through gpt-4o-mini (same model as the rest of the pipeline) to keep call count
low -- reviews are short, so ~25 per call stays well within output limits.

Translation provenance principle (CONTEXT.md): review_text (original Thai) is
never overwritten -- review_text_en is an additive column, so every quote stays
fact-traceable back to its original.

Usage:
    python translate_reviews_th.py                # translate everything untranslated
    python translate_reviews_th.py --batch-size 25
    python translate_reviews_th.py --limit 50      # dry-run a small batch first
"""

import argparse
import logging
import sys
from typing import List

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from pipeline_th import open_db, cost_tracker

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


class ReviewTranslation(BaseModel):
    index: int
    content_en: str


class ReviewBatch(BaseModel):
    translations: List[ReviewTranslation]


SYSTEM_PROMPT = (
    "You translate short Thai consumer product reviews (skincare) into concise, "
    "natural English. Preserve the informal tone and meaning; do not add "
    "commentary. If a review is already in English or is just a number/emoji, "
    "return it unchanged. Return exactly one translation per input, matching "
    "the given index."
)


def translate_batch(client: OpenAI, rows: List[tuple]) -> dict:
    """rows: list of (id, review_text). Returns {id: content_en}."""
    numbered = "\n".join(f"[{i}] {text}" for i, (_id, text) in enumerate(rows))
    resp = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": numbered},
        ],
        response_format=ReviewBatch,
        max_tokens=2000,
    )
    cost_tracker.add(resp.usage)
    parsed = resp.choices[0].message.parsed
    out = {}
    for t in parsed.translations:
        if 0 <= t.index < len(rows):
            out[rows[t.index][0]] = t.content_en
    return out


def run(db_path: str, batch_size: int, limit: int | None) -> None:
    conn = open_db(db_path)
    query = (
        "SELECT id, review_text FROM product_reviews "
        "WHERE review_text IS NOT NULL AND TRIM(review_text) != '' "
        "AND review_text_en IS NULL"
    )
    if limit:
        query += f" LIMIT {limit}"
    rows = conn.execute(query).fetchall()
    rows = [(r["id"], r["review_text"]) for r in rows]
    log.info(f"[TRANSLATE] {len(rows)} reviews need translation")
    if not rows:
        return

    client = OpenAI()
    done = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        try:
            translations = translate_batch(client, batch)
        except Exception as e:
            log.warning(f"  Batch {i // batch_size + 1} failed: {e}")
            continue
        for review_id, content_en in translations.items():
            conn.execute(
                "UPDATE product_reviews SET review_text_en = ? WHERE id = ?",
                (content_en, review_id),
            )
        conn.commit()
        done += len(translations)
        log.info(f"  Batch {i // batch_size + 1}: {len(translations)}/{len(batch)} translated "
                  f"({done}/{len(rows)} total)")

    cost_tracker.report()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate Boots TH product reviews to English")
    parser.add_argument("--db", default="output/acneaid_th.db")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--limit", type=int, default=None, help="Only translate the first N untranslated rows")
    args = parser.parse_args()

    run(args.db, args.batch_size, args.limit)
