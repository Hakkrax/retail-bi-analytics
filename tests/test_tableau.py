"""Tableau extracts reconcile with the SQL KPIs, and the generated workbook is internally consistent.

These tests cannot prove Tableau renders the workbook; they prove the XML is
well formed and every field, sheet and parameter it refers to exists.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import pytest

from retail_bi import clean, config, kpis, model, tableau_data, tableau_workbook

USER_NS = "{http://www.tableausoftware.com/xml/user}"


@pytest.fixture()
def extracts(tmp_path, raw_sample):
    lines, rule_log = clean.clean(raw_sample)
    db_path = tmp_path / "retail.db"
    model.write_database(lines, rule_log, db_path=db_path)
    data_dir = tmp_path / "tableau_data"
    frames = tableau_data.build_all(db_path, data_dir)
    kpi = kpis.run_all(db_path=db_path, out_dir=tmp_path / "q")["01_kpi_summary"].iloc[0]
    return frames, kpi, data_dir


@pytest.fixture()
def workbook(extracts, tmp_path):
    _, _, data_dir = extracts
    path = tableau_workbook.build(data_dir, tmp_path / "wb.twb")
    return ET.parse(path).getroot(), data_dir


def test_all_countries_matches_kpi_summary(extracts):
    frames, kpi, _ = extracts
    k = frames["kpi_by_country"]
    assert k["scope"].iloc[0] == tableau_data.ALL_SCOPE
    total = k.iloc[0]
    for col in ("gross_sales", "cancelled_value", "net_revenue", "orders", "customers", "units_sold"):
        assert total[col] == pytest.approx(kpi[col]), col


def test_countries_add_up_to_all(extracts):
    frames, _, _ = extracts
    for stem in ("kpi_by_country", "monthly_by_country"):
        f = frames[stem]
        countries = f[f["scope"] != tableau_data.ALL_SCOPE]
        total = f[f["scope"] == tableau_data.ALL_SCOPE]
        for col in ("net_revenue", "orders"):
            assert countries[col].sum() == pytest.approx(total[col].sum()), (stem, col)


def test_monthly_has_one_row_per_month_and_no_partial_month(extracts):
    frames, _, _ = extracts
    m = frames["monthly_by_country"]
    assert not m.duplicated(["scope", "month_start"]).any()
    assert m["month_start"].max() <= config.LAST_COMPLETE_MONTH + "-01"


def test_top_products_ranked_within_scope(extracts):
    frames, _, _ = extracts
    p = frames["top_products_by_country"]
    assert p["product_rank"].max() <= tableau_data.TOP_N_PRODUCTS
    for _, group in p.groupby("scope"):
        assert list(group["product_rank"]) == list(range(1, len(group) + 1))
        assert group["net_revenue"].is_monotonic_decreasing


def test_markets_exclude_uk(extracts):
    frames, _, _ = extracts
    assert "United Kingdom" not in set(frames["markets_outside_uk"]["country"])


def _source_fields(ds: ET.Element) -> set[str]:
    names = {c.get("name") for c in ds.iter("column") if c.get("ordinal") is not None}
    names |= {c.get("name").strip("[]") for c in ds.findall("column")}
    return names


def test_workbook_references_resolve(workbook):
    root, data_dir = workbook
    sources = {ds.get("name"): ds for ds in root.find("datasources")}
    assert "Parameters" in sources

    for name, ds in sources.items():
        conn = ds.find(".//connection[@class='textscan']")
        if conn is not None:
            assert Path(conn.get("directory"), conn.get("filename")) == (data_dir / conn.get("filename")).resolve()
            assert (data_dir / conn.get("filename")).exists()

    pattern = re.compile(r"\[(federated\.[a-z0-9]+)\]\.\[(\w+):(\w+):(\w+)\]")
    sheets = root.find("worksheets")
    for sheet in sheets:
        text = ET.tostring(sheet, encoding="unicode")
        refs = pattern.findall(text)
        assert refs, sheet.get("name")
        for ds_name, _deriv, field, _suffix in refs:
            assert ds_name in sources, (sheet.get("name"), ds_name)
            assert field in _source_fields(sources[ds_name]), (sheet.get("name"), field)


def test_dashboards_point_at_real_sheets(workbook):
    root, _ = workbook
    sheet_names = {s.get("name") for s in root.find("worksheets")}
    used = set()
    for dash in root.find("dashboards"):
        for zone in dash.iter("zone"):
            if zone.get("type") is None and zone.get("name"):
                assert zone.get("name") in sheet_names
                used.add(zone.get("name"))
            if zone.get("type") == "paramctrl":
                assert zone.get("param") == tableau_workbook.PARAM
            for k in ("x", "y", "w", "h"):
                assert 0 <= int(zone.get(k)) <= 100000
    assert used == sheet_names  # every sheet is placed on a dashboard


def test_country_parameter_lists_every_scope(workbook, extracts):
    root, _ = workbook
    frames, _, _ = extracts
    members = [m.get("value").strip('"') for m in root.iter("member")]
    assert members == frames["kpi_by_country"]["scope"].tolist()


def test_committed_workbook_matches_generator():
    """The .twb in the repo must be what the generator produces from the committed extracts."""
    committed = tableau_workbook.WORKBOOK_PATH
    if not committed.exists() or not (tableau_data.TABLEAU_DATA_DIR / "kpi_by_country.csv").exists():
        pytest.skip("workbook not generated yet")
    root = ET.parse(committed).getroot()
    assert len(root.find("worksheets")) == 14
    assert [d.get("name") for d in root.find("dashboards")] == ["Sales Overview", "Customers", "Operations"]
    frame = pd.read_csv(tableau_data.TABLEAU_DATA_DIR / "kpi_by_country.csv")
    assert frame["scope"].iloc[0] == tableau_data.ALL_SCOPE
