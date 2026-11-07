"""Read the firm's house style out of a document it already sends: Lesson 1, step 3.

    python tools/capture_brand.py brand/source/larkspur-vale-letter-2026-Q2.pdf

Measures the PDF rather than guessing from a picture of it: every font with how much text
it sets and at what size, every text color with how much text it colors, the colors of
rules and boxes, the repeated footer, the disclosure paragraph, and the logo (cropped at
300 dpi). Writes:

  brand/brand-captured.json   a draft brand.json, every value taken from the PDF
  brand/capture-report.md     the evidence behind each value, and what a person must check
  brand/logo-captured.png     the logo as it appears in the letter

It never overwrites brand/brand.json. A person compares the two, fixes what is wrong, and
copies the values across. Needs pdfplumber (pip install pdfplumber)."""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent


def hexcolor(c):
    """pdfplumber colors are tuples of 0-1 floats: gray (1), RGB (3) or CMYK (4)."""
    if c is None:
        return None
    if isinstance(c, (int, float)):
        c = (c,)
    c = tuple(float(x) for x in c)
    if len(c) == 1:
        c = (c[0],) * 3
    elif len(c) == 4:
        k = c[3]
        c = tuple((1 - x) * (1 - k) for x in c[:3])
    elif len(c) != 3:
        return None
    return "#" + "".join(f"{round(x * 255):02X}" for x in c)


def base_font(name):
    name = name.split("+")[-1]  # subset prefix ABCDEF+Georgia
    fam = re.split(r"[-,]", name)[0]
    return re.sub(r"(MT|PS|Bold|Italic|Regular)+$", "", fam) or fam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    a = ap.parse_args()
    pdf_path = Path(a.pdf)
    fonts = collections.Counter()          # (family, rounded size) -> characters
    family_chars = collections.Counter()
    color_chars = collections.Counter()
    color_by_size = collections.defaultdict(collections.Counter)
    stroke_colors = collections.Counter()
    fill_colors = collections.Counter()
    lines_by_page, bottoms, logo = [], [], None
    with pdfplumber.open(pdf_path) as pdf:
        size_in = (round(pdf.pages[0].width / 72, 2), round(pdf.pages[0].height / 72, 2))
        for pg in pdf.pages:
            for ch in pg.chars:
                if not ch["text"].strip():
                    continue
                fam, sz, col = base_font(ch["fontname"]), round(ch["size"], 1), hexcolor(ch.get("non_stroking_color"))
                fonts[(fam, sz)] += 1
                family_chars[fam] += 1
                color_chars[col] += 1
                color_by_size[sz][col] += 1
            for ob in pg.lines + pg.rects + pg.curves:
                if ob.get("stroking_color") is not None and (ob.get("stroke") or ob["object_type"] == "line"):
                    stroke_colors[hexcolor(ob["stroking_color"])] += round(ob.get("width", 0) or 1)
                if ob.get("fill") and ob.get("non_stroking_color") is not None:
                    fill_colors[hexcolor(ob["non_stroking_color"])] += round((ob.get("width", 0) or 0) * (ob.get("height", 0) or 0))
            words = pg.extract_text_lines()
            lines_by_page.append(words)
            bottoms.append(max(words, key=lambda w: w["top"])["text"] if words else "")
            # logo: the largest image that sits in the top quarter of the page and is not a
            # full-page background
            cands = [i for i in pg.images if i["top"] < pg.height * 0.25
                     and (i["x1"] - i["x0"]) < pg.width * 0.6 and (i["bottom"] - i["top"]) < pg.height * 0.3]
            if logo is None and cands:
                im = max(cands, key=lambda i: (i["x1"] - i["x0"]) * (i["bottom"] - i["top"]))
                bbox = (max(im["x0"], 0), max(im["top"], 0), min(im["x1"], pg.width), min(im["bottom"], pg.height))
                pg.crop(bbox).to_image(resolution=300).save(ROOT / "brand" / "logo-captured.png")
                logo = dict(page=pg.page_number, width_in=round((im["x1"] - im["x0"]) / 72, 2),
                            height_in=round((im["bottom"] - im["top"]) / 72, 2))

    # body font: the family that sets the most text; heading font: the family of the largest size
    body_family = family_chars.most_common(1)[0][0]
    largest = max(fonts, key=lambda k: k[1])
    heading_family = largest[0]
    body_size = max((k for k in fonts if k[0] == body_family), key=lambda k: fonts[k])[1]
    ink = color_by_size[largest[1]].most_common(1)[0][0]
    ink_secondary = color_by_size[body_size].most_common(1)[0][0]
    smallest = min(color_by_size)
    ink_muted = color_by_size[smallest].most_common(1)[0][0]
    others = [c for c, _ in color_chars.most_common() if c not in (ink, ink_secondary, ink_muted)]
    accent = others[0] if others else None
    strokes = [c for c, _ in stroke_colors.most_common()]
    rule = next((c for c in strokes if c != accent), None)

    # footer: the bottom line that repeats on every page; its part before the first | is the firm
    footer = bottoms[0] if bottoms and len(set(bottoms)) == 1 else None
    firm = footer.split("|")[0].strip() if footer and "|" in footer else None
    doc_name = footer.split("|")[1].split(",")[0].strip() if footer and "|" in footer else None

    # disclosure: the paragraph after a heading such as "Important information" or "Disclosures"
    text = "\n".join(l["text"] for page in lines_by_page for l in page)
    m = re.search(r"(?:Important information|Important disclosures?|Disclosures?)\s*\n(.+?)(?:\n\s*" +
                  (re.escape(footer) if footer else r"$") + r"|\Z)", text, re.S | re.I)
    disclosure = re.sub(r"\s*\n\s*", " ", m.group(1)).strip() if m else None

    captured = {
        "_comment": f"Captured by tools/capture_brand.py from {pdf_path.name}. Check every value against the source, "
                    "then copy what is right into brand.json. Slide size and chart palette are not in a letter; see the report.",
        "firm_name": firm, "document_name": "Quarterly Client Review",
        "fonts": {"heading": heading_family, "body": body_family},
        "colors": {"ink": ink, "ink_secondary": ink_secondary, "ink_muted": ink_muted, "rule": rule,
                   "primary": ink, "accent": accent},
        "logo": "brand/logo-captured.png" if logo else None,
        "footer_seen": footer,
        "standing_disclosure": disclosure,
    }
    (ROOT / "brand" / "brand-captured.json").write_text(json.dumps(captured, indent=2), encoding="utf-8")

    # ---- report, with a comparison against the current brand.json if there is one
    cur = json.loads((ROOT / "brand" / "brand.json").read_text(encoding="utf-8")) if (ROOT / "brand" / "brand.json").exists() else {}
    def cmp(path, val):
        node = cur
        for k in path.split("."):
            node = node.get(k) if isinstance(node, dict) else None
        if node is None:
            return "not in brand.json"
        return "same" if str(node).lower() == str(val).lower() else f"brand.json has {node}"
    R = [f"# Brand capture from `{pdf_path.name}`", "",
         f"Page size {size_in[0]} x {size_in[1]} in, {len(lines_by_page)} pages.", "",
         "## Proposed values", "", "| Field | Captured | Evidence | Against brand.json |", "|---|---|---|---|"]
    R.append(f"| firm_name | {firm} | text before the first \\| in the footer repeated on every page | {cmp('firm_name', firm)} |")
    R.append(f"| fonts.heading | {heading_family} | family of the largest text ({largest[1]} pt) | {cmp('fonts.heading', heading_family)} |")
    R.append(f"| fonts.body | {body_family} | family that sets the most characters ({family_chars[body_family]:,} of {sum(family_chars.values()):,}); body size {body_size} pt | {cmp('fonts.body', body_family)} |")
    R.append(f"| colors.ink / primary | {ink} | color of the largest text | {cmp('colors.ink', ink)} |")
    R.append(f"| colors.ink_secondary | {ink_secondary} | color of body-size text | {cmp('colors.ink_secondary', ink_secondary)} |")
    R.append(f"| colors.ink_muted | {ink_muted} | color of the smallest text ({smallest} pt: footer, date, disclosure) | {cmp('colors.ink_muted', ink_muted)} |")
    R.append(f"| colors.accent | {accent} | the remaining text color (kicker), also a rule color | {cmp('colors.accent', accent)} |")
    R.append(f"| colors.rule | {rule} | thin rule color other than the accent | {cmp('colors.rule', rule)} |")
    R.append(f"| logo | {'logo-captured.png' if logo else 'none found'} | largest image, page {logo['page'] if logo else '-'}, {logo['width_in'] if logo else '-'} x {logo['height_in'] if logo else '-'} in | use the original logo file if the firm has one: a crop is lower quality |")
    R.append(f"| standing_disclosure | {len(disclosure or '')} characters | paragraph after the Important information heading | {cmp('standing_disclosure', disclosure)} |")
    R += ["", "## Every font and size", "", "| Font | Size (pt) | Characters |", "|---|---|---|"]
    R += [f"| {f} | {s} | {n:,} |" for (f, s), n in sorted(fonts.items(), key=lambda x: -x[1])]
    R += ["", "## Every text color", "", "| Color | Characters |", "|---|---|"]
    R += [f"| {c} | {n:,} |" for c, n in color_chars.most_common()]
    R += ["", "## Rule and line colors", ""] + [f"- {c}" for c in strokes] + ["",
          "## What a person must still decide", "",
          "- **Slide size.** A letter is a portrait page; the deck is 16:9 (13.333 x 7.5 in). Keep that unless the firm's pitch book differs.",
          "- **Chart palette.** Brand colors are usually too muted to tell four chart series apart. Pick a brighter set in the same family and run the color-vision check (Lesson 1, step 4).",
          "- **Fonts on other computers.** If a font is not installed where the deck is built (a colleague's Mac, a server), LibreOffice substitutes one. Check the page images.",
          "- **The disclosure.** The captured paragraph is the firm's own text. The deck adds a placeholder for the language your CCO approves for this document."]
    (ROOT / "brand" / "capture-report.md").write_text("\n".join(R) + "\n", encoding="utf-8")
    print("\n".join(R[:16]))
    print(f"\nWrote brand/brand-captured.json, brand/capture-report.md, brand/logo-captured.png")


if __name__ == "__main__":
    sys.exit(main())
