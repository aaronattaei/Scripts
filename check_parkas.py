#!/usr/bin/env python3
"""
Checks shopfinalcut.com's Coats & Jackets category for parkas and, when new
ones appear, adds a timestamped entry to a JSON feed and regenerates a
static HTML page (docs/index.html) that GitHub Pages can host.

How it works:
1. Fetches the Coats & Jackets page (sorted by Newest Arrivals).
2. Extracts product name/price/link for every item whose title contains
   "Parka" (case-insensitive) — tweak PARKA_KEYWORDS below if needed.
3. Compares against seen_products.json (created on first run).
4. If there are new items, prepends a {timestamp, items} entry to
   docs/feed.json (newest entry first).
5. Regenerates docs/index.html from the full feed, newest at the top.
6. Updates seen_products.json.

Run this on a schedule (cron, GitHub Actions, etc.) — see README.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---- Config -----------------------------------------------------------------

CATEGORY_URL = "https://www.shopfinalcut.com/en/shop/coats-jackets?sort=newest"
PARKA_KEYWORDS = ["parka"]  # add more terms here if needed, e.g. "anorak"

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "seen_products.json"      # what we've seen before (not public)
DOCS_DIR = ROOT / "docs"                       # served by GitHub Pages
FEED_FILE = DOCS_DIR / "feed.json"             # time-series log of new-item events
SITE_FILE = DOCS_DIR / "index.html"            # generated page

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36"
}


# ---- Scraping -----------------------------------------------------------------

def fetch_parkas():
    """Return a dict of {product_url: {name, price}} for current parkas."""
    resp = requests.get(CATEGORY_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    products = {}
    for link in soup.select('a[href*="/en/product/"]'):
        href = link.get("href", "")
        text = link.get_text(" ", strip=True)
        if not text:
            continue
        if not any(kw.lower() in text.lower() for kw in PARKA_KEYWORDS):
            continue

        full_url = href if href.startswith("http") else f"https://www.shopfinalcut.com{href}"
        price_match = re.search(r"\$[\d,]+\.\d{2}", text)
        price = price_match.group(0) if price_match else "?"
        name = re.split(r"\$", text)[0].strip()

        products[full_url] = {"name": name, "price": price}

    return products


# ---- State handling -------------------------------------------------------

def load_json(path,