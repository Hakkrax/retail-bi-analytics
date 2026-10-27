"""Small, dashboard-ready CSV extracts for the Tableau Public workbook.

Tableau reads these instead of the 90 MB fact table. Each file is built from
the star schema with SQL (or from the documented query results), so every
number on the dashboard traces back to the same definitions as the README.

"Scope" files hold one block of rows per country plus an "All countries"
block. The dashboard's Country selector keeps exactly one block, which keeps
non-additive measures such as distinct customers correct for any selection.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from . import config, kpis

log = logging.getLogger(__name__)

TABLEAU_DIR = config.PROJECT_ROOT / "tableau"
TABLEAU_DATA_DIR = TABLEAU_DIR / "data"
ALL_SCOPE = "All countries"
TOP_N_PRODUCTS = 15
TOP_N_MARKETS = 15

_SCOPED = f"""
scoped AS (
    SELECT country AS scope, * FROM fact_sales_line
    UNION ALL
    SELECT '{ALL_SCOPE}' AS scope, * FROM fact_sales_line
)"""

KPI_BY_SCOPE = f"""
WITH {_SCOPED}
SELECT
    scope,
    ROUND(SUM(CASE WHEN line_type = 'sale' THEN line_revenue ELSE 0 END), 2)          AS gross_sales,
    ROUND(SUM(CASE WHEN line_type = 'cancellation' THEN line_revenue ELSE 0 END), 2)  AS cancelled_value,
    ROUND(SUM(line_revenue), 2)                                                       AS net_revenue,
    COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN invoice END)                     AS orders,
    COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN customer_id END)                 AS customers,
    SUM(CASE WHEN line_type = 'sale' THEN quantity ELSE 0 END)                        AS units_sold
FROM scoped
GROUP BY scope
ORDER BY scope = '{ALL_SCOPE}' DESC, net_revenue DESC
"""

# Complete months only: the data ends on 9 Dec 2011. (Alias is month_start, not
# month, because dim_date.month exists and SQLite would group by that instead.)
MONTHLY_BY_SCOPE = f"""
WITH {_SCOPED}
SELECT
    s.scope,
    SUBSTR(s.invoice_date, 1, 7) || '-01'                                               AS month_start,
    ROUND(SUM(CASE WHEN s.line_type = 'sale' THEN s.line_revenue ELSE 0 END), 2)          AS gross_sales,
    ROUND(SUM(CASE WHEN s.line_type = 'cancellation' THEN s.line_revenue ELSE 0 END), 2)  AS cancelled_value,
    ROUND(SUM(s.line_revenue), 2)                                                       AS net_revenue,
    COUNT(DISTINCT CASE WHEN s.line_type = 'sale' THEN s.invoice END)                   AS orders
FROM scoped AS s
JOIN dim_date AS d ON d.date = s.invoice_date
WHERE d.is_complete_month = 1
GROUP BY s.scope, month_start
ORDER BY s.scope, month_start
"""

TOP_PRODUCTS_BY_SCOPE = f"""
WITH {_SCOPED},
per_product AS (
    SELECT
        scope,
        stock_code,
        SUM(line_revenue)                                          AS net_revenue,
        SUM(CASE WHEN line_type = 'sale' THEN quantity ELSE 0 END) AS units_sold
    FROM scoped
    GROUP BY scope, stock_code
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (PARTITION BY scope ORDER BY net_revenue DESC, stock_code) AS product_rank
    FROM per_product
    WHERE net_revenue > 0
)
SELECT
    r.scope,
    r.product_rank,
    r.stock_code,
    p.description,
    ROUND(r.net_revenue, 2) AS net_revenue,
    r.units_sold
FROM ranked AS r
JOIN dim_product AS p ON p.stock_code = r.stock_code
WHERE r.product_rank <= {TOP_N_PRODUCTS}
ORDER BY r.scope, r.product_rank
"""

_DAY_ABBR = {
    "Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed", "Thursday": "Thu",
    "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun",
}


def _query(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn)


def _run_named(conn: sqlite3.Connection, stem: str) -> pd.DataFrame:
    return kpis.run_query(conn, config.SQL_DIR / f"{stem}.sql")


def markets(country_perf: pd.DataFrame) -> pd.DataFrame:
    """Top markets outside the UK (the UK is 85% of revenue and hides the rest)."""
    out = country_perf[country_perf["country"] != "United Kingdom"]
    out = out.sort_values("net_revenue", ascending=False).head(TOP_N_MARKETS).copy()
    out.insert(0, "market_rank", range(1, len(out) + 1))
    return out[["market_rank", "country", "net_revenue", "orders", "customers", "avg_order_value"]]


def order_timing(weekday_hour: pd.DataFrame) -> pd.DataFrame:
    """Weekday x hour grid with Monday first."""
    out = weekday_hour.copy()
    out["weekday_num"] = (out["weekday_num"] + 6) % 7 + 1  # Mon = 1 ... Sun = 7
    out["day"] = out["day_of_week"].map(_DAY_ABBR)
    return out[["weekday_num", "day", "hour_of_day", "orders", "gross_sales"]]


def rfm_segments(rfm: pd.DataFrame) -> pd.DataFrame:
    out = (
        rfm.groupby("segment")
        .agg(customers=("customer_id", "count"), revenue=("monetary", "sum"))
        .reset_index()
        .sort_values("revenue", ascending=False)
    )
    out["revenue"] = out["revenue"].round(2)
    out["revenue_share"] = (out["revenue"] / out["revenue"].sum()).round(4)
    out.insert(0, "segment_rank", range(1, len(out) + 1))
    return out


def cohorts(cohort: pd.DataFrame, max_months: int = 12, last_cohort: str = "2010-12") -> pd.DataFrame:
    """Months 1-12 for cohorts up to Dec 2010, without cells in the partial final month."""
    out = cohort[(cohort["months_since_first"].between(1, max_months)) & (cohort["cohort_month"] <= last_cohort)]
    active = pd.PeriodIndex(out["cohort_month"], freq="M") + out["months_since_first"].to_numpy()
    out = out[active.astype(str) <= config.LAST_COMPLETE_MONTH].copy()
    out["retention"] = (out["retention_pct"] / 100).round(4)
    return out[["cohort_month", "months_since_first", "cohort_size", "active_customers", "retention"]]


def new_vs_returning(nvr: pd.DataFrame) -> pd.DataFrame:
    """New and returning revenue per complete month.

    The small "Before first purchase" group (cancellations of orders placed
    before the data starts) is left out of this chart; it stays in the SQL output.
    """
    out = nvr[nvr["customer_type"].isin(["New", "Returning"])]
    out = out[out["year_month"] <= config.LAST_COMPLETE_MONTH].copy()
    out["month_start"] = out["year_month"] + "-01"
    return out[["month_start", "customer_type", "customers", "net_revenue"]]


def pareto(p: pd.DataFrame) -> pd.DataFrame:
    out = p.copy()
    out["top_label"] = "Top " + out["top_customers_pct"].astype(str) + "%"
    out["revenue_share"] = (out["revenue_share_pct"] / 100).round(4)
    return out[["top_customers_pct", "top_label", "customers", "net_revenue", "revenue_share"]]


def build_all(db_path: Path = config.DATABASE_PATH, out_dir: Path = TABLEAU_DATA_DIR) -> dict[str, pd.DataFrame]:
    """Write every Tableau CSV and return the frames by file stem."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        frames = {
            "kpi_by_country": _query(conn, KPI_BY_SCOPE),
            "monthly_by_country": _query(conn, MONTHLY_BY_SCOPE),
            "top_products_by_country": _query(conn, TOP_PRODUCTS_BY_SCOPE),
            "markets_outside_uk": markets(_run_named(conn, "04_country_performance")),
            "order_timing": order_timing(_run_named(conn, "09_weekday_hour")),
            "rfm_segments": rfm_segments(_run_named(conn, "05_customer_rfm")),
            "cohort_retention": cohorts(_run_named(conn, "06_cohort_retention")),
            "new_vs_returning": new_vs_returning(_run_named(conn, "07_new_vs_returning")),
            "customer_pareto": pareto(_run_named(conn, "10_customer_pareto")),
        }
    conn.close()
    for stem, frame in frames.items():
        frame.to_csv(out_dir / f"{stem}.csv", index=False)
        log.info("tableau %-24s -> %d rows", stem, len(frame))
    return frames
