"""Run every SQL file in ``sql/`` against the database and save the results."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from . import config

log = logging.getLogger(__name__)


def sql_files(sql_dir: Path = config.SQL_DIR) -> list[Path]:
    return sorted(sql_dir.glob("*.sql"))


def run_query(conn: sqlite3.Connection, path: Path) -> pd.DataFrame:
    return pd.read_sql_query(path.read_text(encoding="utf-8"), conn)


def run_all(
    db_path: Path = config.DATABASE_PATH, out_dir: Path = config.REPORT_DIR / "query_results"
) -> dict[str, pd.DataFrame]:
    """Execute each query, write ``<name>.csv`` and return the frames by name."""
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, pd.DataFrame] = {}
    with sqlite3.connect(db_path) as conn:
        for path in sql_files():
            frame = run_query(conn, path)
            frame.to_csv(out_dir / f"{path.stem}.csv", index=False)
            results[path.stem] = frame
            log.info("query %-24s -> %d rows", path.stem, len(frame))
    conn.close()
    return results
