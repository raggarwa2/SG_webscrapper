"""
One barrier list applied across sources (App & Barriers page).

Every source flags "barriers" differently (a 1-2 star app review, an LLM flag on a
YouTube/Reddit comment, derived tags on Lazada reviews and KiasuParents). This puts
the flagged text from all of them into the same eight types so they can be read side
by side. Keyword-based and multi-label (a comment can carry several types), so it is
directional; unmatched text goes to OTHER rather than being forced into a type.
"""

import re

OTHER = "Other / unclear"

# type -> regex. Order is display order.
TYPES = {
    "App & sign-up friction": r"\bapp\b|\bapps\b|\botp\b|log ?in|log ?on|sign ?up|regist|\bdob\b|birth|freez|frozen|\bhang\b|stuck|crash|doesn'?t work|not working|can'?t open|cannot open|update",
    "Points, rewards & store lock-in": r"\bpoints?\b|reward|redeem|voucher|coupon|\btoken|change stores?|different store|one vendor|preferred registered|optical store",
    "Marketing & privacy": r"unsubscribe|spam|advert|marketing (message|email|sms|list)|mailing list|privacy|nric|fin number|promoting|promotion message",
    "Comfort, handling & vision problems": r"comfort|\bdry|irritat|itch|sting|burn|blurr|cloud|vision|vison|see clearly|painful|thick|heavy|breathable|red eye|infection|fatigue|tired|border of the lens|feel the lens|weight|discomfort|allerg|hard (as hell )?to (remove|take out|insert|put)|difficult (to|removing|inserting)|fragile|\btear",
    "Colour & look (cosmetic lenses)": r"colou?rs?\b|pupil|show up|diameter|brown eyes|green eyes|looks? (funny|good on)|made me look|looking like|olive|hazel|\bgr[ae]y\b|lilac|shiny",
    "Retailer service & upsell": r"sales ?person|salesperson|upsell|pushy|service at the store|\bstaff\b|\brude\b|queue|wait(ing)? time|their service",
    "Price & value": r"\bpric|expensive|\bcost|cheap|afford|value for money|\$ ?\d|overpriced|half the price|worth it",
    "Authenticity & quality control": r"\bfake|counterfeit|authentic|genuine|recalled|recall notice|product recall|particles|defect|quality|\bbatch\b|japanese writing|\bsealed|expir|tamper",
    "Prescription, fitting & eye-care access": r"prescription|optometrist|\bdoctor|eye test|eye exam|\bexam\b|fitting|trial (lens|pair|set)|trialed|trial lenses|check.?up|ophthalm|clinic|\bmanager\b",
    "Availability & where to buy": r"where to buy|can'?t find|cannot find|out of stock|\bstock\b|availab|sold out|not sold|\bimport|order(ed)? from|hong kong|malaysia|\bonline\b|lazada|shopee",
}
_RE = {k: re.compile(v, re.I) for k, v in TYPES.items()}


def classify(text) -> list:
    """Barrier types a piece of text carries, or [OTHER] when none match."""
    t = text if isinstance(text, str) else ""
    hits = [k for k, rx in _RE.items() if rx.search(t)]
    return hits or [OTHER]
