"""Shared fixtures: a tiny raw dataset that hits every cleaning rule once."""

from __future__ import annotations

import pandas as pd
import pytest

S1, S2 = "Year 2009-2010", "Year 2010-2011"


def _row(invoice, code, qty, price, ts, customer="10001", country="United Kingdom", desc="WIDGET", sheet=S1):
    return {
        "invoice": invoice,
        "stock_code": code,
        "description": desc,
        "quantity": qty,
        "invoice_ts": pd.Timestamp(ts),
        "unit_price": price,
        "customer_id": customer,
        "country": country,
        "source_sheet": sheet,
    }


@pytest.fixture()
def raw_sample() -> pd.DataFrame:
    rows = [
        # Valid sales: customer 10001 buys in Jan and again in Mar 2010.
        _row("500001", "85123a", 10, 2.50, "2010-01-04 10:00"),          # lower-case code -> upper
        _row("500001", "22423", 2, 12.75, "2010-01-04 10:00", desc="  CAKE   STAND "),
        _row("500002", "22423", 1, 12.75, "2010-03-01 09:30"),
        # Customer 10002 from EIRE buys once.
        _row("500003", "22423", 4, 12.75, "2010-01-05 11:00", customer="10002", country="EIRE"),
        # Guest sale (no customer id): kept for revenue only.
        _row("500004", "85123A", 3, 2.50, "2010-02-01 12:00", customer=None),
        # Cancellation of part of 500003.
        _row("C500005", "22423", -1, 12.75, "2010-01-06 08:00", customer="10002", country="EIRE"),
        # --- rows that must be removed ---
        # Exact duplicate of the first line.
        _row("500001", "85123a", 10, 2.50, "2010-01-04 10:00"),
        # Sheet overlap: the same invoice appears on both sheets.
        _row("500006", "22423", 1, 12.75, "2010-12-02 10:00", sheet=S1),
        _row("500006", "22423", 1, 12.75, "2010-12-02 10:00", sheet=S2),
        # Bad-debt adjustment.
        _row("A500007", "B", 1, -500.0, "2010-04-01 10:00", customer=None, desc="Adjust bad debt"),
        # Postage and a gift voucher.
        _row("500008", "POST", 1, 18.0, "2010-01-04 10:00", desc="POSTAGE"),
        _row("500009", "gift_0001_20", 1, 20.0, "2010-01-04 10:00", desc="Gift Voucher"),
        # Zero price write-off.
        _row("500010", "22423", -5, 0.0, "2010-01-07 10:00", customer=None, desc="damaged"),
        # Negative quantity with a price, outside a cancellation invoice.
        _row("500011", "22423", -2, 12.75, "2010-01-08 10:00"),
        # Cancellation invoice with a positive quantity (malformed).
        _row("C500012", "22423", 1, 12.75, "2010-01-09 10:00"),
    ]
    df = pd.DataFrame(rows)
    df["customer_id"] = df["customer_id"].astype("string")
    return df
