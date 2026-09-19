# FinalCut Parka Watcher (GitHub Pages version)

Checks shopfinalcut.com's Coats & Jackets page for products with "Parka"
in the name. When new ones appear, it publishes a timestamped entry to a
static site hosted via GitHub Pages — newest at the top, no email needed.

## Repo layout

```
check_parkas.py
seen_products.json      <- created automatically (state, not public)
.github/workflows/check.yml
docs/
  feed.json             <- created automatically (history log)
  index.html            <- created automatically (the public page)
```

## 1. Add the files

- Put `check_parkas.py` in the repo root.
- Put the workflow file at `.github/workflows/check.yml` (create the
  nested folders).
- You don't need to create `seen_products.json`, `docs/feed.json`, or
  `docs/index.html` yourself — the script creates them on first run.

## 2. Give the workflow write access

Settings → Actions → General → Workflow permissions → select
**"Read and write permissions"** → Save.

(The `permissions: contents: write` line in the workflow also asks for
this, but the repo setting must allow it too.)

## 3. Push everything

```bash
git add .
git commit -m "add parka bot"
git push
```

## 4. Run it once manually to create the site

Go to the **Actions** tab → "Check FinalCut Parkas" → **Run workflow**.

This first run treats every current parka as "new," so it'll create
`docs/index.html` with one big entry listing everything currently live.
After that, only genuinely new items get added.

## 5. Turn on GitHub Pages

Settings → Pages → under "Build and deployment," set:
- **Source:** Deploy from a branch
- **Branch:** `main` (or whatever your default branch is), folder `/docs`
- Save.

GitHub will give you a URL like:
`https://<your-username>.github.io/<repo-name>/`

It can take a minute or two to go live the first time.

## 6. Ongoing

The workflow runs every hour (`cron: '0 * * * *'`) automatically. Each
run that finds new parkas:
- adds an entry to `docs/feed.json` (newest first)
- regenerates `docs/index.html` from the full feed
- commits both back to the repo, which re-triggers a Pages deploy

You can always trigger a manual check from the Actions tab too.

## Notes

- The site is a plain static page — refresh it manually or check back;
  it doesn't push notifications to you. If you want a nudge instead of
  just a page, you could still add email or a webhook (e.g. Discord/Slack)
  alongside this — happy to add that if you want it later.
- If the site ever shows 0 parkas found when you know there should be
  some, the site's HTML structure may have changed — the CSS selector
  `a[href*="/en/product/"]` or price regex in `check_parkas.py` would
  need adjusting.
- Hourly polling is plenty — no need to run more often than that.