#!/usr/bin/env python3
"""
Checks shopfinalcut.com's Coats & Jackets category for parkas and, when new
ones appear, adds a timestamped entry to a JSON feed and regenerates a
static HTML page (docs/index.html) that GitHub Pages can host.

Each new-item entry includes: product image, name, sale price vs. original
price, and available sizes (sizes require an extra fetch of the product
page, done only for newly-discovered items to keep requests light).

How it works:
1. Fetches the Coats & Jackets page (sorted by Newest Arrivals).
2. Extracts product name/price(s)/link for every item whose title contains
   "Parka" (case-insensitive) — tweak PARKA_KEYWORDS below if needed.
3. Compares against seen_products.json (created on first run).
4. For any brand-new items, fetches each product page once to grab the
   available sizes, then prepends a {timestamp, items} entry to
   docs/feed.json (newest entry first).
5. Regenerates docs/index.html from the full feed, newest at the top.
6. Updates seen_products.json.

Run this on a schedule (cron, GitHub Actions, etc.) — see README.
"""

import json
import re
import sys
import time
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

# Known size tokens we'll look for on a product page. Extend if FinalCut
# carries numeric or other sizing for some brands.
KNOWN_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]


# ---- Scraping: category page -------------------------------------------------

def fetch_parkas():
    """Return a dict of {product_url: {name, sale_price, original_price}}."""
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
        full_url = full_url.split("?")[0]  # drop any query string for a clean key

        prices = re.findall(r"\$[\d,]+\.\d{2}", text)
        sale_price = prices[0] if len(prices) >= 1 else "?"
        original_price = prices[1] if len(prices) >= 2 else None  # None = not discounted
        name = re.split(r"\$", text)[0].strip()

        products[full_url] = {
            "name": name,
            "sale_price": sale_price,
            "original_price": original_price,
        }

    return products


# ---- Scraping: product page (image + sizes) ----------------------------------

def style_number_from_url(url):
    """Pull the trailing style number out of a product URL slug."""
    match = re.search(r"-(\d{6,})$", url.rstrip("/"))
    return match.group(1) if match else None


def image_url_for(url):
    style = style_number_from_url(url)
    if not style:
        return None
    return f"https://i1.adis.ws/i/harryrosen/{style}?$thumbnail$"


def fetch_sizes(product_url):
    """Fetch a product page and return the list of sizes shown for it."""
    try:
        resp = requests.get(product_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # Sizes are listed between a "Size" label and the sizing-help prompt.
    section_match = re.search(r"\bSize\b(.*?)Need help with sizing", text, re.IGNORECASE)
    section = section_match.group(1) if section_match else text

    found = []
    for size in KNOWN_SIZES:
        # word-boundary match so "S" doesn't match inside "XS"/"XXL" etc.
        if re.search(rf"(?<![A-Z]){re.escape(size)}(?![A-Z])", section):
            found.append(size)

    # Keep a sensible display order regardless of match order
    order = {s: i for i, s in enumerate(KNOWN_SIZES)}
    found.sort(key=lambda s: order.get(s, 99))
    return found


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
        cards = []
        for item in entry["items"]:
            sizes = item.get("sizes") or []
            sizes_html = (
                "".join(f'<span class="size">{s}</span>' for s in sizes)
                if sizes else '<span class="size unavailable">No sizes found</span>'
            )

            if item.get("original_price"):
                price_html = (
                    f'<span class="sale-price">{item["sale_price"]}</span>'
                    f'<span class="orig-price">{item["original_price"]}</span>'
                )
            else:
                price_html = f'<span class="sale-price">{item["sale_price"]}</span>'

            image_html = (
                f'<img class="thumb" src="{item["image"]}" alt="{item["name"]}" loading="lazy">'
                if item.get("image") else '<div class="thumb placeholder"></div>'
            )

            cards.append(f"""
            <li class="product">
                {image_html}
                <div class="details">
                    <a class="name" href="{item['url']}" target="_blank" rel="noopener">{item['name']}</a>
                    <div class="prices">{price_html}</div>
                    <div class="sizes">{sizes_html}</div>
                </div>
            </li>
            """)

        entries_html.append(f"""
        <section class="entry">
            <h2>{entry['timestamp']}</h2>
            <ul class="products">{"".join(cards)}</ul>
        </section>
        """)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FinalCut Parka Watch</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 760px;
         margin: 40px auto; padding: 0 16px; color: #222; background: #fafafa; }}
  h1 {{ font-size: 1.5rem; margin-bottom: 0; }}
  .subtitle {{ color: #666; margin-top: 4px; margin-bottom: 32px; }}
  .entry {{ background: #fff; border: 1px solid #e5e5e5; border-radius: 8px;
            padding: 16px 20px; margin-bottom: 20px; }}
  .entry h2 {{ font-size: 0.9rem; color: #888; margin: 0 0 12px; font-weight: 600; }}
  ul.products {{ list-style: none; padding: 0; margin: 0; }}
  li.product {{ display: flex; gap: 14px; align-items: flex-start; padding: 12px 0;
                border-top: 1px solid #f0f0f0; }}
  li.product:first-child {{ border-top: none; }}
  .thumb {{ width: 64px; height: 64px; object-fit: cover; border-radius: 6px;
            background: #f0f0f0; flex-shrink: 0; }}
  .thumb.placeholder {{ display: block; }}
  .details {{ flex: 1; min-width: 0; }}
  a.name {{ color: #1a1a1a; text-decoration: none; font-weight: 500; display: block;
            margin-bottom: 4px; }}
  a.name:hover {{ text-decoration: underline; }}
  .prices {{ margin-bottom: 6px; }}
  .sale-price {{ font-weight: 600; color: #c0392b; margin-right: 8px; }}
  .orig-price {{ color: #999; text-decoration: line-through; font-size: 0.9rem; }}
  .sizes {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .size {{ font-size: 0.75rem; border: 1px solid #ddd; border-radius: 4px;
           padding: 2px 6px; color: #444; background: #fafafa; }}
  .size.unavailable {{ color: #aaa; font-style: italic; border-style: dashed; }}
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
        items = []
        for url in new_urls:
            info = current[url]
            sizes = fetch_sizes(url)
            time.sleep(1)  # be polite between product-page requests
            items.append({
                "url": url,
                "name": info["name"],
                "sale_price": info["sale_price"],
                "original_price": info["original_price"],
                "image": image_url_for(url),
                "sizes": sizes,
            })

        feed = load_json(FEED_FILE, [])
        new_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "items": items,
        }
        feed.insert(0, new_entry)  # newest first
        save_json(FEED_FILE, feed)

        SITE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SITE_FILE.write_text(render_site(feed))
        print(f"Found {len(new_urls)} new parka(s) — site updated.")
    else:
        print("No new parkas since last check.")
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