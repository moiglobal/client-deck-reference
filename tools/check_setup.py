"""Check that this computer can build the client deck. Lesson 1, Step 4.

    python tools/check_setup.py

Checks Python and its libraries, LibreOffice and Poppler, the SEC User-Agent and the
roic.ai key (present or not; the key itself is never printed), and one small request to
each data source. Writes setup-check.md next to build.py and prints the same lines.
Exit code 0 only if everything the build needs is in place."""
import datetime as dt
import importlib
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

rows, failed = [], 0


def check(name, ok, detail, fix="", warn=False):
    """warn=True: report a missing item without failing (needed later, not now)."""
    global failed
    failed += not ok and not warn
    rows.append(f"| {name} | {'OK' if ok else ('LATER' if warn else 'FAIL')} | {detail} | {'' if ok else fix} |")


check("Python 3.10 or later", sys.version_info >= (3, 10), platform.python_version(),
      "Install Python 3.12 from python.org (or ask Claude to).")
for mod, pip in [("pptx", "python-pptx"), ("matplotlib", "matplotlib"), ("pandas", "pandas"),
                 ("requests", "requests"), ("lxml", "lxml"), ("PIL", "Pillow")]:
    try:
        m = importlib.import_module(mod)
        check(f"Python library {pip}", True, getattr(m, "__version__", "installed"))
    except ImportError:
        check(f"Python library {pip}", False, "missing", f"pip install {pip}")

soffice = (shutil.which("soffice") or shutil.which("libreoffice")
           or next((p for p in [r"C:\Program Files\LibreOffice\program\soffice.exe",
                                "/Applications/LibreOffice.app/Contents/MacOS/soffice"] if Path(p).exists()), None))
check("LibreOffice (PDF and page images)", bool(soffice), soffice or "not found",
      "Install LibreOffice from libreoffice.org; without it, run build.py with --no-render.")
check("Poppler pdftoppm (page images)", bool(shutil.which("pdftoppm")), shutil.which("pdftoppm") or "not found",
      "Install Poppler (Windows: winget install oschwartz10612.Poppler; Mac: brew install poppler).")

from lib.common import SEC_USER_AGENT, secret  # noqa: E402

check("SEC_USER_AGENT (your firm and an email)", "@" in SEC_USER_AGENT,
      "set" if "@" in SEC_USER_AGENT else "not set", "Copy .env.example to .env and fill in SEC_USER_AGENT.")
key = secret("ROIC_API_KEY")
check("roic.ai key", bool(key), "found (not shown)" if key else "not found",
      "Needed for the valuation pages (Lesson 2): paste the key from roic.ai > Account > API into .env.", warn=True)

try:
    import requests
except ImportError:
    requests = None


def reach(name, url, headers=None, fix="", any_status=False):
    if requests is None:
        check(name, False, "requests library missing", "pip install requests")
        return
    try:
        r = requests.get(url, headers=headers or {}, timeout=30)
        blocked = r.headers.get("X-Proxy-Error", "")
        ok = r.status_code == 200 or (any_status and r.status_code < 500 and not blocked)
        detail = f"HTTP {r.status_code}" + (f", {blocked}" if blocked else "")
    except Exception as e:  # noqa: BLE001
        ok, detail = False, type(e).__name__ + ": " + str(e).split("\n")[0][:120]
    check(name, ok, detail, fix)


NET_FIX = ("Your network is blocking this site: ask whoever runs the firm's firewall. "
           "(In a sandboxed Claude app, allow the domain in its network settings.)")
reach("Network: SEC EDGAR (data.sec.gov)", "https://data.sec.gov/submissions/CIK0000909832.json",
      {"User-Agent": SEC_USER_AGENT or "client-deck setup check"}, NET_FIX)
reach("Network: FRED (fred.stlouisfed.org)",
      "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2026-01-02&coed=2026-01-09", None, NET_FIX)
if key:
    reach("Network: roic.ai (api.roic.ai)", "https://api.roic.ai/v3.0.0/stock-prices/NASDAQ:COST?limit=1",
          {"Authorization": f"Bearer {key}"}, NET_FIX + " If HTTP 401: the key is wrong or expired.")
else:
    # no key yet: any answer from the server (even "unauthorized") proves the site is reachable
    reach("Network: roic.ai (api.roic.ai)", "https://api.roic.ai/v3.0.0/stock-prices/NASDAQ:COST?limit=1", None,
          NET_FIX, any_status=True)

out = [f"# Set-up check, {dt.datetime.now():%Y-%m-%d %H:%M}", "",
       f"{platform.system()} {platform.release()}, Python {platform.python_version()}, folder {ROOT}", "",
       "| Check | Result | Detail | How to fix |", "|---|---|---|---|"] + rows + ["",
       "**Ready to build.**" if not failed else f"**{failed} check(s) failed.** Fix them, then run this again."]
(ROOT / "setup-check.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n".join(out))
sys.exit(1 if failed else 0)
