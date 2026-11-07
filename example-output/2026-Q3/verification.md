# Verification: 2026-Q3

Run 2026-11-07 11:39.

## 1. SEC EDGAR figures against roic.ai v2 statements

Same fiscal year, matched by period-end date within 10 days. Tolerance 2%; larger gaps are listed and explained.

| Company | Concept | FY | EDGAR | roic.ai v2 | Gap |
|---|---|---|---|---|---|

**441 of 527 company-year figures agree within 2% (or $50m).** The table lists every gap in revenue and operating cash flow, where both sources should report the same number.

Gaps by concept:

- revenue: 0 gaps. 
- operating_income: 30 gaps. roic.ai's operating income excludes items such as goodwill impairments and legal charges (Booking 2016 and 2020, Alphabet 2018 EU fine, Cummins charges). The deck uses GAAP OperatingIncomeLoss as filed.
- cfo: 0 gaps. 
- capex: 11 gaps. roic.ai's capital-expenditure line is mis-mapped for some issuers (Cummins: about $50-80m a year against $500-730m in the 10-K cash flow statement). DATA-SOURCES.md in the briefing project records the same defect.
- dividends: 3 gaps. Small number of years where roic.ai's dividends line includes other distributions; the deck uses the 10-K's PaymentsOfDividends.
- buybacks: 42 gaps. roic.ai reports repurchases net of stock issued to employees; the deck uses gross PaymentsForRepurchaseOfCommonStock as filed.
  - largest: BKNG operating_income FY2020: EDGAR -631m vs roic.ai 580m
  - largest: DHR buybacks FY2016: EDGAR 0m vs roic.ai -164m
  - largest: DHR buybacks FY2017: EDGAR 0m vs roic.ai -69m
  - largest: DHR buybacks FY2018: EDGAR 0m vs roic.ai -96m
  - largest: DHR buybacks FY2019: EDGAR 0m vs roic.ai -2,216m
  - largest: DHR buybacks FY2020: EDGAR 0m vs roic.ai -1,882m
  - largest: DHR buybacks FY2021: EDGAR 0m vs roic.ai -86m
  - largest: DHR buybacks FY2023: EDGAR 0m vs roic.ai -68m
  - largest: AZO capex FY2016: EDGAR 489m vs roic.ai 10m
  - largest: CMI capex FY2021: EDGAR 734m vs roic.ai 52m
  - largest: CMI capex FY2020: EDGAR 528m vs roic.ai 47m
  - largest: TXN buybacks FY2023: EDGAR 293m vs roic.ai 30m

## 2. Quarter-end P/E against roic.ai v2

v2 TTM P/E for the same period end, rolled to the quarter-end close with v2's own (split-adjusted) prices.

| Company | Deck (v3) | Check (v2) | Gap |
|---|---|---|---|
| GOOGL | 17.0 | 17.1 | 0.3% |
| COST | 45.7 | 45.7 | 0.0% |
| MA | 30.3 | 30.3 | 0.0% |
| MRSH | 20.8 | 20.8 | 0.0% |
| TXN | 42.1 | 42.1 | 0.0% |
| DHR | 39.2 | 39.2 | 0.0% |
| AZO | 19.3 | 19.3 | 0.0% |
| BKNG | 17.9 | 13.4 | 25.3% accepted: Checked 2026-11-06: roic.ai v2 divides by adjusted (non-GAAP) EPS (implied FY2025 EPS $8.84 post-split); v3, used in the deck, divides by GAAP diluted EPS ($6.62 post-split), which matches Booking's FY2025 10-K ($165.57 before the 25-for-1 split). |
| UNP | 22.0 | 22.0 | 0.0% |
| CMI | 26.3 | 26.3 | 0.0% |

## 3. FRED figures recomputed from the raw series

22 of 22 FRED figures match to 0.005, recomputed from the raw series and, for 12-month changes, against FRED's own year-over-year transformation.

## 4. Every number printed on a slide is in the ledger

- client: 0 numbers not found in the ledger

**Result: PASS.**
