"""
Acne-Aid Thailand — Pricing Scraper (Boots.co.th + Watsons.co.th)
==================================================================
Standalone script. Does NOT touch the HK lens project's pipeline_v2.py,
config.yaml, or lensdata.db. New project = new folder = new files, per
the same discipline used on the lens pipeline.

STATUS: validated against real fetched HTML on 2026-07-14. Not yet run
at full volume — test on 1-2 brands first before running the full list.

Confirmed facts this script relies on:
- Boots.co.th (store.boots.co.th) is server-rendered (Vue/Nuxt SSR).
  A plain `requests` call with a normal User-Agent returned HTTP 200
  with full product data. No bot-blocking observed.
- Watsons.co.th BLOCKED a plain curl/requests-style call (HTTP 403),
  even though Anthropic's own fetch tool got through. This means the
  Watsons portion of this script may also get 403'd when you run it
  from your own machine — see the WATSONS TROUBLESHOOTING note below.
  Test Watsons on a single brand first before trusting the full run.
- Watsons' brand "hub" pages (/all-brands/b/{code}/{slug}) are just
  marketing banners with NO product data. The real product grid is at
  /all-brands/list/{code}/{slug} — this script uses the `list` URL.
- Neither site needs Playwright/JS rendering for pricing — both return
  full price data in the raw server-rendered HTML.

Open item: CeraVe's brand code on Watsons.co.th was not found in this
session (Cetaphil, La Roche-Posay, Eucerin, Neutrogena, Smooth E, and
Acne-Aid all confirmed). CeraVe may simply not be sold at Watsons TH —
worth a quick manual check before assuming the script is broken.
"""

import csv
import re
import time
import random
from dataclasses import dataclass, asdict
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIG — edit this as the client's brand/SKU list comes in
# ---------------------------------------------------------------------------

# Boots.co.th: generic keyword search works for ANY brand name, no brand ID
# needed. Confirmed URL: https://store.boots.co.th/products/search?keyword=X
BOOTS_BRANDS = [
    "Acne-Aid",
    "CeraVe",
    "Cetaphil",
    "Neutrogena",
    "La Roche-Posay",
    "Eucerin",
    "Smooth E",
]

# Watsons.co.th: needs the numeric brand code + slug (no universal keyword
# search endpoint found). Confirmed codes below; CeraVe intentionally
# omitted — not found, needs manual confirmation.
WATSONS_BRANDS = [
    {"name": "Acne-Aid", "code": "152199", "slug": "acne-aid"},
    {"name": "Cetaphil", "code": "154204", "slug": "cetaphil"},
    {"name": "La Roche-Posay", "code": "163085", "slug": "laroche-posay"},
    {"name": "Eucerin", "code": "156033", "slug": "eucerin"},
    {"name": "Neutrogena", "code": "165067", "slug": "neutrogena"},
    {"name": "Smooth E", "code": "170110", "slug": "smooth-e"},
    # {"name": "CeraVe", "code": "???", "slug": "cerave"},  # NOT CONFIRMED
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY_RANGE = (1.5, 3.0)  # polite delay between requests, seconds


@dataclass
class ProductRow:
    site: str
    brand_search_term: str
    product_name: str
    sell_price: Optional[float]
    normal_price: Optional[float]
    review_count: Optional[int]
    product_url: Optional[str]
    source_page: str


def _parse_price(text: str) -> Optional[float]:
    """Turn '1,259 THB' / '฿488.00' / '540 THB' into a float."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d.]", "", text)
    return float(cleaned) if cleaned else None


# ---------------------------------------------------------------------------
# BOOTS.CO.TH
# ---------------------------------------------------------------------------

def scrape_boots_brand(brand: str, max_pages: int = 10) -> list[ProductRow]:
    """
    Confirmed structure (from live fetch, 2026-07-14):
      div.product-cell
        div.product-description  -> product name
        div.sell-price            -> current price (e.g. "510\n THB")
        div.normal-price          -> original price, ONLY present if discounted
    Pagination: ?page=2, ?page=3, ... Stop when a page returns 0 product cells.
    """
    rows: list[ProductRow] = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, max_pages + 1):
        url = "https://store.boots.co.th/products/search"
        params = {"keyword": brand}
        if page > 1:
            params["page"] = page

        resp = session.get(url, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"  [Boots] {brand} page {page}: HTTP {resp.status_code}, stopping")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        cells = soup.select("div.product-cell")
        if not cells:
            break  # no more pages

        for cell in cells:
            name_el = cell.select_one(".product-description")
            sell_el = cell.select_one(".sell-price")
            normal_el = cell.select_one(".normal-price")

            rows.append(ProductRow(
                site="Boots.co.th",
                brand_search_term=brand,
                product_name=name_el.get_text(strip=True) if name_el else None,
                sell_price=_parse_price(sell_el.get_text()) if sell_el else None,
                normal_price=_parse_price(normal_el.get_text()) if normal_el else None,
                review_count=None,  # not shown on Boots listing pages
                product_url=None,   # listing uses JS click-through, no <a href> found
                source_page=resp.url,
            ))

        print(f"  [Boots] {brand} page {page}: {len(cells)} products")
        time.sleep(random.uniform(*REQUEST_DELAY_RANGE))

    return rows


# ---------------------------------------------------------------------------
# WATSONS.CO.TH
# ---------------------------------------------------------------------------

def scrape_watsons_brand(brand_name: str, code: str, slug: str) -> list[ProductRow]:
    """
    Confirmed structure (from live fetch, 2026-07-14):
      Each product is an <a href="/en/{product-slug}/p/{SKU_ID}">
      followed by an <h2> with the product name, a price (e.g. "฿188.00"),
      an optional strikethrough original price, and a review count in
      parentheses e.g. "(410)".

    IMPORTANT: plain requests/curl got HTTP 403 from Watsons in testing,
    even with browser-like headers. If you hit 403 here too, this site
    needs stronger anti-bot handling (see WATSONS TROUBLESHOOTING below)
    rather than more retries on this same approach.
    """
    url = f"https://www.watsons.co.th/en/all-brands/list/{code}/{slug}"
    session = requests.Session()
    session.headers.update(HEADERS)

    resp = session.get(url, timeout=20)
    if resp.status_code != 200:
        print(f"  [Watsons] {brand_name}: HTTP {resp.status_code} — see troubleshooting notes")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    rows: list[ProductRow] = []

    # Product links follow the pattern /en/.../p/BP_123456
    product_links = soup.select('a[href*="/p/"]')
    seen_urls = set()

    for link in product_links:
        href = link.get("href", "")
        if href in seen_urls or "/p/" not in href:
            continue
        seen_urls.add(href)

        # The product name is usually in a nearby <h2>; price/review count
        # sit in sibling elements within the same product card container.
        card = link.find_parent(["li", "div"])
        if card is None:
            continue

        name_el = card.select_one("h2")
        text_blob = card.get_text(" ", strip=True)

        price_match = re.search(r"฿\s?([\d,]+\.\d{2})", text_blob)
        strike_match = re.findall(r"฿\s?([\d,]+\.\d{2})", text_blob)
        review_match = re.search(r"\((\d[\d,]*)\)", text_blob)

        sell_price = _parse_price(price_match.group(1)) if price_match else None
        normal_price = (
            _parse_price(strike_match[1]) if len(strike_match) > 1 else None
        )
        review_count = (
            int(review_match.group(1).replace(",", "")) if review_match else None
        )

        rows.append(ProductRow(
            site="Watsons.co.th",
            brand_search_term=brand_name,
            product_name=name_el.get_text(strip=True) if name_el else None,
            sell_price=sell_price,
            normal_price=normal_price,
            review_count=review_count,
            product_url="https://www.watsons.co.th" + href if href.startswith("/") else href,
            source_page=resp.url,
        ))

    print(f"  [Watsons] {brand_name}: {len(rows)} products")
    return rows


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    all_rows: list[ProductRow] = []

    print("=== Boots.co.th ===")
    for brand in BOOTS_BRANDS:
        all_rows.extend(scrape_boots_brand(brand))
        time.sleep(random.uniform(*REQUEST_DELAY_RANGE))

    print("\n=== Watsons.co.th ===")
    for b in WATSONS_BRANDS:
        all_rows.extend(scrape_watsons_brand(b["name"], b["code"], b["slug"]))
        time.sleep(random.uniform(*REQUEST_DELAY_RANGE))

    out_path = "acneaid_th_pricing.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(ProductRow.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in all_rows:
            writer.writerow(asdict(row))

    print(f"\nDone. {len(all_rows)} rows written to {out_path}")


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# WATSONS TROUBLESHOOTING — TESTED 2026-07-14, CONFIRMED RESULT
# ---------------------------------------------------------------------------
# Tested and CONFIRMED NOT TO WORK:
#   - Plain `requests` with full browser headers -> HTTP 403
#   - `cloudscraper` (handles standard Cloudflare JS challenges) -> HTTP 403
#   - Visiting the homepage first to pick up session cookies -> HTTP 403
#     on the homepage itself, before even reaching a brand page.
# This blocks at the connection/fingerprint level, not the header level —
# consistent with the Akamai Bot Manager already noted against Watsons HK
# in the lens project. No amount of header/cookie tuning in plain Python
# will get past this.
#
# CONFIRMED NEXT STEP: use Playwright (real browser engine), same pattern
# as the lens project's Lazada TH discovery module. Watsons' own rendered
# page is plain HTML once past the bot-check — no AJAX/scroll handling
# needed once inside, just a real browser context to get past the wall.
# A quick Claude-in-Chrome pull (like the Shopee TH test) is a viable
# stopgap for the current one-time SKU list while a proper Playwright
# module gets built.
#
# Do NOT keep trying plain-Python variations on this — it's a wall, not
# a header-tuning problem.
