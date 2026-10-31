"""Statistical charts used in the report.

Each function draws one figure and saves it. The figures are deliberately
simple: a reader should understand each one in a few seconds, with the
title and axis labels doing most of the explaining.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from cro.viz import theme

COUNTRY_NAMES = {"FRA": "France", "IND": "India", "USA": "United States"}


def scatter_hazard_development(master: pd.DataFrame, path: Path) -> None:
    """Hazard against development, with one straight line per country.

    One line for all regions would mostly connect the India group to the
    France/USA group. One line per country shows the link *inside* each
    country, which is the fair comparison (hypothesis H2).
    """
    theme.apply_style()
    data = master.dropna(subset=["hazard_equal", "shdi"])

    fig, ax = plt.subplots(figsize=(8.5, 6))

    for iso3, group in data.groupby("iso3"):
        color = theme.COUNTRY_COLORS[iso3]
        ax.scatter(group["hazard_equal"], group["shdi"], s=38, alpha=0.75,
                   color=color, edgecolor="white", linewidth=0.6,
                   label=COUNTRY_NAMES[iso3], zorder=3)

        # Least-squares line for this country only.
        slope, intercept = np.polyfit(group["hazard_equal"], group["shdi"], 1)
        x = np.linspace(group["hazard_equal"].min(), group["hazard_equal"].max(), 50)
        ax.plot(x, intercept + slope * x, color=color, linewidth=2.2, zorder=4)

    # Label the most extreme cases so the chart has a story.
    for _, row in data.nlargest(3, "hazard_equal").iterrows():
        ax.annotate(row["region_name"], (row["hazard_equal"], row["shdi"]),
                    xytext=(6, 6), textcoords="offset points", fontsize=8,
                    color=theme.COLORS["muted"])

    ax.set_xlabel("Climate hazard index (0-1)")
    ax.set_ylabel("Subnational HDI")
    ax.set_title("The big gap is between countries; inside countries it is smaller")
    ax.legend(loc="lower left", fontsize=8)

    theme.save_figure(fig, path, note="Each dot is an admin-1 region. One line per country. "
                                      "Association, not causation.")


def top_regions_bar(master: pd.DataFrame, path: Path, n: int = 5) -> None:
    """The regions with the highest risk inside each country.

    On a shared scale, the whole top 15 is Indian. Showing the top regions
    of each country tells the reader where to look inside France and the USA.
    """
    theme.apply_style()
    parts = [group.nlargest(n, "risk_equal") for _, group in master.groupby("iso3")]
    data = pd.concat(parts).iloc[::-1]

    fig, ax = plt.subplots(figsize=(7.5, 6))
    ax.barh(data["region_name"], data["risk_equal"],
            color=[theme.COUNTRY_COLORS[iso3] for iso3 in data["iso3"]])
    for y, value in enumerate(data["risk_equal"]):
        ax.text(value + 0.01, y, f"{value:.2f}", va="center", fontsize=8,
                color=theme.COLORS["muted"])
    ax.set_xlabel("Risk index (0-1, same scale for all countries)")
    ax.set_title(f"The {n} highest-risk regions in each country")
    ax.grid(axis="y", visible=False)

    handles = [Line2D([0], [0], marker="s", linestyle="", markersize=9,
                      color=theme.COUNTRY_COLORS[iso3], label=name)
               for iso3, name in COUNTRY_NAMES.items()]
    ax.legend(handles=handles, loc="lower right", fontsize=8)

    theme.save_figure(fig, path)


def forest_plot(slopes: pd.DataFrame, path: Path) -> None:
    """Within-country slope of SHDI on hazard, with confidence intervals."""
    theme.apply_style()
    data = slopes.sort_values("slope")

    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    y_positions = np.arange(len(data))

    ax.errorbar(data["slope"], y_positions,
                xerr=[data["slope"] - data["ci_low"], data["ci_high"] - data["slope"]],
                fmt="o", color=theme.COLORS["ink"], ecolor=theme.COLORS["muted"],
                capsize=4, markersize=7)

    ax.axvline(0, color=theme.COLORS["muted"], linewidth=1, linestyle="--")
    ax.set_yticks(y_positions)
    ax.set_yticklabels([f"{COUNTRY_NAMES.get(iso, iso)} (n={n})"
                        for iso, n in zip(data["iso3"], data["n_regions"])])
    ax.set_xlabel("Slope of SHDI on hazard (change from lowest to highest hazard)")
    ax.set_title("The gap inside each country")
    ax.grid(axis="y", visible=False)

    theme.save_figure(fig, path, note="Bars are 95% confidence intervals.")


def coefficient_plot(coefficients: pd.DataFrame, path: Path) -> None:
    """Compare the hazard coefficient with and without country effects."""
    theme.apply_style()
    data = coefficients[coefficients["term"] == "hazard_equal"].reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(7.5, 2.8))
    y = np.arange(len(data))
    ax.errorbar(data["beta"], y,
                xerr=[data["beta"] - data["ci_low"], data["ci_high"] - data["beta"]],
                fmt="s", color=theme.COLORS["blue"], ecolor=theme.COLORS["muted"],
                capsize=4, markersize=8)
    ax.axvline(0, color=theme.COLORS["muted"], linestyle="--", linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(data["model"])
    ax.set_ylim(-0.7, len(data) - 0.3)
    ax.set_xlabel("Hazard coefficient (change in SHDI)")
    ax.set_title("Country effects make the link smaller, but it stays negative")
    ax.grid(axis="y", visible=False)

    theme.save_figure(fig, path, note="Bars are 95% confidence intervals.")


def rank_stability_heatmap(stability: pd.DataFrame, path: Path) -> None:
    """Spearman correlation between index versions."""
    theme.apply_style()
    versions = sorted(set(stability["version_a"]) | set(stability["version_b"]))
    matrix = pd.DataFrame(np.eye(len(versions)), index=versions, columns=versions)

    for row in stability.itertuples():
        matrix.loc[row.version_a, row.version_b] = row.spearman_rho
        matrix.loc[row.version_b, row.version_a] = row.spearman_rho

    fig, ax = plt.subplots(figsize=(5.8, 4.6))
    image = ax.imshow(matrix.to_numpy(), cmap="Blues", vmin=0, vmax=1)

    ax.set_xticks(range(len(versions)))
    ax.set_yticks(range(len(versions)))
    ax.set_xticklabels(versions, rotation=30, ha="right")
    ax.set_yticklabels(versions)
    ax.set_title("Ranking stability across index versions")

    for i in range(len(versions)):
        for j in range(len(versions)):
            value = matrix.iloc[i, j]
            ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if value > 0.6 else theme.COLORS["ink"])

    fig.colorbar(image, ax=ax, shrink=0.8, label="Spearman correlation of ranks")
    ax.grid(False)

    theme.save_figure(fig, path)


def distribution_panels(master: pd.DataFrame, path: Path) -> None:
    """Small multiples of the four main indicators, split by country."""
    theme.apply_style()
    variables = [
        ("hd35_area", "Heat days per year"),
        ("hazard_equal", "Hazard index"),
        ("exposure_score", "Exposure score (population rank)"),
        ("shdi", "Subnational HDI"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for ax, (column, label) in zip(axes.flat, variables):
        data = master.dropna(subset=[column])
        groups = [data.loc[data["iso3"] == iso3, column] for iso3 in ["FRA", "IND", "USA"]]
        box = ax.boxplot(groups, patch_artist=True, widths=0.55,
                         medianprops={"color": theme.COLORS["ink"], "linewidth": 1.6},
                         flierprops={"marker": "o", "markersize": 3,
                                     "markerfacecolor": theme.COLORS["muted"],
                                     "markeredgewidth": 0})
        for patch, iso3 in zip(box["boxes"], ["FRA", "IND", "USA"]):
            patch.set_facecolor(theme.COUNTRY_COLORS[iso3])
            patch.set_alpha(0.65)
            patch.set_edgecolor("white")

        ax.set_xticks([1, 2, 3])
        ax.set_xticklabels(["France", "India", "USA"])
        ax.set_title(label, loc="left")
        ax.grid(axis="x", visible=False)

    fig.suptitle("Distribution of key indicators by country", x=0.01, ha="left",
                 fontsize=14, fontweight="bold")
    theme.save_figure(fig, path)


def plot_all(master: pd.DataFrame, tables: dict, figures_dir: Path) -> list[Path]:
    """Draw every statistical figure."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    scatter_hazard_development(master, figures_dir / "fig_01_hazard_vs_development.png")
    outputs.append(figures_dir / "fig_01_hazard_vs_development.png")

    distribution_panels(master, figures_dir / "fig_02_distributions.png")
    outputs.append(figures_dir / "fig_02_distributions.png")

    top_regions_bar(master, figures_dir / "fig_03_top_regions.png")
    outputs.append(figures_dir / "fig_03_top_regions.png")

    coefficient_plot(tables["coefficients"], figures_dir / "fig_04_coefficients.png")
    outputs.append(figures_dir / "fig_04_coefficients.png")

    forest_plot(tables["slopes"], figures_dir / "fig_05_country_slopes.png")
    outputs.append(figures_dir / "fig_05_country_slopes.png")

    rank_stability_heatmap(tables["stability"], figures_dir / "fig_06_rank_stability.png")
    outputs.append(figures_dir / "fig_06_rank_stability.png")

    return outputs
