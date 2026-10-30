"""Shared look and feel for every figure.

Keeping colours and fonts in one place means the report, the maps and the
dashboard look like one project rather than three.
"""

from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt

# A small, colour-blind-friendly palette.
COLORS = {
    "ink": "#1b2a3a",
    "muted": "#6b7c8f",
    "grid": "#dde3ea",
    "accent": "#c8553d",
    "blue": "#2f6f8f",
    "green": "#3f8f6b",
    "sand": "#d9a441",
    "grey": "#9aa7b4",
}

COUNTRY_COLORS = {
    "FRA": "#2f6f8f",
    "IND": "#c8553d",
    "USA": "#3f8f6b",
}

# Sequential scales for hazard / exposure / risk, and a diverging scale for
# clusters.
CMAP_HAZARD = "YlOrRd"
CMAP_RISK = "magma_r"
CMAP_DEVELOPMENT = "viridis"
CMAP_EXPOSURE = "cividis"

LISA_COLORS = {
    "HH": "#b2182b",
    "LL": "#2166ac",
    "HL": "#ef8a62",
    "LH": "#67a9cf",
    "not significant": "#e6e6e6",
    "no neighbours": "#c9c9c9",
}


def apply_style() -> None:
    """Set matplotlib defaults used by all static figures."""
    mpl.rcParams.update({
        "figure.dpi": 120,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.edgecolor": COLORS["muted"],
        "axes.labelcolor": COLORS["ink"],
        "axes.titlecolor": COLORS["ink"],
        "text.color": COLORS["ink"],
        "xtick.color": COLORS["muted"],
        "ytick.color": COLORS["muted"],
        "axes.grid": True,
        "grid.color": COLORS["grid"],
        "grid.linewidth": 0.6,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
    })


def save_figure(fig, path, note: str | None = None) -> None:
    """Save a figure and add a small source note at the bottom."""
    if note:
        fig.text(0.01, 0.005, note, fontsize=7, color=COLORS["muted"], ha="left")
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
