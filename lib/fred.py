"""FRED: keyless CSV download of a series' full history, cut at the period's as-of date.

Only series FRED labels "Public Domain: Citation Requested" are used in the client deck
(Treasury yields from the Federal Reserve's H.15, BLS and Fed statistics). Third-party
copyrighted series (ICE BofA indices, S&P indices) need the owner's written permission
for client materials and are deliberately absent.

Point-in-time caveat: FRED serves the latest revised values. A March run repeated in June
can show slightly different CPI or payroll history. ALFRED keeps vintages if a firm needs
exact reproduction."""
import datetime as dt
import io

import pandas as pd

from .common import CACHE, http_get, fetch_stamp

SERIES = {
    # id: (title, producer, frequency)
    "DGS1MO": ("1-month Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS3MO": ("3-month Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS6MO": ("6-month Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS1": ("1-year Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS2": ("2-year Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS3": ("3-year Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS5": ("5-year Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS7": ("7-year Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS10": ("10-year Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS20": ("20-year Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DGS30": ("30-year Treasury constant maturity", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "DFII10": ("10-year TIPS yield (real)", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "T10YIE": ("10-year breakeven inflation", "Federal Reserve Bank of St. Louis", "daily"),
    "DFF": ("Effective federal funds rate", "Board of Governors of the Federal Reserve System (H.15)", "daily"),
    "CPIAUCSL": ("CPI for all urban consumers, all items, SA", "U.S. Bureau of Labor Statistics", "monthly"),
    "UNRATE": ("Unemployment rate", "U.S. Bureau of Labor Statistics", "monthly"),
    "PAYEMS": ("All employees, total nonfarm", "U.S. Bureau of Labor Statistics", "monthly"),
    "INDPRO": ("Industrial production index", "Board of Governors of the Federal Reserve System (G.17)", "monthly"),
}


def series_url(sid):
    return f"https://fred.stlouisfed.org/series/{sid}"


def get(sid: str, as_of: dt.date, fetch_date: str) -> pd.Series:
    """Full history of one series up to and including as_of. The raw CSV is cached per
    fetch day so a rebuild the same day does not hit FRED again."""
    key = f"fred/{fetch_date}/{sid}.csv"
    text = http_get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": sid},
                    host_gap=0.7, cache_key=key)
    df = pd.read_csv(io.StringIO(text))
    df.columns = ["date", "value"]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.dropna().set_index("date")["value"]
    s = s[s.index <= pd.Timestamp(as_of)]
    s.attrs.update(sid=sid, title=SERIES[sid][0], producer=SERIES[sid][1],
                   retrieved=fetch_stamp(CACHE / key), url=series_url(sid))
    if s.empty:
        raise RuntimeError(f"FRED {sid}: no observations on or before {as_of}")
    return s


def last_on_or_before(s: pd.Series, when) -> tuple:
    """(date, value) of the last observation on or before `when`."""
    sub = s[s.index <= pd.Timestamp(when)]
    if sub.empty:
        raise RuntimeError(f"FRED {s.attrs.get('sid')}: nothing on or before {when}")
    return sub.index[-1].date(), float(sub.iloc[-1])
