# Client Deck: reference implementation

The finished worked example from Latticework's course **The Client Deck: Build a Quarterly Client Review Your Firm Regenerates in One Command** (December 2026). It builds the quarterly client review of Larkspur Vale Capital, a fictional adviser with ten real holdings at invented weights, from SEC EDGAR, FRED and roic.ai, in one command, with a figure ledger that traces every number to its source.

**Not a programmer? Start with the lessons, not this folder.** Open this folder in Claude Code (the Code tab of the Claude desktop app) and ask in plain English, for example: *"Read README.md and tell me what this project does. Then run tools/check_setup.py and tell me what to fix."*

**Before you use any of this.** This is a teaching example, not legal or compliance advice, and nothing in it makes a deck compliant. A deck you send to clients or prospects may be an advertisement under the SEC's Marketing Rule; that is a question for your chief compliance officer, and you may wish to clear the deck with your own counsel before sending it to clients. The example shows roic.ai data to clients; you may wish to check roic.ai's terms of use (and those of any data provider) before you do the same. The deck shows no performance. Larkspur Vale Capital is fictional.

## Start

1. Copy `.env.example` to `.env` and fill in your roic.ai key and your firm's SEC User-Agent (your firm's name and a monitored email address). `.env` stays on your computer; never commit it.
2. Ask Claude Code: "Run tools/check_setup.py and tell me what to fix."
3. Install the skill: copy `skill/client-deck/` to `.claude/skills/client-deck/` in this folder. Then ask: "Build the client review for 2026-Q3."

`example-output/2026-Q3/` holds the example's own output (PDF, review checklist, verification report, figure ledger) so you can compare yours with it. Your builds go to `runs/`.

---

## The project in detail

A quarterly client review for **Larkspur Vale Capital**, a fictional registered investment adviser (zero hits in the SEC's adviser search for "Larkspur Vale" on 2026-11-06). Built 2026-11-06 for Course #2 Phase 1. Every figure comes from SEC EDGAR, FRED or roic.ai, or from the firm's own holdings file.

## One command

```bash
python build.py --period 2026-Q3
```

Then check it:

```bash
python tools/verify.py --period 2026-Q3
```

`ROIC_API_KEY` and `SEC_USER_AGENT` (firm name and a monitored email) must be set, in the environment or in `.env`. A cold build from an empty folder took about two minutes on 2026-11-07, and `verify.py` passed with 291 figures in the ledger for 2026-Q3.

## What a run writes (`runs/<period>/`)

| File | What it is |
|---|---|
| `larkspur-vale-review-<period>-client-DRAFT.pptx` / `.pdf` | 16 pages, including the two roic.ai valuation pages |
| `larkspur-vale-review-<period>-internal-DRAFT.pptx` / `.pdf` | Only when an exhibit in `config/exhibits.json` is marked `client_safe: false`; none is in the example |
| `pages-*/page-NN.png` | Every page rendered, for the visual check |
| `figure-ledger-client.csv` (and `-internal.csv` when built) | Every number on every page: value, source, series or XBRL tag, period, URL, derivation |
| `review-checklist.md` | Compliance checklist, data warnings, page titles, flagged words |
| `verification.md` | Output of `tools/verify.py` |
| `snapshot.json` | Every downloaded input for the period (the archive) |
| `summary.json` | Key figures the next period's "what changed" page reads |
| `manifest.json` | SHA-256 of every file in the run |

`runs/2026-Q2/summary.json` ships with the project, so your first 2026-Q3 build already has a "what changed" page comparing against the second quarter.

## Layout

| Path | Role |
|---|---|
| `brand/brand.json`, `brand/logo.png` | The house style (Lesson 1). `tools/make_logo.py` draws the fictional logo |
| `config/portfolio-<period>.json` | The firm's holdings file: weights, sectors, featured holding, analyst notes |
| `config/exhibits.json` | The exhibit set, its order, and any exhibit the firm keeps out of the client version |
| `lib/fred.py`, `lib/edgar.py`, `lib/roic.py` | One module per source, each with the traps it guards against written at the top |
| `lib/data.py` | Pulls one period's snapshot, point in time |
| `lib/exhibits.py` | The 16 exhibits; titles are computed from the data |
| `lib/deck.py`, `lib/style.py` | Page furniture and chart styling, read from `brand.json` |
| `build.py` | The one command |
| `tools/verify.py` | Independent checks |
| `tools/check_setup.py` | Lesson 1 set-up check: Python libraries, LibreOffice, Poppler, keys present (never printed), one request to each source; writes `setup-check.md` |
| `tools/capture_brand.py` | Lesson 1 brand capture: measures fonts, colors, rules, footer, disclosure and logo out of a PDF; writes `brand/brand-captured.json` and `brand/capture-report.md`, never `brand.json` |
| `tools/make_sample_letter.py` | Makes Larkspur Vale's stand-in client letter (`brand/source/`), because the firm is fictional |
| `.env.example` | Copy to `.env` for the roic.ai key and the SEC User-Agent. Environment variables work too. Never commit `.env` |
| `skill/client-deck/SKILL.md` | The skill (Lesson 3): instructions only; the code, brand, holdings and archive stay in this project folder. Copy the folder to `.claude/skills/client-deck/` to install it |
| `example-output/2026-Q3/` | The example's own output, to compare against |
| `cache/` | Raw downloads (about 90 MB); safe to delete, rebuilt on the next run |

## Pages (client version)

1. Cover
2. The quarter at a glance (four figures)
3. Treasury yield curve now, a year ago, two years ago (FRED H.15)
4. 10-year real yield and breakeven inflation, 15 years (FRED)
5. Federal funds rate, 2-year Treasury and CPI inflation, 10 years (FRED)
6. Four-panel economy page: CPI, unemployment, payrolls, industrial production (FRED)
7. Quality table: growth, margins, free cash flow, share count, cash returned, per holding and weighted (EDGAR)
8. Share count indexed to 100, ten years, split-proof (EDGAR)
9. Where ten years of operating cash went, per holding and weighted (EDGAR)
10. Featured holding: revenue, operating margin, free cash flow per share (EDGAR)
11. Valuation against each holding's own ten-year P/E range (roic.ai)
12. Valuation and return-on-capital table (roic.ai)
13. Positioning: weights by holding and sector (firm file)
14. What changed since last quarter (archive)
15. Sources and methodology
16. Important information, with the CCO placeholder and the review record

## Data terms

The valuation pages show roic.ai data to clients, on the view that the data are shown, not resold. You may wish to check roic.ai's terms of use before you do the same. To keep any page out of the client version, set `client_safe: false` for it in `config/exhibits.json`: the build then also writes an internal version with that page.
