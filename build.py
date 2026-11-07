"""Build the quarterly client review for one period.

    python build.py --period 2026-Q3
    python build.py --period 2026-Q3 --signoff "Jane Doe, CCO, 2026-10-07"

Writes runs/<period>/: the client deck (.pptx and .pdf; plus an internal version when any
exhibit in config/exhibits.json is marked client_safe=false), page images for
review, the figure ledger (every number on every slide with its source), the review
checklist, the data snapshot, and a manifest with file hashes. Without --signoff every
page carries a DRAFT watermark. Nothing is ever sent anywhere."""
import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lib import data
from lib.common import RUNS, ROOT, Ledger, load_json, save_json, sha256
from lib.deck import Deck
from lib.exhibits import Exhibits
from lib.style import BRAND

SOFFICE = (shutil.which("soffice") or shutil.which("libreoffice") or next(
    (p for p in [r"C:\Program Files\LibreOffice\program\soffice.exe", "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
     if Path(p).exists()), "soffice"))
PDFTOPPM = shutil.which("pdftoppm") or "pdftoppm"
# Words that can turn a description into a prediction or a promise. Flagged for the
# reviewer, never auto-edited.
RISKY = re.compile(r"\b(will|expect\w*|forecast\w*|should|guarantee\w*|outperform\w*|beat|target|recommend\w*|"
                   r"return(s)? of|track record|best|safe)\b", re.I)


def render(pptx, outdir):
    """PPTX -> PDF (LibreOffice) -> one PNG per page (Poppler), for the visual check."""
    prof = Path(tempfile.mkdtemp(prefix="lo-"))
    subprocess.run([SOFFICE, f"-env:UserInstallation=file:///{prof.as_posix()}", "--headless",
                    "--convert-to", "pdf", "--outdir", str(outdir), str(pptx)],
                   check=True, capture_output=True, timeout=240)
    pdf = outdir / (pptx.stem + ".pdf")
    png_dir = outdir / f"pages-{pptx.stem}"
    png_dir.mkdir(exist_ok=True)
    for old in png_dir.glob("*.png"):
        old.unlink()
    subprocess.run([PDFTOPPM, "-r", "110", "-png", str(pdf), str(png_dir / "page")], check=True, timeout=240)
    shutil.rmtree(prof, ignore_errors=True)
    return pdf, sorted(png_dir.glob("*.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", required=True, help="e.g. 2026-Q3")
    ap.add_argument("--audience", default="both", choices=["both", "client", "internal"])
    ap.add_argument("--signoff", help="Name, role and date of the compliance approval. Omit for a DRAFT.")
    ap.add_argument("--refresh", action="store_true", help="Re-download data even if this period has a snapshot")
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()

    run = RUNS / a.period
    run.mkdir(parents=True, exist_ok=True)
    cfg = load_json(ROOT / "config" / "exhibits.json")["exhibits"]
    ROIC_EXHIBITS = {"valuation", "valuation_table"}
    need_roic = any(e["enabled"] and e["id"] in ROIC_EXHIBITS for e in cfg)
    snap_path = run / "snapshot.json"
    if snap_path.exists() and not a.refresh:
        snap = load_json(snap_path)
        print(f"Using archived snapshot {snap_path} (fetched {snap['fetch_date']}); --refresh to re-download")
        # The firm's own file (weights, featured holding, analyst notes) is always read
        # fresh; only downloaded data come from the archive.
        port = load_json(ROOT / "config" / f"portfolio-{a.period}.json")
        if {h["ticker"] for h in port["holdings"]} != {h["ticker"] for h in snap["portfolio"]["holdings"]}:
            sys.exit("Holdings changed since the snapshot was taken: rebuild with --refresh.")
        snap["portfolio"] = port
        if need_roic and not snap.get("roic"):
            sys.exit("This period's snapshot has no roic.ai data (it was built without the valuation pages): rebuild with --refresh.")
    else:
        snap = data.collect(a.period, dt.date.today().isoformat(), need_roic=need_roic)
        save_json(snap, snap_path)

    prev_path = RUNS / data.prev_period(a.period) / "summary.json"
    prev = load_json(prev_path) if prev_path.exists() else None
    if prev:
        prev["label_short"] = prev["period"].replace("-", " ")

    internal_only = [e["id"] for e in cfg if e["enabled"] and not e["client_safe"]]
    if a.audience == "both":
        # An internal version differs from the client version only by the internal-only
        # exhibits; when there are none it would be an identical copy, so skip it.
        audiences = ["client", "internal"] if internal_only else ["client"]
    else:
        audiences = [a.audience]
    status = "FINAL" if a.signoff else "DRAFT"
    outputs, checklist_bits = [], {}
    summary = None
    for aud in audiences:
        tmp = Path(tempfile.mkdtemp(prefix="charts-"))
        deck = Deck(snap["label"], draft=not a.signoff, audience=aud)
        led = Ledger()
        ex = Exhibits(snap, deck, led, tmp, prev)
        titles = []
        for e in cfg:
            if not e["enabled"] or (aud == "client" and not e["client_safe"]):
                continue
            n_before = len(deck.prs.slides)
            fn = getattr(ex, e["id"])
            if e["id"] == "methodology":
                fn(aud)
            elif e["id"] == "disclosures":
                fn(a.signoff)
            else:
                fn()
            for sl in list(deck.prs.slides)[n_before:]:
                texts = [sh.text_frame.text for sh in sl.shapes if sh.has_text_frame]
                titles.append((len(deck.prs.slides), e["id"], texts))
        slug = re.sub(r"[^a-z0-9]+", "-", BRAND.get("firm_short", BRAND["firm_name"]).lower()).strip("-")
        name = f"{slug}-review-{a.period}-{aud}-{status}"
        pptx = run / f"{name}.pptx"
        deck.save(pptx)
        led.write(run / f"figure-ledger-{aud}.csv")
        for t in deck.overflow:
            snap["warnings"].append(f"Title still too long at 20pt ({aud}): {t}")
        outputs.append(pptx)
        checklist_bits[aud] = (titles, len(led.rows))
        summary = ex.summary
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"Wrote {pptx.name}: {len(deck.prs.slides)} pages, {len(led.rows)} ledger rows")

    save_json(dict(period=a.period, label=snap["label"], as_of=snap["as_of"], summary=summary), run / "summary.json")

    # ---- review checklist
    lines = [f"# Review checklist: {snap['label']} ({a.period})", "",
             f"Status: **{status}**" + (f", approved by {a.signoff}" if a.signoff else
                                       ". Every page is watermarked. Do not distribute until compliance signs off and the deck is rebuilt with --signoff."),
             f"Data as of {snap['as_of']}; downloaded {snap['fetch_date']}.", "",
             "## Before anything leaves the firm", "",
             "- [ ] Chief Compliance Officer (or counsel) has reviewed the client version in full, including the disclosures page.",
             "- [ ] The disclosure placeholder on the last page has been replaced with the firm's approved language.",
             "- [ ] No page shows or implies performance, returns, a track record, a testimonial or a recommendation.",
             "- [ ] Words flagged below have been read in context and accepted or reworded.",
             "- [ ] The firm has read the terms of use of every data provider shown (roic.ai, FRED, SEC EDGAR) and is content to show that data to clients.",
             "- [ ] The approved PDF and this run folder are archived under the firm's books-and-records policy.", "",
             "## Data warnings from this run", ""]
    lines += [f"- {w}" for w in snap["warnings"]] or ["- none"]
    for aud, (titles, nled) in checklist_bits.items():
        lines += ["", f"## {aud.title()} version: {len(titles)} pages, {nled} figures in the ledger", ""]
        for n, eid, texts in titles:
            flagged = sorted({m.group(0).lower() for t in texts for m in RISKY.finditer(t)})
            head = next((t for t in texts if t.strip()), "") if eid == "cover" else (texts[1] if len(texts) > 1 else "")
            lines.append(f"- p.{n} `{eid}`: {head.strip()[:110]}" + (f"  **check wording: {', '.join(flagged)}**" if flagged else ""))
    (run / "review-checklist.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- render and manifest
    rendered = []
    if not a.no_render:
        for pptx in outputs:
            pdf, pngs = render(pptx, run)
            rendered.append(pdf)
            print(f"Rendered {pdf.name}: {len(pngs)} page images in {pngs[0].parent.name}/")
    files = sorted(p for p in run.iterdir() if p.is_file() and p.name != "manifest.json")
    save_json(dict(period=a.period, built=dt.datetime.now().isoformat(timespec="seconds"), status=status,
                   signoff=a.signoff, python=sys.version.split()[0],
                   files={p.name: sha256(p) for p in files}), run / "manifest.json")
    print(f"Done. Open {run / 'review-checklist.md'} first.")


if __name__ == "__main__":
    main()
