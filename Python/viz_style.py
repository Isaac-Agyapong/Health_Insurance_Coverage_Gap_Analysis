"""Shared chart style: a policy-brief look (ivory paper, serif titles, one meaning per colour).

Colour meanings, used the same way in every chart, the dashboard and the app:
    NAVY    states that expanded Medicaid (and the model's estimated effect)
    ORANGE  states that had not expanded by 2023
    GOLD    the highlighted finding or group
    GREY    everything else (context series, excluded states)
"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

NAVY, ORANGE, GOLD = "#1d4e89", "#d1603d", "#d99a1e"
NAVY_LIGHT, ORANGE_LIGHT = "#9fb6d4", "#efb7a3"
GREY, GREY_LIGHT = "#8a8780", "#cfccc4"
PAPER, INK, INK_2, RULE = "#f7f5ef", "#1b1b1b", "#55524c", "#dedad0"
GROUP_COLORS = {
    "Expanded 2014": NAVY,
    "Expanded 2015-2017": "#4f7cb3",
    "Expanded 2019-2022": NAVY_LIGHT,
    "Not expanded by 2023": ORANGE,
    "Excluded (early coverage)": GREY_LIGHT,
}

IMAGE_DIR = Path(__file__).resolve().parents[1] / "Image"
IMAGE_DIR.mkdir(exist_ok=True)


def apply():
    plt.rcParams.update({
        "figure.facecolor": PAPER, "axes.facecolor": PAPER, "savefig.facecolor": PAPER,
        "figure.dpi": 110, "savefig.dpi": 150, "figure.figsize": (9, 4.8),
        "font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 10,
        "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
        "axes.edgecolor": GREY_LIGHT, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": RULE, "grid.linewidth": 0.7,
        "axes.axisbelow": True, "axes.titlesize": 14, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.titlepad": 30,
        "legend.frameon": False, "lines.linewidth": 2.2,
        "xtick.major.size": 0, "ytick.major.size": 0,
    })


def title(ax, text, sub=None):
    """Serif headline stating the finding, plus a grey one-line takeaway underneath."""
    ax.set_title(text, fontfamily="Georgia", fontsize=14, fontweight="bold", loc="left", pad=30 if sub else 12)
    if sub:
        ax.text(0, 1.03, sub, transform=ax.transAxes, color=INK_2, fontsize=10, va="bottom")


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
