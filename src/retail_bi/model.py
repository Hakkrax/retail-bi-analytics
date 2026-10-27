"""Build a star schema in SQLite and CSV extracts for the BI tool.

Tables
------
fact_sales_line   one row per kept invoice line (sales and cancellations)
dim_product       one row per stock code, with its most common description
dim_customer      one row per known customer, with home country and first purchase
dim_date          one row per calendar day in the data range
data_quality_log  the cleaning rule log from ``clean.clean``
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from . import config

log = logging.getLogger(__name__)


def build_dim_product(lines: pd.DataFrame) -> pd.DataFrame:
    sales = lines[lines["line_type"] == "sale"]
    desc = (
        sales.dropna(subset=["description"])
        .groupby(["stock_code", "description"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["stock_code", "n"], ascending=[True, False])
        .drop_duplicates("stock_code")
        .set_index("stock_code")["description"]
    )
    stats = lines.groupby("stock_code").agg(
        first_sold=("invoice_ts", "min"),
        last_sold=("invoice_ts", "max"),
        description_variants=("description", "nunique"),
    )
    dim = stats.join(desc.rename("description"), how="left").reset_index()
    dim["description"] = dim["description"].fillna("UNKNOWN")
    return dim[["stock_code", "description", "description_variants", "first_sold", "last_sold"]]


def build_dim_customer(lines: pd.DataFrame) -> pd.DataFrame:
    known = lines[lines["has_customer"]]
    country = (
        known.groupby(["customer_id", "country"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["customer_id", "n"], ascending=[True, False])
        .drop_duplicates("customer_id")
        .set_index("customer_id")["country"]
    )
    sales = known[known["line_type"] == "sale"]
    first = sales.groupby("customer_id")["invoice_ts"].min().rename("first_purchase_ts")
    dim = pd.concat([country.rename("home_country"), first], axis=1).reset_index()
    dim = dim.rename(columns={"index": "customer_id"})
    dim["cohort_month"] = dim["first_purchase_ts"].dt.to_period("M").astype("string")
    return dim


def build_dim_date(lines: pd.DataFrame) -> pd.DataFrame:
    days = pd.date_range(lines["invoice_ts"].min().normalize(), lines["invoice_ts"].max().normalize(), freq="D")
    dim = pd.DataFrame({"date": days})
    dim["year"] = dim["date"].dt.year
    dim["quarter"] = dim["date"].dt.quarter
    dim["month"] = dim["date"].dt.month
    dim["year_month"] = dim["date"].dt.strftime("%Y-%m")
    dim["month_name"] = dim["date"].dt.strftime("%b")
    dim["iso_week"] = dim["date"].dt.isocalendar().week.astype(int)
    dim["day_of_week"] = dim["date"].dt.day_name()
    dim["is_weekend"] = dim["date"].dt.dayofweek >= 5
    dim["is_complete_month"] = dim["year_month"] <= config.LAST_COMPLETE_MONTH
    dim["date"] = dim["date"].dt.strftime("%Y-%m-%d")
    return dim


def build_fact(lines: pd.DataFrame) -> pd.DataFrame:
    fact = lines[
        [
            "invoice",
            "invoice_ts",
            "stock_code",
            "customer_id",
            "country",
            "quantity",
            "unit_price",
            "line_revenue",
            "line_type",
        ]
    ].copy()
    fact.insert(0, "line_id", range(1, len(fact) + 1))
    fact["invoice_date"] = fact["invoice_ts"].dt.strftime("%Y-%m-%d")
    fact["invoice_ts"] = fact["invoice_ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return fact


DDL = """
DROP TABLE IF EXISTS fact_sales_line;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS data_quality_log;

CREATE TABLE dim_product (
    stock_code           TEXT PRIMARY KEY,
    description          TEXT NOT NULL,
    description_variants INTEGER NOT NULL,
    first_sold           TEXT NOT NULL,
    last_sold            TEXT NOT NULL
);

CREATE TABLE dim_customer (
    customer_id       TEXT PRIMARY KEY,
    home_country      TEXT NOT NULL,
    first_purchase_ts TEXT,
    cohort_month      TEXT
);

CREATE TABLE dim_date (
    date              TEXT PRIMARY KEY,
    year              INTEGER NOT NULL,
    quarter           INTEGER NOT NULL,
    month             INTEGER NOT NULL,
    year_month        TEXT NOT NULL,
    month_name        TEXT NOT NULL,
    iso_week          INTEGER NOT NULL,
    day_of_week       TEXT NOT NULL,
    is_weekend        INTEGER NOT NULL,
    is_complete_month INTEGER NOT NULL
);

CREATE TABLE fact_sales_line (
    line_id      INTEGER PRIMARY KEY,
    invoice      TEXT NOT NULL,
    invoice_ts   TEXT NOT NULL,
    stock_code   TEXT NOT NULL REFERENCES dim_product(stock_code),
    customer_id  TEXT REFERENCES dim_customer(customer_id),
    country      TEXT NOT NULL,
    quantity     INTEGER NOT NULL,
    unit_price   REAL NOT NULL CHECK (unit_price > 0),
    line_revenue REAL NOT NULL,
    line_type    TEXT NOT NULL CHECK (line_type IN ('sale', 'cancellation')),
    invoice_date TEXT NOT NULL REFERENCES dim_date(date)
);

CREATE INDEX ix_fact_date     ON fact_sales_line(invoice_date);
CREATE INDEX ix_fact_customer ON fact_sales_line(customer_id);
CREATE INDEX ix_fact_product  ON fact_sales_line(stock_code);
CREATE INDEX ix_fact_invoice  ON fact_sales_line(invoice);

CREATE TABLE data_quality_log (
    rule        TEXT NOT NULL,
    action      TEXT NOT NULL,
    rows        INTEGER NOT NULL,
    line_value  REAL NOT NULL,
    description TEXT NOT NULL
);
"""


def _to_sql_ready(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d %H:%M:%S")
        elif pd.api.types.is_bool_dtype(out[col]):
            out[col] = out[col].astype(int)
    return out.astype(object).where(out.notna(), None)


def write_database(
    lines: pd.DataFrame, rule_log: pd.DataFrame, db_path: Path = config.DATABASE_PATH
) -> dict[str, int]:
    """Rebuild the SQLite database from scratch and return table row counts."""
    tables = {
        "dim_product": build_dim_product(lines),
        "dim_customer": build_dim_customer(lines),
        "dim_date": build_dim_date(lines),
        "fact_sales_line": build_fact(lines),
        "data_quality_log": rule_log,
    }
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    with sqlite3.connect(tmp) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(DDL)
        for name, frame in tables.items():
            ready = _to_sql_ready(frame)
            cols = ", ".join(ready.columns)
            marks = ", ".join("?" for _ in ready.columns)
            conn.executemany(
                f"INSERT INTO {name} ({cols}) VALUES ({marks})",  # noqa: S608 - fixed table names
                ready.itertuples(index=False, name=None),
            )
            log.info("loaded %-17s %d rows", name, len(ready))
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"foreign key violations: {violations[:5]}")
    conn.close()
    # Swap in atomically so a failed build never leaves a half-written database.
    tmp.replace(db_path)
    return {name: len(frame) for name, frame in tables.items()}


def write_exports(db_path: Path = config.DATABASE_PATH, out_dir: Path = config.EXPORT_DIR) -> list[Path]:
    """Write the CSV files the Tableau / Power BI workbook connects to."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with sqlite3.connect(db_path) as conn:
        for table in ["fact_sales_line", "dim_product", "dim_customer", "dim_date", "data_quality_log"]:
            frame = pd.read_sql_query(f"SELECT * FROM {table}", conn)  # noqa: S608
            path = out_dir / f"{table}.csv"
            frame.to_csv(path, index=False)
            written.append(path)
            log.info("exported %s (%d rows)", path.name, len(frame))
    conn.close()
    return written
