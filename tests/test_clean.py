from __future__ import annotations

import pandas as pd
import pytest

from retail_bi import clean
from retail_bi.pipeline import reconcile


@pytest.fixture()
def cleaned(raw_sample):
    return clean.clean(raw_sample)


def _rule_rows(rule_log: pd.DataFrame, rule: str) -> int:
    return int(rule_log.loc[rule_log["rule"] == rule, "rows"].iloc[0])


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ("input", 15),
        ("unparseable", 0),
        ("sheet_overlap", 1),
        ("exact_duplicate", 1),
        ("bad_debt_adjustment", 1),
        ("non_product_code", 2),
        ("non_positive_price", 1),
        ("stock_adjustment", 1),
        ("cancel_positive_qty", 1),
        ("kept_sale", 6),
        ("kept_cancellation", 1),
        ("no_customer_id", 1),
    ],
)
def test_each_rule_catches_its_row(cleaned, rule, expected):
    _, rule_log = cleaned
    assert _rule_rows(rule_log, rule) == expected


def test_rows_are_conserved(cleaned):
    lines, rule_log = cleaned
    removed = rule_log.loc[rule_log["action"] == "remove", "rows"].sum()
    assert len(lines) + removed == _rule_rows(rule_log, "input")


def test_revenue_reconciles(raw_sample, cleaned):
    _, rule_log = cleaned
    raw_value = float((raw_sample["quantity"] * raw_sample["unit_price"]).sum())
    assert reconcile(raw_value, rule_log) == pytest.approx(0, abs=1e-9)


def test_kept_lines_are_valid(cleaned):
    lines, _ = cleaned
    assert (lines["unit_price"] > 0).all()
    sales = lines[lines["line_type"] == "sale"]
    cancels = lines[lines["line_type"] == "cancellation"]
    assert (sales["quantity"] > 0).all()
    assert (cancels["quantity"] < 0).all()
    assert cancels["invoice"].str.startswith("C").all()
    assert not lines.duplicated(["invoice", "stock_code", "quantity", "invoice_ts", "unit_price"]).any()


def test_standardisation(cleaned):
    lines, _ = cleaned
    assert "85123a" not in set(lines["stock_code"])
    assert "CAKE STAND" in set(lines["description"])
    assert "Ireland" in set(lines["country"])
    assert "EIRE" not in set(lines["country"])


def test_line_revenue_sign(cleaned):
    lines, _ = cleaned
    net = lines["line_revenue"].sum()
    # sales 25 + 25.5 + 12.75 + 51 + 7.5, overlap invoice (first copy) 12.75, cancellation -12.75
    assert net == pytest.approx(25 + 25.5 + 12.75 + 51 + 7.5 + 12.75 - 12.75)

