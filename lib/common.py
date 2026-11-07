"""Shared plumbing: paths, polite HTTP with a raw-response cache, the figure ledger."""
import csv
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
RUNS = ROOT / "runs"




def secret(name):
    """An API key from the environment or, failing that, from a .env file in the project
    folder (one NAME=value per line). The .env file keeps the keys with the project and works
    where environment variables are not visible (sandboxed apps). Never commit, share or
    package .env; the Lesson 3 download ships .env.example instead."""
    v = os.environ.get(name)
    if v:
        return v.strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, val = line.partition("=")
            if k.strip() == name and val.strip():
                return val.strip().strip('"').strip("'")
    return None


# SEC asks every automated client to declare who it is: the firm's name and a monitored
# address, in SEC_USER_AGENT (environment or .env). There is deliberately no default.
SEC_USER_AGENT = secret("SEC_USER_AGENT") or ""

_last_call = {}


def _gate(host: str, min_gap: float):
    """Serialize calls per host: FRED 429s on bursts, SEC caps at 10 requests a second."""
    wait = _last_call.get(host, 0) + min_gap - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.time()


def http_get(url: str, *, headers=None, params=None, host_gap=0.25, cache_key=None,
             max_age_hours=None, binary=False, retries=4):
    """GET with retries. If cache_key is given, the raw body is stored under cache/ and
    reused while younger than max_age_hours (None = reuse forever)."""
    path = None
    if cache_key:
        path = CACHE / cache_key
        if path.exists():
            age_h = (time.time() - path.stat().st_mtime) / 3600
            if max_age_hours is None or age_h < max_age_hours:
                return path.read_bytes() if binary else path.read_text(encoding="utf-8")
    host = url.split("/")[2]
    last = None
    for attempt in range(retries):
        _gate(host, host_gap)
        try:
            r = requests.get(url, headers=headers, params=params, timeout=60)
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(r.content)
            return r.content if binary else r.text
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(3 * (attempt + 1))
            continue
        raise RuntimeError(f"GET {url} -> HTTP {r.status_code}: {r.text[:200]}")
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")


def fetch_stamp(path: Path) -> str:
    """When a cached raw file was retrieved (its mtime), as an ISO timestamp."""
    return dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


class Ledger:
    """Every number that appears on a slide is written here with where it came from.

    One row per displayed figure: slide, label, the value as displayed, the raw value,
    the source system, the exact series/tag/endpoint, the observation date or fiscal
    period, a URL a reviewer can open, and how the number was derived."""

    FIELDS = ["slide", "label", "display", "value", "source", "series_or_tag",
              "period", "url", "derivation"]

    def __init__(self):
        self.rows = []

    def add(self, slide, label, display, value, source, series_or_tag, period, url, derivation=""):
        self.rows.append(dict(slide=slide, label=label, display=display,
                              value=value if value is None else round(float(value), 6),
                              source=source, series_or_tag=series_or_tag, period=period,
                              url=url, derivation=derivation))
        return display

    def write(self, path: Path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.FIELDS)
            w.writeheader()
            w.writerows(self.rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=str)
