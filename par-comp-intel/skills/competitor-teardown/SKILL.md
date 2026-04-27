---
name: competitor-teardown
description: "Generate a strategic competitor teardown Word document (.docx) for a single competitor — covering executive summary, company snapshot, strategy, ICP, product/service differentiation, SWOT, and curated news with PAR-specific takeaways. Use this skill any time the user asks to create, refresh, regenerate, or update a competitor teardown / strategic overview / deep-dive / strategic profile / competitor brief for the PAR Competitive Intelligence Monitor — including weekly refresh runs that name a specific competitor (e.g. SpotOn, Toast, Square, Olo, Lightspeed, NCR Voyix, etc.). Trigger this skill even if the user only says 'refresh the SpotOn deep-dive' or 'rebuild the Toast teardown' without explicitly mentioning Word documents — the deliverable is always a .docx in the dashboard's teardowns folder. Do NOT use this skill for the dashboard's auto-refreshing news, financial, or product-update feeds — those have their own pipeline. Use this skill specifically for the human-curated narrative document."
---

# Competitor Teardown Generator

Build the strategic teardown .docx for a named competitor. The output complements the auto-fetched data in the Competitive Intelligence Monitor by adding curated narrative, ICP framing, SWOT, and PAR-specific takeaways that the AI-generated dashboard text can't produce.

## When this runs

This skill is invoked as part of the **weekly site refresh** — typically on Monday mornings, alongside the data fetcher's regular cadence. The user will name a specific competitor (e.g. "Refresh the SpotOn teardown" or "Rebuild the Toast teardown"). One competitor per invocation.

It is also invoked **ad hoc** when the user asks for a new competitor's teardown for the first time. The first time a competitor is added, expect to do meaningful research; on weekly refreshes, focus on what changed in the last 7 days and update only the affected sections.

## Workflow overview

```
  ┌──────────────────────────────────────────────────────────────────┐
  │ 1. Identify the competitor and check for an existing content     │
  │    JSON file in the repo at par-comp-intel/teardowns/<slug>.json │
  ├──────────────────────────────────────────────────────────────────┤
  │ 2. Research — pull recent news, product updates, financials,     │
  │    customer reviews. Use web_search and web_fetch.               │
  ├──────────────────────────────────────────────────────────────────┤
  │ 3. Update the content JSON (or create it from scratch). Keep all │
  │    sections that are still accurate; rewrite stale ones.         │
  ├──────────────────────────────────────────────────────────────────┤
  │ 4. Run the build script to produce the .docx                     │
  ├──────────────────────────────────────────────────────────────────┤
  │ 5. Validate the .docx with the docx skill's validator            │
  ├──────────────────────────────────────────────────────────────────┤
  │ 6. Commit content JSON + .docx to the repo                       │
  └──────────────────────────────────────────────────────────────────┘
```

## Step 1 — Identify the competitor and locate existing content

The dashboard already has a `COMPETITORS` array in `par-comp-intel/dashboard.html`. Use the same `id` slug from that array as the filename (e.g. `spoton`, `tost`, `lspd`, `olo`, `paytronix`).

Look for an existing content file at:
```
par-comp-intel/teardowns/<slug>.json
```

- **If it exists**: this is a refresh. Load it as the starting point. Most fields likely don't need to change week-to-week — only update what's stale.
- **If it doesn't exist**: this is a first-time build. Use `references/content_template.json` to understand the schema and `references/spoton_example.json` to see fully filled-in voice and depth. Bias toward the depth shown in the SpotOn example — short bullets and shallow analysis don't earn their place in the document.

## Step 2 — Research

Use web_search and web_fetch to pull:

| Source | What to look for |
|---|---|
| Company website | Latest product pages, leadership team, customer logos |
| TechCrunch, Restaurant Dive, Nation's Restaurant News, Restaurant Business Online, Hospitality Tech, Restaurant Technology News | News in the last 7 days (refresh) or last 12–18 months (first build) |
| Crunchbase, PitchBook (if accessible) | Funding rounds, valuation history, investor list — **only for private companies** |
| Yahoo Finance, SEC EDGAR | Recent 10-K/10-Q, earnings call commentary — **only for public companies** |
| LinkedIn (search via web_search, do not log in) | Headcount changes, key leadership hires, hiring patterns |
| G2, Capterra, Reddit r/restaurantowners | Customer sentiment, pricing complaints, ETF friction signals |
| The dashboard itself (par-comp-intel/data/news.json, alerts.json) | Pre-classified news already tracked for this competitor — load this file from the repo and use the recent items as your news inventory baseline |

For **weekly refreshes**, the most efficient research path is to load the dashboard's own `news.json` and look at items from the last 7 days for this competitor. The auto-fetcher has already done the headline collection — your job is to add the analyst layer.

**Source quality rules:**
- Prefer original sources (company press releases, primary publications) over aggregators.
- Do not invent statistics. If a number is uncertain, say so explicitly (e.g. "estimated $400–500M, analyst triangulation; not publicly disclosed").
- Every news item in the `news` array must have a real URL that resolves. If you can't find a permalink, drop the item.
- Respect copyright limits: paraphrase headlines and source descriptions; do not copy verbatim text. The "headline" field is your one-line paraphrase, not a verbatim copy from the publication.

## Step 3 — Update the content JSON

The JSON schema is documented in `references/content_template.json`. The voice and depth target is in `references/spoton_example.json`.

Save the updated file to:
```
par-comp-intel/teardowns/<slug>.json
```

### Section-by-section refresh checklist for weekly runs

For weekly refreshes, walk through this checklist. Most sections will be unchanged week-to-week.

- **executive_summary** — refresh only if there's been a material strategic change (funding, M&A, leadership change, divestiture, IPO filing). Otherwise leave alone.
- **company_snapshot** — update headcount, valuation, last round, recent hires only when they change. Bump `prepared_date` always.
- **strategy.thesis / pillars** — these change rarely (quarters, not weeks). Leave alone unless something fundamental shifted.
- **strategy.inflection_points** — add new entries for material events from the last week. Keep the list to 5–7 highest-signal items; remove old/lower-signal items if needed.
- **icp** — change only if the competitor announced a vertical pivot or new ICP-defining product.
- **product_diff** — add new products to the `products` list. Move items between `strengths` and `weaknesses` only if a release closed a gap or opened one.
- **swot** — refresh quarterly, not weekly. Only update individual bullets if something material shifted.
- **news** — **always rebuild this from scratch**. Pull the 6–10 highest-signal items from the last 12–18 months, with at least 2–3 from the last 30 days. Each item needs date + headline + source + url + takeaway.
- **par_playbook** — rarely changes; only update `signals` and `actions` if the dashboard's tracked alert categories or PAR's competitive posture shifted.

### Content quality bar

Each section should pass the **"would this earn its place in a paid analyst report?"** test. Specifics:

- Bullets that are 5 words long are too short. Aim for one substantive sentence per bullet — typically 15–35 words.
- Use **bold** sparingly to emphasize the 1–3 key facts per paragraph (dollar amounts, percentages, named entities, strategic conclusions). Do not bold whole sentences.
- Every "PAR Takeaway" in the news section must be PAR-specific — what should PAR sales/product/exec actually do differently because of this news? Generic commentary fails the bar.
- The "Why this matters for PAR" line in the executive summary is the most-read sentence in the whole document. Make it count.

## Step 4 — Run the build script

```bash
node scripts/build_teardown.js \
  par-comp-intel/teardowns/<slug>.json \
  par-comp-intel/teardowns/<slug>_Teardown.docx
```

The script reads the JSON content file and writes the .docx. It uses PAR brand colors (purple `#6864D1`, dark `#2F3452`) and Arial throughout. All sections are optional — if a key is missing from the JSON, that section is omitted from the document.

The script supports inline `**bold**` markdown in body strings (the `**` delimiter). No other inline markdown is supported — keep formatting at the structural level (headings, bullets, tables) rather than inline.

If `npm` doesn't have `docx` installed in the environment, install it: `npm install -g docx`.

## Step 5 — Validate

```bash
python3 /mnt/skills/public/docx/scripts/office/validate.py par-comp-intel/teardowns/<slug>_Teardown.docx
```

Expect output ending with `All validations PASSED!`. If validation fails, the most common cause is a malformed input JSON — fix the JSON and rerun the build script. Do not edit the .docx directly.

## Step 6 — Commit to the repo

Commit both files:
```bash
git add par-comp-intel/teardowns/<slug>.json par-comp-intel/teardowns/<slug>_Teardown.docx
git commit -m "teardown: refresh <CompetitorName> (week of YYYY-MM-DD)

- Updated company_snapshot, news, and inflection_points
- [list any other sections that materially changed]
- Regenerated <slug>_Teardown.docx via competitor-teardown skill"
git push origin main
```

After push, the .docx is available at:
```
https://echou-par.github.io/par-comp-intel/teardowns/<slug>_Teardown.docx
```

## Wiring into the dashboard (one-time, on first build)

When a teardown is first added for a competitor, the Strategic Analysis tab on the competitor detail page should show a "Download full teardown (.docx)" link. The link points to the GitHub Pages URL above. Once the link is added (one-time HTML edit per competitor), the dashboard will automatically serve the latest version after every weekly refresh — no further dashboard changes needed.

If the user has not yet wired this link into the dashboard, mention it after the commit so they know to do it on the next dashboard edit.

## Edge cases

- **Competitor not in COMPETITORS array.** Don't generate a teardown for a competitor that isn't tracked in the dashboard. Ask the user to add it to `COMPETITORS` first.
- **Competitor was recently acquired** (e.g. Spendgo by Olo, Dec 2025). Note the acquisition prominently in the executive summary and company_snapshot. The teardown is still useful — it documents the acquired entity's prior strategy and integration trajectory — but flag the status change in the first paragraph.
- **Public company with thin recent news.** Lean on 10-K/10-Q risk factors and recent earnings call commentary for the inflection_points section. Public-company source material is richer than private-company material; use it.
- **First-time build for a brand-new competitor.** This will take longer than a weekly refresh — budget for genuine research depth, not a 5-minute fill-in. Quality of the first build determines how useful weekly refreshes are.
