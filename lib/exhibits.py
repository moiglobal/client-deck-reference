"""The firm's recurring exhibit set. Each exhibit: compute from the snapshot, write every
displayed number to the ledger, draw the chart, place it on a slide with a takeaway title
computed from the data (never typed by hand, so it cannot drift from the chart)."""
import datetime as dt
import statistics as st

import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from . import edgar as E
from .deck import CONTENT_H, CONTENT_TOP, CONTENT_W, M, W
from .style import BRAND, C, CAT, P, end_labels, fig, label_end, save, trim_time_ticks

FRED_SRC = "Federal Reserve Bank of St. Louis (FRED)"
EDGAR_SRC = "SEC EDGAR"
ROIC_SRC = "roic.ai"


# ------------------------------------------------------------------ helpers
def fs(snap, sid):
    f = snap["fred"][sid]
    s = pd.Series([v for _, v in f["obs"]], index=pd.to_datetime([d for d, _ in f["obs"]]))
    s.attrs.update(sid=sid, url=f["url"], title=f["title"], producer=f["producer"])
    return s


def at(s, when):
    sub = s[s.index <= pd.Timestamp(when)]
    return sub.index[-1].date(), float(sub.iloc[-1])


def monthly(s):
    """Put a monthly series on a complete month calendar. October 2025 CPI and
    unemployment were never published (federal shutdown), so FRED has no row for that
    month; counting 12 rows back would then compare August with July of the prior year."""
    out = s.asfreq("MS")
    out.attrs.update(s.attrs)
    return out


def yoy(s):
    m = monthly(s)
    return (m / m.shift(12) - 1) * 100


def fmt_pct(x, d=1, sign=False):
    return f"{x:+.{d}f}%" if sign else f"{x:.{d}f}%"


def fmt_pt(x, d=1):
    return f"{x:+.{d}f} pt"


def month_name(d):
    return pd.Timestamp(d).strftime("%B %Y")


def long_date(d):
    d = pd.Timestamp(d)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def holdings(snap):
    return snap["portfolio"]["holdings"]


def wnorm(snap):
    hs = holdings(snap)
    tot = sum(h["weight"] for h in hs)
    return {h["ticker"]: h["weight"] / tot for h in hs}


def ev(snap, t, concept, fy):
    r = snap["edgar"][t]["concepts"][concept].get(fy) or snap["edgar"][t]["concepts"][concept].get(str(fy))
    if r is None:
        raise KeyError(f"{t} {concept} FY{fy} missing")
    return r


def fy_window(snap, t):
    ys = sorted(int(k) for k in snap["edgar"][t]["concepts"]["revenue"])
    return ys[-10:]


def share_ratio(snap, t, fy):
    sh = snap["edgar"][t]["shares"]
    return (sh.get(fy) or sh.get(str(fy)))["ratio"]


def share_series(snap, t):
    """Split-consistent share count by FY: the latest filed count rolled back by the
    within-filing ratios."""
    sh = snap["edgar"][t]["shares"]
    ys = sorted(int(k) for k in sh)
    out = {ys[-1]: (sh.get(ys[-1]) or sh.get(str(ys[-1])))["val"]}
    for y in reversed(ys):
        out[y - 1] = out[y] / share_ratio(snap, t, y)
    return out


def cik_url(snap, t, concept, fy):
    r = ev(snap, t, concept, fy)
    return E.filing_url(snap["edgar"][t]["cik"], r["accn"]) if r["accn"] else ""


def offcal(snap):
    """Holdings whose fiscal year does not end in December, named for the footnotes."""
    out = []
    for h in snap["portfolio"]["holdings"]:
        ends = [v["end"] for v in snap["edgar"][h["ticker"]]["concepts"]["revenue"].values()]
        m = pd.Timestamp(max(ends)).month
        if m != 12:
            out.append((h["name"], pd.Timestamp(max(ends)).strftime("%B")))
    return out


def offcal_text(snap):
    o = offcal(snap)
    if not o:
        return "All holdings report on calendar years."
    return "Fiscal years as each company reports them (" + "; ".join(f"{n} ends in {m}" for n, m in o) + ")."


# ------------------------------------------------------------------ exhibits
class Exhibits:
    def __init__(self, snap, deck, ledger, tmp, prev=None):
        self.s, self.d, self.L, self.tmp, self.prev = snap, deck, ledger, tmp, prev
        self.as_of = dt.date.fromisoformat(snap["as_of"])
        self.summary = {}

    def note(self, exhibit):
        """The analyst's own footnote for an exhibit, from the period's holdings file. Data
        cannot know that a base year was distorted; a portfolio manager does."""
        n = self.s["portfolio"].get("notes", {}).get(exhibit)
        if n:
            self.L.add(exhibit, "analyst note", n, None, "Firm analyst note", f"config/portfolio-{self.s['period']}.json",
                       self.s["as_of"], "")
            return " " + n
        return ""

    def gaps_note(self, *sids):
        """Months a monthly series skips (October 2025 CPI and unemployment were never
        published), stated rather than interpolated."""
        miss = {}
        for sid in sids:
            if self.s["fred"][sid]["freq"] != "monthly":
                continue
            x = fs(self.s, sid)
            full = pd.date_range(x.index[0], x.index[-1], freq="MS")
            for d in full.difference(x.index):
                miss.setdefault(d.strftime("%B %Y"), []).append(sid)
        if not miss:
            return ""
        return " No data published for " + "; ".join(f"{m} ({', '.join(v)})" for m, v in miss.items()) + ": the line breaks there."

    def src_fred(self, *sids):
        names = sorted({self.s["fred"][x]["producer"] for x in sids} - {"Federal Reserve Bank of St. Louis"})
        extra = " (breakeven computed by FRED from H.15 yields)" if "T10YIE" in sids else ""
        return (f"Source: {'; '.join(names)}{extra}, via {FRED_SRC}; series {', '.join(sids)}. "
                f"Retrieved {self.s['fred'][sids[0]]['retrieved'][:10]}.")

    # ---------- 1 cover
    def cover(self):
        d, s = self.d, self.s
        slide = d.prs.slides.add_slide(d.blank)
        d.n += 1
        slide.background.fill.solid()
        from .deck import rgb
        slide.background.fill.fore_color.rgb = rgb(C["surface_alt"])
        d.rect(slide, 0, 0, 0.32, 7.5, C["primary"])
        from pptx.util import Inches
        from .common import ROOT
        slide.shapes.add_picture(str(ROOT / BRAND["logo"]), Inches(1.0), Inches(0.9), height=Inches(0.75))
        d.text(slide, 1.0, 2.55, 10, 1.0, BRAND["document_name"], size=44, font=BRAND["fonts"]["heading"], color=C["ink"])
        d.text(slide, 1.0, 3.55, 10, 0.6, s["label"], size=26, color=C["accent"], font=BRAND["fonts"]["heading"])
        d.text(slide, 1.0, 4.35, 10, 0.4, f"Market and company data as of {long_date(s['as_of'])}", size=15,
               color=C["ink_secondary"])
        line = slide.shapes.add_connector(1, Inches(1.0), Inches(4.95), Inches(4.0), Inches(4.95))
        line.line.color.rgb = rgb(C["accent"])
        d.text(slide, 1.0, 6.25, 11.3, 0.7,
               f"For clients of {BRAND['firm_name']}. This review describes markets and the businesses we own; "
               "it does not report investment performance. Please read the important information at the end.",
               size=11, color=C["ink_muted"])

    # ---------- 2 at a glance
    def glance(self):
        s, L = self.s, self.L
        dgs10 = fs(s, "DGS10")
        d_now, v_now = at(dgs10, self.as_of)
        d_q, v_q = at(dgs10, dt.date.fromisoformat(s["q_start"]) - dt.timedelta(days=1))
        cpi = yoy(fs(s, "CPIAUCSL")).dropna()
        un = fs(s, "UNRATE")
        un_m = monthly(un)
        un_prev12 = float(un_m.loc[un.index[-1] - pd.DateOffset(months=12)])
        rev_cagr = {}
        for h in holdings(s):
            t = h["ticker"]
            ys = fy_window(s, t)
            rev_cagr[t] = ((ev(s, t, "revenue", ys[-1])["val"] / ev(s, t, "revenue", ys[-6])["val"]) ** 0.2 - 1) * 100
        w = wnorm(s)
        port_cagr = sum(w[t] * rev_cagr[t] for t in w)
        sl = "At a glance"
        tiles = [
            (L.add(sl, "10-year Treasury yield, quarter end", fmt_pct(v_now, 2), v_now, FRED_SRC, "DGS10", str(d_now), dgs10.attrs["url"]),
             "10-year Treasury yield",
             L.add(sl, "10-year yield change in quarter", f"{(v_now - v_q):+.2f} pt in the quarter", v_now - v_q, FRED_SRC, "DGS10",
                   f"{d_q} to {d_now}", dgs10.attrs["url"], "DGS10 at quarter end minus DGS10 at prior quarter end")),
            (L.add(sl, "CPI inflation, year over year", fmt_pct(cpi.iloc[-1]), cpi.iloc[-1], FRED_SRC, "CPIAUCSL",
                   month_name(cpi.index[-1]), fs(s, "CPIAUCSL").attrs["url"], "CPIAUCSL / CPIAUCSL 12 months earlier - 1"),
             "Consumer price inflation",
             f"year over year, {month_name(cpi.index[-1])}"),
            (L.add(sl, "Unemployment rate", fmt_pct(un.iloc[-1]), un.iloc[-1], FRED_SRC, "UNRATE", month_name(un.index[-1]), un.attrs["url"]),
             "Unemployment rate",
             L.add(sl, "Unemployment change over 12 months",
                   (f"{un.iloc[-1] - un_prev12:+.1f} pt over 12 months, {month_name(un.index[-1])}" if abs(un.iloc[-1] - un_prev12) >= 0.05
                    else f"unchanged over 12 months, {month_name(un.index[-1])}"),
                   un.iloc[-1] - un_prev12, FRED_SRC, "UNRATE",
                   f"{month_name(un.index[-1] - pd.DateOffset(months=12))} to {month_name(un.index[-1])}", un.attrs["url"])),
            (L.add(sl, "Holdings' revenue growth, 5-year CAGR, weighted", fmt_pct(port_cagr), port_cagr, EDGAR_SRC,
                   "Revenues (see methodology for tag per company)", "latest five fiscal years", "",
                   "weight-averaged compound annual growth of each holding's revenue, latest FY vs five years earlier"),
             "Revenue growth of our holdings",
             "a year, compounded over five fiscal years"),
        ]
        slide = self.d.page("This quarter", "The quarter at a glance",
                            "Four figures that frame the review. Each is defined, dated and sourced on the pages that follow.",
                            source="Sources: Federal Reserve (H.15) and U.S. Bureau of Labor Statistics via FRED; company 10-K filings via SEC EDGAR. "
                                   "Monthly data shown as published by the as-of date.")
        tw, gap = (W - 2 * M - 3 * 0.3) / 4, 0.3
        for i, (big, lab, small) in enumerate(tiles):
            x = M + i * (tw + gap)
            self.d.rect(slide, x, 2.35, tw, 3.2, C["surface_alt"])
            self.d.rect(slide, x, 2.35, tw, 0.07, C["primary"] if i < 3 else C["accent"])
            self.d.text(slide, x + 0.25, 2.7, tw - 0.5, 0.45, lab, size=14, color=C["ink_secondary"], bold=True)
            self.d.text(slide, x + 0.25, 3.25, tw - 0.5, 1.0, big, size=44, font=BRAND["fonts"]["heading"], color=C["ink"])
            self.d.text(slide, x + 0.25, 4.45, tw - 0.5, 0.8, small, size=13, color=C["ink_muted"])
        self.summary.update(dgs10=v_now, cpi_yoy=float(cpi.iloc[-1]), cpi_month=month_name(cpi.index[-1]),
                            unrate=float(un.iloc[-1]), un_month=month_name(un.index[-1]), port_rev_cagr=port_cagr)

    # ---------- 3 yield curve
    def yield_curve(self):
        s, L = self.s, self.L
        mats = [("DGS1MO", "1m"), ("DGS3MO", "3m"), ("DGS6MO", "6m"), ("DGS1", "1y"), ("DGS2", "2y"), ("DGS3", "3y"),
                ("DGS5", "5y"), ("DGS7", "7y"), ("DGS10", "10y"), ("DGS20", "20y"), ("DGS30", "30y")]
        dates = [self.as_of, self.as_of - dt.timedelta(days=365), self.as_of - dt.timedelta(days=730)]
        curves = []
        for dd in dates:
            curves.append([at(fs(s, sid), dd) for sid, _ in mats])
        f, ax = fig(CONTENT_W, CONTENT_H)
        x = np.arange(len(mats))
        names = [long_date(cv[8][0]) for cv in curves]
        cols = [CAT[0], CAT[1], CAT[2]]
        items = []
        for i, cv in enumerate(reversed(curves)):
            k = 2 - i
            ys = [v for _, v in cv]
            ax.plot(x, ys, color=cols[k], lw=2.6 if k == 0 else 2.0, marker="o", ms=5 if k == 0 else 4, zorder=3 + (k == 0))
            items.append((x[-1], ys[-1], names[k], cols[k]))
        ax.set_xticks(x, [m for _, m in mats])
        ax.set_xlim(-0.3, len(mats) + 2.3)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}%"))
        ax.set_xlabel("Maturity", color=C["ink_muted"])
        end_labels(ax, items)
        f.tight_layout()
        path = save(f, self.tmp / "yield_curve.png")
        sp_now = curves[0][8][1] - curves[0][1][1]
        sp_1y = curves[1][8][1] - curves[1][1][1]
        sl = "Yield curve"
        for i, cv in enumerate(curves):
            for (sid, m), (dd, v) in zip(mats, cv):
                if sid in ("DGS3MO", "DGS10", "DGS30"):
                    L.add(sl, f"{m} yield, {['quarter end', '1y earlier', '2y earlier'][i]}", f"{v:.2f}%", v, FRED_SRC, sid, str(dd),
                          fs(s, sid).attrs["url"])
        L.add(sl, "10y minus 3m, quarter end", fmt_pt(sp_now, 2), sp_now, FRED_SRC, "DGS10 - DGS3MO", str(curves[0][8][0]), fs(s, "DGS10").attrs["url"])
        L.add(sl, "10y minus 3m, one year earlier", fmt_pt(sp_1y, 2), sp_1y, FRED_SRC, "DGS10 - DGS3MO", str(curves[1][8][0]), fs(s, "DGS10").attrs["url"])
        shape = "slopes upward" if sp_now > 0.25 else ("is inverted" if sp_now < -0.25 else "is nearly flat")
        title = f"The Treasury curve {shape}: 10-year minus 3-month is {sp_now:+.2f} pt"
        sub = f"A year earlier the same spread was {sp_1y:+.2f} pt. Long yields set the discount rate applied to every business we own."
        slide = self.d.page("Markets", title, sub, source=self.src_fred(*[m for m, _ in mats]) +
                            " Constant-maturity yields, last business day on or before each date.")
        self.d.picture(slide, path)
        self.summary.update(spread_10y3m=sp_now, dgs2=curves[0][4][1], dgs3mo=curves[0][1][1])

    # ---------- 4 real yields
    def real_yields(self):
        s, L = self.s, self.L
        start = pd.Timestamp(self.as_of) - pd.DateOffset(years=15)
        r = fs(s, "DFII10")
        b = fs(s, "T10YIE")
        rm, bm = r[r.index >= start].resample("ME").mean(), b[b.index >= start].resample("ME").mean()
        f, ax = fig(CONTENT_W, CONTENT_H)
        ax.axhline(0, color=C["ink_muted"], lw=0.8)
        ax.plot(rm.index, rm.values, color=CAT[0])
        ax.plot(bm.index, bm.values, color=CAT[1])
        dr, vr = at(r, self.as_of)
        db, vb = at(b, self.as_of)
        ax.set_xlim(rm.index[0], rm.index[-1] + pd.DateOffset(months=52))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}%"))
        trim_time_ticks(ax, rm.index[-1])
        end_labels(ax, [(rm.index[-1], rm.values[-1], f"Real yield (10-year TIPS)  {vr:.2f}%", CAT[0]),
                        (bm.index[-1], bm.values[-1], f"Breakeven inflation  {vb:.2f}%", CAT[1])])
        f.tight_layout()
        path = save(f, self.tmp / "real_yields.png")
        avg_r = float(r[r.index >= start].mean())
        sl = "Real yields"
        L.add(sl, "10y real yield, quarter end", f"{vr:.2f}%", vr, FRED_SRC, "DFII10", str(dr), r.attrs["url"])
        L.add(sl, "10y breakeven, quarter end", f"{vb:.2f}%", vb, FRED_SRC, "T10YIE", str(db), b.attrs["url"])
        L.add(sl, "10y real yield, 15-year average", f"{avg_r:.2f}%", avg_r, FRED_SRC, "DFII10",
              f"{r[r.index >= start].index[0].date()} to {dr}", r.attrs["url"], "mean of daily observations")
        hist = r[r.index < pd.Timestamp(dr)]  # everything in the archive, back to 2009
        higher = hist[hist >= vr]
        if higher.empty:
            title = f"10-year real yields reach {vr:.1f}%, the highest since at least {hist.index[0].year}"
            L.add(sl, "Real yield: highest since at least", str(hist.index[0].year), vr, FRED_SRC, "DFII10",
                  f"{hist.index[0].date()} to {dr}", r.attrs["url"],
                  "every daily observation in the window is below the quarter-end value")
            since = ""
        else:
            title = f"Investors earn {vr:.1f}% a year over inflation on 10-year TIPS"
            since = (f"; it was last this high on {long_date(higher.index[-1])}"
                     if higher.index[-1] < pd.Timestamp(dr) - pd.DateOffset(years=1) else "")
        sub = (f"The real yield is what a Treasury that protects against inflation pays over inflation; its 15-year average is "
               f"{avg_r:.1f}%{since}. Breakeven inflation, the rate implied by market prices, is {vb:.1f}%.")
        slide = self.d.page("Markets", title, sub, source=self.src_fred("DFII10", "T10YIE") + " Monthly averages of daily data; end labels show the quarter-end value.")
        self.d.picture(slide, path)
        self.summary.update(real10=vr, breakeven10=vb)

    # ---------- 5 policy vs 2y vs CPI
    def policy(self):
        s, L = self.s, self.L
        start = pd.Timestamp(self.as_of) - pd.DateOffset(years=10)
        ff, two = fs(s, "DFF"), fs(s, "DGS2")
        cpi = yoy(fs(s, "CPIAUCSL")).dropna()
        ffm = ff[ff.index >= start].resample("ME").mean()
        twm = two[two.index >= start].resample("ME").mean()
        cpm = cpi[cpi.index >= start]
        f, ax = fig(CONTENT_W, CONTENT_H)
        ax.plot(ffm.index, ffm.values, color=CAT[0])
        ax.plot(twm.index, twm.values, color=CAT[1])
        ax.plot(cpm.index, cpm.values, color=CAT[2])
        dff, vff = at(ff, self.as_of)
        d2, v2 = at(two, self.as_of)
        ax.set_xlim(ffm.index[0], ffm.index[-1] + pd.DateOffset(months=40))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
        trim_time_ticks(ax, ffm.index[-1])
        end_labels(ax, [(ffm.index[-1], ffm.values[-1], f"Federal funds rate  {vff:.2f}%", CAT[0]),
                        (twm.index[-1], twm.values[-1], f"2-year Treasury  {v2:.2f}%", CAT[1]),
                        (cpm.index[-1], cpm.values[-1], f"CPI inflation  {cpm.values[-1]:.1f}% ({cpm.index[-1].strftime('%b')})", CAT[2])])
        f.tight_layout()
        path = save(f, self.tmp / "policy.png")
        sl = "Policy rate"
        L.add(sl, "Effective fed funds, quarter end", f"{vff:.2f}%", vff, FRED_SRC, "DFF", str(dff), ff.attrs["url"])
        L.add(sl, "2-year Treasury, quarter end", f"{v2:.2f}%", v2, FRED_SRC, "DGS2", str(d2), two.attrs["url"])
        L.add(sl, "CPI inflation yoy, latest published", f"{cpm.values[-1]:.1f}%", cpm.values[-1], FRED_SRC, "CPIAUCSL",
              month_name(cpm.index[-1]), fs(s, "CPIAUCSL").attrs["url"], "12-month change in the index")
        gap = v2 - vff
        L.add(sl, "2-year minus fed funds", fmt_pt(gap, 2), gap, FRED_SRC, "DGS2 - DFF", str(d2), two.attrs["url"])
        rel = "below" if gap < 0 else "above"
        title = f"The 2-year Treasury yields {abs(gap):.2f} pt {rel} the federal funds rate"
        sub = (f"When the 2-year yield sits {rel} the policy rate, bond prices imply a {'lower' if gap < 0 else 'higher'} average policy "
               f"rate over the next two years, before any term premium. Consumer prices rose {cpm.values[-1]:.1f}% in the year to "
               f"{month_name(cpm.index[-1])}.")
        slide = self.d.page("Markets", title, sub, source=self.src_fred("DFF", "DGS2", "CPIAUCSL") +
                            " Rates are monthly averages of daily data; end labels show quarter-end values." + self.gaps_note("CPIAUCSL"))
        self.d.picture(slide, path)
        self.summary.update(fedfunds=vff)

    # ---------- 6 macro dashboard
    def dashboard(self):
        s, L = self.s, self.L
        start = pd.Timestamp(self.as_of) - pd.DateOffset(years=10)
        cpi = yoy(fs(s, "CPIAUCSL"))
        un = monthly(fs(s, "UNRATE"))
        pay = monthly(fs(s, "PAYEMS")).diff().rolling(3).mean()
        ip = yoy(fs(s, "INDPRO"))
        panels = [("Consumer prices, % change over 12 months", cpi, "%", "CPIAUCSL", "12-month % change"),
                  ("Unemployment rate, %", un, "%", "UNRATE", "level"),
                  ("Payrolls, monthly change, thousands (3-month average)", pay, "k", "PAYEMS", "3-month average of monthly change"),
                  ("Industrial production, % change over 12 months", ip, "%", "INDPRO", "12-month % change")]
        f, axs = fig(CONTENT_W, CONTENT_H, nrows=2, ncols=2)
        sl = "Economy"
        for ax, (ttl, ser, unit, sid, how) in zip(axs.flat, panels):
            x = ser[ser.index >= start]
            x = x.loc[:x.last_valid_index()]
            ax.plot(x.index, x.values, color=CAT[0], lw=1.8)
            ax.set_title(ttl, fontsize=12, pad=4)
            if unit == "k":
                ax.set_ylim(max(x.min(), -400) - 50, min(x.max(), 700) + 60)  # 2020 swings clipped; noted in source line
                lab = f"{x.values[-1]:,.0f}k"
            else:
                lab = f"{x.values[-1]:.1f}%" if unit == "%" else f"{x.values[-1]:.1f}"
            label_end(ax, x.index[-1], x.values[-1], f"{lab}  {x.index[-1].strftime('%b %Y')}", CAT[0], size=10)
            ax.set_xlim(x.index[0], x.index[-1] + pd.DateOffset(months=34))
            trim_time_ticks(ax, x.index[-1])
            ax.tick_params(labelsize=10)
            if unit == "k":
                ax.axhline(0, color=C["ink_muted"], lw=0.8)
            L.add(sl, ttl, lab, x.values[-1], FRED_SRC, sid, month_name(x.index[-1]), fs(s, sid).attrs["url"], how)
        f.tight_layout(h_pad=1.6, w_pad=3)
        path = save(f, self.tmp / "dashboard.png")
        pay_now = pay.dropna().iloc[-1]
        pay_6m = pay.dropna().loc[:pay.dropna().index[-1] - pd.DateOffset(months=3)].iloc[-1]
        verb = "slowed to" if pay_now < pay_6m - 25 else ("picked up to" if pay_now > pay_6m + 25 else "held at")
        L.add(sl, "Payrolls 3-month average, three months earlier", f"{pay_6m:,.0f}k", pay_6m, FRED_SRC, "PAYEMS",
              month_name(pay.dropna().index[-1] - pd.DateOffset(months=3)), fs(s, "PAYEMS").attrs["url"],
              "basis for the verb in the title (more than 25k lower = slowed)")
        title = f"Jobs growth {verb} {pay_now:,.0f}k a month, from {pay_6m:,.0f}k; inflation {cpi.dropna().iloc[-1]:.1f}%"
        slide = self.d.page("Economy", title,
                            "The four monthly series that most often change the conversation with clients, over ten years.",
                            source=self.src_fred("CPIAUCSL", "UNRATE", "PAYEMS", "INDPRO") +
                            " Payroll axis clipped at the 2020 extremes. Monthly data as published by the as-of date." +
                            self.gaps_note("CPIAUCSL", "UNRATE", "PAYEMS", "INDPRO"))
        self.d.picture(slide, path)
        self.summary.update(payrolls_3m=float(pay_now))

    # ---------- 7 quality table
    def quality(self):
        s, L = self.s, self.L
        sl = "Quality table"
        rows = [["Company", "Weight", "FY", "Revenue growth\n5-yr CAGR", "Operating\nmargin", "Margin change\nover 5 yrs",
                 "Free cash flow\nmargin", "Share count\nchange, 5 yrs", "Cash returned\n% of FCF, 5 yrs"]]
        w = wnorm(s)
        agg = {k: 0.0 for k in ("g", "om", "dom", "fcf", "sh", "ret")}
        shrinkers = 0
        for h in sorted(holdings(s), key=lambda h: -h["weight"]):
            t = h["ticker"]
            ys = fy_window(s, t)
            y, y5 = ys[-1], ys[-6]
            rev, rev5 = ev(s, t, "revenue", y)["val"], ev(s, t, "revenue", y5)["val"]
            oi, oi5 = ev(s, t, "operating_income", y)["val"], ev(s, t, "operating_income", y5)["val"]
            cfo, capex = ev(s, t, "cfo", y)["val"], ev(s, t, "capex", y)["val"]
            g = ((rev / rev5) ** 0.2 - 1) * 100
            om, om5 = oi / rev * 100, oi5 / rev5 * 100
            fcf = (cfo - capex) / rev * 100
            sh = (np.prod([share_ratio(s, t, k) for k in ys[-5:]]) - 1) * 100
            fcf5 = sum(ev(s, t, "cfo", k)["val"] - ev(s, t, "capex", k)["val"] for k in ys[-5:])
            ret5 = sum(ev(s, t, "dividends", k)["val"] + ev(s, t, "buybacks", k)["val"] for k in ys[-5:])
            ret = ret5 / fcf5 * 100
            shrinkers += sh < 0
            url = cik_url(s, t, "revenue", y)
            tag = ev(s, t, "revenue", y)["tag"]
            cells = [
                L.add(sl, f"{t} revenue CAGR", fmt_pct(g), g, EDGAR_SRC, tag, f"FY{y5}-FY{y}", url, "(rev FY / rev FY-5)^(1/5) - 1"),
                L.add(sl, f"{t} operating margin", fmt_pct(om), om, EDGAR_SRC, "OperatingIncomeLoss / " + tag, f"FY{y}", url),
                L.add(sl, f"{t} margin change", fmt_pt(om - om5), om - om5, EDGAR_SRC, "OperatingIncomeLoss / " + tag, f"FY{y5} to FY{y}", url),
                L.add(sl, f"{t} FCF margin", fmt_pct(fcf), fcf, EDGAR_SRC,
                      f"({ev(s, t, 'cfo', y)['tag']} - {ev(s, t, 'capex', y)['tag']}) / revenue", f"FY{y}", cik_url(s, t, "cfo", y)),
                L.add(sl, f"{t} share count change", fmt_pct(sh, sign=True), sh, EDGAR_SRC, s["edgar"][t]["shares_tag"],
                      f"FY{ys[-6]}-FY{y}", E.filing_url(s["edgar"][t]["cik"], (s["edgar"][t]["shares"].get(y) or s["edgar"][t]["shares"].get(str(y)))["accn"]),
                      "product of five within-filing year-over-year ratios (split-proof)"),
                L.add(sl, f"{t} cash returned / FCF", f"{ret:.0f}%", ret, EDGAR_SRC,
                      "(dividends + buybacks) / (CFO - capex), summed", f"FY{ys[-5]}-FY{y}", cik_url(s, t, "cfo", y)),
            ]
            rows.append([h["name"], f"{h['weight']:.0f}%", f"{y}"] + cells)
            for k, v in zip(agg, (g, om, om - om5, fcf, sh, ret)):
                agg[k] += w[t] * v
        port = [L.add(sl, f"Portfolio {k}", (fmt_pt(v) if k == "dom" else fmt_pct(v, sign=(k == "sh")) if k != "ret" else f"{v:.0f}%"),
                      v, EDGAR_SRC, "weighted average of the rows above", "as above", "", "weights renormalized to exclude cash")
                for k, v in agg.items()]
        rows.append(["Portfolio, weighted", f"{100 - s['portfolio']['cash_weight']:.0f}%", ""] + port)
        title = f"Our companies turn {agg['fcf']:.0f}% of revenue into free cash flow"
        sub = (f"Weighted revenue growth of {agg['g']:.1f}% a year over five years; {shrinkers} of {len(holdings(s))} "
               f"have fewer shares outstanding than five years ago.")
        slide = self.d.page("What we own", title, sub,
                            source="Source: company 10-K filings via SEC EDGAR (XBRL company facts), filed on or before the as-of date; most recent "
                                   "restatement of each year. FY = latest fiscal year reported. Free cash flow = operating cash flow minus "
                                   "capital expenditure. Weights exclude cash." + self.note("quality"))
        self.d.table(slide, M, 2.0, W - 2 * M, rows,
                     [2.15, 0.8, 0.65, 1.35, 1.15, 1.35, 1.35, 1.25, 1.18], font_size=12, row_h=0.355, bold_last=True)
        self.summary.update(port_fcf_margin=agg["fcf"], shrinkers=int(shrinkers))

    # ---------- 8 share counts
    def shares(self):
        s, L = self.s, self.L
        sl = "Share counts"
        series = {}
        for h in holdings(s):
            t = h["ticker"]
            ys = fy_window(s, t)
            idx = [100.0]
            for y in ys:
                idx.append(idx[-1] * share_ratio(s, t, y))
            series[t] = (h["name"], [ys[0] - 1] + ys, idx)
        order = sorted(series, key=lambda t: series[t][2][-1])
        f, axs = fig(CONTENT_W, CONTENT_H, nrows=2, ncols=5, sharey=True)
        for ax, t in zip(axs.flat, order):
            name, ys, idx = series[t]
            col = CAT[3] if idx[-1] < 100 else CAT[1]
            ax.axhline(100, color=C["ink_muted"], lw=0.8, ls=(0, (3, 3)))
            ax.plot(ys, idx, color=col, lw=2)
            ax.plot([ys[-1]], [idx[-1]], "o", color=col, ms=5)
            ax.set_title(name, fontsize=12, pad=3)
            ax.text(0.98, 0.99, f"{idx[-1]:.0f}", transform=ax.transAxes, ha="right", va="top", fontsize=15,
                    fontweight="bold", color=C["ink"])
            ax.set_xticks([ys[0], ys[-1]], [str(ys[0]), str(ys[-1])])
            ax.tick_params(labelsize=10)
            sh_last = s["edgar"][t]["shares"].get(ys[-1]) or s["edgar"][t]["shares"].get(str(ys[-1]))
            L.add(sl, f"{t} share index FY{ys[-1]} (FY{ys[0]}=100)", f"{idx[-1]:.0f}", idx[-1], EDGAR_SRC, s["edgar"][t]["shares_tag"],
                  f"FY{ys[0]}-FY{ys[-1]}", E.filing_url(s["edgar"][t]["cik"], sh_last["accn"]),
                  "chain of within-filing year-over-year ratios; immune to stock splits")
        axs[0, 0].set_ylim(min(min(v[2]) for v in series.values()) - 8, 124)
        f.tight_layout(h_pad=1.4, w_pad=0.8)
        path = save(f, self.tmp / "shares.png")
        fewer = sum(series[t][2][-1] < 100 for t in series)
        lo = order[0]
        title = f"{fewer} of {len(series)} companies have fewer shares than ten years ago"
        sub = (f"Each line is shares outstanding indexed to 100 ten fiscal years ago. A falling line means each share we own is a "
               f"larger slice of the business; {series[lo][0]} has retired {100 - series[lo][2][-1]:.0f}% of its shares.")
        slide = self.d.page("What we own", title, sub,
                            source="Source: company 10-K filings via SEC EDGAR. Weighted-average diluted shares (Alphabet: shares outstanding at "
                                   "year end, the only all-class series it files). Year-over-year ratios are taken from within one filing, so stock "
                                   "splits (Alphabet's 20-for-1 in 2022, for example) do not distort the line.")
        self.d.picture(slide, path)

    # ---------- 9 capital allocation
    def capital(self):
        """Where ten years of each company's operating cash went. Cumulative over the decade,
        so a single odd year (a pandemic year with little operating cash) cannot dominate."""
        s, L = self.s, self.L
        sl = "Capital allocation"
        w = wnorm(s)
        comps = [("capex", "Capital spending"), ("acquisitions", "Acquisitions"), ("dividends", "Dividends"),
                 ("buybacks", "Share repurchases")]
        rows = []
        for h in holdings(s):
            t = h["ticker"]
            ys = fy_window(s, t)
            cfo = sum(ev(s, t, "cfo", y)["val"] for y in ys)
            shares_ = {k: sum(ev(s, t, k, y)["val"] for y in ys) / cfo * 100 for k, _ in comps}
            rows.append(dict(t=t, name=h["name"], ys=ys, cfo=cfo, **shares_))
            for k, lab in comps:
                L.add(sl, f"{t} {lab.lower()}, % of operating cash flow, 10 yrs", f"{shares_[k]:.0f}%", shares_[k], EDGAR_SRC,
                      f"sum {E.CONCEPTS[k][0]} / sum NetCashProvidedByUsedInOperatingActivities", f"FY{ys[0]}-FY{ys[-1]}",
                      cik_url(s, t, "cfo", ys[-1]), "ten fiscal years summed")
        port = {k: sum(w[r["t"]] * r[k] for r in rows) for k, _ in comps}
        rows.sort(key=lambda r: r["dividends"] + r["buybacks"])
        rows.append(dict(t="PORT", name="Portfolio, weighted", **port))
        f, ax = fig(CONTENT_W, CONTENT_H)
        y = np.arange(len(rows))
        y = np.where(y == len(rows) - 1, y + 0.45, y)  # separate the portfolio row
        left = np.zeros(len(rows))
        for (k, lab), col in zip(comps, CAT):
            v = np.array([r[k] for r in rows])
            ax.barh(y, v, 0.66, left=left, color=col, label=lab, edgecolor=C["surface"], linewidth=1.5)
            for yi, vi, li in zip(y, v, left):
                if vi >= 9:
                    ax.text(li + vi / 2, yi, f"{vi:.0f}", ha="center", va="center", fontsize=10, color="white", fontweight="bold")
            left += v
        for yi, tot in zip(y, left):
            ax.text(tot + 2, yi, f"{tot:.0f}%", va="center", fontsize=11, color=C["ink"], fontweight="bold")
        ax.axvline(100, color=C["ink"], lw=1, ls=(0, (4, 3)))
        ax.set_yticks(y, [r["name"] for r in rows])
        ax.get_yticklabels()[-1].set_fontweight("bold")
        ax.tick_params(axis="y", labelsize=12, labelcolor=C["ink"])
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", visible=True)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax.set_xlim(0, max(left) + 22)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=4, fontsize=11)
        ax.set_xlabel("Share of ten years' operating cash flow (dashed line: 100%)", fontsize=11, color=C["ink_muted"])
        f.tight_layout()
        path = save(f, self.tmp / "capital.png")
        ret = port["dividends"] + port["buybacks"]
        inv = port["capex"] + port["acquisitions"]
        for k, lab in comps:
            L.add(sl, f"Portfolio {lab.lower()}, % of operating cash flow", f"{port[k]:.0f}%", port[k], EDGAR_SRC,
                  "weighted average of the company rows", "ten fiscal years", "", "weights exclude cash")
        L.add(sl, "Portfolio returned to owners", f"{ret:.0f}%", ret, EDGAR_SRC, "dividends + buybacks", "ten fiscal years", "")
        L.add(sl, "Portfolio reinvested", f"{inv:.0f}%", inv, EDGAR_SRC, "capex + acquisitions", "ten fiscal years", "")
        over = [r["name"] for r in rows[:-1] if sum(r[k] for k, _ in comps) > 100]
        L.add(sl, "Companies above 100% of operating cash flow", str(len(over)), len(over), EDGAR_SRC, "count of company rows over 100%",
              "ten fiscal years", "", ", ".join(over))
        title = f"In ten years our companies paid owners {ret:.0f}% of operating cash"
        words = {0: "None", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}
        sub = (f"They reinvested another {inv:.0f}% in their businesses. {words.get(len(over), len(over))} of {words[len(rows) - 1].lower()} companies "
               f"spent more than their operating cash flow over the decade, drawing on borrowing or cash on hand.")
        slide = self.d.page("What we own", title, sub,
                            source="Source: company 10-K cash flow statements via SEC EDGAR, ten fiscal years summed per company. " + offcal_text(s) +
                                   " Portfolio row weights companies as held today. Lines a company does not file in a year "
                                   "count as zero; each case is listed in the review checklist." + self.note("capital"))
        self.d.picture(slide, path)
        self.summary.update(payout_10y=ret, reinvest_10y=inv)

    # ---------- 10 featured holding
    def featured(self):
        s, L = self.s, self.L
        t = s["portfolio"]["featured"]
        h = next(h for h in holdings(s) if h["ticker"] == t)
        sl = f"Featured: {h['name']}"
        ys = fy_window(s, t)
        rev = [ev(s, t, "revenue", y)["val"] / 1e9 for y in ys]
        om = [ev(s, t, "operating_income", y)["val"] / ev(s, t, "revenue", y)["val"] * 100 for y in ys]
        shs = share_series(s, t)
        fcfps = [(ev(s, t, "cfo", y)["val"] - ev(s, t, "capex", y)["val"]) / shs[y] for y in ys]
        f, axs = fig(CONTENT_W, CONTENT_H, ncols=3)
        for ax, (ttl, v, fmt) in zip(axs, [("Revenue, $ billions", rev, "${:,.0f}bn"), ("Operating margin, %", om, "{:.1f}%"),
                                           ("Free cash flow per share, $", fcfps, "${:,.2f}")]):
            ax.bar(range(len(ys)), v, 0.64, color=[P["context"]] * (len(ys) - 1) + [CAT[0]])
            ax.set_title(ttl, fontsize=13, pad=6)
            ax.set_xticks([0, len(ys) - 1], [f"FY{ys[0]}", f"FY{ys[-1]}"])
            ax.text(len(ys) - 1, v[-1], fmt.format(v[-1]), ha="center", va="bottom", fontsize=12, fontweight="bold", color=C["ink"])
            ax.text(0, v[0], fmt.format(v[0]), ha="center", va="bottom", fontsize=10, color=C["ink_secondary"])
            ax.tick_params(labelsize=10)
            ax.set_ylim(0, max(v) * 1.15)
        f.tight_layout(w_pad=3)
        path = save(f, self.tmp / "featured.png")
        url = cik_url(s, t, "revenue", ys[-1])
        L.add(sl, f"{t} revenue FY{ys[-1]}", f"${rev[-1]:,.0f}bn", rev[-1] * 1e9, EDGAR_SRC, ev(s, t, "revenue", ys[-1])["tag"], f"FY{ys[-1]}", url)
        L.add(sl, f"{t} revenue FY{ys[0]}", f"${rev[0]:,.0f}bn", rev[0] * 1e9, EDGAR_SRC, ev(s, t, "revenue", ys[0])["tag"], f"FY{ys[0]}", cik_url(s, t, "revenue", ys[0]))
        L.add(sl, f"{t} operating margin FY{ys[-1]}", f"{om[-1]:.1f}%", om[-1], EDGAR_SRC, "OperatingIncomeLoss / revenue", f"FY{ys[-1]}", url)
        L.add(sl, f"{t} operating margin FY{ys[0]}", f"{om[0]:.1f}%", om[0], EDGAR_SRC, "OperatingIncomeLoss / revenue", f"FY{ys[0]}", cik_url(s, t, "revenue", ys[0]))
        L.add(sl, f"{t} FCF per share FY{ys[-1]}", f"${fcfps[-1]:,.2f}", fcfps[-1], EDGAR_SRC,
              f"(CFO - capex) / {s['edgar'][t]['shares_tag']}", f"FY{ys[-1]}", cik_url(s, t, "cfo", ys[-1]), "split-consistent share count")
        L.add(sl, f"{t} FCF per share FY{ys[0]}", f"${fcfps[0]:,.2f}", fcfps[0], EDGAR_SRC,
              f"(CFO - capex) / {s['edgar'][t]['shares_tag']}", f"FY{ys[0]}", cik_url(s, t, "cfo", ys[0]), "split-consistent share count")
        g = ((rev[-1] / rev[0]) ** (1 / (len(ys) - 1)) - 1) * 100
        # Compare three-year averages: a single base year (Costco's FY2016 operating cash flow
        # was unusually low) would make a compound growth rate meaningless.
        early, late = float(np.mean(fcfps[:3])), float(np.mean(fcfps[-3:]))
        gf = late / early if early > 0 else None
        L.add(sl, f"{t} revenue CAGR, {len(ys) - 1} years", fmt_pct(g), g, EDGAR_SRC, "revenue", f"FY{ys[0]}-FY{ys[-1]}", url)
        title = f"{h['name']}: revenue up {g:.0f}% a year since fiscal {ys[0]}; operating margin {om[-1]:.1f}%"
        if gf is not None:
            L.add(sl, f"{t} FCF per share, ratio of 3-yr averages", f"{gf:.1f} times", gf, EDGAR_SRC, "FCF per share",
                  f"FY{ys[0]}-{ys[2]} vs FY{ys[-3]}-{ys[-1]}", url, f"mean {late:.2f} / mean {early:.2f}")
            L.add(sl, f"{t} FCF per share, FY{ys[-3]}-{ys[-1]} average", f"${late:,.2f}", late, EDGAR_SRC, "FCF per share",
                  f"FY{ys[-3]}-FY{ys[-1]}", url)
            L.add(sl, f"{t} FCF per share, FY{ys[0]}-{ys[2]} average", f"${early:,.2f}", early, EDGAR_SRC, "FCF per share",
                  f"FY{ys[0]}-FY{ys[2]}", url)
            rel = f"{gf:.1f} times" if gf >= 1 else f"{(1 - gf) * 100:.0f}% below"
            sub = (f"Free cash flow per share averaged ${late:,.2f} in fiscal {ys[-3]}-{ys[-1]}, {rel} the ${early:,.2f} of "
                   f"fiscal {ys[0]}-{ys[2]}. This page rotates through the portfolio; it describes the business, not the stock's return.")
        else:
            sub = "This page rotates through the portfolio; it describes the business, not the stock's return."
        slide = self.d.page("Featured holding", title, sub,
                            source=f"Source: {h['name']} 10-K filings via SEC EDGAR, fiscal years {ys[0]}-{ys[-1]}. Free cash flow = operating cash "
                                   f"flow minus capital expenditure; per share on weighted-average diluted shares.")
        self.d.picture(slide, path)

    # ---------- 11 valuation ranges (roic.ai)
    def _val_rows(self):
        s = self.s
        out = []
        for h in holdings(s):
            t = h["ticker"]
            r = s["roic"][t]
            now = r["ttm_pe"] * r["price_as_of"] * r["split_factor"] / r["price_at_period_end"]
            lows = [a["pe_lo"] for a in r["annual"] if a["pe_lo"] and 0 < a["pe_lo"] < 150]
            highs = [a["pe_hi"] for a in r["annual"] if a["pe_hi"] and 0 < a["pe_hi"] < 150]
            avgs = [a["pe_avg"] for a in r["annual"] if a["pe_avg"] and 0 < a["pe_avg"] < 150]
            out.append(dict(t=t, name=h["name"], w=h["weight"], now=now, lo=min(lows), hi=max(highs), med=st.median(avgs),
                            n=len(avgs), fy0=min(a["fy"] for a in r["annual"]), fy1=max(a["fy"] for a in r["annual"]), r=r))
        return out

    def valuation(self):
        s, L = self.s, self.L
        sl = "Valuation ranges"
        rows = sorted(self._val_rows(), key=lambda v: v["now"] / v["med"])
        f, ax = fig(CONTENT_W, CONTENT_H)
        for i, v in enumerate(rows):
            ax.plot([v["lo"], v["hi"]], [i, i], color=P["context"], lw=9, solid_capstyle="round", alpha=0.55)
            ax.plot([v["med"]], [i], "|", color=C["ink"], ms=18, mew=2)
            col = CAT[0] if v["now"] <= v["med"] else CAT[1]
            ax.plot([v["now"]], [i], "o", color=col, ms=11, mec=C["surface"], mew=2, zorder=5)
            ax.text(max(v["hi"], v["now"]) + 3, i, f"{v['now']:.0f}x now  |  median {v['med']:.0f}x", va="center", fontsize=11, color=C["ink"])
            url = f"https://api.roic.ai/v3.0.0/fundamental/multiples/{v['r']['symbol']}"
            L.add(sl, f"{v['t']} P/E at quarter end", f"{v['now']:.0f}x", v["now"], ROIC_SRC, "pe_ratio (TTM) rolled to quarter-end price",
                  f"TTM to {v['r']['ttm_period_end']}; price {v['r']['price_date']}", url,
                  f"pe_ratio {v['r']['ttm_pe']:.2f} x close {v['r']['price_as_of']} x split {v['r']['split_factor']:g} / close {v['r']['price_at_period_end']} ({v['r']['price_period_end_date']})")
            L.add(sl, f"{v['t']} 10-yr median P/E", f"{v['med']:.0f}x", v["med"], ROIC_SRC, "average_price_earnings_ratio (annual)",
                  f"FY{v['fy0']}-FY{v['fy1']}", url, f"median of {v['n']} fiscal-year averages")
        ax.set_yticks(range(len(rows)), [v["name"] for v in rows])
        ax.tick_params(axis="y", labelsize=12, labelcolor=C["ink"])
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", visible=True)
        ax.set_xlim(0, max(max(v["hi"], v["now"]) for v in rows) + 30)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}x"))
        ax.set_xlabel("Price to trailing earnings. Bar: range of yearly highs and lows over ten fiscal years. Tick: median. Dot: quarter end.",
                      fontsize=11, color=C["ink_muted"])
        f.tight_layout()
        path = save(f, self.tmp / "valuation.png")
        above = sum(v["now"] > v["med"] for v in rows)
        w = wnorm(s)
        ey = sum(w[v["t"]] / v["now"] for v in rows) * 100
        d10, v10 = at(fs(s, "DGS10"), self.as_of)
        L.add(sl, "Portfolio earnings yield", fmt_pct(ey), ey, ROIC_SRC, "weighted 1 / P/E", self.s["as_of"], "", "weights exclude cash")
        L.add(sl, "10-year Treasury", fmt_pct(v10, 2), v10, FRED_SRC, "DGS10", str(d10), fs(s, "DGS10").attrs["url"])
        old_rows = [f"{v['name']} ({pd.Timestamp(v['r']['ttm_period_end']).strftime('%B %Y')})" for v in rows
                    if (self.as_of - dt.date.fromisoformat(v["r"]["ttm_period_end"])).days > 200]
        stale = (" Older trailing data, because later vendor rows are empty: " + ", ".join(old_rows) + ".") if old_rows else ""
        title = f"{above} of {len(rows)} holdings trade above their own ten-year median P/E"
        sub = (f"The portfolio's weighted earnings yield is {ey:.1f}%, against {v10:.2f}% on the 10-year Treasury. "
               f"Valuation is one input to our decisions, not a forecast.")
        slide = self.d.page("Valuation", title, sub,
                            source="Source: roic.ai standardized multiples, Federal Reserve H.15 via FRED. Trailing GAAP diluted earnings "
                                   "from the latest quarter reported 45 days before quarter end, rolled forward to the quarter-end price." + stale)
        self.d.picture(slide, path)
        self.summary.update(port_earnings_yield=ey, above_median=int(above))

    # ---------- 12 valuation table (roic.ai)
    def valuation_table(self):
        s, L = self.s, self.L
        sl = "Valuation table"
        rows = [["Company", "Weight", "P/E now", "10-yr median", "vs median", "EV / EBITDA", "Return on\ninvested capital", "Trailing data\nthrough"]]
        for v in sorted(self._val_rows(), key=lambda v: -v["w"]):
            r = v["r"]
            url = f"https://api.roic.ai/v3.0.0/fundamental/multiples/{r['symbol']}"
            prem = (v["now"] / v["med"] - 1) * 100
            L.add(sl, f"{v['t']} P/E at quarter end", f"{v['now']:.1f}x", v["now"], ROIC_SRC, "pe_ratio (TTM, GAAP diluted EPS) rolled to quarter-end price",
                  f"TTM to {r['ttm_period_end']}; price {r['price_date']}", url)
            L.add(sl, f"{v['t']} 10-yr median P/E", f"{v['med']:.1f}x", v["med"], ROIC_SRC, "average_price_earnings_ratio (annual)",
                  f"FY{v['fy0']}-FY{v['fy1']}", url, f"median of {v['n']} fiscal-year averages")
            rows.append([v["name"], f"{v['w']:.0f}%", f"{v['now']:.1f}x", f"{v['med']:.1f}x",
                         L.add(sl, f"{v['t']} premium to median", fmt_pct(prem, 0, sign=True), prem, ROIC_SRC, "P/E now / median - 1", r["ttm_period_end"], url),
                         L.add(sl, f"{v['t']} EV/EBITDA", f"{r['ttm_ev_ebitda']:.1f}x", r["ttm_ev_ebitda"], ROIC_SRC, "ev_to_ttm_ebitda",
                               f"TTM to {r['ttm_period_end']}", url, "at the period-end price, not rolled forward"),
                         L.add(sl, f"{v['t']} ROIC", fmt_pct(r["roic_ttm"]), r["roic_ttm"], ROIC_SRC, "return_on_inv_capital",
                               f"TTM to {r['roic_period_end']}", f"https://api.roic.ai/v3.0.0/fundamental/ratios/profitability/{r['symbol']}"),
                         pd.Timestamp(r["ttm_period_end"]).strftime("%b %Y")])
        slide = self.d.page("Valuation", "Valuation and returns on capital, holding by holding",
                            "P/E rolled to the quarter-end price; enterprise value to EBITDA at the vendor's period-end price.",
                            source="Source: roic.ai standardized fundamentals. Return on invested capital as defined by the vendor. "
                                   "Trailing data end on the dates shown; vendor fundamentals can lag company filings by a quarter or more.")
        self.d.table(slide, M, 2.0, W - 2 * M, rows, [2.6, 0.9, 1.25, 1.4, 1.3, 1.45, 1.6, 1.7], font_size=12, row_h=0.37)

    # ---------- 13 positioning
    def positioning(self):
        s, L = self.s, self.L
        sl = "Positioning"
        hs = sorted(holdings(s), key=lambda h: h["weight"])
        sectors = {}
        for h in hs:
            sectors[h["sector"]] = sectors.get(h["sector"], 0) + h["weight"]
        sectors["Cash"] = s["portfolio"]["cash_weight"]
        sec = sorted(sectors.items(), key=lambda kv: kv[1])
        f, (a1, a2) = fig(CONTENT_W, CONTENT_H, ncols=2)
        for ax, items, ttl in [(a1, [(h["name"], h["weight"]) for h in hs], "By holding"), (a2, sec, "By sector")]:
            ax.barh(range(len(items)), [v for _, v in items], 0.62, color=[P["context"] if n == "Cash" else CAT[0] for n, _ in items])
            ax.set_yticks(range(len(items)), [n for n, _ in items])
            ax.tick_params(axis="y", labelsize=11.5, labelcolor=C["ink"])
            for i, (_, v) in enumerate(items):
                ax.text(v + 0.3, i, f"{v:.0f}%", va="center", fontsize=11, color=C["ink"])
            ax.set_title(ttl, fontsize=13)
            ax.grid(axis="y", visible=False)
            ax.set_xticks([])
            ax.spines["bottom"].set_visible(False)
            ax.set_xlim(0, max(v for _, v in items) * 1.2)
        f.tight_layout(w_pad=4)
        path = save(f, self.tmp / "positioning.png")
        for h in hs:
            L.add(sl, f"{h['ticker']} weight", f"{h['weight']:.0f}%", h["weight"], "Firm holdings file", f"config/portfolio-{s['period']}.json",
                  s["as_of"], "")
        for n, v in sec:
            L.add(sl, f"{n} weight", f"{v:.0f}%", v, "Firm holdings file", "sum of holding weights by the firm's sector classification", s["as_of"], "")
        top = max(hs, key=lambda h: h["weight"])
        title = f"{len(hs)} holdings in {len(sectors) - 1} sectors; the largest, {top['name']}, is {top['weight']:.0f}%"
        slide = self.d.page("Positioning", title,
                            f"Weights at {long_date(s['as_of'])}, as a share of the strategy's model portfolio, including cash.",
                            source=f"Source: {BRAND['firm_name']} holdings records. Sector classification is the firm's own.")
        self.d.picture(slide, path)
        self.summary.update(weights={h["ticker"]: h["weight"] for h in hs}, cash=s["portfolio"]["cash_weight"])

    # ---------- 14 what changed
    def changed(self):
        s, L = self.s, self.L
        sl = "What changed"
        filings = {}
        for t, rec in s["edgar"].items():
            for fl in rec["filings_in_quarter"]:
                filings[fl["form"]] = filings.get(fl["form"], 0) + 1
        self.summary.update(filings=filings)
        prev = self.prev
        if not prev:
            slide = self.d.page("Since last quarter", "What changed since last quarter",
                                "No archived review for the previous quarter was found, so there is nothing to compare yet.")
            return
        cur = self.summary
        rows = [["Market and economy", prev["label_short"], s["period"].replace("-", " "), "Change"]]

        def r(lab, key, unit="%", d=2):
            a, b = prev["summary"].get(key), cur.get(key)
            if a is None or b is None:
                return
            ch = b - a
            disp_ch = f"{ch:+.{d}f} pt" if unit in ("%", "pt") else f"{ch:+,.0f}"
            if unit == "%":
                da, db = f"{a:.{d}f}%", f"{b:.{d}f}%"
            elif unit == "pt":
                da, db = f"{a:+.{d}f}", f"{b:+.{d}f}"
            else:
                da, db = f"{a:,.0f}", f"{b:,.0f}"
            L.add(sl, f"{lab}, previous review", da, a, "archived previous review", key, prev["as_of"],
                  f"runs/{prev['period']}/summary.json")
            L.add(sl, f"{lab}, this review", db, b, "this review", key, s["as_of"], "")
            rows.append([lab, da, db,
                         L.add(sl, f"{lab} change", disp_ch, ch, "this deck and the archived previous deck", key,
                               f"{prev['as_of']} to {s['as_of']}", "", "difference of the two archived values")])
        r("10-year Treasury yield", "dgs10")
        r("2-year Treasury yield", "dgs2")
        r("10-year minus 3-month, pt", "spread_10y3m", unit="pt")
        r("10-year real yield", "real10")
        r("Effective federal funds rate", "fedfunds")
        r("CPI inflation, year over year", "cpi_yoy", d=1)
        r("Unemployment rate", "unrate", d=1)
        r("Payrolls, 3-month average change (k)", "payrolls_3m", unit="k", d=0)
        rows2 = [["Portfolio", prev["label_short"], s["period"].replace("-", " "), "Change"]]
        pw, cw = prev["summary"].get("weights", {}), cur.get("weights", {})
        for t in sorted(set(pw) | set(cw), key=lambda t: (-(cw.get(t, 0) - pw.get(t, 0)), t)):
            a, b = pw.get(t, 0), cw.get(t, 0)
            if a != b:
                name = next((h["name"] for h in holdings(s) if h["ticker"] == t), t)
                L.add(sl, f"{t} weight, previous review", f"{a:.0f}%", a, "Firm holdings file", f"config/portfolio-{prev['period']}.json", prev["as_of"], "")
                rows2.append([name, f"{a:.0f}%", f"{b:.0f}%", L.add(sl, f"{t} weight change", f"{b - a:+.0f} pt", b - a, "Firm holdings file",
                                                                   "weight", f"{prev['as_of']} to {s['as_of']}", "")])
        moved = len(rows2) - 1  # holdings only; cash is not a position
        a, b = prev["summary"].get("cash", 0), cur.get("cash", 0)
        if a != b:
            L.add(sl, "Cash weight, previous review", f"{a:.0f}%", a, "Firm holdings file", f"config/portfolio-{prev['period']}.json", prev["as_of"], "")
            L.add(sl, "Cash weight change", f"{b - a:+.0f} pt", b - a, "Firm holdings file", "cash_weight", f"{prev['as_of']} to {s['as_of']}", "")
            rows2.append(["Cash", f"{a:.0f}%", f"{b:.0f}%", f"{b - a:+.0f} pt"])
        nf = sum(filings.values())
        rows2.append(["Company filings during the quarter", "", "",
                      L.add(sl, "Filings in quarter", f"{nf}", nf, EDGAR_SRC, "submissions: 10-K, 10-Q, 8-K, proxy", f"{s['q_start']} to {s['as_of']}",
                            "https://www.sec.gov/cgi-bin/browse-edgar", ", ".join(f"{k} {v}" for k, v in sorted(filings.items())))])
        title = f"Since last quarter: {moved} weight changes; 10-year yield {cur['dgs10'] - prev['summary']['dgs10']:+.2f} pt"
        slide = self.d.page("Since last quarter", title,
                            f"Compared with the archived review for the {(prev['label'][0].lower() + prev['label'][1:]).replace(' quarter ', ' quarter of ')}. Previous values "
                            f"are read from that review's archive, not retyped.",
                            source="Sources: as on the earlier pages; previous values read from the archived snapshot of the previous review. "
                                   "Company filings counted from SEC EDGAR submissions (10-K, 10-Q, 8-K, proxy statements).")
        self.d.table(slide, M, 2.0, 6.55, rows, [3.05, 1.1, 1.1, 1.3], font_size=12, row_h=0.37)
        self.d.table(slide, M + 6.85, 2.0, W - 2 * M - 6.85, rows2, [2.6, 0.8, 0.8, 1.17], font_size=12, row_h=0.37)

    # ---------- 15 sources and methodology
    def methodology(self, audience):
        s = self.s
        fred_ids = ", ".join(s["fred"].keys())
        left = [
            [("Data sources", {"bold": True, "size": 13, "color": C["ink"]})],
            f"FRED (Federal Reserve Bank of St. Louis): {fred_ids}. Only series FRED labels Public Domain: Citation Requested "
            f"(Federal Reserve H.15 and G.17, BLS). Retrieved {s['fred']['DGS10']['retrieved'][:10]}.",
            "SEC EDGAR: XBRL company facts (data.sec.gov/api/xbrl/companyfacts) for ten holdings; one company extension element read "
            "from the filing's own XBRL instance (Alphabet acquisitions); filing lists from data.sec.gov/submissions.",
        ]
        left.append("roic.ai v3 API: standardized TTM and annual valuation multiples, return on invested capital, daily prices and "
                    "split history, used under roic.ai's terms of use.")
        left += [
            "Firm records: holdings, weights and sector classification (config/portfolio-<period>.json).",
            [("What is not in this review", {"bold": True, "size": 13, "color": C["ink"]})],
            "Investment performance, returns, benchmarks, forecasts and recommendations. Pages describe markets and businesses only.",
        ]
        right = [
            [("Methods", {"bold": True, "size": 13, "color": C["ink"]})],
            "Point in time: company figures come only from 10-Ks filed on or before the as-of date; each fiscal year uses the most recent "
            "filed restatement. Monthly economic data are treated as published 45 days after the month begins.",
            offcal_text(s),
            "Tags: each figure uses an ordered list of XBRL tags; changes of tag and gaps are listed in the review checklist.",
            "Share counts are chain-linked using year-over-year ratios taken from within one filing, so stock splits do not distort them.",
            "Portfolio figures weight each holding by its share of invested assets (cash excluded).",
            "Every number shown is listed, with its source record, in the figure ledger archived with this deck.",
        ]
        slide = self.d.page("Sources and methodology", "How this review is built",
                            f"Data as of {long_date(s['as_of'])}. Built {s['fetch_date']} by the firm's client-deck routine.")
        self.d.text(slide, M, 2.0, 5.95, 4.6, left, size=11.5, color=C["ink_secondary"], spacing=7)
        self.d.text(slide, M + 6.3, 2.0, 5.95, 4.6, right, size=11.5, color=C["ink_secondary"], spacing=7)

    # ---------- 16 disclosures
    def disclosures(self, signoff):
        s = self.s
        paras = [
            BRAND["standing_disclosure"],
            "[Firm-specific disclosure language approved by the Chief Compliance Officer goes here: adviser registration status, "
            "where the Form ADV Part 2 can be obtained, risks of the strategy, and any language the firm's policies require.]",
            "This review does not report or imply investment performance. Statements about markets describe conditions on the "
            "dates shown and are not predictions. Past company results do not indicate future results.",
            "Third-party data are used under each provider's terms. Treasury and economic data: Board of Governors of the Federal "
            "Reserve System and U.S. Bureau of Labor Statistics, via FRED, Federal Reserve Bank of St. Louis. Company data: filings "
            "with the U.S. Securities and Exchange Commission. Valuation multiples and returns on capital: roic.ai.",
            [("Review record", {"bold": True, "size": 14, "color": C["ink"]})],
            (f"Approved for distribution by {signoff}." if signoff else
             "NOT APPROVED. This draft has not been reviewed by the firm's compliance function and must not be distributed."),
        ]
        slide = self.d.page("Before you read further", "Important information", None)
        self.d.text(slide, M, 1.55, W - 2 * M, 5.0, paras, size=12, color=C["ink_secondary"], spacing=9)
