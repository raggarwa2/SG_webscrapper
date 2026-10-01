"""
build_persona_funnel_category.py -- Gold persona x funnel-stage table,
category-level (all 10 tracked brands), real and reproducible.

Reads output/acneaid_persona_funnel_tagged_all_channels.csv (built this
session by all_channel_persona_classifier.py + all_channel_funnel_classifier.py,
QC'd and regression-tested -- see acneaid_medallion/gold/
QC_ALL_CHANNEL_PERSONA_TAGGING_FINALIZATION.md for the full audit trail).

Supersedes gold/persona_funnel_metrics.csv, which had no producing script
anywhere in the repo (a Rule 6 violation -- a fragile, hand-authored,
non-reproducible snapshot). This script is the producing script; re-run it
any time the source corpus changes and every downstream number (this CSV,
and the dashboard that reads it) regenerates.

stage_share_pct is a persona's share of ITS OWN funnel-classified volume,
not a sequential cohort -- no individual mention is tracked from one stage
to the next. A mention with a persona_key but no funnel_stage_signal
(most mentions -- funnel-stage language is a content-quality ceiling, same
finding as persona tagging itself) is excluded from the stage_share_pct
denominator, not treated as a stage.

CATEGORY-LEVEL = all 10 tracked brands (Acne-Aid + 9 competitors), each
mention already brand-resolved by an earlier entity-resolution pass. This
is NOT the same "category-level" term used elsewhere in this project for
brand_key=null discourse -- here it means "all brands", per explicit
scoping instruction this session. See QC doc for the full distinction.

2026-08-11 fix: QC_FINAL_PERSONA_JOURNEY_AUDIT_20260810.md Finding 1
(SERIOUS) found Instagram's ig_post_* rows include brand/retailer feed
posts (its own sale calendar -- "Acne-Aid Brand of the Week...40% off"),
not consumer voice. First pass of this fix excluded all ig_post_* by
mention_id prefix -- too blunt: classify_instagram_content_type.py had
already built a real per-post classification (by actual owner_username,
not text heuristics) in output/acneaid_persona_funnel_tagged_all_channels_
WITH_IG_CONTENT_TYPE.csv, showing only 50/221 ig_post rows are actually
brand_official; 60 are reseller_marketing (third-party/deal pages, not
the brand but not a genuine individual either); 111 are individual
(genuine posters, wrongly excluded by the prefix-only pass). That
content-type file predates last night's Lazada persona reclassification,
but ig_content_type only depends on the static Instagram owner-account
DB (not on any persona run), so it's joined onto the current corpus by
mention_id below rather than re-derived. brand_official and
reseller_marketing are both excluded (neither is genuine first-person
consumer experience); individual ig_post rows and all ig_comment rows
are kept.
"""
from pathlib import Path

import pandas as pd

GOLD = Path(__file__).resolve().parent
REPO_ROOT = GOLD.parent.parent
CORPUS_PATH = REPO_ROOT / "output" / "acneaid_persona_funnel_tagged_all_channels.csv"
IG_CONTENT_TYPE_PATH = REPO_ROOT / "output" / "acneaid_persona_funnel_tagged_all_channels_WITH_IG_CONTENT_TYPE.csv"
OUT_PATH = GOLD / "persona_funnel_metrics_v2.csv"
EXCLUDED_IG_CONTENT_TYPES = {"brand_official", "reseller_marketing"}

STAGES = ["Awareness", "Consideration", "Trial", "Purchase", "Retention"]
PERSONA_NAMES = {
    "A": "Acne Novice", "B": "DIY Experimenter", "C": "Clinical Seeker",
    "D": "Deal-Driven Buyer", "E": "Chronic Warrior", "F": "Value-Loyal Repeater",
}
PERSONA_ORDER = ["A", "B", "C", "D", "E", "F"]


def main():
    df = pd.read_csv(CORPUS_PATH)

    n_before = len(df)
    n_before_tagged = df["persona_key"].notna().sum()

    ig_types = pd.read_csv(IG_CONTENT_TYPE_PATH, usecols=["mention_id", "ig_content_type"]).set_index("mention_id")["ig_content_type"]
    df["ig_content_type"] = df["mention_id"].map(ig_types)
    is_ig_row = df["mention_id"].astype(str).str.startswith(("ig_post_", "ig_comment_"))
    unmatched_ig = int((is_ig_row & df["ig_content_type"].isna()).sum())
    if unmatched_ig:
        print(f"  [warn] {unmatched_ig} Instagram rows have no ig_content_type match -- kept as-is (not excluded)")

    is_excluded = df["ig_content_type"].isin(EXCLUDED_IG_CONTENT_TYPES)
    n_excluded = int(is_excluded.sum())
    n_excluded_tagged = int(df.loc[is_excluded, "persona_key"].notna().sum())
    df = df[~is_excluded].drop(columns=["ig_content_type"]).copy()
    print(f"Excluded {n_excluded} Instagram brand_official/reseller_marketing rows "
          f"({n_excluded_tagged} were persona-tagged) per QC_FINAL_PERSONA_JOURNEY_AUDIT_20260810.md "
          f"Finding 1 + classify_instagram_content_type.py: "
          f"{n_before} -> {len(df)} rows, {n_before_tagged} -> {df['persona_key'].notna().sum()} tagged")

    rows = []
    for p in PERSONA_ORDER:
        p_rows = df[df["persona_key"] == p]
        p_total_mentions = len(p_rows)
        p_funnel = p_rows[p_rows["funnel_stage_signal"].notna()]
        p_funnel_total = len(p_funnel)

        for stage in STAGES:
            n = int((p_funnel["funnel_stage_signal"] == stage).sum())
            pct = round(n / p_funnel_total * 100, 1) if p_funnel_total > 0 else 0.0
            rows.append({
                "persona_key": p,
                "persona_name": PERSONA_NAMES[p],
                "journey_stage": stage,
                "volume_absolute": n,
                "stage_share_pct": pct,
                "persona_total_funnel_classified": p_funnel_total,
                "persona_total_mentions": p_total_mentions,
                "funnel_classified_rate_pct": round(p_funnel_total / p_total_mentions * 100, 1),
            })

    out = pd.DataFrame(rows)

    total_tagged = df["persona_key"].notna().sum()
    out["category_share_pct"] = out["persona_key"].map(
        lambda p: round((df["persona_key"] == p).sum() / total_tagged * 100, 1)
    )

    # QC finding 2026-08-10 (see QC_SHOPEE_8_8_PERSONA_CLASSIFICATION.md): the
    # shopee_8.8_sale batch is a flash-sale pull, not representative of the
    # full-year discourse mix (D+F skew much higher than baseline). Rather than
    # silently blend it into category_share_pct, also compute the same share
    # EXCLUDING that batch (if the corpus_batch column is present -- older corpus
    # snapshots without it fall back to the combined-only view).
    if "corpus_batch" in df.columns:
        baseline = df[df["corpus_batch"] != "shopee_8.8_sale"]
        baseline_total_tagged = baseline["persona_key"].notna().sum()
        out["category_share_pct_excl_8_8_sale"] = out["persona_key"].map(
            lambda p: round((baseline["persona_key"] == p).sum() / baseline_total_tagged * 100, 1)
        )
    else:
        out["category_share_pct_excl_8_8_sale"] = None

    out.to_csv(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH} ({len(out)} rows)")

    print("\n=== Verification digest ===")
    print(f"Total corpus rows: {len(df)}")
    print(f"Total persona-tagged (any brand): {total_tagged}")
    for p in PERSONA_ORDER:
        sub = out[out["persona_key"] == p]
        print(f"\n{p} ({PERSONA_NAMES[p]}): {sub['persona_total_mentions'].iloc[0]} mentions, "
              f"{sub['category_share_pct'].iloc[0]}% category share "
              f"({sub['category_share_pct_excl_8_8_sale'].iloc[0]}% excl. 8.8 sale batch), "
              f"{sub['funnel_classified_rate_pct'].iloc[0]}% also funnel-classified")
        for _, r in sub.iterrows():
            print(f"    {r['journey_stage']:<14} {r['stage_share_pct']:>5.1f}%  (n={r['volume_absolute']})")


if __name__ == "__main__":
    main()
