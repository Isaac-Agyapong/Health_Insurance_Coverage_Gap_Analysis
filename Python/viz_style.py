"""Shared chart style: a bold infographic look (Bahnschrift condensed type, clean off-white canvas, one meaning per
colour). The Power BI report uses the same palette.

Colour meanings, used the same way in every chart, the dashboard and the README:
    EXP     emerald: states that expanded Medicaid (and the estimated effect of expansion)
    NONEXP  rose: states that had not expanded by 2023
    SUN     sunflower: the highlighted finding or group
    GREY    everything else (context series, excluded states)
    INDIGO  sequential scale for uninsured rates on maps (used for nothing else)
"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FuncFormatter

EXP, EXP_2, EXP_L = "#0e9f6e", "#3dbb8f", "#9bdcc3"
NONEXP, NONEXP_L = "#d63f6c", "#f2a7bd"
SUN, SUN_L = "#f5b700", "#fbe3a0"
GREY, GREY_LIGHT = "#8a94a0", "#cdd3da"
PAPER, INK, INK_2, RULE = "#f5f6f1", "#1f2d3d", "#5b6b7c", "#e2e6df"
FONT = ["Bahnschrift", "Segoe UI", "DejaVu Sans"]
INDIGO_SCALE = LinearSegmentedColormap.from_list(
    "indigo", ["#eeeaf7", "#d2c8ee", "#a999dd", "#7e6cc7", "#5a48a8", "#3b2b7a"])
GROUP_COLORS = {
    "Expanded 2014": EXP,
    "Expanded 2015-2017": EXP_2,
    "Expanded 2019-2022": EXP_L,
    "Not expanded by 2023": NONEXP,
    "Excluded (early coverage)": GREY_LIGHT,
}

IMAGE_DIR = Path(__file__).resolve().parents[1] / "Image"
IMAGE_DIR.mkdir(exist_ok=True)


def apply():
    plt.rcParams.update({
        "figure.facecolor": PAPER, "axes.facecolor": PAPER, "savefig.facecolor": PAPER,
        "figure.dpi": 110, "savefig.dpi": 150, "figure.figsize": (9, 4.8),
        "font.family": FONT, "font.size": 10.5,
        "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
        "axes.edgecolor": GREY_LIGHT, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": RULE, "grid.linewidth": 0.8,
        "axes.axisbelow": True, "axes.titlesize": 15, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.titlepad": 30,
        "legend.frameon": False, "lines.linewidth": 2.6, "lines.solid_capstyle": "round",
        "xtick.major.size": 0, "ytick.major.size": 0,
    })


def title(ax, text, sub=None):
    """Bold condensed headline stating the finding, plus a grey one-line takeaway underneath."""
    ax.set_title(text, fontsize=15, fontweight="bold", loc="left", pad=30 if sub else 12, color=INK)
    if sub:   # offset in points (not axes fraction) so it sits the same distance under the title at any figure height
        ax.annotate(sub, (0, 1), xycoords="axes fraction", xytext=(0, 9), textcoords="offset points",
                    color=INK_2, fontsize=10.5, va="bottom")


def pct(ax, axis="y", decimals=0):
    fmt = FuncFormatter(lambda v, _: f"{v:.{decimals}f}%")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def pts(ax, axis="y"):
    fmt = FuncFormatter(lambda v, _: f"{v:+.0f}" if v else "0")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def source(fig, text="Source: Census SAHIE 2008-2023; KFF expansion tracker. Adults 18-64 at or below 138% of poverty."):
    fig.text(0.01, -0.02, text, color=GREY, fontsize=8, ha="left", va="top")


def save(fig, name):
    fig.tight_layout()
    fig.savefig(IMAGE_DIR / f"{name}.png", bbox_inches="tight")
    plt.close(fig)
