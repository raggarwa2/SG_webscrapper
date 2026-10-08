"""
Stage 1 EBI read-out helpers shared by the Brand Protection, App & Barriers and
Market & Competitors pages: the data cut-off, the minimum-sample rule, the
evidence-strength tags, the "what this can't tell you yet" box, listing
de-duplication and the pack-volume parser used for price-per-100-mL.

Ground rules (EBI_insights_plan.md): every insight carries an evidence label and
its n; a percentage whose base is below MIN_N is not shown, only the count.
"""

import html
import re

import pandas as pd
import streamlit as st

CUTOFF = "2 Oct 2026"
CUTOFF_DATE = "2026-10-02"
MIN_N = 15          # smallest base a percentage may be shown on
MIN_COUNT = 10      # fewest comments a theme or bar needs to be drawn at all; under it, a count in a note only


def is_thin(n) -> bool:
    """True when a base is under MIN_N but not empty: the chart may be drawn, but only as directional."""
    return 0 < n < MIN_N

_TAGS = {
    "fact": ("Market fact", "ev-fact"),
    "dir": ("Directional", "ev-dir"),
    "int": ("Needs internal data", "ev-int"),
}


def tag(kind: str) -> str:
    label, cls = _TAGS[kind]
    return f'<span class="ev {cls}">{label}</span>'


def page_header(question: str, kinds: list, caption: str = "") -> None:
    """Decision question + evidence tags at the top of a page."""
    st.markdown(
        '<div class="ev-head">'
        f'<div class="ev-q">{html.escape(question)}</div>'
        + "".join(tag(k) for k in kinds)
        + (f'<div class="ev-meta" style="margin:6px 0 0">{caption}</div>' if caption else "")
        + "</div>",
        unsafe_allow_html=True,
    )


def limits(items: list) -> None:
    """The "what this can't tell you yet" box. items are trusted inline-HTML strings."""
    st.markdown(
        '<div class="ev-limits"><b>What this can&rsquo;t tell you yet</b><ul>'
        + "".join(f"<li>{i}</li>" for i in items)
        + "</ul></div>",
        unsafe_allow_html=True,
    )


def share(k: int, n: int) -> str:
    """'k/n = x%' when n >= MIN_N, else just the count so a thin base can't read as a rate."""
    if n >= MIN_N:
        return f"{k / n * 100:.0f}% ({k}/{n})"
    return f"{k} of {n} (n<{MIN_N}, % hidden)"


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

def dedupe_listings(products: pd.DataFrame) -> pd.DataFrame:
    """The scrapers re-pulled the same marketplace listings across runs (143 rows,
    far fewer distinct listings). One row per (site, seller, title), latest scrape wins."""
    if products.empty:
        return products
    d = products.sort_values("scraped_at")
    return d.drop_duplicates(["site", "store_name", "product_name"], keep="last")


_NUM = r"(\d+(?:\.\d+)?)"
_RE_COUNT_X_VOL = re.compile(rf"(\d+)\s*[x×]\s*{_NUM}\s*ml", re.I)
_RE_VOL_X_COUNT = re.compile(rf"{_NUM}\s*ml\s*[x×]\s*(\d+)", re.I)
_RE_VOL = re.compile(rf"{_NUM}\s*ml", re.I)


def volume_ml(product_name, pack_size=None) -> float:
    """Total solution volume in mL parsed from a listing title (falling back to its
    pack_size field), e.g. '300mL x 3' -> 900, '3 x300ml + 90ml travel kit' -> 900,
    'Biotrue 300ml Twin Pack' -> 600. NaN when no volume is stated or the result is
    implausible (< 30 mL or > 3,000 mL) — those listings are excluded from per-mL
    price rather than guessed."""
    for text in (product_name, pack_size):
        t = str(text) if isinstance(text, str) else ""
        first = _RE_VOL.search(t) if t else None
        if not first:
            continue
        # A "N x V ml" / "V ml x N" multiplier only counts if it applies to the FIRST volume
        # stated; later ones are bonus items ("... + Free 120ml x 2").
        m = _RE_COUNT_X_VOL.search(t)
        if m and m.start() <= first.start():
            vol = int(m.group(1)) * float(m.group(2))
        else:
            m = _RE_VOL_X_COUNT.search(t)
            if m and m.start() <= first.start():
                vol = float(m.group(1)) * int(m.group(2))
            else:
                vol = float(first.group(1))
                bundle = re.search(r"bundle of (\d+)|x\s*(\d+)\s*(?:btls?|bottles?)", t, re.I)
                if bundle:
                    vol *= int(bundle.group(1) or bundle.group(2))
                elif re.search(r"twin", t, re.I):
                    vol *= 2
                elif re.search(r"triple|3[- ]?pack", t, re.I):
                    vol *= 3
        if 30 <= vol <= 3000:
            return vol
    return float("nan")


def note(df: pd.DataFrame, source: str, date_col: str = None, noun: str = "items") -> str:
    """One-line chart footnote: 'Source · Mon YYYY – Mon YYYY · N noun' (dates when available)."""
    if df is None or len(df) == 0:
        return source
    parts = [source]
    if date_col and date_col in df.columns:
        d = pd.to_datetime(df[date_col], errors="coerce", utc=True).dropna()
        if not d.empty:
            lo, hi = d.min().strftime("%b %Y"), d.max().strftime("%b %Y")
            parts.append(lo if lo == hi else f"{lo} \u2013 {hi}")
    parts.append(f"{len(df):,} {noun}")
    return " \u00b7 ".join(parts)


def count(n: int, noun: str) -> str:
    """'1 review' / '5 reviews': drop the plural 's' on the first plural word when n == 1."""
    if n == 1:
        noun = re.sub(r"\b(\w{3,})s\b", r"\1", noun, count=1)
    return f"{n:,} {noun}"
