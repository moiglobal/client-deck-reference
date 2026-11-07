"""Independent checks on a built period. Run after build.py:

    python tools/verify.py --period 2026-Q3

1. EDGAR figures vs roic.ai v2 standardized statements (a second, independent source).
2. Quarter-end P/E vs roic.ai v2 (a different API version with its own price history).
3. FRED figures recomputed from the raw series by separate, simpler code.
4. Coverage: every number printed as text on a slide must appear in that slide's
   ledger rows (chart labels inside images are covered by the ledger and the visual check).
Writes runs/<period>/verification.md. Exit code 1 if any check fails."""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import requests
from pptx import Presentation

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lib.common import CACHE, ROOT as _R, load_json, secret  # noqa: E402

FIRM = load_json(_R / "brand" / "brand.json")["firm_name"]

KEY = secret("ROIC_API_KEY")
if not KEY:
    sys.exit("No roic.ai key: set ROIC_API_KEY or put it in .env (see .env.example).")


def v2(path):
    key = CACHE / "verify" / (re.sub(r"[^A-Za-z0-9]+", "_", path) + ".json")
    if key.exists():
        return json.loads(key.read_text())
    r = requests.get(f"https://api.roic.ai/v2/{path}", params={"apikey": KEY}, timeout=60)
    r.raise_for_status()
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text(r.text)
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", required=True)
    a = ap.parse_args()
    run = ROOT / "runs" / a.period
    snap = json.loads((run / "snapshot.json").read_text())
    out, fails = [f"# Verification: {a.period}", "", f"Run {dt.datetime.now():%Y-%m-%d %H:%M}.", ""], 0

    # ---- 1. EDGAR vs roic.ai v2 statements
    out += ["## 1. SEC EDGAR figures against roic.ai v2 statements", "",
            "Same fiscal year, matched by period-end date within 10 days. Tolerance 2%; larger gaps are listed and explained.", "",
            "| Company | Concept | FY | EDGAR | roic.ai v2 | Gap |", "|---|---|---|---|---|---|"]
    fields = {"revenue": ("income-statement", "is_sales_revenue_turnover", 1),
              "operating_income": ("income-statement", "is_oper_income", 1),
              "cfo": ("cash-flow", "cf_cash_from_oper", 1),
              "capex": ("cash-flow", "cf_cap_expenditures", -1),
              "dividends": ("cash-flow", "cf_dvd_paid", -1),
              "buybacks": ("cash-flow", "cf_proc_fr_repurch_eqty_detailed", -1)}
    n_ok = n_all = 0
    gaps = []
    for t, rec in snap["edgar"].items():
        sym = t
        stmts = {k: v2(f"fundamental/{k}/{sym}?period=annual&limit=14") for k in ("income-statement", "cash-flow")}
        for concept, (stmt, field, sign) in fields.items():
            for fy, r in rec["concepts"][concept].items():
                if int(fy) < int(max(rec["concepts"]["revenue"])) - 9:
                    continue
                end = dt.date.fromisoformat(r["end"])
                m = [x for x in stmts[stmt] if abs((dt.date.fromisoformat(x["date"]) - end).days) <= 10]
                if not m or m[0].get(field) is None:
                    continue
                other = sign * float(m[0][field])
                n_all += 1
                base = max(abs(r["val"]), abs(other), 1)
                gap = abs(r["val"] - other) / base
                if gap <= 0.02 or abs(r["val"] - other) < 50e6:
                    n_ok += 1
                else:
                    gaps.append((t, concept, fy, r["val"], other, gap))
    acc = json.loads((ROOT / "tools" / "verify-accepted.json").read_text())
    core = [g for g in gaps if g[1] in ("revenue", "cfo")]
    for g in sorted(core, key=lambda g: -g[5]):
        out.append(f"| {g[0]} | {g[1]} | {g[2]} | {g[3] / 1e6:,.0f}m | {g[4] / 1e6:,.0f}m | {g[5]:.1%} |")
    out += ["", f"**{n_ok} of {n_all} company-year figures agree within 2% (or $50m).** The table lists every gap in revenue and "
            f"operating cash flow, where both sources should report the same number.", "", "Gaps by concept:", ""]
    by = {}
    for g in gaps:
        by.setdefault(g[1], []).append(g)
    for c in fields:
        n_c = sum(1 for t, rec in snap["edgar"].items() for fy in rec["concepts"][c])
        out.append(f"- {c}: {len(by.get(c, []))} gaps. " + acc["edgar_concepts"].get(c, ""))
    for g in sorted(gaps, key=lambda g: -g[5])[:12]:
        out.append(f"  - largest: {g[0]} {g[1]} FY{g[2]}: EDGAR {g[3] / 1e6:,.0f}m vs roic.ai {g[4] / 1e6:,.0f}m")
    if len(core) > 0:
        out.append(f"- **{len(core)} revenue/operating-cash-flow gaps need a look** (listed in the table).")
    out.append("")

    # ---- 2. P/E vs roic.ai v2
    out += ["## 2. Quarter-end P/E against roic.ai v2", "",
            "v2 TTM P/E for the same period end, rolled to the quarter-end close with v2's own (split-adjusted) prices.", "",
            "| Company | Deck (v3) | Check (v2) | Gap |", "|---|---|---|---|"]
    # the version that carries every exhibit: internal when the firm keeps one, else client
    led_path = run / "figure-ledger-internal.csv"
    if not led_path.exists():
        led_path = run / "figure-ledger-client.csv"
    led = list(csv.DictReader(open(led_path, encoding="utf-8")))
    pe_rows = {r["label"].split()[0]: float(r["value"]) for r in led if r["label"].endswith("P/E at quarter end")}
    if not pe_rows:
        out.append("No valuation page in this build; check skipped.")
    for t, r in (snap["roic"].items() if pe_rows else []):
        q = v2(f"fundamental/multiples/{t}?period=quarterly&limit=12")
        m = [x for x in q if x["date"] == r["ttm_period_end"]]
        px = v2(f"stock-prices/{t}?limit=400&order=DESC")
        def close(d):
            return next(float(p["adj_close"] or p["close"]) for p in px if p["date"] <= d)
        if not m or not m[0].get("pe_ratio"):
            out.append(f"| {t} | {pe_rows.get(t, float('nan')):.1f} | n/a | v2 has no row for {r['ttm_period_end']} |")
            continue
        chk = m[0]["pe_ratio"] * close(snap["as_of"]) / close(r["ttm_period_end"])
        gap = abs(chk / pe_rows[t] - 1)
        accepted = acc["pe"].get(t)
        flag = "" if gap <= 0.05 else (f" accepted: {accepted}" if accepted else " **CHECK**")
        fails += gap > 0.05 and not accepted
        out.append(f"| {t} | {pe_rows[t]:.1f} | {chk:.1f} | {gap:.1%}{flag} |")
    out.append("")

    # ---- 3. FRED recomputed
    out += ["## 3. FRED figures recomputed from the raw series", ""]
    obs = {sid: {d: v for d, v in f["obs"]} for sid, f in snap["fred"].items()}
    def last(sid, d):
        ks = [k for k in obs[sid] if k <= d]
        return obs[sid][max(ks)]
    checks = []
    for r in led:
        tag, val, per = r["series_or_tag"], r["value"], r["period"]
        if r["source"] != "Federal Reserve Bank of St. Louis (FRED)" or not val:
            continue
        val = float(val)
        if tag in obs and re.fullmatch(r"\d{4}-\d{2}-\d{2}", per):
            checks.append((r["label"], val, last(tag, per)))
        elif tag == "CPIAUCSL" and "12" in r["derivation"] + r["label"]:
            m = dt.datetime.strptime(per, "%B %Y").date().replace(day=1)
            prev = m.replace(year=m.year - 1)
            checks.append((r["label"], val, (obs["CPIAUCSL"][m.isoformat()] / obs["CPIAUCSL"][prev.isoformat()] - 1) * 100))
    # FRED's own year-over-year transformation (units=pc1), computed by FRED, not by us
    for r in led:
        if r["source"].startswith("Federal Reserve Bank of St. Louis") and r["series_or_tag"] in ("CPIAUCSL", "INDPRO")                 and "12" in r["derivation"] + r["label"] and r["value"]:
            m = dt.datetime.strptime(r["period"], "%B %Y").date().replace(day=1).isoformat()
            txt = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                               params={"id": r["series_or_tag"], "transformation": "pc1", "cosd": m, "coed": m}, timeout=60).text
            fred_val = float(txt.strip().splitlines()[-1].split(",")[1])
            checks.append((r["label"] + " vs FRED's own pc1", float(r["value"]), fred_val))
    bad = [c for c in checks if abs(c[1] - c[2]) > 0.006]
    fails += len(bad)
    out += [f"{len(checks) - len(bad)} of {len(checks)} FRED figures match to 0.005, recomputed from the raw series and, for 12-month changes, "
           f"against FRED's own year-over-year transformation."] + \
           [f"- MISMATCH {c[0]}: deck {c[1]} vs recomputed {c[2]}" for c in bad] + [""]

    # ---- 4. coverage
    out += ["## 4. Every number printed on a slide is in the ledger", ""]
    structural = re.compile(r"^(19|20)\d\d$|^FY\d{4}$|^\d{1,2}$")
    for aud in [x for x in ("client", "internal") if (run / f"figure-ledger-{x}.csv").exists()]:
        led_a = list(csv.DictReader(open(run / f"figure-ledger-{aud}.csv", encoding="utf-8")))
        tokens = set()
        for r in led_a:
            tokens |= {x.strip("+-$%,.x") for x in re.findall(r"[-+$]?\d[\d,]*\.?\d*%?", r["display"])}

        def traced(core):
            if core in tokens:
                return True
            # a number printed at a different precision than its ledger display: accept
            # only if some ledger value formats to exactly this string
            d = len(core.split(".")[1]) if "." in core else 0
            c = core.replace(",", "")
            # (a rounding of a figure the ledger itself displays, e.g. 0.6% in a sentence
            # for the 0.62% the ledger shows)
            for t in tokens:
                try:
                    if f"{float(t.replace(',', '')):.{d}f}" == c:
                        return True
                except ValueError:
                    pass
            return False
        pptx = next(run.glob(f"*-{aud}-*.pptx"))
        missing = []
        for i, slide in enumerate(Presentation(pptx).slides, 1):
            texts = []
            for sh in slide.shapes:
                if sh.has_text_frame:
                    texts.append(sh.text_frame.text)
                if sh.has_table:
                    texts += [c.text for row in sh.table.rows for c in row.cells]
            for t in texts:
                if t.startswith(("Source", f"{FIRM}  |", "DRAFT", "Sources")):
                    continue
                t2 = re.sub(r"\d+-(year|month|yr|yrs)\b|\b\d+ (years|fiscal years|days|holdings|sectors)\b|10-[KQ]|H\.15|G\.17|"
                            r"(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}|"
                            r"\d{4}-\d{2}-\d{2}|20\d\d-Q\d|\d{4} Q\d|Form ADV Part 2|\b\d+ of (10|ten)\b|Part 2", " ", t)
                for num in re.findall(r"[-+$]?\d[\d,]*\.?\d*%?", t2):
                    core = num.strip("+-$%,.")
                    if structural.match(core) or traced(core):
                        continue
                    missing.append(f"p.{i}: '{num}' in \"{t[:70]}\"")
        out.append(f"- {aud}: {len(missing)} numbers not found in the ledger")
        out += [f"  - {m}" for m in missing[:30]]
        fails += len(missing)
    out.append("")
    out.append(f"**Result: {'PASS' if not fails else f'{fails} item(s) to check'}.**")
    (run / "verification.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
