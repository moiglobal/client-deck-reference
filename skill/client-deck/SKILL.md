---
name: client-deck
description: Builds the firm's Quarterly Client Review for one period, in the firm's house style, from SEC EDGAR, FRED and roic.ai data. Produces the client deck (.pptx and .pdf; plus an internal version if the firm marks any exhibit internal-only), page images, a figure ledger tracing every number to its source, a review checklist and an archive. Every page is watermarked DRAFT until a compliance sign-off is supplied. Never sends, uploads or emails anything. Use when asked to build, rebuild, refresh or check the quarterly client review or client deck for a period such as 2026-Q3, or to check the deck set-up.
---

# Client deck

Course #2, Lesson 3 (Latticework, "The Client Deck"). The skill holds the instructions; the firm's project folder holds the code, the brand, the holdings files and the archive of every run.

## Find the project folder

The project folder is the one that contains `build.py`, `brand/brand.json` and `config/exhibits.json`. Use the folder the user selected or named. If there is more than one candidate, ask which. Run every command below from that folder.

## What you need

- Python 3.10 or later with `python-pptx`, `matplotlib`, `pandas`, `requests`, `lxml`, `Pillow` (`pdfplumber` for the brand capture only).
- LibreOffice and Poppler (`pdftoppm`) for the PDF and page images. Without them, add `--no-render` and say that no PDF was made.
- The roic.ai key and the SEC User-Agent, either as environment variables (`ROIC_API_KEY`, `SEC_USER_AGENT`) or in a `.env` file in the project folder (copy `.env.example`). Never print, repeat or move the key.
- The firm's holdings file for the period: `config/portfolio-<period>.json` (holdings, weights, featured holding, analyst notes).

## Steps

1. Run `python tools/check_setup.py`. If any check fails, show the user the "How to fix" column and stop.
2. Confirm the period with the user (for example `2026-Q3`) and that `config/portfolio-<period>.json` exists. If it does not, copy the previous period's file, then ask the user for the new weights, the featured holding and any analyst notes. Never guess weights.
3. Build: `python build.py --period <period>`
   This downloads the data (or reuses the period's archived snapshot), builds the deck, renders page images and writes `runs/<period>/`.
4. Verify: `python tools/verify.py --period <period>`
   Stop and report if the result is not PASS. Do not edit numbers by hand to make it pass.
5. Look at every page image in `runs/<period>/pages-*/` and check for overlapping labels, titles that wrap, empty charts and anything a client could misread.
6. Report to the user: the titles of all pages, the data warnings at the top of `review-checklist.md`, the verification result, and the path of the client PDF (and the internal PDF, if one was built).
7. Stop. The deck stays DRAFT. Only after the user says compliance has approved it, rebuild with
   `python build.py --period <period> --signoff "<name, role, date>"`
   using the name and date the user gives, word for word.

## Rules

- Never email, upload, post or share the deck. Producing the files is the whole job.
- Never add performance, returns, benchmark comparisons, testimonials, ratings or forecasts to any page.
- The client version never contains an exhibit marked `client_safe: false` in `config/exhibits.json`. Do not change that flag unless the user asks.
- Titles and subtitles are written by code from the data. To change what a page says, change the code or the analyst note in the holdings file, then rebuild.
- If a data source fails, stop and report the error. Do not substitute numbers from memory or from the previous period.
