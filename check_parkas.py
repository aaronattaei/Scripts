#!/usr/bin/env python3
"""
Checks shopfinalcut.com's Coats & Jackets category for parkas and notifies
you (via email) when a new product shows up that wasn't there last time.

How it works:
1. Fetches the Coats & Jackets page (sorted by Newest Arrivals).
2. Extracts product name/brand/price/link for every item whose title
   contains "Parka" (case-insensitive) — tweak PARKA_KEYWORDS below if
   FinalCut uses different wording.
3. Compares against seen_products.json (created on first run).
4. Emails you a summary of anything new, then updates seen_products.json.

Run this on a schedule (cron, GitHub Actions, etc.) — see README below.
"""

import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---- Config ---------------------------------------------------------------

CATEGORY_URL = "https://www.shopfinalcut.com/en/shop/coats-jackets?sort=newest"
PARKA_KEYWORDS = ["parka"]  # add more terms here if needed, e.g. "anorak"

STATE_FILE = Path(__file__).parent / "seen_products.json"

# Email settings — fill these in, or set as environment variables of the
# same name (recommended so you don't commit credentials to disk).
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")         # your email address
SMTP_PASS = os.environ.get("SMTP_PASS", "")         # app password, not your real password
NOTIFY_TO = os.environ.get("NOTIFY_TO", SMTP_USER)  # where the alert goes

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36"
}


# ---- Scraping ---------------------------------------------------------------

def fetch_parkas():
    """Return a dict of {product_url: {name, price, brand}} for current parkas."""
    resp = requests.get(CATEGORY_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    products = {}
    # Product tiles link to /en/product/<slug>. Grab every such link and
    # pull the visible text near it for name/price.
    for link in soup.select('a[href*="/en/product/"]'):
        href = link.get("href", "")
        text = link.get_text(" ", strip=True)
        if not text:
            continue
        if not any(kw.lower() in text.lower() for kw in PARKA_KEYWORDS):
            continue

        full_url = href if href.startswith("http") else f"https://www.shopfinalcut.com{href}"
        # Text usually looks like "Brand Name Product Name$XX.XX$YY.YYSave ZZ%"
        price_match = re.search(r"\$[\d,]+\.\d{2}", text)
        price = price_match.group(0) if price_match else "?"
        name = re.split(r"\$", text)[0].strip()

        products[full_url] = {"name": name, "price": price}

    return products


# ---- State handling ---------------------------------------------------------

def load_seen():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_seen(products):
    STATE_FILE.write_text(json.dumps(products, indent=2))


# ---- Notification -----------------------------------------------------------

def send_email(new_items):
    if not SMTP_USER or not SMTP_PASS:
        print("SMTP_USER/SMTP_PASS not set — skipping email, printing instead:\n")
        for url, info in new_items.items():
            print(f"- {info['name']} ({info['price']}) -> {url}")
        return

    lines = [f"- {info['name']} ({info['price']})\n  {url}" for url, info in new_items.items()]
    body = "New parkas on ShopFinalCut:\n\n" + "\n\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"🧥 {len(new_items)} new parka(s) on FinalCut"
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [NOTIFY_TO], msg.as_string())

    print(f"Emailed {len(new_items)} new item(s) to {NOTIFY_TO}")


# ---- Main ---------------------------------------------------------------

def main():
    current = fetch_parkas()
    seen = load_seen()

    new_urls = set(current) - set(seen)
    new_items = {url: current[url] for url in new_urls}

    if new_items:
        send_email(new_items)
    else:
        print("No new parkas since last check.")

    save_seen(current)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as e:
        print(f"Fetch failed: {e}", file=sys.stderr)
        sys.exit(1)