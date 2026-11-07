"""Make the stand-in for "last quarter's client letter" that Lesson 1's brand capture reads.

    python tools/make_sample_letter.py

A real firm skips this: it already has a letter. Larkspur Vale is fictional, so this
writes a two-page Word letter in the firm's style and converts it to PDF with LibreOffice,
the way most firms produce theirs. Output: brand/source/larkspur-vale-letter-2026-Q2.docx
and .pdf. The letter describes markets only; it shows no performance."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "brand" / "source"
NAVY, OCHRE, GREY, MUTED = "1E2A4F", "B8862E", "4B5563", "6B7280"
HEAD, BODY = "Georgia", "Calibri"
DISCLOSURE = ("Larkspur Vale Capital is a fictional firm created for a Latticework course. This material is for "
              "illustration only. It is not an offer or solicitation, and it is not investment advice. The companies "
              "shown are discussed as examples of analysis; their inclusion is not a recommendation. Data come from "
              "public sources believed reliable but not guaranteed.")


def run(p, text, font=BODY, size=11, color=GREY, bold=False, italic=False):
    r = p.add_run(text)
    r.font.name, r.font.size, r.font.bold, r.font.italic = font, Pt(size), bold, italic
    r.font.color.rgb = RGBColor.from_string(color)
    r._element.rPr.rFonts.set(qn("w:eastAsia"), font)
    return r


def rule(p, color=OCHRE, sz=12):
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    b = OxmlElement("w:bottom")
    for k, v in {"w:val": "single", "w:sz": str(sz), "w:space": "4", "w:color": color}.items():
        b.set(qn(k), v)
    bdr.append(b)
    pPr.append(bdr)


def para(doc, text, **kw):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(kw.pop("after", 8))
    p.paragraph_format.line_spacing = 1.15
    run(p, text, **kw)
    return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Inches(1))
    sec.top_margin, sec.bottom_margin = Inches(0.8), Inches(0.9)

    # letterhead: logo, then an ochre rule
    hp = sec.header.paragraphs[0]
    hp.add_run().add_picture(str(ROOT / "brand" / "logo.png"), height=Inches(0.55))
    rule(hp)
    fp = sec.footer.paragraphs[0]
    run(fp, "Larkspur Vale Capital  |  Letter to Clients, Second quarter 2026", size=8.5, color=MUTED)

    p = para(doc, "LETTER TO CLIENTS", size=9.5, color=OCHRE, bold=True, after=2)
    para(doc, "Second quarter 2026", font=HEAD, size=24, color=NAVY, after=4)
    para(doc, "July 15, 2026", size=10, color=MUTED, after=14)
    para(doc, "Dear clients,", after=10)
    body = [
        "Each quarter we write to describe what we see in markets and in the businesses we own on your behalf. "
        "This letter does the same, and, as always, it describes conditions on the dates shown rather than "
        "predicting what comes next.",
        "Interest rates moved less this quarter than in the two before it. The yield on the 10-year Treasury ended "
        "June close to where it began April, and the gap between short and long maturities narrowed. For the "
        "businesses we own, the level of rates matters less than their ability to fund themselves from their own "
        "cash flow, which nearly all of them do.",
    ]
    for t in body:
        para(doc, t)
    para(doc, "What we look for", font=HEAD, size=15, color=NAVY, after=4)
    for t in [
        "We look for companies that have grown revenue for a decade, earn high margins on the capital they "
        "employ, and return cash to their owners through dividends and the retirement of shares. We read each "
        "company's annual report and filings with the Securities and Exchange Commission before we read anyone's "
        "opinion of it.",
        "Over the next quarters we will continue to send this letter, together with our quarterly client review, "
        "which sets out the figures behind these observations holding by holding.",
    ]:
        para(doc, t)
    doc.add_page_break()
    para(doc, "How we work with you", font=HEAD, size=15, color=NAVY, after=4)
    for t in [
        "Your portfolio is managed to the objectives and constraints set out in your investment policy statement. "
        "If your circumstances have changed, please tell us, so that we can review them together.",
        "Our Form ADV Part 2, which describes our services, fees and the risks of our strategy, is available on "
        "request.",
    ]:
        para(doc, t)
    para(doc, "With best regards,", after=2)
    para(doc, "The Partners of Larkspur Vale Capital", font=HEAD, size=12, color=NAVY, italic=True, after=24)
    p = para(doc, "Important information", font=HEAD, size=11, color=NAVY, bold=True, after=3)
    rule(p, color="D9DCE3", sz=6)
    para(doc, DISCLOSURE, size=8.5, color=MUTED)

    docx_path = OUT / "larkspur-vale-letter-2026-Q2.docx"
    doc.save(docx_path)
    soffice = shutil.which("soffice") or r"C:\Program Files\LibreOffice\program\soffice.exe"
    prof = Path(tempfile.mkdtemp(prefix="lo-"))
    subprocess.run([soffice, f"-env:UserInstallation=file:///{prof.as_posix()}", "--headless", "--convert-to", "pdf",
                    "--outdir", str(OUT), str(docx_path)], check=True, capture_output=True, timeout=240)
    shutil.rmtree(prof, ignore_errors=True)
    print(f"Wrote {docx_path.name} and {docx_path.with_suffix('.pdf').name} in {OUT}")


if __name__ == "__main__":
    main()
