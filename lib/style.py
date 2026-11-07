"""Chart styling that reads brand.json, so every chart matches the deck without per-chart work."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .common import ROOT, load_json  # noqa: E402

BRAND = load_json(ROOT / "brand" / "brand.json")
C = BRAND["colors"]
P = BRAND["chart_palette"]
CAT = P["categorical"]
DPI = 220


def setup():
    names = {f.name for f in font_manager.fontManager.ttflist}
    body = BRAND["fonts"]["body"] if BRAND["fonts"]["body"] in names else "DejaVu Sans"
    plt.rcParams.update({
        "font.family": body,
        "font.size": 12,
        "axes.edgecolor": C["rule"],
        "axes.labelcolor": C["ink_secondary"],
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlecolor": C["ink"],
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": P["grid"],
        "grid.linewidth": 0.8,
        "xtick.color": C["ink_muted"],
        "ytick.color": C["ink_muted"],
        "xtick.labelsize": 11,
        "ytick.labelsize": 11,
        "ytick.left": False,
        "legend.frameon": False,
        "legend.fontsize": 11,
        "lines.linewidth": 2.0,
        "figure.facecolor": C["surface"],
        "axes.facecolor": C["surface"],
        "savefig.facecolor": C["surface"],
    })


def fig(w_in, h_in, **kw):
    setup()
    return plt.subplots(figsize=(w_in, h_in), **kw)


def save(f, path):
    f.savefig(path, dpi=DPI)
    plt.close(f)
    return path


def label_end(ax, x, y, text, color, dy=0, ha="left", weight="bold", size=11):
    """Direct label at a line's end (secondary encoding: identity never by color alone)."""
    ax.annotate(text, (x, y), xytext=(6, dy), textcoords="offset points", va="center",
                ha=ha, color=C["ink"], fontsize=size, fontweight=weight,
                bbox=dict(boxstyle="round,pad=0.15", fc=C["surface"], ec="none", alpha=0.85))
    ax.plot([x], [y], "o", ms=6, color=color, mec=C["surface"], mew=1.5, zorder=5)


def end_labels(ax, items, min_gap_frac=0.075, size=11):
    """Direct labels at line ends, pushed apart vertically so they never collide.
    items: (x, y, text, color). Call after the y-limits are final."""
    lo, hi = ax.get_ylim()
    gap = (hi - lo) * min_gap_frac
    order = sorted(range(len(items)), key=lambda i: items[i][1])
    ys = [items[i][1] for i in order]
    for _ in range(50):
        moved = False
        for k in range(1, len(ys)):
            if ys[k] - ys[k - 1] < gap:
                push = (gap - (ys[k] - ys[k - 1])) / 2
                ys[k - 1] -= push
                ys[k] += push
                moved = True
        if not moved:
            break
    for k, i in enumerate(order):
        x, y, text, color = items[i]
        ax.plot([x], [y], "o", ms=6, color=color, mec=C["surface"], mew=1.5, zorder=5)
        ax.annotate(text, (x, ys[k]), xytext=(8, 0), textcoords="offset points", va="center", ha="left",
                    color=C["ink"], fontsize=size, fontweight="bold", annotation_clip=False,
                    bbox=dict(boxstyle="round,pad=0.15", fc=C["surface"], ec="none", alpha=0.85))


def trim_time_ticks(ax, last):
    """Time axes leave room on the right for end labels; drop the tick labels that would
    fall in that empty space so the chart never seems to show future years."""
    import matplotlib.dates as mdates
    import pandas as pd
    limit = mdates.date2num(pd.Timestamp(last))
    lo = ax.get_xlim()[0]
    ax.set_xticks([t for t in ax.get_xticks() if lo - 1 <= t <= limit + 1])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
