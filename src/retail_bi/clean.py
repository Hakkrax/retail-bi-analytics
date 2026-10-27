"""Clean and classify raw invoice lines.

Every rule is applied in a fixed order. Rows are not silently dropped:
each one is either kept (as a sale or a cancellation) or removed with a
named reason, and the rule log records how many rows and how much gross
line value each rule touched. That log is what makes the revenue
reconciliation test possible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from . import config

log = logging.getLogger(__name__)

# Country labels in the source that do not geocode in Tableau / Power BI.
COUNTRY_FIXES = {
    "EIRE": "Ireland",
    "RSA": "South Africa",
    "USA": "United States",
    "Korea": "South Korea",
    "Unspecified": "Unknown",
    "European Community": "Unknown",
    "West Indies": "Unknown",
}


@dataclass
class RuleLog:
    """Row-level audit of what each cleaning rule did."""

    entries: list[dict] = field(default_factory=list)

    def add(self, rule: str, action: str, rows: pd.DataFrame, description: str) -> None:
        self.entries.append(
            {
                "rule": rule,
                "action": action,
                "rows": int(len(rows)),
                "line_value": float((rows["quantity"] * rows["unit_price"]).sum()),
                "description": description,
            }
        )
        log.info("%-22s %-7s rows=%-8d %s", rule, action, len(rows), description)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.entries)


def standardise(df: pd.DataFrame) -> pd.DataFrame:
    """Fix types and text formatting without removing anything."""
    out = df.copy()
    out["invoice"] = out["invoice"].astype("string").str.strip()
    out["stock_code"] = out["stock_code"].astype("string").str.strip().str.upper()
    out["description"] = (
        out["description"].astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    )
    out["country"] = out["country"].astype("string").str.strip().replace(COUNTRY_FIXES)
    out["customer_id"] = out["customer_id"].astype("string").str.strip()
    out["invoice_ts"] = pd.to_datetime(out["invoice_ts"], errors="coerce")
    out["quantity"] = pd.to_numeric(out["quantity"], errors="coerce")
    out["unit_price"] = pd.to_numeric(out["unit_price"], errors="coerce")
    return out


def _take(df: pd.DataFrame, mask: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    return df[mask], df[~mask]


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (clean_lines, rule_log).

    ``clean_lines`` holds sale and cancellation lines for real products, with a
    ``line_type`` column and a signed ``line_revenue``.
    """
    rules = RuleLog()
    df = standardise(raw)
    rules.add("input", "count", df, "raw rows from both workbook sheets")

    # 1. Unparseable core fields.
    bad, df = _take(
        df,
        df["invoice"].isna()
        | df["invoice_ts"].isna()
        | df["quantity"].isna()
        | df["unit_price"].isna()
        | df["stock_code"].isna(),
    )
    rules.add("unparseable", "remove", bad, "missing invoice, date, quantity, price or stock code")

    # 2. Sheet overlap: the two sheets share 1-9 Dec 2010. Keep the first
    #    sheet's copy of any invoice that appears in both.
    sheets = df.groupby("invoice")["source_sheet"].agg(["nunique", "first"])
    shared = sheets.index[sheets["nunique"] > 1]
    first_sheet = df["invoice"].map(sheets["first"])
    overlap, df = _take(df, df["invoice"].isin(shared) & (df["source_sheet"] != first_sheet))
    rules.add("sheet_overlap", "remove", overlap, "invoice lines repeated across the two yearly sheets")

    # 3. Duplicate lines within an invoice. The description is free text that
    #    was sometimes relabelled mid-entry (e.g. "SPOTTY BUNTING" vs
    #    "BUNTING , SPOTTY" on one invoice), so it is not part of the key;
    #    the stock code identifies the product.
    key_cols = [c for c in config.RAW_COLUMNS.values() if c != "description"]
    dupes, df = _take(df, df.duplicated(subset=key_cols, keep="first"))
    rules.add("exact_duplicate", "remove", dupes, "same product, quantity, price and time repeated on an invoice")

    # 4. Bad-debt adjustments (invoice prefix 'A').
    adj, df = _take(df, df["invoice"].str.startswith("A"))
    rules.add("bad_debt_adjustment", "remove", adj, "accounting adjustment invoices (prefix A), not sales")

    # 5. Fees, postage, manual adjustments and test codes.
    nonprod, df = _take(
        df,
        df["stock_code"].isin(config.NON_PRODUCT_CODES)
        | df["stock_code"].str.startswith(config.NON_PRODUCT_PREFIXES),
    )
    rules.add("non_product_code", "remove", nonprod, "postage, fees, discounts, vouchers, manual and test codes")

    # 6. Zero or negative price: free items and stock write-offs.
    zero, df = _take(df, df["unit_price"] <= 0)
    rules.add("non_positive_price", "remove", zero, "zero or negative unit price (write-offs, free items)")

    is_cancel = df["invoice"].str.startswith("C")

    # 7. Negative quantity that is not a cancellation invoice: stock adjustments.
    stockadj, df = _take(df, (df["quantity"] <= 0) & ~is_cancel)
    rules.add("stock_adjustment", "remove", stockadj, "negative quantity outside a cancellation invoice")
    is_cancel = df["invoice"].str.startswith("C")

    # 8. Cancellation invoices must carry negative quantities.
    odd_cancel, df = _take(df, is_cancel & (df["quantity"] >= 0))
    rules.add("cancel_positive_qty", "remove", odd_cancel, "cancellation invoice with non-negative quantity")

    df = df.copy()
    df["line_type"] = df["invoice"].str.startswith("C").map({True: "cancellation", False: "sale"})
    df["line_revenue"] = (df["quantity"] * df["unit_price"]).round(2)
    df["has_customer"] = df["customer_id"].notna()

    rules.add("kept_sale", "keep", df[df["line_type"] == "sale"], "valid product sale lines")
    rules.add(
        "kept_cancellation", "keep", df[df["line_type"] == "cancellation"], "valid product cancellation lines"
    )
    rules.add("no_customer_id", "flag", df[~df["has_customer"]], "kept for revenue; excluded from customer KPIs")

    df = df.drop(columns=["source_sheet"]).reset_index(drop=True)
    df["customer_id"] = df["customer_id"].astype("string")
    return df, rules.to_frame()
