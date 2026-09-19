#!/usr/bin/env python3
"""
Checks shopfinalcut.com's Coats & Jackets category for parkas and tracks
three kinds of changes against the last run:
  1. New listings  — a product URL we haven't seen before.
  2. Price drops    — an already-seen item's sale price has decreased.
  3. Restocks       — an already-seen item now shows a size that wasn't
                       available last time (best-effort — see caveat below).

Each run that finds any of the above adds a timestamped entry to
docs/feed.json and regenerates docs/index.html (newest first) for
GitHub Pages to serve.

COST NOTE: unlike the original version (which only fetched product pages
for brand-new items), catching restocks means every currently-listed
parka's product page gets re-fetched on every run, not just new ones.
That's meaningfully more requests to FinalCut's site. If your parka list
is small this is fine; if it grows large, consider a less frequent
schedule (e.g. every few hours or daily instead of hourly).

SIZING CAVEAT: size detection is a best-effort text match against known
size labels (XS–XXXL) found on the product page. It currently can't tell
a disabled/sold-out size apart from a purchasable one — both show up as
"available" here. This affects both the "sizes shown" list and restock
detection. Fix pending a look at the site's actual size-selector markup.
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
STATE_FILE = ROOT / "seen_products.json"      # last-known state per item (not public)
DOCS_DIR = ROOT / "docs"                       # served by GitHub Pages
FEED_FILE = DOCS_DIR / "feed.json"             # time-series log of change events
SITE_FILE = DOCS_DIR / "index.html"            # generated page

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36"
}

KNOWN_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]
SIZE_ORDER = {s: i for i, s in enumerate(KNOWN_SIZES)}


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
        full_url = full_url.split("?")[0]

        prices = re.findall(r"\$[\d,]+\.\d{2}", text)
        sale_price = prices[0] if len(prices) >= 1 else "?"
        original_price = prices[1] if len(prices) >= 2 else None
        name = re.split(r"\$", text)[0].strip()

        products[full_url] = {
            "name": name,
            "sale_price": sale_price,
            "original_price": original_price,
        }

    return products


def parse_price(price_str):
    """'$499.99' -> 499.99. Returns None for missing/unparseable prices."""
    if not price_str or price_str == "?":
        return None
    try:
        return float(price_str.replace("$", "").replace(",", ""))
    except ValueError:
        return None


# ---- Scraping: product page (image + sizes) ----------------------------------

def style_number_from_url(url):
    match = re.search(r"-(\d{6,})$", url.rstrip("/"))
    return match.group(1) if match else None


def image_url_for(url):
    style = style_number_from_url(url)
    if not style:
        return None
    return f"https://i1.adis.ws/i/harryrosen/{style}?$thumbnail$"


def fetch_sizes(product_url):
    """Fetch a product page and return the list of sizes shown for it.

    CAVEAT: see module docstring — this can't yet distinguish a disabled
    (sold-out) size from a purchasable one.
    """
    try:
        resp = requests.get(product_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    section_match = re.search(r"\bSize\b(.*?)Need help with sizing", text, re.IGNORECASE)
    section = section_match.group(1) if section_match else text

    found = []
    for size in KNOWN_SIZES:
        if re.search(rf"(?<![A-Z]){re.escape(size)}(?![A-Z])", section):
            found.append(size)

    found.sort(key=lambda s: SIZE_ORDER.get(s, 99))
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

def render_price_html(item):
    if item.get("original_price"):
        return (
            f'<span class="sale-price">{item["sale_price"]}</span>'
            f'<span class="orig-price">{item["original_price"]}</span>'
        )
    return f'<span class="sale-price">{item["sale_price"]}</span>'


def render_sizes_html(sizes):
    if sizes:
        return "".join(f'<span class="size">{s}</span>' for s in sizes)
    return '<span class="size unavailable">No sizes found</span>'


def render_product_card(item, extra_note=""):
    image_html = (
        f'<img class="thumb" src="{item["image"]}" alt="{item["name"]}" loading="lazy">'
        if item.get("image") else '<div class="thumb placeholder"></div>'
    )
    note_html = f'<div class="note">{extra_note}</div>' if extra_note else ""
    return f"""
    <li class="product">
        {image_html}
        <div class="details">
            <a class="name" href="{item['url']}" target="_blank" rel="noopener">{item['name']}</a>
            <div class="prices">{render_price_html(item)}</div>
            {note_html}
            <div class="sizes">{render_sizes_html(item.get('sizes') or [])}</div>
        </div>
    </li>
    """


def render_section(title, css_class, items, note_fn=None):
    if not items:
        return ""
    cards = "".join(
        render_product_card(item, note_fn(item) if note_fn else "")
        for item in items
    )
    return f"""
    <div class="section {css_class}">
        <h3>{title}</h3>
        <ul class="products">{cards}</ul>
    </div>
    """


def render_site(feed):
    entries_html = []
    if not feed:
        entries_html.append("<p class='empty'>No changes spotted yet — check back soon.</p>")

    for entry in feed:
        # Backward compatibility: older entries only have "items" (all new listings).
        new_items = entry.get("new", entry.get("items", []))
        price_drops = entry.get("price_drops", [])
        restocks = entry.get("restocks", [])

        sections = (
            render_section("🆕 New Listings", "new", new_items)
            + render_section(
                "💸 Price Drops", "price-drop", price_drops,
                note_fn=lambda i: f'was <span class="was-price">{i["old_price"]}</span>'
                                   f' → now <span class="now-price">{i["new_price"]}</span>'
            )
            + render_section(
                "📦 Restocked", "restock", restocks,
                note_fn=lambda i: f'newly available: {", ".join(i["newly_available"])}'
            )
        )

        entries_html.append(f"""
        <section class="entry">
            <h2>{entry['timestamp']}</h2>
            {sections}
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
  .section {{ margin-bottom: 16px; }}
  .section:last-child {{ margin-bottom: 0; }}
  .section h3 {{ font-size: 0.85rem; margin: 0 0 8px; color: #555; }}
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
  .prices {{ margin-bottom: 4px; }}
  .sale-price {{ font-weight: 600; color: #c0392b; margin-right: 8px; }}
  .orig-price {{ color: #999; text-decoration: line-through; font-size: 0.9rem; }}
  .note {{ font-size: 0.8rem; color: #666; margin-bottom: 6px; }}
  .was-price {{ text-decoration: line-through; color: #999; }}
  .now-price {{ color: #c0392b; font-weight: 600; }}
  .sizes {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .size {{ font-size: 0.75rem; border: 1px solid #ddd; border-radius: 4px;
           padding: 2px 6px; color: #444; background: #fafafa; }}
  .size.unavailable {{ color: #aaa; font-style: italic; border-style: dashed; }}
  .empty {{ color: #888; }}
</style>
</head>
<body>
  <h1>🧥 FinalCut Parka Watch</h1>
  <p class="subtitle">New listings, price drops, and restocks on shopfinalcut.com, newest first.</p>
  {"".join(entries_html)}
</body>
</html>
"""


# ---- Main -----------------------------------------------------------------

def main():
    scraped = fetch_parkas()
    seen = load_json(STATE_FILE, {})

    new_entries = []
    price_drop_entries = []
    restock_entries = []
    updated_state = {}

    for url, info in scraped.items():
        prior = seen.get(url)

        # Always (re)fetch sizes — needed for restock detection on existing
        # items, and for display on new ones.
        sizes = fetch_sizes(url)
        time.sleep(1)  # be polite between product-page requests

        enriched = {
            "url": url,
            "name": info["name"],
            "sale_price": info["sale_price"],
            "original_price": info["original_price"],
            "image": image_url_for(url),
            "sizes": sizes,
        }
        updated_state[url] = {
            "name": info["name"],
            "sale_price": info["sale_price"],
            "original_price": info["original_price"],
            "sizes": sizes,
        }

        if prior is None:
            new_entries.append(enriched)
            continue

        # Price drop check
        old_price_val = parse_price(prior.get("sale_price"))
        new_price_val = parse_price(info["sale_price"])
        if old_price_val is not None and new_price_val is not None and new_price_val < old_price_val:
            drop_item = dict(enriched)
            drop_item["old_price"] = prior["sale_price"]
            drop_item["new_price"] = info["sale_price"]
            price_drop_entries.append(drop_item)

        # Restock check — a size present now that wasn't before
        prior_sizes = set(prior.get("sizes", []))
        newly_available = [s for s in sizes if s not in prior_sizes]
        if newly_available:
            restock_item = dict(enriched)
            restock_item["newly_available"] = sorted(
                newly_available, key=lambda s: SIZE_ORDER.get(s, 99)
            )
            restock_entries.append(restock_item)

    if new_entries or price_drop_entries or restock_entries:
        feed = load_json(FEED_FILE, [])
        new_entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "new": new_entries,
            "price_drops": price_drop_entries,
            "restocks": restock_entries,
        }
        feed.insert(0, new_entry)
        save_json(FEED_FILE, feed)

        SITE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SITE_FILE.write_text(render_site(feed))
        print(
            f"New: {len(new_entries)}, Price drops: {len(price_drop_entries)}, "
            f"Restocks: {len(restock_entries)} — site updated."
        )
    else:
        print("No changes since last check.")
        if not SITE_FILE.exists():
            feed = load_json(FEED_FILE, [])
            save_json(FEED_FILE, feed)
            SITE_FILE.parent.mkdir(parents=True, exist_ok=True)
            SITE_FILE.write_text(render_site(feed))

    save_json(STATE_FILE, updated_state)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        sys.exit(1)