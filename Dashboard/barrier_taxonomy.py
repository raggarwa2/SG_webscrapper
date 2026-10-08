"""
One barrier list for the whole dashboard (set B).

Every source flags "barriers" differently (a 1-2 star app review, a model flag on a YouTube/Reddit comment, derived tags on
Lazada reviews and KiasuParents), and the old keyword list (set A) merged comfort with handling and could not be linked to
the desk research. Set B is the research framework's own list (10 consolidated barriers) plus colour & look, availability,
authenticity and store service. Each label rolls up to one of the eight themes (THEME_OF; the theme list is theme_tags.THEMES),
so reports lead with a theme and show the barrier label as detail.

classify(text) returns the labels a piece of text carries:
  - the model's labels once Scripts/theme_tag_sg.py has tagged the text (stored in Scripts/output/theme_tags_sg.db), else
  - a keyword draft (KEYWORDS), which is directional only: it leaves about a third of flagged items as OTHER.
Unmatched or label-free text is OTHER rather than forced into a type.
"""

import hashlib
import json
import re
import sqlite3
from pathlib import Path

OTHER = "Other / unclear"

# keyword draft: label -> regex. Order is display order.
KEYWORDS = {
    "Price & channel cost": r"\bpric|expensive|\bcost|cheap|afford|overpriced|value for money|johor|\bjb\b|coupon|half the price|cheaper|worth it",
    "Loyalty & rewards": r"\bpoints?\b|redeem|one vendor|change stores?|different store|preferred registered|e-?stamp|voucher|loyalty|reward|points.{0,30}(gone|lost|expired|missing|reset)|catalogue",
    "Registration / login friction": r"\botp\b|log ?in|log ?on|sign ?up|regist|\bdob\b|birth|freez|frozen|\bhang\b|stuck|crash|can'?t open|cannot open|forced update|update (loop|prompt)|app update|verif|residen|nric|fin number",
    "Unwanted messaging / privacy": r"unsubscribe|spam|advert|marketing (message|email|sms|list)|mailing list|privacy|promo(tion)? (sms|message|whatsapp)|share (my )?(mobile|number)",
    "App utility & support": r"remind|reorder|re-order|track(er|ing)? points|useless app|whatsapp|customer (service|support|help)|no (chat|reply|response)|chat support",
    "Product experience": r"comfort|\bdry|irritat|itch|sting|burn|blurr|cloud|vision|vison|astigmat|presbyop|red eye|painful|discomfort|allerg|bad experience|didn'?t (like|work)|fatigue|tired",
    "Fear / handling difficulty": r"infection|scared|afraid|\bfear|touch(ing)? (my |the )?eye|inserting|insert\b|remov(e|ing)|put (it |them )?in|take (it |them )?out|hard (as hell )?to (wear|use|remove|take out|insert|put)|difficult (to|removing|inserting)|fragile|\btear",
    "Lack of professional guidance": r"prescription|optometrist|\bdoctor|eye (test|exam)|\bexam\b|fitting|trial (lens|pair|set)|trialed|check.?up|ophthalm|clinic|\becp\b|myopia|no one (told|taught)|teach",
    "Colour & look (cosmetic lenses)": r"colou?rs?\b|pupil|show up|diameter|brown eyes|green eyes|looks? (funny|good on)|made me look|looking like|olive|hazel|\bgr[ae]y\b|lilac|shiny",
    "Availability & where to buy": r"where to buy|can'?t find|cannot find|out of stock|\bstock\b|availab|sold out|not sold|\bimport|order(ed)? from|hong kong|malaysia|\bonline\b|lazada|shopee",
    "Authenticity & quality control": r"\bfake|counterfeit|authentic|genuine|recalled|recall notice|product recall|particles|defect|quality|\bbatch\b|japanese writing|\bsealed|expir|tamper",
    "Store service & upsell": r"sales ?person|salesperson|upsell|pushy|service at the store|\bstaff\b|\brude\b|queue|wait(ing)? time|their service",
}
_RE = {k: re.compile(v, re.I) for k, v in KEYWORDS.items()}
TYPES_B = KEYWORDS      # name kept for triangulation_pages
TYPES = KEYWORDS

# what each label means (also the tagging prompt)
DEFINITIONS = {
    "Price & channel cost": "seen as expensive, cheaper elsewhere (online, Johor Bahru, marketplace coupons), cost across channels",
    "Loyalty & rewards": "points tied to one store, purchases elsewhere earn nothing, points frozen or reset, vouchers or rewards missing or reduced",
    "Registration / login friction": "OTP, login or forced app update failing; sign-up needing a mobile number, ID or residency; app freezing or crashing",
    "Unwanted messaging / privacy": "promotional messages, cannot unsubscribe, reluctance to share a mobile number, privacy worries",
    "App utility & support": "app seen as only a points tracker, no reorder or lens-change reminder, no chat or help when something fails",
    "Product experience": "discomfort, dryness, irritation, blurred or cloudy vision, a lens that feels thick, heavy or unbreathable, astigmatism or presbyopia not served, a previous bad experience",
    "Fear / handling difficulty": "fear of infection or touching the eye, difficulty inserting or removing, lens folding or tearing",
    "Lack of professional guidance": "no eye-care professional prompt, thin fitting or teaching, teaching tied to a bulk purchase, no trial lens, unclear advice",
    "Colour & look (cosmetic lenses)": "colour not showing, pupil size, unnatural look, shade choice",
    "Availability & where to buy": "cannot find where to buy, out of stock, only sold abroad or by importers",
    "Authenticity & quality control": "fake or grey-market worries, recalls, defects, particles, tampered or expired packs",
    "Store service & upsell": "pushy staff, upselling, a sales person's attitude or claims, long waits, rude or slow service at a retailer",
}

# label -> theme (theme list: theme_tags.THEMES)
THEME_OF = {
    "Price & channel cost": "Price & value",
    "Loyalty & rewards": "Loyalty & app",
    "Registration / login friction": "Loyalty & app",
    "Unwanted messaging / privacy": "Loyalty & app",
    "App utility & support": "Loyalty & app",
    "Product experience": "Comfort & product",
    "Fear / handling difficulty": "Fitting & guidance",
    "Lack of professional guidance": "Fitting & guidance",
    "Colour & look (cosmetic lenses)": "Look & colour",
    "Availability & where to buy": "Access & availability",
    "Authenticity & quality control": "Trust & authenticity",
    "Store service & upsell": "Service",
}

TAG_DB = Path(__file__).resolve().parent.parent / "Scripts" / "output" / "theme_tags_sg.db"


def norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def text_key(text) -> str:
    """Brand-free key: a barrier label depends on what the text says, not on the brand."""
    return hashlib.sha1(norm(text).encode("utf-8")).hexdigest()[:16]


_store = {"mtime": None, "labels": {}}


def _labels() -> dict:
    """{text_key: [labels]} from the tagging run; reloaded when the file changes."""
    try:
        mtime = TAG_DB.stat().st_mtime
    except OSError:
        return {}
    if _store["mtime"] != mtime:
        labels: dict = {}
        try:
            con = sqlite3.connect(f"file:{TAG_DB}?mode=ro", uri=True)
            for k, v in con.execute("SELECT text_key, barriers FROM theme_tags WHERE barriers IS NOT NULL AND text_key IS NOT NULL"):
                got = [x for x in json.loads(v) if x in KEYWORDS]
                labels[k] = sorted(set(labels.get(k, [])) | set(got), key=list(KEYWORDS).index)
            con.close()
        except (sqlite3.Error, ValueError):
            labels = {}
        _store.update(mtime=mtime, labels=labels)
    return _store["labels"]


def classify_b(text) -> list:
    """Keyword draft: labels a piece of text carries, or [OTHER] when none match."""
    t = text if isinstance(text, str) else ""
    hits = [k for k, rx in _RE.items() if rx.search(t)]
    return hits or [OTHER]


def is_tagged(text) -> bool:
    return text_key(text) in _labels()


def classify(text) -> list:
    """Labels a piece of text carries: the model's once tagged, else the keyword draft. [OTHER] when none."""
    got = _labels().get(text_key(text))
    if got is not None:
        return got or [OTHER]
    return classify_b(text)


def themes_of(text) -> list:
    """The themes of a text's labels (one per theme), or [OTHER] when it carries none."""
    out = []
    for lab in classify(text):
        t = THEME_OF.get(lab)
        if t and t not in out:
            out.append(t)
    return out or [OTHER]
