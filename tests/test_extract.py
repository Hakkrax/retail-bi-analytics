from __future__ import annotations

import pandas as pd
import pytest

from retail_bi import config, extract


def _excel_like_sheet() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Invoice": ["489434"],
            "StockCode": ["85048"],
            "Description": ["15CM CHRISTMAS GLASS BALL 20 LIGHTS"],
            "Quantity": [12],
            "InvoiceDate": [pd.Timestamp("2009-12-01 07:45")],
            "Price": [6.95],
            "Customer ID": [13085.0],
            "Country": ["United Kingdom"],
        }
    )


def test_standardise_sheet_renames_and_tags():
    out = extract.standardise_sheet(_excel_like_sheet(), "Year 2009-2010")
    assert list(out.columns) == [*config.RAW_COLUMNS.values(), "source_sheet"]
    assert out.loc[0, "source_sheet"] == "Year 2009-2010"


def test_standardise_sheet_rejects_missing_columns():
    with pytest.raises(ValueError, match=r"missing columns: \['Country'\]"):
        extract.standardise_sheet(_excel_like_sheet().drop(columns=["Country"]), "bad")


def test_download_skips_existing_file(tmp_path, monkeypatch):
    dest = tmp_path / "data.zip"
    dest.write_bytes(b"already here")

    def fail(*_a, **_k):
        raise AssertionError("should not download")

    monkeypatch.setattr(extract.urllib.request, "urlretrieve", fail)
    assert extract.download(dest=dest) == dest
