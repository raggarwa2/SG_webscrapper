"""
Live findings for the Answer page's fact cards. Each finding is computed from the same loaders and rules as the detail page it
points to (app and retail: voice_data, the one tagged item table; trade: market_competitors.trade_facts; demand:
trends_signals.facts; listings: brand_protection._prepare), so a card can never disagree with its detail tab.

A finding is a dict: icon, stat, stat_label, tone, base_label, n (None = no sample), headline, detail (bullet list),
label (Market fact / Directional), base, where.
"""

import pandas as pd

import barrier_taxonomy
import barriers_friction
import brand_protection
import ebi
import market_competitors
import trends_signals
import voice_data as vd


def _s(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _app(d: pd.DataFrame) -> dict | None:
    a = vd.app(d)
    if a.empty:
        return None
    eras = vd.app_eras(a)
    last = eras.iloc[-1]
    if last["n"] < ebi.MIN_N:
        return None
    f = barriers_friction.app_facts()
    neg = a[a["sentiment"] == "negative"].copy()
    neg["labels"] = neg["text"].map(barrier_taxonomy.classify)
    cnt = neg.explode("labels")["labels"].value_counts()
    cnt = cnt[cnt.index != barrier_taxonomy.OTHER]
    detail = [f"**{store}:** {x['mean']:.2f} stars ({x['n']:,} ratings, {x['one'] / x['n'] * 100:.0f}% 1-star)" for store, x in f["stores"].items()]
    detail += [f"**{r['era']}:** {r['neg']:.0f}% of {int(r['n'])} written reviews negative" for _, r in eras.iterrows() if r["n"] >= ebi.MIN_N]
    detail += [f"**{lab}:** {int(k)} of {len(neg)} negative reviews" for lab, k in cnt.head(3).items()]
    if f["after_update"]:
        detail.append(f"**Broke after an update:** {f['after_update']} of {f['neg']} one- and two-star reviews")
    return dict(icon="phone", stat=f"{last['neg']:.0f}%", stat_label=f"of {last['era']} written app reviews are negative",
                tone="neg", base_label=f"n={int(last['n'])} reviews", n=int(last["n"]),
                headline="The app is poorly rated; complaints are sign-in, launch, points and messages", detail=detail,
                label="Directional", base=f"{len(neg)} negative of {len(a)} written reviews, read by the shared tagger", where="Barriers & journey > App")


def _retailer(d: pd.DataFrame) -> dict | None:
    a, m = vd.app(d), vd.maps(d)
    if m.empty or a.empty:
        return None
    loy_m = int(sum("Loyalty & app" in gp for gp in m["gpol"]))
    ca = vd.complaints(a)
    loy_a = int(ca.loc[ca["group"] == "Loyalty & app", "item_id"].nunique())
    word = "an app complaint, not a store complaint" if loy_a > loy_m else "felt in store as much as in the app"
    acu = int(m["text"].str.contains("acuvue", case=False, na=False).sum())
    return dict(icon="cart", stat=f"{loy_m} vs {loy_a}", stat_label="loyalty and app topics: store reviews vs app complaints",
                tone="info", base_label=f"n={len(m)} store reviews", n=len(m),
                headline=f"The retailer link is {word}",
                detail=[f"**Store reviews:** loyalty or app topics in {loy_m} of {len(m)} contact-lens reviews",
                        f"**App reviews:** {loy_a} complaint items on loyalty, points, registration or the app, of {len(a)}",
                        f"**Store reviews are about the shop:** only {acu} of {len(m)} name Acuvue"],
                label="Directional", base=f"{len(m)} store reviews; {len(a)} app reviews", where="Barriers & journey > Retail")


def _demand() -> dict | None:
    t, mf = trends_signals.facts(), market_competitors.trade_facts()
    if not t:
        return None
    opp = mf and (t["idx_chg"] > 0) != (mf["units"] > 0)
    detail = [f"**Acuvue search interest:** {ebi.pct(t['idx_chg'])} vs {t['prev']} ({t['window']})",
              f"**Share of category searches:** {t['share_prev']:.0f}% to {t['share_now']:.0f}%"]
    if t["cat_chg"] is not None:
        detail.append(f"**Category search interest:** {ebi.pct(t['cat_chg'])}")
    if mf:
        detail.append(f"**Lens imports (units):** {ebi.pct(mf['units'])}, {mf['first']} to {mf['last']}; Singapore also re-exports")
    return dict(icon="trend-up" if t["idx_chg"] >= 0 else "trend-down", stat=f"{ebi.pct(t['idx_chg'])}",
                stat_label=f"Acuvue search interest vs {t['prev']}", tone="info", base_label="Google Trends index", n=None,
                headline="Search interest and imports point opposite ways" if opp else "Search interest is moving with imports",
                detail=detail, label="Directional", base=f"Google Trends index, {t['weeks']} weekly points; UN Comtrade annual",
                where="Brand & market > Demand")


def _trade() -> dict | None:
    t = market_competitors.trade_facts()
    if not t:
        return None
    u, v, p = t["units"], t["value"], t["price"]
    word = "fell" if u < 0 else "rose"
    drift = "shrinking" if u < -5 else "growing" if u > 5 else "flat"
    detail = [f"**Units:** imports of HS 9001.30 {ebi.pct(u)}, {t['first']} to {t['last']}",
              f"**Value:** {ebi.pct(v)}, unit price {ebi.pct(p)}: " + ("the move is in volume, not price" if abs(p) < abs(u) / 2 else "price moved too"),
              "**Caveat:** imports are a proxy for demand (Singapore also re-exports); trade data is the only source, SingStat has nothing at this product level"]
    return dict(icon="trend-down" if u < 0 else "trend-up", stat=f"{ebi.pct(u)}", stat_label=f"lens imports in units, {t['first']} to {t['last']}",
                tone="neg" if u < -5 else "info", base_label="UN Comtrade", n=None,
                headline=f"Lens imports {word} about {abs(u):.0f}% in {t['first']}-{str(t['last'])[-2:]}: the category is likely {drift}", detail=detail,
                label="Market fact", base=f"UN Comtrade, {t['n_years']} years", where="Market & Channel > Competitors & category")


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


def build(d: pd.DataFrame, products_all: pd.DataFrame) -> list:
    """The fact cards in display order. A live finding that cannot be computed is skipped, not shown stale."""
    found = [_app(d), _retailer(d), _demand(), _trade(), _listings(products_all)]
    return [f for f in found if f]
