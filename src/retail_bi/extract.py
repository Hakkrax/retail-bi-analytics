"""Download the UCI Online Retail II dataset and cache it as Parquet.

The source is a ~45 MB zip holding one Excel workbook with two sheets
(2009-2010 and 2010-2011). Reading the Excel file takes minutes, so the
first run writes a Parquet copy and later runs reuse it.
"""

from __future__ import annotations

import logging
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from . import config

log = logging.getLogger(__name__)


def download(url: str = config.DATASET_URL, dest: Path = config.RAW_ZIP) -> Path:
    """Download the dataset zip unless it is already present."""
    if dest.exists() and dest.stat().st_size > 0:
        log.info("raw zip already present: %s (%d bytes)", dest, dest.stat().st_size)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading %s", url)
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed https URL
    tmp.replace(dest)
    log.info("saved %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def standardise_sheet(sheet: pd.DataFrame, name: str) -> pd.DataFrame:
    """Check one sheet has every expected column and rename to snake_case."""
    missing = set(config.RAW_COLUMNS) - set(sheet.columns)
    if missing:
        raise ValueError(f"sheet {name!r} is missing columns: {sorted(missing)}")
    out = sheet.rename(columns=config.RAW_COLUMNS)[list(config.RAW_COLUMNS.values())].copy()
    out["source_sheet"] = name
    return out


def read_workbook(zip_path: Path) -> pd.DataFrame:
    """Read both yearly sheets and stack them with standard column names."""
    with zipfile.ZipFile(zip_path) as zf, zf.open(config.RAW_XLSX_NAME) as fh:
        sheets = pd.read_excel(
            fh,
            sheet_name=None,
            dtype={"Invoice": str, "StockCode": str, "Description": str, "Country": str},
            engine="openpyxl",
        )
    frames = []
    for name, sheet in sheets.items():
        sheet = standardise_sheet(sheet, name)
        frames.append(sheet)
        log.info("read sheet %r: %d rows", name, len(sheet))
    return pd.concat(frames, ignore_index=True)


def load_raw(refresh: bool = False) -> pd.DataFrame:
    """Return the raw dataset, using the Parquet cache when available."""
    if config.RAW_PARQUET.exists() and not refresh:
        log.info("using cached raw parquet: %s", config.RAW_PARQUET)
        return pd.read_parquet(config.RAW_PARQUET)
    zip_path = download()
    df = read_workbook(zip_path)
    config.RAW_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    # Customer ID arrives as float (NaN for guests); keep it as nullable text.
    df["customer_id"] = (
        df["customer_id"].astype("Int64").astype("string")
    )
    df.to_parquet(config.RAW_PARQUET, index=False)
    log.info("cached raw parquet: %s (%d rows)", config.RAW_PARQUET, len(df))
    return df
