# ============================================================
# Reference data from insight.txt (the research framework)
# ============================================================
# Edit the wording here if the reference framework changes -
# run_triangulation.py just reads these lists, no logic lives here.

# --- Slide 1: HK purchase-channel taxonomy (Prompt A) ---------------------
# "online": True  -> a scraper could plausibly reach this channel
# "online": False -> physical/walk-in retail, out of scope for gap-closing
CHANNEL_TAXONOMY = [
    {"category": "CL online shops", "online": True,
     "examples": ["HKCONS", "Contact Lens Easy", "GopopStation", "Wonder Lens", "Dailycon"]},
    {"category": "Independent optical stores", "online": False,
     "examples": []},
    {"category": "CL concept-shop platforms", "online": True,
     "examples": ["Olens", "Pinkicon", "CL Mall"]},
    {"category": "Chain optical stores", "online": False,
     "examples": ["Optical 88", "Lenscrafters"]},
    {"category": "Supermarket/department store", "online": False,
     "examples": ["Donki", "Yata", "Citysuper", "Matsukiyo"]},
    {"category": "Optometric centres", "online": False,
     "examples": []},
    {"category": "Overseas platforms", "online": True,
     "examples": ["Rakuten", "Taobao/T-Mall"]},
    {"category": "HKTVmall", "online": True,
     "examples": ["HKTVmall"]},
    {"category": "FB/IG shops", "online": True,
     "examples": []},
    {"category": "Open-concept shops", "online": False,
     "examples": ["Owndays", "Line", "Zoff"]},
]

# --- Slide 2: reasons for NOT choosing/switching to a brand (Prompt B) ----
BARRIERS = [
    "used to current brand",
    "too expensive",
    "not on promotion",
    "not fashionable/trendy",
    "too few variants",
    "longer wait time",
    "lack of familiarity",
    "bad reviews",
    "no ECP recommendation",
    "low ad visibility",
    "unattractive packaging",
    "difficult to find",
    "not available at ECP",
    "not suitable for my age",
    "no trial lens",
    "matches CL solution brand",
    "previous bad experience",
]

# --- Slide 3: Stated vs Derived Importance attribute quadrant (Prompt C) --
ATTRIBUTE_QUADRANT = {
    "Key Drivers": [
        "comfortable for eyes",
        "can wear 12+ hours",
        "clear/crisp vision",
        "trustworthy brand",
    ],
    "Basic Requirements": [
        "safe and reliable",
        "high quality",
        "eye health commitment",
    ],
    "Potential Differentiators": [
        "doctor/expert recommended",
        "friend/family recommended",
        "suitable for me",
        "easy to repurchase",
        "available in multiple places",
    ],
    "Low Importance": [
        "premium feel",
        "trendy",
        "internationally renowned",
        "social status",
    ],
}

ATTRIBUTE_TO_QUADRANT = {
    attr: quadrant
    for quadrant, attrs in ATTRIBUTE_QUADRANT.items()
    for attr in attrs
}
