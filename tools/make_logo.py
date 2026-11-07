"""Draws the fictional firm's logo (a larkspur spire beside the wordmark) to brand/logo.png.
A real firm skips this: Lesson 1 copies its existing logo file into brand/."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse
import json, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
b = json.load(open(root / "brand" / "brand.json"))
ink, acc = b["colors"]["primary"], b["colors"]["accent"]
f = plt.figure(figsize=(3.85, 1.0), dpi=400)
ax = f.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 3.85); ax.set_ylim(0, 1); ax.axis("off")
ax.plot([0.42, 0.42], [0.08, 0.92], color=acc, lw=2.2, solid_capstyle="round")
for i, y in enumerate([0.22, 0.38, 0.53, 0.66, 0.77, 0.86]):
    s = 0.17 - i * 0.022
    for side in (-1, 1):
        ax.add_patch(Ellipse((0.42 + side * s * 0.62, y), s * 1.15, s * 0.62, angle=side * 28, color=ink))
ax.text(0.85, 0.58, "LARKSPUR VALE", fontsize=25, family=b["fonts"]["heading"], color=ink, va="center")
ax.text(0.87, 0.2, "C A P I T A L", fontsize=11, family=b["fonts"]["body"], color=acc, va="center", fontweight="bold")
f.savefig(root / "brand" / "logo.png", transparent=True)
print("wrote brand/logo.png")
