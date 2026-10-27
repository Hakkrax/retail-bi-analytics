"""Checks against the real built database. Skipped until the pipeline has run."""

from __future__ import annotations

import json
import sqlite3

import pytest

from retail_bi import config

pytestmark = [
    pytest.mark.full_data,
    pytest.mark.skipif(not config.DATABASE_PATH.exists(), reason="run `python -m retail_bi.pipeline` first"),
]


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(config.DATABASE_PATH)
    yield c
    c.close()


def scalar(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_no_invalid_prices_or_quantities(conn):
    assert scalar(conn, "SELECT COUNT(*) FROM fact_sales_line WHERE unit_price <= 0") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM fact_sales_line WHERE line_type='sale' AND quantity <= 0") == 0
    assert scalar(conn, "SELECT COUNT(*) FROM fact_sales_line WHERE line_type='cancellation' AND quantity >= 0") == 0


def test_no_duplicate_lines(conn):
    dupes = scalar(
        conn,
        """SELECT COUNT(*) FROM (
               SELECT invoice, stock_code, quantity, invoice_ts, unit_price, COUNT(*) n
               FROM fact_sales_line
               GROUP BY 1, 2, 3, 4, 5, customer_id, country HAVING n > 1)""",
    )
    assert dupes == 0


def test_no_non_product_codes(conn):
    codes = ", ".join(f"'{c}'" for c in config.NON_PRODUCT_CODES)
    assert scalar(conn, f"SELECT COUNT(*) FROM fact_sales_line WHERE stock_code IN ({codes})") == 0  # noqa: S608
    assert scalar(conn, "SELECT COUNT(*) FROM fact_sales_line WHERE stock_code LIKE 'GIFT\\_%' ESCAPE '\\'") == 0


def test_date_range(conn):
    assert scalar(conn, "SELECT MIN(invoice_date) FROM fact_sales_line") == "2009-12-01"
    assert scalar(conn, "SELECT MAX(invoice_date) FROM fact_sales_line") == "2011-12-09"


def test_quality_log_reconciles(conn):
    raw = scalar(conn, "SELECT line_value FROM data_quality_log WHERE rule = 'input'")
    accounted = scalar(conn, "SELECT SUM(line_value) FROM data_quality_log WHERE action IN ('keep', 'remove')")
    assert accounted == pytest.approx(raw, abs=0.01)


def test_fact_matches_kept_rows(conn):
    kept = scalar(conn, "SELECT SUM(rows) FROM data_quality_log WHERE action = 'keep'")
    assert scalar(conn, "SELECT COUNT(*) FROM fact_sales_line") == kept


def test_summary_json_matches_database(conn):
    path = config.REPORT_DIR / "kpi_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    net = scalar(conn, "SELECT ROUND(SUM(line_revenue), 2) FROM fact_sales_line")
    assert summary["net_revenue"] == pytest.approx(net, abs=0.01)
