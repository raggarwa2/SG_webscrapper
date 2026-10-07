# ============================================================
# Reference framework for the Singapore triangulation
# ============================================================
# Adapted from the HK framework (triangulation_hk/mappings.py).
# - BARRIERS and ATTRIBUTE_QUADRANT are carried over unchanged: they are
#   consumer-psychology lists, not HK-specific. If an SG research agency
#   supplies its own slides, replace the wording here.
# - CHANNEL_TAXONOMY is a DRAFT SG taxonomy (no agency slide exists for SG yet).
#   Validate with the team. run_triangulation.py just reads these lists.

# --- SG purchase-channel taxonomy (Prompt A) ------------------------------
# "online": True  -> a scraper could plausibly reach this channel
# "online": False -> physical/walk-in retail, out of scope for gap-closing
# "sites":  products.site values that count as coverage for the whole category
# "gmaps_chains": chains whose Google Maps reviews are scraped (gmaps_data_sg.db)
# "app_reviews": counts the MyACUVUE app-store reviews (app_data_sg.db)
# "examples": store_name keywords (word-boundary, case-insensitive) that count as coverage
CHANNEL_TAXONOMY = [
    # Per context.md: powered lenses cannot be sold online in SG (HSA), so Lazada/Shopee/
    # TikTok Shop only legitimately carry solutions and cosmetic lenses. Powered-lens
    # listings there are a grey-market/compliance signal, not a legitimate channel.
    {"category": "Lazada (LazMall + marketplace)", "online": True,
     "sites": ["lazada_sg"], "examples": []},
    {"category": "Shopee", "online": True,
     "sites": ["shopee_sg"], "examples": []},
    {"category": "TikTok Shop", "online": True,
     "sites": ["tiktok_shop"], "examples": []},
    {"category": "MyACUVUE app / brand-direct", "online": True,
     "sites": [], "examples": ["MyACUVUE", "Acuvue Official"], "app_reviews": True},
    {"category": "Pure-play CL online shops", "online": True,
     "sites": [], "examples": ["Lenskart"]},
    {"category": "Drugstore / pharmacy chains (incl. Watsons Optical)", "online": True,
     "sites": [], "examples": ["Watsons", "Guardian", "Unity"]},
    {"category": "Optical chains", "online": False,
     "sites": [], "examples": ["Owndays", "Better Vision", "Optical 88", "Zoff"],
     "gmaps_chains": ["Owndays", "Better Vision", "Optical 88", "Zoff"]},
    {"category": "Independent / local optical stores", "online": False,
     "sites": [], "examples": [], "gmaps_chains": ["Capitol Optical", "Nanyang Optical", "Visio Optical"]},
    {"category": "Optometrist / ECP clinics", "online": False,
     "sites": [], "examples": []},
    {"category": "Supermarket / department store", "online": False,
     "sites": [], "examples": ["Donki", "NTUC", "FairPrice", "Isetan"]},
    {"category": "Concept-shop / K-beauty colour-lens platforms", "online": True,
     "sites": [], "examples": ["Olens", "Pinkicon"]},
    {"category": "Social shops (FB/IG/Carousell)", "online": True,
     "sites": [], "examples": ["Carousell"]},
]

# --- Barriers to choosing / registering with / staying with a brand (Prompt B) ---
# 10 consolidated SG barriers (was 27 granular ones): fewer, broader buckets give enough
# mentions per barrier to read a pattern. Each phrase keeps its sub-issues in brackets so
# the classifier still recognises them. Sources: analysis/4_persona_barrier_framework.md,
# MyACUVUE app-store reviews, and the competitive-positioning / loyalty research.
BARRIERS = [
    "price and channel cost (seen as expensive; cheaper elsewhere: online, Johor Bahru, cosmetic lenses, marketplace coupons)",
    "loyalty rules limit value (points tied to one store; purchases elsewhere earn nothing; competitor or retailer vouchers/e-stamps more attractive)",
    "rewards unreliable or reduced (points reset or frozen; voucher not delivered; reward catalogue cut)",
    "registration or login friction (OTP, login or forced app update failure; mobile number, ID or residency requirements)",
    "app low utility (seen as points tracker; no reorder or lens-change reminder)",
    "unwanted messaging or privacy concern (promo SMS/WhatsApp, cannot unsubscribe, reluctant to share mobile number)",
    "prefers WhatsApp/seller chat or lacks support (orders via seller on WhatsApp; no chat or customer help when something fails)",
    "product experience (discomfort or dryness; vision quality issue such as astigmatism or presbyopia; previous bad experience)",
    "fear or handling difficulty (fear of infection, touching the eye, inserting or removing lenses)",
    "lack of professional guidance (no ECP prompt or recommendation; thin fitting or teaching; teaching tied to bulk purchase; no trial lens; unclear myopia-management information)",
]

# --- Stated vs Derived Importance attribute quadrant (Prompt C) -----------
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

# --- Brand normalisation --------------------------------------------------
# SG tables spell brands differently (products/reviews: "Acuvue", "Bausch & Lomb";
# social scrapers: "MyACUVUE", "Bausch + Lomb", forum: "ACUVUE"). Keys are lowercase.
BRAND_ALIASES = {
    "acuvue": "Acuvue",
    "myacuvue": "Acuvue",
    "alcon": "Alcon",
    "bausch & lomb": "Bausch & Lomb",
    "bausch + lomb": "Bausch & Lomb",
    "bausch and lomb": "Bausch & Lomb",
    "coopervision": "CooperVision",
    "olens": "Olens",
}

# Brands that get a Prompt D summary (the competitive set in context.md).
FOCUS_BRANDS = ["Acuvue", "Alcon", "Bausch & Lomb", "CooperVision", "Olens"]
