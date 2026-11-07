"""SEC EDGAR: annual figures from each company's XBRL 'companyfacts', point in time.

Rules this module enforces, each one learned from a real filing:
- Only 10-K facts filed on or before the as-of date are used, so a deck dated
  September 30 never shows a number the company had not yet published.
- Flows (revenue, cash flow lines) must cover 340-380 days, which keeps quarterly and
  year-to-date facts out and admits 52/53-week fiscal years.
- Each fiscal year takes the value from the most recent 10-K that reports it, i.e. the
  company's latest restated figure for that year.
- Companies change tags over time (Revenues -> RevenueFromContractWithCustomer...). Each
  concept has an ordered list of tags; each year uses the first tag that has a value,
  and a tag switch is checked against an overlap year so a definitional break is caught.
- Share counts are chain-linked using ratios taken from inside a single filing, so
  stock splits (Alphabet 20-for-1 in 2022, Booking in 2026) never appear as a collapse
  in shares outstanding."""
import datetime as dt
import json

import pandas as pd

from .common import CACHE, SEC_USER_AGENT, http_get, fetch_stamp

HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}

CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "operating_income": ["OperatingIncomeLoss"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dividends": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"],
    "acquisitions": ["PaymentsToAcquireBusinessesNetOfCashAcquired", "PaymentsToAcquireBusinessesGross"],
    "diluted_shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
}
# Concepts where "no fact at all in a year" genuinely means zero (AutoZone pays no
# dividend; Union Pacific made no acquisitions). Every other gap is an error.
ZERO_IF_ABSENT = {"dividends", "acquisitions", "buybacks"}
FLOW = {"revenue", "operating_income", "cfo", "capex", "dividends", "buybacks",
        "acquisitions", "diluted_shares"}


def facts(cik: int, fetch_date: str) -> dict:
    key = f"edgar/{fetch_date}/CIK{cik:010d}.json"
    text = http_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                    headers=HEADERS, host_gap=0.15, cache_key=key)
    d = json.loads(text)
    d["_retrieved"] = fetch_stamp(CACHE / key)
    return d


def submissions(cik: int, fetch_date: str) -> dict:
    key = f"edgar/{fetch_date}/submissions-CIK{cik:010d}.json"
    text = http_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                    headers=HEADERS, host_gap=0.15, cache_key=key)
    return json.loads(text)


def filing_url(cik: int, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/"


def _rows(d, tag, as_of, flow):
    g = d["facts"].get("us-gaap", {}).get(tag)
    if not g:
        return []
    unit = "shares" if "shares" in g["units"] else ("USD" if "USD" in g["units"] else next(iter(g["units"])))
    out = []
    for x in g["units"][unit]:
        if x.get("form") not in ("10-K", "10-K/A", "10-KT"):
            continue
        if x["filed"] > as_of.isoformat():
            continue
        end = dt.date.fromisoformat(x["end"])
        if flow:
            if "start" not in x:
                continue
            days = (end - dt.date.fromisoformat(x["start"])).days
            if not 340 <= days <= 380:
                continue
        elif "start" in x:
            continue
        out.append(dict(end=end, val=float(x["val"]), accn=x["accn"], filed=x["filed"],
                        form=x["form"], tag=tag, unit=unit))
    return out


def fiscal_year_ends(d, as_of):
    """Fiscal year-end dates, read from the revenue flows of 10-Ks filed by as_of."""
    ends = set()
    for tag in CONCEPTS["revenue"] + ["OperatingIncomeLoss", "NetCashProvidedByUsedInOperatingActivities"]:
        ends |= {r["end"] for r in _rows(d, tag, as_of, True)}
    return sorted(ends)


def annual(d, concept, as_of, fy_ends):
    """One row per fiscal year end: value, tag, accession, filed date. Latest filing wins."""
    flow = concept in FLOW
    by_end = {}
    switch_checks = []
    # The most recent filing wins across all tags (a later 10-K that restates a year for a
    # divestiture, as Danaher's did for Envista, may use a different tag than the
    # original). Within one filing, tag priority decides (Mastercard tags both net
    # 'Revenues' and a gross figure in the same 10-K).
    for prio, tag in enumerate(CONCEPTS[concept]):
        for r in _rows(d, tag, as_of, flow):
            r["prio"] = prio
            k = r["end"]
            cur = by_end.get(k)
            if cur is None:
                by_end[k] = r
                continue
            if cur["tag"] != r["tag"] and cur["val"] and r["filed"] == cur["filed"]:
                switch_checks.append((k, cur["tag"], r["tag"], r["val"] / cur["val"]))
            if (r["filed"], -r["prio"]) > (cur["filed"], -cur["prio"]):
                by_end[k] = r
    out = []
    for e in fy_ends:
        # instants and 52/53-week years can end a few days apart across tags
        match = [v for k, v in by_end.items() if abs((k - e).days) <= 7]
        if match:
            out.append(dict(match[0], fy_end=e))
        elif concept in ZERO_IF_ABSENT:
            out.append(dict(end=e, fy_end=e, val=0.0, accn=None, filed=None, form=None,
                            tag="(not reported: treated as zero)", unit="USD"))
    df = pd.DataFrame(out)
    if not df.empty:
        df["fy"] = df["fy_end"].apply(lambda x: x.year)
        df = df.drop_duplicates("fy", keep="last").set_index("fy").sort_index()
    df.attrs["switch_checks"] = switch_checks
    return df


# The companyfacts API carries standard-taxonomy facts only. When a company reports a
# line under its own extension element, read it from the filing's XBRL instance instead.
# Alphabet files "Acquisitions, net of cash acquired, and purchases of intangible and
# other assets" as goog:AcquisitionsNetOfCash... (found 2026-11-06).
EXTENSIONS = {
    1652044: {"acquisitions": r"^Acquisitions\w*NetOfCashAcquired\w*$"},
}


def ten_k_filings(cik, fetch_date, as_of):
    s = submissions(cik, fetch_date)
    pages = [s["filings"]["recent"]]
    # 'recent' holds the latest ~1,000 filings; a large filer's Form 4s push older 10-Ks
    # into the paged archive files.
    for f in s["filings"].get("files", []):
        pages.append(json.loads(http_get(f"https://data.sec.gov/submissions/{f['name']}",
                                         headers=HEADERS, host_gap=0.15,
                                         cache_key=f"edgar/{fetch_date}/{f['name']}")))
    out = []
    for r in pages:
        for i, form in enumerate(r["form"]):
            if form in ("10-K", "10-K/A") and r["filingDate"][i] <= as_of.isoformat():
                out.append(dict(accn=r["accessionNumber"][i], filed=r["filingDate"][i],
                                report=r["reportDate"][i], doc=r["primaryDocument"][i]))
    return out


def extension_annual(cik, concept, fetch_date, as_of, fy_ends):
    """Annual values of a company extension element, read from each 10-K's XBRL instance.
    Latest filing wins per year, as in annual(). Returns the same frame shape."""
    import re
    import xml.etree.ElementTree as ET
    pat = re.compile(EXTENSIONS[cik][concept])
    by_end = {}
    for f in ten_k_filings(cik, fetch_date, as_of):
        if f["report"] < fy_ends[0].isoformat():
            continue
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{f['accn'].replace('-', '')}/"
        idx = json.loads(http_get(base + "index.json", headers=HEADERS, host_gap=0.15,
                                  cache_key=f"edgar/xbrl/{f['accn']}-index.json"))
        names = [i["name"] for i in idx["directory"]["item"]]
        inst = [n for n in names if n.endswith("_htm.xml")] or \
               [n for n in names if n.endswith(".xml") and not re.search(r"_(cal|def|lab|pre)\.xml$|FilingSummary", n)]
        if not inst:
            continue
        xml = http_get(base + inst[0], headers=HEADERS, host_gap=0.15,
                       cache_key=f"edgar/xbrl/{f['accn']}-{inst[0]}")
        root = ET.fromstring(xml.encode("utf-8"))
        ns_x = "{http://www.xbrl.org/2003/instance}"
        ctx = {}
        for c in root.iter(ns_x + "context"):
            if c.find(f"{ns_x}entity/{ns_x}segment") is not None:
                continue  # dimensional context: a breakdown, not the total
            p = c.find(ns_x + "period")
            st, en = p.find(ns_x + "startDate"), p.find(ns_x + "endDate")
            if st is not None and en is not None:
                ctx[c.get("id")] = (dt.date.fromisoformat(st.text), dt.date.fromisoformat(en.text))
        for el in root:
            local = el.tag.split("}")[-1]
            if pat.match(local) and el.get("contextRef") in ctx and el.text:
                st, en = ctx[el.get("contextRef")]
                if 340 <= (en - st).days <= 380:
                    if en not in by_end or f["filed"] > by_end[en]["filed"]:
                        by_end[en] = dict(end=en, val=float(el.text), accn=f["accn"], filed=f["filed"],
                                          form="10-K", tag=local + " (company extension)", unit="USD")
    out = []
    for e in fy_ends:
        match = [v for k, v in by_end.items() if abs((k - e).days) <= 7]
        if match:
            out.append(dict(match[0], fy_end=e))
    df = pd.DataFrame(out)
    if not df.empty:
        df["fy"] = df["fy_end"].apply(lambda x: x.year)
        df = df.set_index("fy").sort_index()
    df.attrs["switch_checks"] = []
    return df


def chain_linked_shares(d, as_of, fy_ends):
    """Split-proof share-count index. For each pair of consecutive fiscal years, the ratio
    is taken from the latest single 10-K that reports both years, so both numbers share a
    split basis. Returns (DataFrame indexed by FY with 'ratio_to_prior', tag used)."""
    for concept in ("diluted_shares", "shares_outstanding"):
        for tag in CONCEPTS[concept]:
            rows = _rows(d, tag, as_of, concept in FLOW)
            if not rows:
                continue
            by_accn = {}
            for r in rows:
                by_accn.setdefault(r["accn"], {})
                by_accn[r["accn"]][r["end"]] = r
            filed_of = {a: max(v["filed"] for v in recs.values()) for a, recs in by_accn.items()}
            ends = [e for e in fy_ends]
            ratios = {}
            for a, b in zip(ends[:-1], ends[1:]):
                best = None
                for accn, recs in by_accn.items():
                    ra = next((v for k, v in recs.items() if abs((k - a).days) <= 7), None)
                    rb = next((v for k, v in recs.items() if abs((k - b).days) <= 7), None)
                    if ra and rb and ra["val"]:
                        if best is None or filed_of[accn] > best[0]:
                            best = (filed_of[accn], rb["val"] / ra["val"], accn, ra["val"], rb["val"])
                if best:
                    ratios[b.year] = dict(ratio_to_prior=best[1], accn=best[2],
                                          prior_val=best[3], val=best[4], filed=best[0])
            if len(ratios) >= 9:
                df = pd.DataFrame.from_dict(ratios, orient="index").sort_index()
                df.attrs["tag"] = tag
                return df
    raise RuntimeError("no share-count tag gives ten linked years")
