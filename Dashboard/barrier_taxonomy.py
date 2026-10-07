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


# ---------------------------------------------------------------------------
# Proposed set B: the 10 consolidated barriers from triangulation_sg/mappings.py, with the sparse
# ones merged for display (loyalty + rewards; app utility + support) and three market-level types
# added that the loyalty/registration framework does not cover (colour & look, availability,
# authenticity). Draft keywords for comparison with the current set; directional only.
# ---------------------------------------------------------------------------
TYPES_B = {
    "Price & channel cost": r"pric|expensive|cost|cheap|afford|overpriced|value for money|johor|jb|coupon|half the price|cheaper|worth it",
    "Loyalty & rewards": r"points?|redeem|one vendor|change stores?|different store|preferred registered|e-?stamp|voucher|loyalty|reward|points.{0,30}(gone|lost|expired|missing|reset)|catalogue",
    "Registration / login friction": r"otp|log ?in|log ?on|sign ?up|regist|dob|birth|freez|frozen|hang|stuck|crash|can'?t open|cannot open|forced update|update (loop|prompt)|app update|verif|residen|nric|fin number",
    "Unwanted messaging / privacy": r"unsubscribe|spam|advert|marketing (message|email|sms|list)|mailing list|privacy|promo(tion)? (sms|message|whatsapp)|share (my )?(mobile|number)",
    "App utility & support": r"remind|reorder|re-order|track(er|ing)? points|useless app|whatsapp|customer (service|support|help)|no (chat|reply|response)|chat support",
    "Product experience": r"comfort|dry|irritat|itch|sting|burn|blurr|cloud|vision|vison|astigmat|presbyop|red eye|painful|discomfort|allerg|bad experience|didn'?t (like|work)|fatigue|tired",
    "Fear / handling difficulty": r"infection|scared|afraid|fear|touch(ing)? (my |the )?eye|inserting|insert|remov(e|ing)|put (it |them )?in|take (it |them )?out|hard (as hell )?to (wear|use|remove|take out|insert|put)|difficult (to|removing|inserting)|fragile|tear",
    "Lack of professional guidance": r"prescription|optometrist|doctor|eye (test|exam)|exam|fitting|trial (lens|pair|set)|trialed|check.?up|ophthalm|clinic|ecp|myopia|no one (told|taught)|teach",
    "Colour & look (cosmetic lenses)": r"colou?rs?|pupil|show up|diameter|brown eyes|green eyes|looks? (funny|good on)|made me look|looking like|olive|hazel|gr[ae]y|lilac|shiny",
    "Availability & where to buy": r"where to buy|can'?t find|cannot find|out of stock|stock|availab|sold out|not sold|import|order(ed)? from|hong kong|malaysia|online|lazada|shopee",
    "Authenticity & quality control": r"fake|counterfeit|authentic|genuine|recalled|recall notice|product recall|particles|defect|quality|batch|japanese writing|sealed|expir|tamper",
}
_RE_B = {k: re.compile(v, re.I) for k, v in TYPES_B.items()}


def classify_b(text) -> list:
    """Set-B barrier types a piece of text carries, or [OTHER] when none match."""
    t = text if isinstance(text, str) else ""
    hits = [k for k, rx in _RE_B.items() if rx.search(t)]
    return hits or [OTHER]
