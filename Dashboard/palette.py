"""The one colour home for every chart. A colour means one thing on every page; no module writes its own hex code.

Blocks: brand, sentiment, lens (source type), theme, neutral greys, heatmap scales. Import from here (sg_common re-exports the
brand and sentiment names so older imports keep working)."""

# Brand: Acuvue teal is Acuvue's identity wherever brands are drawn. Where a chart highlights Acuvue, peers use PEER_GREY.
BRAND_COLORS = {
    "Acuvue": "#178197",
    "Alcon": "#0A7CC1",
    "Bausch & Lomb": "#A51890",
    "CooperVision": "#051F4A",
    "Olens": "#59A5D7",
}
FOCAL_COLOR = BRAND_COLORS["Acuvue"]
PEER_GREY = "#9AA5B1"

# Sentiment: green positive, red negative, grey neutral, light blue mixed (the pair used before the palette existed).
SENTIMENT_COLORS = {"positive": "#168012", "neutral": "#9AA5B1", "mixed": "#59A5D7", "negative": "#DD1C14"}
POS_COLOR, NEG_COLOR = SENTIMENT_COLORS["positive"], SENTIMENT_COLORS["negative"]
POS_LIGHT, NEG_LIGHT = "#A9D4A5", "#F2B5B1"
POS_BG, NEG_BG = "#E4F5E9", "#FDE8E6"      # pale chip backgrounds in the page chrome      # a side with under 10 mentions: the lighter shade of the same colour

# Lens (source type). The app takes the MyACUVUE app icon blue (sampled from the App Store listing).
LENS_COLORS = {
    "Consumer voice": FOCAL_COLOR,
    "Consumer, brand-named": FOCAL_COLOR,
    "Category voice": "#8CC4CF",
    "Consumer, no brand": "#8CC4CF",
    "MyACUVUE app": "#034B91",
    "App": "#034B91",
    "Retail reviews": "#C98B2B",
    "Retail experience": "#C98B2B",
    "Owned experience": "#034B91",
    "Brand broadcast": "#4F6D7A",
}
APP_COLOR = LENS_COLORS["MyACUVUE app"]

# Theme (the eight tagging themes, keyed by name so a theme keeps its colour on every chart). Loyalty & app is the app's finding,
# so it carries the app colour.
THEME_COLORS = {
    "Comfort & product": "#7C5CBF",
    "Price & value": "#2B6CB0",
    "Look & colour": "#B83280",
    "Trust & authenticity": "#C05621",
    "Access & availability": "#64748B",
    "Fitting & guidance": "#D69E2E",
    "Loyalty & app": APP_COLOR,
    "Service": "#B08968",
}
OTHER_THEME = "#B8C0CC"

# Neutrals
LOW_GREY = "#CBD5E1"        # a bar or cell under the display minimum
GRID = "#EEF2F6"
TEXT = "#191919"
WHITE = "#FFFFFF"        # label text on a dark bar
TEXT_MUTED = "#64748B"      # captions, axis notes, "directional only"
RULE = "#94A3B8"            # zero lines, dotted thresholds, borders
BAND = "#E2E8F0"            # row highlight bands

# Heatmap scales: one diverging (net sentiment) and one sequential (counts).
NET_SCALE = [[0, NEG_COLOR], [0.5, "#F1F5F9"], [1, POS_COLOR]]
SEQ_LO, SEQ_MID, SEQ_HI = "#F1F5F9", "#B8D8DE", "#5FB0C0"
SEQ_SCALE = [[0, SEQ_LO], [1, SEQ_HI]]

# More neutrals and accents
AMBER = "#B7791F"          # warning text, "directional only", promo, unverified
INK = "#051F4A"            # dark navy text and rings

# Channel (source), keyed by name so a channel keeps its colour on every chart. Mid tones: white labels read on them.
CHANNEL_COLORS = {
    "Xiaohongshu": "#D6567F", "Xiaohongshu comments": "#E58FAB", "YouTube": "#5B7B9A", "TikTok": "#0F172A",
    "Instagram": "#8E6BD8", "Facebook": "#3F6FBF", "Reddit": "#C26B1A", "KiasuParents": "#A98467",
    "Lazada reviews": "#C2855A", "MyACUVUE app": APP_COLOR, "Google Maps": LENS_COLORS["Retail reviews"],
    "Facebook retailer reviews": LENS_COLORS["Retail reviews"],
}

# Content type of a post or comment
CONTENT_COLORS = {"promo": AMBER, "education_news": SENTIMENT_COLORS["mixed"], "giveaway_spam": PEER_GREY, "experience": POS_COLOR,
                  "opinion": "#0B3556", "question": "#7C5CBF", "other": LOW_GREY}

# Generic ordered series (segments, sub-brands): assigned by a fixed key order, never by the order a chart happens to draw them.
SERIES = ["#178197", "#B7791F", "#7C5CBF", "#2B6CB0", "#C05621", "#B83280", "#64748B", "#5FB0C0"]
SUBBRAND = list(BRAND_COLORS.values()) + [TEXT_MUTED]

THEME_INK = "#0B3556"        # dark navy label text on the pale desk-research box
