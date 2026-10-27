"""Paths and constants shared by every pipeline step."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
EXPORT_DIR = PROJECT_ROOT / "exports"
SQL_DIR = PROJECT_ROOT / "sql"
FIGURE_DIR = PROJECT_ROOT / "docs" / "figures"
REPORT_DIR = PROJECT_ROOT / "reports"

DATASET_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
RAW_ZIP = RAW_DIR / "online_retail_ii.zip"
RAW_XLSX_NAME = "online_retail_II.xlsx"
RAW_PARQUET = INTERIM_DIR / "online_retail_raw.parquet"

CLEAN_PARQUET = PROCESSED_DIR / "transactions_clean.parquet"
DATABASE_PATH = PROCESSED_DIR / "retail.db"

# Column names after standardising the two Excel sheets.
RAW_COLUMNS = {
    "Invoice": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_ts",
    "Price": "unit_price",
    "Customer ID": "customer_id",
    "Country": "country",
}

# Stock codes that are fees, adjustments or postage rather than products.
# Found by profiling: they are alphabetic codes whose descriptions are not goods.
NON_PRODUCT_CODES = frozenset(
    {
        "POST",       # postage
        "DOT",        # dotcom postage
        "C2",         # carriage
        "M",          # manual adjustment
        "BANK CHARGES",
        "AMAZONFEE",
        "CRUK",       # charity commission
        "D",          # discount
        "S",          # samples
        "PADS",       # pad-to-match-price adjustment
        "B",          # adjust bad debt
        "ADJUST",
        "ADJUST2",
        "TEST001",
        "TEST002",
        "SP1002",
        "DCGSSBOY",   # description is just "update"
        "DCGSSGIRL",
    }
)
# Gift vouchers (GIFT_0001_10 ... _90) are stored value, not merchandise.
NON_PRODUCT_PREFIXES = ("GIFT_",)

# The last calendar month in the data is incomplete (ends 9 Dec 2011).
LAST_COMPLETE_MONTH = "2011-11"
