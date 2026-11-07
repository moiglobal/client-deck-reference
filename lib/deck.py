"""PowerPoint assembly in the firm's house style (python-pptx). Layout lives here once."""
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from .common import ROOT
from .style import BRAND, C

W, H = BRAND["slide"]["width_in"], BRAND["slide"]["height_in"]
HF, BF = BRAND["fonts"]["heading"], BRAND["fonts"]["body"]
M = 0.55  # side margin, inches
CONTENT_TOP, CONTENT_H = 1.95, 4.55
CONTENT_W = W - 2 * M


def rgb(hexstr):
    return RGBColor.from_string(hexstr.lstrip("#"))


class Deck:
    def __init__(self, period_label, draft=True, audience="internal"):
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(W), Inches(H)
        self.blank = self.prs.slide_layouts[6]
        self.period_label = period_label
        self.draft = draft
        self.audience = audience
        self.n = 0
        self.overflow = []

    # ---------- primitives ----------
    def text(self, slide, x, y, w, h, s, size=12, font=None, color=None, bold=False,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False, spacing=None):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = anchor
        paras = s if isinstance(s, list) else [s]
        for i, ptxt in enumerate(paras):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = align
            if spacing:
                p.space_after = Pt(spacing)
            runs = ptxt if isinstance(ptxt, list) else [(ptxt, {})]
            for rt, fmt in runs:
                r = p.add_run()
                r.text = rt
                f = r.font
                f.name = fmt.get("font", font or BF)
                f.size = Pt(fmt.get("size", size))
                f.bold = fmt.get("bold", bold)
                f.italic = fmt.get("italic", italic)
                f.color.rgb = rgb(fmt.get("color", color or C["ink"]))
        return tb

    def rect(self, slide, x, y, w, h, fill, line=None):
        s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
        if line:
            s.line.color.rgb = rgb(line)
        else:
            s.line.fill.background()
        s.shadow.inherit = False
        return s

    def watermark(self, slide):
        if not self.draft:
            return
        tb = self.text(slide, 1.2, 2.9, W - 2.4, 1.6, "DRAFT  |  NOT FOR DISTRIBUTION", size=54,
                       font=HF, color=C["draft"], bold=True, align=PP_ALIGN.CENTER,
                       anchor=MSO_ANCHOR.MIDDLE)
        tb.rotation = -24
        for r in tb.text_frame.paragraphs[0].runs:
            clr = r._r.find(qn("a:rPr")).find(qn("a:solidFill")).find(qn("a:srgbClr"))
            a = etree.SubElement(clr, qn("a:alpha"))
            a.set("val", "16000")
        # A second, unmissable marker that survives printing in greyscale.
        self.text(slide, W - M - 3.2, 0.12, 3.2, 0.22, "DRAFT: pending compliance review",
                  size=9, color=C["draft"], bold=True, align=PP_ALIGN.RIGHT)

    def fit(self, title, box_in, start=26, floor=20):
        """Largest size (26pt down to 20pt) at which the title fits one line, measured with
        the real heading font. Data-written titles vary in length every period."""
        try:
            from PIL import ImageFont
            import matplotlib.font_manager as fm
            path = fm.findfont(fm.FontProperties(family=HF), fallback_to_default=False)
            for size in range(start, floor - 1, -1):
                f = ImageFont.truetype(path, size * 10)  # 10x for precision; widths in 1/10 pt
                if f.getlength(title) / 10 <= box_in * 72 * 0.97:
                    return size
            self.overflow.append(title)
            return floor
        except Exception:
            return start

    # ---------- page furniture ----------
    def page(self, kicker, title, subtitle=None, source=None, notes=None):
        slide = self.prs.slides.add_slide(self.blank)
        self.n += 1
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb(C["surface"])
        self.text(slide, M, 0.38, 8, 0.28, kicker.upper(), size=11, color=C["accent"], bold=True)
        logo = ROOT / BRAND["logo"]
        slide.shapes.add_picture(str(logo), Inches(W - M - 1.62), Inches(0.34), height=Inches(0.42))
        self.text(slide, M, 0.68, W - 2 * M - 0.2, 0.7, title, size=self.fit(title, W - 2 * M - 0.2), font=HF, color=C["ink"])
        if subtitle:
            self.text(slide, M, 1.38, W - 2 * M, 0.5, subtitle, size=14, color=C["ink_secondary"])
        if source:
            self.text(slide, M, 6.62, W - 2 * M, 0.36, source, size=9, color=C["ink_muted"],
                      anchor=MSO_ANCHOR.BOTTOM)
        line = slide.shapes.add_connector(1, Inches(M), Inches(7.03), Inches(W - M), Inches(7.03))
        line.line.color.rgb = rgb(C["rule"])
        line.line.width = Pt(0.75)
        foot = BRAND["footer"].format(firm_name=BRAND["firm_name"],
                                      document_name=BRAND["document_name"],
                                      period_label=self.period_label)
        if self.audience == "internal":
            foot += "  |  INTERNAL VERSION: contains pages not cleared for clients"
        self.text(slide, M, 7.1, 10, 0.25, foot, size=9, color=C["ink_muted"])
        self.text(slide, W - M - 1, 7.1, 1, 0.25, str(self.n), size=9, color=C["ink_muted"],
                  align=PP_ALIGN.RIGHT)
        if notes:
            slide.notes_slide.notes_text_frame.text = notes
        return slide

    def picture(self, slide, path, x=M, y=CONTENT_TOP, w=CONTENT_W, h=CONTENT_H):
        slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))

    def table(self, slide, x, y, w, rows, col_w, header_rows=1, font_size=12, row_h=0.36,
              bold_last=False, align=None):
        nr, nc = len(rows), len(rows[0])
        gt = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w), Inches(row_h * nr)).table
        tbl = gt._tbl
        tbl.tblPr.set("firstRow", "0")
        tbl.tblPr.set("bandRow", "0")
        style = tbl.tblPr.find(qn("a:tableStyleId"))
        if style is not None:
            style.text = "{5940675A-B579-460E-94D1-54222C63F5DA}"  # 'No Style, Table Grid'
        for j, cw in enumerate(col_w):
            gt.columns[j].width = Inches(cw)
        for i in range(nr):
            gt.rows[i].height = Inches(row_h)
            for j in range(nc):
                cell = gt.cell(i, j)
                cell.margin_left = cell.margin_right = Inches(0.06)
                cell.margin_top = cell.margin_bottom = Inches(0.02)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                head = i < header_rows
                last = bold_last and i == nr - 1
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb(C["surface_alt"] if (head or last) else C["surface"])
                tf = cell.text_frame
                tf.word_wrap = True
                a = (align[j] if align else ("l" if j == 0 else "r"))
                # one paragraph per line, so a two-line header aligns on both lines
                for k, line in enumerate(str(rows[i][j]).split("\n")):
                    p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                    if k == 0:
                        p.text = ""
                    r = p.add_run()
                    r.text = line
                    r.font.name = BF
                    r.font.size = Pt(font_size - (1 if head else 0))
                    r.font.bold = head or last
                    r.font.color.rgb = rgb(C["ink_secondary"] if head else C["ink"])
                    p.alignment = {"l": PP_ALIGN.LEFT, "r": PP_ALIGN.RIGHT, "c": PP_ALIGN.CENTER}[a]
                self._borders(cell, bottom=C["rule"] if not head else C["ink_muted"])
        return gt

    @staticmethod
    def _borders(cell, bottom):
        """Only a thin bottom rule per cell. Border elements must precede the cell fill in
        the XML (schema order lnL, lnR, lnT, lnB, fill) or PowerPoint offers to repair."""
        tcPr = cell._tc.get_or_add_tcPr()
        for i, edge in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
            ln = etree.Element(qn(edge))
            if edge == "a:lnB":
                ln.set("w", "9525")
                sf = etree.SubElement(ln, qn("a:solidFill"))
                c = etree.SubElement(sf, qn("a:srgbClr"))
                c.set("val", bottom.lstrip("#"))
            else:
                ln.set("w", "0")
                etree.SubElement(ln, qn("a:noFill"))
            tcPr.insert(i, ln)

    def save(self, path):
        for slide in self.prs.slides:
            self.watermark(slide)
        self.prs.save(path)
