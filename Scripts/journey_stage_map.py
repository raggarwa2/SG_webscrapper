"""Static source -> journey_stage lookup for the SG MyACUVUE dashboard.

This is a SOURCE-LEVEL HEURISTIC, not a per-row classification. Every record
from a given source gets the same journey_stage tag. The Thailand project's
per-row LLM persona/funnel classifiers (all_channel_persona_classifier.py,
all_channel_funnel_classifier.py) that would do this properly are not present
in this repo, and their persona taxonomy (Acne Novice, DIY Experimenter, ...)
is skincare-specific and doesn't transfer to contact lenses. Until a real
per-row classifier is built for SG, this lookup — taken directly from
context.md's Data Source Mapping table — is the stand-in.

Values are "/"-joined because context.md maps several sources to more than
one stage; dashboard code splitting on "/" gets the full set for that source.
"""

JOURNEY_STAGE_BY_SOURCE = {
    "lazada": "Consideration/Purchase/Repeat",
    "tiktok_shop": "Awareness/Consideration",
    "youtube": "Awareness/Engagement/Consideration",
    "instagram": "Awareness/Engagement",
    "facebook": "Awareness/Engagement",
    "reddit": "Awareness/Consideration",
    "kiasuparents_forum": "Awareness/Consideration",
    "xhs": "Awareness/Consideration",
}

# Not a funnel stage at all -- per context.md's own Data Source Mapping table,
# grey-market powered/cosmetic lens listings are "Purchase (compliance angle,
# not persona) ... not journey-stage data per se". Any products row with
# compliance_flag=True gets this instead of its site's normal funnel tag.
COMPLIANCE_JOURNEY_STAGE = "Purchase (compliance flag - not funnel data)"


def journey_stage_for(source: str) -> str:
    """Look up the journey_stage tag for a source key. Raises KeyError on an
    unrecognized source rather than silently returning a guess."""
    return JOURNEY_STAGE_BY_SOURCE[source]
