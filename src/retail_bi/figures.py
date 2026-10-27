"""Static charts for the README and case study (PNG, light theme).

These are documentation figures. The interactive dashboard lives on
Tableau Public; see docs/TABLEAU_BUILD_GUIDE.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import pandas as pd  # noqa: E402

from . import config  # noqa: E402

log = logging.getLogger(__name__)

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
BLUE_LIGHT = "#86b6ef"
SEQ = ["#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update(
    {
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK_2,
        "axes.titlecolor": INK,
        "axes.titlesize": 13,
        "axes.titleweight": "semibold",
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "font.size": 10,
        "font.family": "DejaVu Sans",
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
    }
)

GBP = mticker.FuncFormatter(
    lambda v, _: "£0" if v == 0 else (f"£{v / 1e6:.1f}M" if abs(v) >= 1e6 else f"£{v / 1e3:.0f}k")
)


def _save(fig: plt.Figure, name: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    fig.savefig(path)
    plt.close(fig)
    log.info("figure %s", path.name)
    return path


def monthly_trend(df: pd.DataFrame, out_dir: Path) -> Path:
    data = df[df["is_complete_month"] == 1].copy()
    data["month"] = pd.to_datetime(data["year_month"])
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(data["month"], data["net_revenue"], color=BLUE, linewidth=2, marker="o", markersize=4)
    ax.yaxis.set_major_formatter(GBP)
    ax.grid(axis="x", visible=False)
    ax.set_ylim(bottom=0)
    ax.set_title("Net revenue by month (complete months, Dec 2009 – Nov 2011)")
    peak = data.loc[data["net_revenue"].idxmax()]
    ax.annotate(
        f"Peak {peak['month']:%b %Y}\n£{peak['net_revenue'] / 1e6:.2f}M",
        (peak["month"], peak["net_revenue"]),
        xytext=(-90, -10),
        textcoords="offset points",
        color=INK_2,
        fontsize=9,
    )
    return _save(fig, "monthly_net_revenue", out_dir)


def top_products(df: pd.DataFrame, out_dir: Path, n: int = 10) -> Path:
    data = df.head(n).iloc[::-1]
    labels = [d.title()[:34] for d in data["description"]]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.barh(labels, data["net_revenue"], color=BLUE, height=0.6)
    ax.xaxis.set_major_formatter(GBP)
    ax.grid(axis="y", visible=False)
    for y, v in enumerate(data["net_revenue"]):
        ax.text(v, y, f"  £{v / 1e3:.0f}k", va="center", color=INK_2, fontsize=8.5)
    ax.set_title(f"Top {n} products by net revenue")
    ax.margins(x=0.12)
    return _save(fig, "top_products", out_dir)


def countries(df: pd.DataFrame, out_dir: Path, n: int = 12) -> Path:
    data = df[df["country"] != "United Kingdom"].head(n).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.barh(data["country"], data["net_revenue"], color=BLUE, height=0.6)
    ax.xaxis.set_major_formatter(GBP)
    ax.grid(axis="y", visible=False)
    uk = df.loc[df["country"] == "United Kingdom", "revenue_share_pct"]
    uk_share = float(uk.iloc[0]) if len(uk) else 0.0
    ax.set_title(f"Top international markets by net revenue (UK excluded: {uk_share:.0f}% of total)")
    return _save(fig, "international_markets", out_dir)


def cohort_heatmap(df: pd.DataFrame, out_dir: Path, max_months: int = 12) -> Path:
    data = df[(df["months_since_first"] >= 1) & (df["months_since_first"] <= max_months)]
    data = data[data["cohort_month"] <= "2010-12"].copy()
    # Drop cells that fall in the partial final month (Dec 2011 has 9 days).
    active = pd.PeriodIndex(data["cohort_month"], freq="M") + data["months_since_first"].to_numpy()
    data = data[active.astype(str) <= config.LAST_COMPLETE_MONTH]
    grid =data.pivot(index="cohort_month", columns="months_since_first", values="retention_pct")
    fig, ax = plt.subplots(figsize=(10, 5.4))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq_blue", SEQ)
    im = ax.imshow(grid.values, cmap=cmap, aspect="auto", vmin=0, vmax=max(40, float(grid.max().max())))
    ax.set_xticks(range(len(grid.columns)), [str(c) for c in grid.columns])
    ax.set_yticks(range(len(grid.index)), grid.index)
    ax.set_xlabel("Months since first purchase")
    ax.grid(False)
    for (i, j), v in pd.DataFrame(grid.values).stack().dropna().items():
        ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7.5, color=INK if v < 30 else SURFACE)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("% of cohort active", color=INK_2)
    cbar.outline.set_visible(False)
    ax.set_title("Monthly cohort retention (% of first-month customers who buy again)")
    return _save(fig, "cohort_retention", out_dir)


def weekday_hour(df: pd.DataFrame, out_dir: Path) -> Path:
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    grid = df.pivot_table(index="day_of_week", columns="hour_of_day", values="orders", aggfunc="sum")
    grid = grid.reindex([d for d in order if d in grid.index]).fillna(0)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq_blue", SEQ)
    im = ax.imshow(grid.values, cmap=cmap, aspect="auto")
    ax.set_xticks(range(len(grid.columns)), [f"{h:02d}" for h in grid.columns])
    ax.set_yticks(range(len(grid.index)), grid.index)
    ax.set_xlabel("Hour of day (UK time)")
    ax.grid(False)
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("Orders", color=INK_2)
    cbar.outline.set_visible(False)
    ax.set_title("When orders are placed")
    return _save(fig, "orders_by_weekday_hour", out_dir)


def cleaning_summary(rule_log: pd.DataFrame, out_dir: Path) -> Path:
    removed = rule_log[(rule_log["action"] == "remove") & (rule_log["rows"] > 0)].sort_values("rows")
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.barh(removed["rule"].str.replace("_", " "), removed["rows"], color=BLUE, height=0.6)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(axis="y", visible=False)
    for y, v in enumerate(removed["rows"]):
        ax.text(v, y, f"  {v:,}", va="center", color=INK_2, fontsize=8.5)
    total_in = int(rule_log.loc[rule_log["rule"] == "input", "rows"].iloc[0])
    ax.set_title(f"Rows removed by each cleaning rule (of {total_in:,} raw rows)")
    ax.margins(x=0.15)
    return _save(fig, "cleaning_rules", out_dir)


def build_all(results: dict[str, pd.DataFrame], rule_log: pd.DataFrame, out_dir: Path = config.FIGURE_DIR) -> list[Path]:
    return [
        monthly_trend(results["02_monthly_trend"], out_dir),
        top_products(results["03_top_products"], out_dir),
        countries(results["04_country_performance"], out_dir),
        cohort_heatmap(results["06_cohort_retention"], out_dir),
        weekday_hour(results["09_weekday_hour"], out_dir),
        cleaning_summary(rule_log, out_dir),
    ]
