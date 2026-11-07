"""roic.ai v3: prices and standardized valuation multiples.

- Identifiers are EXCHANGE:SYMBOL (NASDAQ:COST). A bare ticker is rejected with HTTP 400.
- The key goes in an 'Authorization: Bearer' header, never in a URL that could be logged.
- Terms of use: the firm shows roic.ai figures in the client deck because the data are not
  resold to clients (Larkspur Vale's decision for this example). Read roic.ai's current
  terms of use yourself before doing the same; to keep a page out of the client version,
  set client_safe to false in config/exhibits.json.
- Fundamentals can lag the filings by a quarter or more (Costco's FY2026 10-K was filed in
  October 2026; the v3 TTM rows still ended in May on 2026-11-06). Every figure shown
  carries its own period-end date."""
import json
import os

from .common import http_get, secret

BASE = "https://api.roic.ai/v3.0.0"


def _key():
    k = secret("ROIC_API_KEY")
    if not k:
        raise RuntimeError("No roic.ai key: set ROIC_API_KEY, or copy .env.example to .env and paste the key there "
                           "(roic.ai > Account > API).")
    return k


def _get(path, params, cache_key):
    text = http_get(f"{BASE}/{path}", headers={"Authorization": f"Bearer {_key()}"},
                    params=params, host_gap=0.3, cache_key=cache_key)
    d = json.loads(text)
    if isinstance(d, dict) and "error" in d:
        raise RuntimeError(f"roic.ai {path}: {d['error']}")
    return d


def endpoint_url(path, params=None):
    q = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    return f"{BASE}/{path}" + (f"?{q}" if q else "")


def prices(symbol, fetch_date, limit=600):
    """Daily closes, newest first, about two years. Unadjusted for splits per roic's own
    convention at the time of the call; only same-day ratios are used downstream."""
    d = _get(f"stock-prices/{symbol}", {"limit": limit, "order": "desc"},
             f"roic/{fetch_date}/prices-{symbol.replace(':', '_')}.json")
    return d["data"]


def close_on_or_before(symbol, when, fetch_date):
    for row in prices(symbol, fetch_date):
        if row["date"] <= when.isoformat():
            return row["date"], float(row["close"])
    raise RuntimeError(f"roic.ai {symbol}: no close on or before {when}")


def multiples(symbol, period_type, limit, fetch_date):
    params = {"period_type": period_type, "limit": limit, "order": "desc"}
    return _get(f"fundamental/multiples/{symbol}", params,
                f"roic/{fetch_date}/multiples-{period_type}-{symbol.replace(':', '_')}.json")["data"]


def per_share(symbol, period_type, limit, fetch_date):
    params = {"period_type": period_type, "limit": limit, "order": "desc"}
    return _get(f"fundamental/per-share/{symbol}", params,
                f"roic/{fetch_date}/pershare-{period_type}-{symbol.replace(':', '_')}.json")["data"]


def profitability(symbol, period_type, limit, fetch_date):
    params = {"period_type": period_type, "limit": limit, "order": "desc"}
    return _get(f"fundamental/ratios/profitability/{symbol}", params,
                f"roic/{fetch_date}/profit-{period_type}-{symbol.replace(':', '_')}.json")["data"]


def enterprise_value(symbol, period_type, limit, fetch_date):
    params = {"period_type": period_type, "limit": limit, "order": "desc"}
    return _get(f"fundamental/enterprise-value/{symbol}", params,
                f"roic/{fetch_date}/ev-{period_type}-{symbol.replace(':', '_')}.json")["data"]


def splits(symbol, fetch_date):
    """Split history. factor = new shares per old share (25 for Booking's 2026 25-for-1)."""
    d = _get("stock-splits", {"identifier": symbol, "order": "desc", "limit": 50},
             f"roic/{fetch_date}/splits-{symbol.replace(':', '_')}.json")
    return d["data"]


def split_factor_between(symbol, d0, d1, fetch_date):
    """Product of split factors executed after d0 and on or before d1 (ISO dates)."""
    f = 1.0
    for s in splits(symbol, fetch_date):
        if d0 < s["execution_date"] <= d1:
            f *= float(s["factor"])
    return f
