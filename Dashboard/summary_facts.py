"""
Live findings for the Summary cards. Each finding is computed from the same loaders and rules as the detail page it points to
(app: barriers_friction.app_facts; barriers: the journey frame; retailers: gmaps_signals; trade: market_competitors.trade_facts;
voice and reach: market_competitors.reach_facts; listings: brand_protection._prepare), so a card can never disagree with its
detail tab. Two findings stay as dated text because no code reproduces them: the brand-posts-mention-the-app count and the
Stage 2 limitation.

A finding is a dict: icon, stat, stat_label, tone, base_label, n (None = no sample), headline, detail (bullet list),
label (Market fact / Directional / Needs internal data), base, where.
"""

import pandas as pd

import barriers_friction
import brand_protection
import ebi
import gmaps_signals
import insights
import market_competitors


def _s(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _app(jf_all: pd.DataFrame) -> dict | None:
    f = barriers_friction.app_facts()
    if not f["neg"]:
        return None
    share = f["on_path"] / f["neg"] * 100
    detail = [f"**{store}:** {d['mean']:.2f} stars ({d['n']:,} ratings, {d['one'] / d['n'] * 100:.0f}% 1-star)" for store, d in f["stores"].items()]
    detail += [f"**Sign-up or launch:** {f['on_path']} of {f['neg']} written 1-2 star reviews, {share:.0f}% (OTP not arriving, date-of-birth entry, freezes, forced-update loop)",
               f"**Broke after an update:** {f['after_update']} of {f['neg']}"]
    return dict(icon="phone", stat=f"{share:.0f}%", stat_label=f"of {f['neg']} low-rated app reviews cite sign-up or launch",
                tone="neg", base_label=f"n={f['neg']} app reviews", n=f["neg"],
                headline="The app is poorly rated; most complaints are sign-up and launch", detail=detail,
                label="Directional", base=f"{f['neg']} written 1-2 star reviews of {f['written']} written", where="Journey & barriers > full app detail")


def _barriers(jf_all: pd.DataFrame) -> dict | None:
    if jf_all is None or jf_all.empty:
        return None
    b = jf_all[jf_all["is_barrier"] == 1].drop_duplicates(["source", "brand", "text"])
    if b.empty:
        return None
    by = b["source"].value_counts()
    enough = [s for s, n in by.items() if n >= ebi.MIN_N]
    detail = [f"**{len(b):,}** barrier-flagged comments in total, including the app reviews",
              " | ".join(f"**{s}** {int(n)}" for s, n in by.items())]
    ig = int(by.get("Instagram", 0))
    if ig:
        detail.append(f"Note from 7 Oct, not recounted live: about 20 of the {ig} Instagram flags are replies to one 2021 Alcon eye-drop giveaway, "
                      "where people list symptoms, not purchase barriers. Without that post Instagram is under the floor")
    detail.append("Use as barrier types to test in Stage 2, not as how many customers hit each")
    return dict(icon="ban", stat=f"{len(b):,}", stat_label=f"barrier comments; only {_s(len(enough), 'source')} reach n={ebi.MIN_N}",
                tone="warn", base_label=f"n={len(b):,} comments", n=len(b),
                headline=f"Barrier comments are spread across sources; only {len(enough)} have enough volume", detail=detail,
                label="Directional", base=f"{len(b):,} comments; {_s(len(enough), 'source')} reach the {ebi.MIN_N} floor", where="Journey & barriers")


def _retailer(app: dict) -> dict | None:
    gm, _ = gmaps_signals.load_gmaps()
    if gm.empty:
        return None
    fr = gm[gm["is_friction"] == 1]
    lp = int(fr["theme_list"].map(lambda x: "loyalty_points" in x).sum())
    k = barriers_friction.app_facts()
    if not k["neg"]:
        return None
    detail = [f"**Google Maps:** loyalty or points in {lp} of {len(fr)} friction reviews",
              f"**App reviews:** points and retailer lock-in in {k['points_or_lock']} of {k['neg']} low-rated reviews",
              "**Store complaints** are mostly about staff and fitting, waits, upsell and stock"]
    word = "an app complaint, not a store complaint" if k["points_or_lock"] > lp else "felt in store as much as in the app"
    return dict(icon="cart", stat=f"{lp} vs {k['points_or_lock']}", stat_label="loyalty mentions: Maps friction reviews vs app reviews",
                tone="info", base_label=f"n={len(fr)} Maps reviews", n=len(fr),
                headline=f"The retailer link is {word}", detail=detail,
                label="Directional", base=f"{len(fr)} Maps friction reviews; {k['neg']} low-rated app reviews", where="Market & Channel > Retailers")


def _trade() -> dict | None:
    t = market_competitors.trade_facts()
    if not t:
        return None
    u, v, p = t["units"], t["value"], t["price"]
    word = "fell" if u < 0 else "rose"
    drift = "shrinking" if u < -5 else "growing" if u > 5 else "flat"
    detail = [f"**Units:** imports of HS 9001.30 {u:+.0f}%, {t['first']} to {t['last']}",
              f"**Value:** {v:+.0f}%, unit price {p:+.0f}%: " + ("the move is in volume, not price" if abs(p) < abs(u) / 2 else "price moved too"),
              "**Caveat:** imports are a proxy for demand (Singapore also re-exports); trade data is the only source, SingStat has nothing at this product level"]
    return dict(icon="trend-down" if u < 0 else "trend-up", stat=f"{u:+.0f}%", stat_label=f"lens imports in units, {t['first']} to {t['last']}",
                tone="neg" if u < -5 else "info", base_label="UN Comtrade", n=None,
                headline=f"Lens imports {word} about {abs(u):.0f}% in {t['first']}-{str(t['last'])[-2:]}: the category is likely {drift}", detail=detail,
                label="Market fact", base=f"UN Comtrade, {t['n_years']} years", where="Market & Channel > Competitors & category")


def _voice(frames: dict, brands: list) -> dict | None:
    r = market_competitors.reach_facts(frames, brands)
    items = r["items"][r["items"] > 0].sort_values(ascending=False)
    if items.empty:
        return None
    n_all = int(items.sum())
    top = items.index[0]
    tied = [b for b in items.index if items[b] >= 0.97 * items.iloc[0]]
    share = items.iloc[0] / n_all * 100
    stat = f"{share:.0f}% each" if len(tied) > 1 else f"{share:.0f}%"
    names = " and ".join(tied) if len(tied) > 1 else top
    detail = [f"**Items per brand:** " + ", ".join(f"{b} {int(n):,}" for b, n in items.items()) + f" (of {n_all:,}, the Brand Health pool)"]
    if r["leaders"]:
        detail.append("**Leader by measure:** " + "; ".join(f"{b} on {m.lower()}" for m, b in r["leaders"].items()))
    if r["conc"]:
        detail.append("**Read with care:** " + "; ".join(r["conc"]))
    return dict(icon="megaphone", stat=stat, stat_label=f"share of voice, {names}" + ("; one item often drives reach" if r["conc"] else ""),
                tone="info", base_label=f"n={n_all:,} items", n=n_all,
                headline="Who is loudest depends on the measure, and one item often drives it" if len(set(r["leaders"].values())) > 1
                else f"{top} leads on every measure with enough posts",
                detail=detail, label="Directional", base="Varies by platform", where="Conversation & content")


def _listings(products_all: pd.DataFrame) -> dict | None:
    if products_all is None or products_all.empty:
        return None
    _, d = brand_protection._prepare(products_all)
    fl = d[d["compliance_flag"] == 1]
    if fl.empty:
        return None
    acu = int((fl["brand"] == "Acuvue").sum())
    return dict(icon="shield", stat=f"{len(fl):,}", stat_label=f"lens listings offered online, {acu} of them ACUVUE",
                tone="neg", base_label=f"n={len(fl):,} listings", n=len(fl),
                headline="Lenses are offered for direct online sale, illegal under the HSA",
                detail=[f"**{len(fl):,}** distinct lens listings flagged, **{acu}** of them ACUVUE ({acu / len(fl) * 100:.0f}%)"
                        + (": mostly a category-wide problem, not only ours" if acu / len(fl) < 0.5 else ""),
                        "Shows an offer, not a completed sale or genuine stock",
                        "Lens solution (for example RevitaLens) is outside the rule and is compared on price separately"],
                label="Market fact", base=f"{len(fl):,} listings", where="Market & Channel > Brand protection")


# Not reproducible from code (see the plan note of 7 Oct), so these stay as dated text.
_FB_APP = dict(icon="message", stat="3%", stat_label="of Facebook brand posts mention the app (4 of 120)", tone="warn",
               base_label="n=4 posts", n=4, headline="Few brand posts mention the app, so pushing it cannot be tested yet",
               detail=["**Facebook:** 4 of 120 brand posts (3%) mention the app, registering or points",
                       "**Instagram:** 31 of 158 collected posts (20%)",
                       "Counted on 2 Oct and not repeated: the collection has since grown, and no code records how the count was made"],
               label="Directional", base="278 collected posts at 2 Oct (Facebook 120 + Instagram 158)", where="Conversation & content")
_LIMIT = dict(icon="lock", stat="Not testable", stat_label="7% to 14% target needs internal data", tone="info", base_label="no data", n=None,
              headline="EBI cannot say if we are on track for 7% to 14%",
              detail=["No registration, CRM or conversion data in the scraped sources",
                      "The Stage 2 bridge lists the internal data and survey that would test each hypothesis"],
              label="Needs internal data", base="n/a", where="Evidence & Stage 2")


def build(jf_all: pd.DataFrame, products_all: pd.DataFrame, frames: dict, brands: list) -> list:
    """The Summary findings in display order. A live finding that cannot be computed is skipped, not shown stale."""
    app = _app(jf_all)
    found = [app, _barriers(jf_all), _retailer(app), _trade(), _voice(frames, brands), _listings(products_all), _FB_APP, _LIMIT]
    return [f for f in found if f]
