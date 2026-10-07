"""
The Category users and barrier framework (desk research, Research runs 1 to 4) as data: one row per claim.

It used to be charted on its own (Positioning strips, then a claim-by-source grid on Journey & barriers). It now rides as a
marker on the theme rows of the Brand Health themes view (brand_themes.py), so research and data sit on one grid.
Levels follow the rubric in analysis/4_persona_barrier_framework.md: 3 High, 2 Medium, 1 Low. Stages and set-B barrier
names are as in the framework tables; theme_tags.B_TO_THEME maps each barrier to a theme.
"""

import theme_tags

LEVEL = {1: "Low", 2: "Medium", 3: "High"}
USERS = ["Existing wearers", "New wearers", "Active considerers"]

# (category user, stage, set-B barrier, confidence level, what the research says, source IDs)
RESEARCH = [
    ("Existing wearers", "Engagement", "Registration / login friction", 2, "OTP, login and eligibility gating", "R4-C-03, C-04, C-05, C-15"),
    ("Existing wearers", "Consideration", "Price & channel cost", 2, "Compares cost across stores, online and Johor Bahru", "R4-C-06; R3-C-21"),
    ("Existing wearers", "Purchase", "Loyalty & rewards", 2, "Points earned only at the chosen store; other purchases earn nothing", "R4-C-11, C-12"),
    ("Existing wearers", "Repeat/Retention", "Product experience", 2, "Dryness and discomfort", "R1-C-24"),
    ("Existing wearers", "Repeat/Retention", "Loyalty & rewards", 2, "Store-binding and points freezing", "R4-C-13"),
    ("Existing wearers", "Repeat/Retention", "App utility & support", 1, "App seen as a points tracker", "R4-C-14"),
    ("Existing wearers", "Repeat/Retention", "Price & channel cost", 1, "Price-driven re-use of dailies", "R3-C-09, C-10"),
    ("New wearers", "Consideration", "Fear / handling difficulty", 2, "Fear of infection; lens rolling behind the eye", "R4-C-08; R1-C-06"),
    ("New wearers", "Trial", "Fear / handling difficulty", 2, "Handling and orientation difficulty after teaching", "R4-C-08"),
    ("New wearers", "Trial", "Lack of professional guidance", 1, "Thin fitting; free teaching tied to a 2-box minimum", "R4-C-09, C-10; R3-C-02"),
    ("New wearers", "Purchase", "Price & channel cost", 2, "Own-brand clear lenses about S$1 against about S$2.03 for ACUVUE 1-Day Moist", "R3-C-01, C-04"),
    ("New wearers", "Purchase", "Loyalty & rewards", 2, "Welcome rewards range from S$20 to S$60", "R2-C-13"),
    ("New wearers", "Repeat/Retention", "Product experience", 2, "First-year dropout: vision, discomfort (non-SG)", "R1-C-14"),
    ("New wearers", "Repeat/Retention", "Fear / handling difficulty", 2, "Handling is 15% to 25% of dropout reasons (non-SG)", "R1-C-14"),
    ("Active considerers", "Awareness", "Lack of professional guidance", 2, "Few are told they are candidates; information comes from providers", "R1-C-02; R4-C-07"),
    ("Active considerers", "Consideration", "Fear / handling difficulty", 2, "Fear of touching the eye; handling anxiety", "R1-C-06, C-07; R4-C-08"),
    ("Active considerers", "Consideration", "Lack of professional guidance", 2, "No ECP prompt; ECPs default to spectacles", "R1-C-09, C-10, C-11"),
    ("Active considerers", "Consideration", "Availability & where to buy", 2, "Cosmetic lenses listed widely and cheaply outside ECPs", "SC-PRD; R3-C-20"),
    ("Active considerers", "Consideration", "Price & channel cost", 2, "Myopia-control cost (parents)", "R3-C-20"),
    ("Active considerers", "Purchase", "Availability & where to buy", 1, "Cosmetic buying outside the ECP channel (S$5 to S$36 per listing)", "SC-PRD"),
]


def by_theme() -> dict:
    """{theme: {"claims": n, "level": top confidence, "stages": [stage, ...], "users": [...], "notes": [...]}} for every theme a
    research claim maps to."""
    out: dict = {}
    for user, stage, barrier, level, note, _ in RESEARCH:
        t = theme_tags.B_TO_THEME.get(barrier)
        if not t:
            continue
        d = out.setdefault(t, {"claims": 0, "level": 0, "stages": [], "users": [], "notes": []})
        d["claims"] += 1
        d["level"] = max(d["level"], level)
        for key, v in (("stages", stage), ("users", user)):
            if v not in d[key]:
                d[key].append(v)
        d["notes"].append(f"{user}, {stage} ({LEVEL[level]}): {note}")
    return out
