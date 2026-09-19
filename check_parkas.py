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

def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ---- Site generation -------------------------------------------------------

def render_site(feed):
    entries_html = []
    if not feed:
        entries_html.append("<p class='empty'>No new parkas spotted yet — check back soon.</p>")
    for entry in feed:
        items_html = "\n".join(
            f"""<li>
                <a href="{item['url']}" target="_blank" rel="noopener">{item['name']}</a>
                <span class="price">{item['price']}</span>
            </li>"""
            for item in entry["items"]
        )
        entries_html.append(f"""
        <section class="entry">
            <h2>{entry['timestamp']}</h2>
            <ul>{items_html}</ul>
        </section>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinalCut Parka Watch</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 700px;
         margin: 40px auto; padding: 0 16px; color: #222; background: #fafafa; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0; }}
  .subtitle {{ color: #666; margin-top: 4px; margin-bottom: 32px; }}
  .entry {{ background: #fff; border: 1px solid #e5e5e5; border-radius: 8px;
            padding: 16px 20px; margin-bottom: 20px; }}
  .entry h2 {{ font-size: 0.9rem; color: #888; margin: 0 0 10px; font-weight: 600; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{ display: flex; justify-content: space-between; padding: 8px 0;
        border-top: 1px solid #f0f0f0; }}
  li:first-child {{ border-top: none; }}
  a {{ color: #1a1a1a; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .price {{ color: #555; font-variant-numeric: tabular-nums; }}
  .empty {{ color: #888; }}
</style>
</head>
<body>
  <h1>🧥 FinalCut Parka Watch</h1>
  <p class="subtitle">New parkas on shopfinalcut.com, newest first.</p>
  {"".join(entries_html)}
</body>
</html>
"""


# ---- Main -----------------------------------------------------------------

def main():
    current = fetch_parkas()
    seen = load_json(STATE_FILE, {})

    new_urls = set(current) - set(seen)

    if new_urls:
        feed = load_json(FEED_FILE, [])
        new_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "items": [
                {"url": url, "name": current[url]["name"], "price": current[url]["price"]}
                for url in new_urls
            ],
        }
        feed.insert(0, new_entry)  # newest first
        save_json(FEED_FILE, feed)

        SITE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SITE_FILE.write_text(render_site(feed))
        print(f"Found {len(new_urls)} new parka(s) — site updated.")
    else:
        print("No new parkas since last check.")
        # Still make sure the site exists on first-ever run even with 0 new items
        if not SITE_FILE.exists():
            feed = load_json(FEED_FILE, [])
            save_json(FEED_FILE, feed)
            SITE_FILE.parent.mkdir(parents=True, exist_ok=True)
            SITE_FILE.write_text(render_site(feed))

    save_json(STATE_FILE, current)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        sys.exit(1)