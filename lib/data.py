"""Pull every input for one period into a single snapshot (archived with the deck)."""
import datetime as dt

import pandas as pd

from . import edgar, fred, roic
from .common import ROOT, SEC_USER_AGENT, load_json

QUARTER_END = {"Q1": (3, 31), "Q2": (6, 30), "Q3": (9, 30), "Q4": (12, 31)}
# A month's figure is treated as published 45 days after the month begins (CPI and
# industrial production appear mid-month, payrolls in the first week). Conservative on
# purpose: a deck dated September 30 must not show September CPI, published in October.
MONTHLY_LAG_DAYS = 45
# A quarter's earnings are treated as reported 45 days after it ends (10-Q deadline for
# large accelerated filers is 40 days).
EARNINGS_LAG_DAYS = 45


def parse_period(period):
    y, q = period.split("-")
    m, d = QUARTER_END[q]
    as_of = dt.date(int(y), m, d)
    start = dt.date(int(y), m - 2, 1)
    label = {"Q1": "First", "Q2": "Second", "Q3": "Third", "Q4": "Fourth"}[q] + f" quarter {y}"
    return as_of, start, label


def prev_period(period):
    y, q = period.split("-")
    n = int(q[1])
    return f"{int(y) - 1}-Q4" if n == 1 else f"{y}-Q{n - 1}"


def collect(period, fetch_date, log=print, need_roic=True):
    as_of, q_start, label = parse_period(period)
    if "@" not in SEC_USER_AGENT:
        raise SystemExit("Set SEC_USER_AGENT to your firm's name and a monitored email address, in the environment or in "
                         ".env (see .env.example). SEC EDGAR asks every automated client to identify itself.")
    port = load_json(ROOT / "config" / f"portfolio-{period}.json")
    snap = dict(period=period, label=label, as_of=as_of.isoformat(), q_start=q_start.isoformat(),
                fetch_date=fetch_date, portfolio=port, warnings=[])

    # ---- FRED ----
    log("FRED: downloading series")
    snap["fred"] = {}
    for sid, (title, producer, freq) in fred.SERIES.items():
        s = fred.get(sid, as_of, fetch_date)
        if freq == "monthly":
            cutoff = pd.Timestamp(as_of - dt.timedelta(days=MONTHLY_LAG_DAYS))
            s = s[s.index <= cutoff]
        s = s[s.index >= pd.Timestamp("2009-01-01")]
        snap["fred"][sid] = dict(title=title, producer=producer, freq=freq, url=s.attrs["url"],
                                 retrieved=s.attrs["retrieved"],
                                 obs=[[d.date().isoformat(), float(v)] for d, v in s.items()])
        last = s.index[-1].date()
        stale_days = (as_of - last).days
        limit = 10 if freq == "daily" else 80
        if stale_days > limit:
            snap["warnings"].append(f"FRED {sid}: last observation {last} is {stale_days} days before the as-of date")

    # ---- EDGAR ----
    snap["edgar"] = {}
    for h in port["holdings"]:
        t, cik = h["ticker"], h["cik"]
        log(f"EDGAR: {t}")
        d = edgar.facts(cik, fetch_date)
        fy_all = edgar.fiscal_year_ends(d, as_of)
        fy = fy_all[-11:]  # ten years of flows, plus one more for the 10-year share link
        rec = dict(cik=cik, entity=d.get("entityName"), retrieved=d["_retrieved"], concepts={})
        for c in ["revenue", "operating_income", "cfo", "capex", "dividends", "buybacks", "acquisitions"]:
            if cik in edgar.EXTENSIONS and c in edgar.EXTENSIONS[cik]:
                df = edgar.extension_annual(cik, c, fetch_date, as_of, fy)
            else:
                df = edgar.annual(d, c, as_of, fy)
            rec["concepts"][c] = {int(k): dict(val=r["val"], tag=r["tag"], accn=r["accn"], filed=r["filed"],
                                               end=r["fy_end"].isoformat())
                                  for k, r in df.iterrows()}
            for (end, t_hi, t_lo, ratio) in df.attrs.get("switch_checks", []):
                if abs(ratio - 1) > 0.01 and end >= fy[1]:
                    snap["warnings"].append(
                        f"EDGAR {t} {c} FY{end.year}: {t_lo} differs from {t_hi} by {ratio - 1:+.1%} in the same filing; {t_hi} used")
            missing = [e.year for e in fy[1:] if e.year not in rec["concepts"][c]]
            if missing:
                snap["warnings"].append(f"EDGAR {t} {c}: no value for FY {missing}")
            zeros = [k for k, v in rec["concepts"][c].items() if v["accn"] is None and k >= fy[1].year]
            if zeros:
                snap["warnings"].append(f"EDGAR {t} {c}: no fact filed for FY {zeros}; treated as zero (check the cash flow statement)")
        sh = edgar.chain_linked_shares(d, as_of, fy)
        rec["shares_tag"] = sh.attrs["tag"]
        rec["shares"] = {int(k): dict(ratio=r["ratio_to_prior"], accn=r["accn"], val=r["val"],
                                      prior=r["prior_val"], filed=r["filed"]) for k, r in sh.iterrows()}
        # filings made during the quarter
        s = edgar.submissions(cik, fetch_date)
        r = s["filings"]["recent"]
        rec["filings_in_quarter"] = [
            dict(form=r["form"][i], date=r["filingDate"][i], accn=r["accessionNumber"][i])
            for i in range(len(r["form"]))
            if q_start.isoformat() <= r["filingDate"][i] <= as_of.isoformat()
            and r["form"][i] in ("10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "DEF 14A")]
        snap["edgar"][t] = rec

    # ---- roic.ai ----
    snap["roic"] = {}
    if not need_roic:
        # No enabled exhibit uses roic.ai (Lesson 1's three-page deck): no key needed.
        log("roic.ai: skipped, no enabled exhibit uses it")
        return snap
    cutoff = (as_of - dt.timedelta(days=EARNINGS_LAG_DAYS)).isoformat()
    for h in port["holdings"]:
        t, sym = h["ticker"], h["roic"]
        log(f"roic.ai: {sym}")
        ttm = [x for x in roic.multiples(sym, "ttm", 8, fetch_date)
               if x["period_end_date"] <= cutoff and x.get("pe_ratio")]
        ann = [x for x in roic.multiples(sym, "annual", 12, fetch_date) if x["period_end_date"] <= as_of.isoformat()][:10]
        prof = [x for x in roic.profitability(sym, "ttm", 8, fetch_date)
                if x["period_end_date"] <= cutoff and x.get("return_on_inv_capital") is not None]
        if not ttm or not prof:
            raise RuntimeError(f"roic.ai {sym}: no populated TTM row ending on or before {cutoff}")
        row = ttm[0]
        age = (as_of - dt.date.fromisoformat(row["period_end_date"])).days
        if age > 200:
            snap["warnings"].append(f"roic.ai {t}: newest populated TTM valuation row ends {row['period_end_date']} "
                                    f"({age} days before the as-of date); later rows are empty at the vendor")
        px_date, px = roic.close_on_or_before(sym, as_of, fetch_date)
        row_px_date, row_px = roic.close_on_or_before(sym, dt.date.fromisoformat(row["period_end_date"]), fetch_date)
        # roic.ai prices are not split-adjusted (Booking: 4,194 -> 176 on its 25-for-1 split,
        # 2026-04-06). Roll the P/E forward with the split factor from the vendor's split
        # history, then check no unexplained jump remains in the window.
        split_f = roic.split_factor_between(sym, row_px_date, px_date, fetch_date)
        series = sorted((p for p in roic.prices(sym, fetch_date) if row_px_date <= p["date"] <= px_date),
                        key=lambda p: p["date"])
        for a, b in zip(series, series[1:]):
            f = roic.split_factor_between(sym, a["date"], b["date"], fetch_date)
            if not 0.6 < b["close"] * f / a["close"] < 1.6:
                raise RuntimeError(f"roic.ai {sym}: unexplained price jump {a['date']}->{b['date']}")
        if split_f != 1.0:
            snap["warnings"].append(f"roic.ai {t}: split factor {split_f:g} applied between {row_px_date} and {px_date}")
        snap["roic"][t] = dict(
            symbol=sym, ttm_period_end=row["period_end_date"], ttm_pe=row.get("pe_ratio"),
            ttm_ev_ebitda=row.get("ev_to_ttm_ebitda"), price_as_of=px, price_date=px_date,
            price_at_period_end=row_px, price_period_end_date=row_px_date, split_factor=split_f,
            roic_ttm=prof[0].get("return_on_inv_capital"), roic_period_end=prof[0]["period_end_date"],
            annual=[dict(fy=x["fiscal_year"], end=x["period_end_date"], pe_avg=x.get("average_price_earnings_ratio"),
                         pe_hi=x.get("pe_ratio_with_high_clos_pr"), pe_lo=x.get("pe_ratio_with_low_clos_pr"))
                    for x in ann])
    return snap
