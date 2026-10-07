# Re-tags Facebook SG data with (a) a strict CONTACT-LENS flag separate from
# spectacle lenses, (b) a barrier tag using the project's 10-barrier taxonomy
# (triangulation_sg/mappings.py BARRIERS) plus two PROPOSED retail-access tags
# not in that taxonomy, (c) contest/spam detection for brand-page comments.
# Rule-based, no LLM cost; safe to re-run (overwrites the new columns only).
import re, sqlite3
from pathlib import Path

OUT = Path(__file__).parent / "output"

CL = re.compile(r"contact lens|contact lense|contacts\b|\bCL\b|daily disposable|dailies|acuvue|air optix|biofinity|"
                r"myday|clariti|biotrue|ortho-?k|okto|隐形|隱形|trial lens|monthly lens|colou?red lens|circle lens", re.I)
SPEC = re.compile(r"spectacle|glasses|frame|progressive|sunglass|nose pad|bifocal", re.I)

# (tag, regex) -- first match wins; order = specificity.
BARRIER_RULES = [
    ("[PROPOSED] eye-exam gating or fee",
     re.compile(r"checking fee|pay for the check|more than 6 months|eye ?(check|exam)\w* (is )?required|need(ed)? (a|an) (eye )?(check|exam)|not the same", re.I)),
    ("[PROPOSED] stock / appointment availability or delivery wait",
     re.compile(r"out of stock|no stock|not available|didn.?t have|restock|ready stock|hold ready stock|deliver|wait(ed)? (for )?\d* ?(months|weeks)|no response|appointment (is )?full|no (more )?slot", re.I)),
    ("rewards unreliable or reduced",
     re.compile(r"voucher.{0,120}(yet to|no avail|emailed|not|never|still)|(not|never|still).{0,40}voucher|redeem", re.I)),
    ("price and channel cost",
     re.compile(r"expensive|overpriced|price|cheap|\$\d|discount|voucher not|too much", re.I)),
    ("product experience",
     re.compile(r"irritat|dry(ness| eye)|uncomfortable|pain|discomfort|blurr|headache|broke|torn|foggy|stuck in my eye", re.I)),
    ("fear or handling difficulty",
     re.compile(r"phobia|scared|afraid|first time.{0,30}(wear|put)|insert|remove|put (it )?on", re.I)),
    ("lack of professional guidance",
     re.compile(r"pushy|upsell|not explain|didn.?t explain|trial|sample|fitting|where (can|to) (i )?(buy|purchase|get)|do you have|near \w+|how to (buy|order)", re.I)),
    ("prefers WhatsApp/seller chat or lacks support",
     re.compile(r"whatsapp|chat support|no reply|customer service|unresponsive", re.I)),
]

CONTEST = re.compile(r"gardens by the bay|marina bay sands|fort canning|jewel changi|liked and shared|^done!?|hope to win|good luck|"
                     r"^i need acuvue|^@followers|congratulations|ig story|multime|unlockedyouraccounts|^[\W\d]{0,6}$", re.I)


def barrier_for(text: str):
    for tag, rx in BARRIER_RULES:
        if rx.search(text or ""):
            return tag
    return None


def add_cols(conn, table, cols):
    have = {r[1] for r in conn.execute(f"pragma table_info({table})")}
    for c, t in cols.items():
        if c not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {c} {t}")


def retag_retailers():
    conn = sqlite3.connect(OUT / "facebook_retailers_sg.db")
    add_cols(conn, "fb_retailer_reviews", {"is_contact_lens": "INTEGER", "is_spectacle_only": "INTEGER", "barrier_tag": "TEXT", "barrier_polarity": "TEXT"})
    add_cols(conn, "fb_retailer_posts", {"is_contact_lens": "INTEGER"})
    for rid, text, rec in conn.execute("select review_key,text,recommended from fb_retailer_reviews").fetchall():
        cl = bool(CL.search(text or ""))
        spec = bool(SPEC.search(text or "")) and not cl
        # barrier tags only on contact-lens reviews, and only on non-recommend OR friction wording
        tag = barrier_for(text) if cl else None
        # 'barrier' = complaint (not recommended); 'mitigated' = recommended review describing a barrier the
        # retailer solved (e.g. free delivery when out of stock) -- useful as a what-works signal.
        pol = None if not tag else ("barrier" if rec == 0 else "mitigated")
        conn.execute("update fb_retailer_reviews set is_contact_lens=?, is_spectacle_only=?, barrier_tag=?, barrier_polarity=? where review_key=?",
                     (int(cl), int(spec), tag, pol, rid))
    for pid, text in conn.execute("select post_id,text from fb_retailer_posts").fetchall():
        conn.execute("update fb_retailer_posts set is_contact_lens=? where post_id=?", (int(bool(CL.search(text or ""))), pid))
    conn.commit()
    return conn


def retag_brand():
    conn = sqlite3.connect(OUT / "facebook_data_sg.db")
    add_cols(conn, "fb_comments", {"is_contest_or_spam": "INTEGER", "barrier_tag": "TEXT", "barrier_polarity": "TEXT"})
    for cid, text, sent in conn.execute("select id,comment_text,sentiment from fb_comments").fetchall():
        contest = bool(CONTEST.search(text or ""))
        tag = None if contest else barrier_for(text)
        pol = None if not tag else ("barrier" if sent in ("negative", "neutral", "mixed") else "mitigated")
        conn.execute("update fb_comments set is_contest_or_spam=?, barrier_tag=?, barrier_polarity=? where id=?",
                     (int(contest), tag, pol, cid))
    conn.commit()
    return conn


if __name__ == "__main__":
    r = retag_retailers()
    print("retailer reviews: contact-lens =", r.execute("select sum(is_contact_lens) from fb_retailer_reviews").fetchone()[0],
          "| spectacle-only =", r.execute("select sum(is_spectacle_only) from fb_retailer_reviews").fetchone()[0])
    for row in r.execute("select barrier_tag,barrier_polarity,count(*) from fb_retailer_reviews where is_contact_lens=1 and barrier_tag is not null group by 1,2 order by 3 desc"): print("  ", row)
    b = retag_brand()
    print("brand comments: contest/spam =", b.execute("select sum(is_contest_or_spam) from fb_comments where brand!='Olens'").fetchone()[0],
          "of", b.execute("select count(*) from fb_comments where brand!='Olens'").fetchone()[0])
    for row in b.execute("select barrier_tag,barrier_polarity,count(*) from fb_comments where brand!='Olens' and barrier_tag is not null group by 1,2 order by 3 desc"): print("  ", row)
