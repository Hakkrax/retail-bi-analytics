"""Build the star schema from the fixture and run every SQL file against it."""

from __future__ import annotations

import sqlite3

import pytest

from retail_bi import clean, kpis, model


@pytest.fixture()
def db(tmp_path, raw_sample):
    lines, rule_log = clean.clean(raw_sample)
    path = tmp_path / "retail.db"
    counts = model.write_database(lines, rule_log, db_path=path)
    return path, counts


def test_tables_loaded(db):
    _, counts = db
    assert counts["fact_sales_line"] == 7
    assert counts["dim_product"] == 2
    assert counts["dim_customer"] == 2  # guest lines have no customer row
    assert counts["dim_date"] == 333  # 2010-01-04 .. 2010-12-02 inclusive


def test_rebuild_is_idempotent(tmp_path, raw_sample):
    lines, rule_log = clean.clean(raw_sample)
    path = tmp_path / "retail.db"
    first = model.write_database(lines, rule_log, db_path=path)
    second = model.write_database(lines, rule_log, db_path=path)
    assert first == second
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fact_sales_line").fetchone()[0] == 7


def test_foreign_keys_hold(db):
    path, _ = db
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_every_query_runs(db, tmp_path):
    path, _ = db
    results = kpis.run_all(db_path=path, out_dir=tmp_path / "out")
    assert len(results) == len(kpis.sql_files()) >= 10
    # 08 only lists products with >= 1,000 of sales, which the tiny fixture lacks.
    allowed_empty = {"08_cancellations"}
    for name, frame in results.items():
        assert name in allowed_empty or not frame.empty, f"{name} returned no rows"
        assert (tmp_path / "out" / f"{name}.csv").exists()


def test_kpi_summary_values(db, tmp_path):
    path, _ = db
    s = kpis.run_all(db_path=path, out_dir=tmp_path / "out")["01_kpi_summary"].iloc[0]
    assert s["gross_sales"] == pytest.approx(25 + 25.5 + 12.75 + 51 + 7.5 + 12.75)
    assert s["cancelled_value"] == pytest.approx(-12.75)
    assert s["orders"] == 5  # 500001, 500002, 500003, 500004, 500006
    assert s["customers"] == 2
    assert s["avg_order_value"] == pytest.approx(round(134.5 / 5, 2))


def test_new_vs_returning_labels(db, tmp_path):
    path, _ = db
    frame = kpis.run_all(db_path=path, out_dir=tmp_path / "out")["07_new_vs_returning"]
    got = {(r.year_month, r.customer_type) for r in frame.itertuples()}
    assert ("2010-01", "New") in got
    assert ("2010-03", "Returning") in got  # customer 10001 comes back in March


def test_cohort_month_zero_is_100_percent(db, tmp_path):
    path, _ = db
    frame = kpis.run_all(db_path=path, out_dir=tmp_path / "out")["06_cohort_retention"]
    assert (frame.loc[frame["months_since_first"] == 0, "retention_pct"] == 100).all()
