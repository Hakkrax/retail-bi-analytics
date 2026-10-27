"""Generate the Tableau workbook (``tableau/retail_dashboard.twb``).

A .twb file is XML. This module writes it from a short specification (data
sources, calculated fields, worksheets, dashboards), so the workbook can be
rebuilt whenever the data changes and reviewed as code.

The tests check that the XML is well formed and that every field a sheet uses
exists in its CSV or as a calculated field. Only opening the file in Tableau
proves that it renders; see ``docs/TABLEAU_BUILD_GUIDE.md``.

Usage:
    python -m retail_bi.tableau_workbook            # extracts + workbook
    python -m retail_bi.tableau_workbook --no-data  # workbook only
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd

from . import config
from .tableau_data import ALL_SCOPE, TABLEAU_DATA_DIR, TABLEAU_DIR

log = logging.getLogger(__name__)

WORKBOOK_PATH = TABLEAU_DIR / "retail_dashboard.twb"
VERSION = "18.1"
PARAM = "[Parameters].[Parameter 1]"
DASH_W, DASH_H = 1200, 950
EXTRACT_POSITION = "before_layout"  # Tableau 2026.3 schema: after the columns, before <layout>
EXTRACT_DIR = TABLEAU_DIR / "extracts"
DEVICE_PREVIEW: list[str] = []
CAPTIONS = {"month_start": "Date", "product_rank": "#", "market_rank": "#", "segment_rank": "#",
            "weekday_num": "#", "hour_of_day": "Hour", "top_customers_pct": "Top % of customers",
            "months_since_first": "Months since first purchase", "cohort_month": "Cohort"}
FOCUS: str | None = None  # window open on load (default: first dashboard); for visual checks  # extra elements after <active> in dashboard windows

GBP = 'c"£"#,##0;-"£"#,##0'
GBP2 = 'c"£"#,##0.00;-"£"#,##0.00'
INT = "n#,##0;-#,##0"
PCT1 = "p0.0%"
PCT0 = "p0%"

SOURCE_LINE = (
    "Source: Chen, D. (2012) Online Retail II, UCI Machine Learning Repository, CC BY 4.0. "
    "Net revenue = sales minus cancellations. The data has no cost column, so no margin is shown."
)


# --------------------------------------------------------------------------- XML helpers


def _attr(value: object) -> str:
    return escape(str(value), {'"': "&quot;", "\n": "&#10;"})


def tag(name: str, attrs: dict | None = None, children: list[str] | str | None = None) -> str:
    a = "".join(f' {k}="{_attr(v)}"' for k, v in (attrs or {}).items() if v is not None)
    if children is None or children == []:
        return f"<{name}{a} />"
    body = children if isinstance(children, str) else "\n".join(children)
    return f"<{name}{a}>{body}</{name}>"


def _short_hash(text: str, prefix: str) -> str:
    digest = hashlib.sha1(text.encode()).digest()
    return prefix + base64.b32encode(digest).decode().lower()[:28]


# --------------------------------------------------------------------------- model


@dataclass
class Col:
    name: str
    datatype: str  # string | integer | real | date | boolean
    role: str  # dimension | measure
    type: str  # nominal | ordinal | quantitative
    caption: str | None = None
    fmt: str | None = None
    formula: str | None = None  # set for calculated fields

    @property
    def ref(self) -> str:
        return f"[{self.name}]"

    def xml(self) -> str:
        attrs = {
            "caption": self.caption,
            "datatype": self.datatype,
            "default-format": self.fmt,
            "name": self.ref,
            "role": self.role,
            "type": self.type,
        }
        calc = [tag("calculation", {"class": "tableau", "formula": self.formula})] if self.formula else None
        return tag("column", attrs, calc)


@dataclass
class Source:
    stem: str
    caption: str
    scoped: bool = False
    dates: tuple[str, ...] = ()
    dims: tuple[str, ...] = ()  # numeric columns that act as discrete dimensions
    formats: dict[str, str] = field(default_factory=dict)
    calcs: list[Col] = field(default_factory=list)
    cols: dict[str, Col] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return _short_hash(self.stem, "federated.")

    @property
    def filename(self) -> str:
        return f"{self.stem}.csv"

    def load_columns(self, data_dir: Path) -> None:
        frame = pd.read_csv(data_dir / self.filename, nrows=200)
        if frame.empty:
            raise ValueError(f"{self.filename} has no rows; run the pipeline first")
        self.cols = {}
        for name, dtype in frame.dtypes.items():
            if name in self.dates:
                col = Col(name, "date", "dimension", "ordinal")
            elif pd.api.types.is_integer_dtype(dtype):
                col = Col(name, "integer", "measure", "quantitative")
            elif pd.api.types.is_float_dtype(dtype):
                col = Col(name, "real", "measure", "quantitative")
            else:
                col = Col(name, "string", "dimension", "nominal")
            if name in self.dims:
                col.role, col.type = "dimension", "ordinal"
            col.caption = CAPTIONS.get(name, name.replace("_", " ").capitalize())
            col.fmt = self.formats.get(name)
            self.cols[name] = col
        if self.scoped:
            self.calcs.insert(
                0,
                Col("Calculation_scope_match", "boolean", "dimension", "nominal",
                    caption="Selected country", formula=f"[scope] = {PARAM}"),
            )

    def field(self, name: str) -> Col:
        if name in self.cols:
            return self.cols[name]
        for calc in self.calcs:
            if calc.name == name:
                return calc
        raise KeyError(f"{self.stem}: no column or calculation named {name!r}")

    def connection_xml(self, data_dir: Path) -> str:
        textscan = _short_hash(self.stem, "textscan.")
        columns = [
            tag("column", {"datatype": c.datatype, "name": c.name, "ordinal": i})
            for i, c in enumerate(self.cols.values())
        ]
        return tag("connection", {"class": "federated"}, [
            tag("named-connections", None, [
                tag("named-connection", {"caption": self.stem, "name": textscan}, [
                    tag("connection", {
                        "class": "textscan",
                        "directory": data_dir.resolve().as_posix(),
                        "filename": self.filename,
                        "password": "",
                        "server": "",
                    }),
                ]),
            ]),
            tag("relation", {
                "connection": textscan,
                "name": self.filename,
                "table": f"[{self.stem}#csv]",
                "type": "table",
            }, [
                tag("columns", {"character-set": "UTF-8", "header": "yes", "locale": "en_GB", "separator": ","}, columns),
            ]),
        ])

    def extract_xml(self, extract_dir: Path) -> str:
        """Point the data source at its .hyper extract (Tableau Public opens extracts only)."""
        hyper = (extract_dir / f"{self.stem}.hyper").resolve().as_posix()
        return tag("extract", {"count": "-1", "enabled": "true", "units": "records"}, [
            tag("connection", {
                "access_mode": "readonly", "author-locale": "en_GB", "class": "hyper", "dbname": hyper,
                "default-settings": "hyper", "schema": "Extract", "sslmode": "", "tablename": "Extract",
                "update-time": "10/27/2026 12:00:00 PM", "username": "tableau",
            }, [
                tag("relation", {"name": "Extract", "table": "[Extract].[Extract]", "type": "table"}),
                tag("refresh", {"increment-key": "", "incremental-updates": "false"}),
            ]),
        ])

    def xml(self, data_dir: Path, extract_dir: Path | None = None) -> str:
        body = [self.connection_xml(data_dir)]
        if extract_dir is not None and EXTRACT_POSITION == "after_connection":
            body.append(self.extract_xml(extract_dir))
        body.append(tag("aliases", {"enabled": "yes"}))
        body += [c.xml() for c in self.cols.values() if c.caption or c.fmt]
        body += [c.xml() for c in self.calcs]
        if extract_dir is not None and EXTRACT_POSITION == "before_layout":
            body.append(self.extract_xml(extract_dir))
        body.append(tag("layout", {"dim-ordering": "alphabetic", "dim-percentage": "0.5",
                                   "measure-ordering": "alphabetic", "measure-percentage": "0.4",
                                   "show-structure": "true"}))
        if extract_dir is not None and EXTRACT_POSITION == "end":
            body.append(self.extract_xml(extract_dir))
        return tag("datasource", {"caption": self.caption, "inline": "true", "name": self.name,
                                  "version": VERSION}, body)

    def write_hyper(self, data_dir: Path, extract_dir: Path) -> Path:
        """Copy the CSV into a Tableau Hyper extract with the same columns and types."""
        from tableauhyperapi import (Connection, CreateMode, HyperProcess, Inserter, SchemaName,
                                     SqlType, TableDefinition, TableName, Telemetry)

        types = {"string": SqlType.text(), "integer": SqlType.big_int(), "real": SqlType.double(),
                 "date": SqlType.date()}
        frame = pd.read_csv(data_dir / self.filename)
        table = TableDefinition(TableName("Extract", "Extract"),
                                [TableDefinition.Column(c.name, types[c.datatype]) for c in self.cols.values()])
        rows = []
        for record in frame.itertuples(index=False):
            row = []
            for value, col in zip(record, self.cols.values()):
                if pd.isna(value):
                    row.append(None)
                elif col.datatype == "date":
                    row.append(pd.Timestamp(value).date())
                elif col.datatype == "integer":
                    row.append(int(value))
                elif col.datatype == "real":
                    row.append(float(value))
                else:
                    row.append(str(value))
            rows.append(row)
        extract_dir.mkdir(parents=True, exist_ok=True)
        path = extract_dir / f"{self.stem}.hyper"
        with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
            with Connection(hyper.endpoint, path, CreateMode.CREATE_AND_REPLACE) as conn:
                conn.catalog.create_schema(SchemaName("Extract"))
                conn.catalog.create_table(table)
                with Inserter(conn, table) as inserter:
                    inserter.add_rows(rows)
                    inserter.execute()
        return path


_DERIVATION = {"none": "None", "sum": "Sum", "avg": "Avg", "usr": "User", "tmn": "Month-Trunc"}


@dataclass
class Ref:
    """A field placed on a shelf, e.g. SUM(net_revenue) or MONTH(month_start)."""

    source: Source
    name: str
    deriv: str = "sum"  # none | sum | avg | usr | tmn

    @property
    def col(self) -> Col:
        return self.source.field(self.name)

    @property
    def suffix(self) -> str:
        if self.deriv in ("sum", "avg", "tmn"):
            return "qk"
        if self.deriv == "usr":
            return "qk" if self.col.type == "quantitative" else "nk"
        return "ok" if self.col.type == "ordinal" else "nk"

    @property
    def instance(self) -> str:
        return f"[{self.deriv}:{self.name}:{self.suffix}]"

    @property
    def full(self) -> str:
        return f"[{self.source.name}].{self.instance}"

    def instance_xml(self) -> str:
        kind = {"qk": "quantitative", "ok": "ordinal", "nk": "nominal"}[self.suffix]
        attrs = {"column": self.col.ref, "derivation": _DERIVATION[self.deriv], "name": self.instance,
                 "pivot": "key", "type": kind}
        return tag("column-instance", attrs)


@dataclass
class Sheet:
    name: str
    title: str
    source: Source
    mark: str  # Bar | Line | Square | Text | Area
    rows: list[Ref] = field(default_factory=list)
    cols: list[Ref] = field(default_factory=list)
    color: Ref | None = None
    text: Ref | None = None
    tooltips: list[Ref] = field(default_factory=list)
    big_number: bool = False

    def refs(self) -> list[Ref]:
        out = [*self.rows, *self.cols, *self.tooltips]
        out += [r for r in (self.color, self.text) if r is not None]
        if self.source.scoped:
            out.append(self.scope_ref)
        return out

    @property
    def scope_ref(self) -> Ref:
        return Ref(self.source, "Calculation_scope_match", "none")

    def _dependencies(self) -> list[str]:
        cols: dict[str, Col] = {}
        instances: dict[str, str] = {}
        for ref in self.refs():
            col = ref.col
            cols[col.name] = col
            if col.formula:  # list the source columns a calculation reads
                for name in re.findall(r"\[([^\]]+)\]", col.formula):
                    if name in self.source.cols:
                        cols[name] = self.source.cols[name]
            instances[ref.instance] = ref.instance_xml()
        deps = [tag("datasource-dependencies", {"datasource": self.source.name},
                    [c.xml() for c in cols.values()] + list(instances.values()))]
        if self.source.scoped:
            deps.append(tag("datasource-dependencies", {"datasource": "Parameters"}, [_PARAMETER_DEP]))
        return deps

    def _table_style(self) -> str:
        if not self.big_number:
            return tag("style")
        return tag("style", None, [tag("style-rule", {"element": "cell"}, [
            tag("format", {"attr": "font-size", "value": "20"}),
            tag("format", {"attr": "font-weight", "value": "bold"}),
            tag("format", {"attr": "text-align", "value": "center"}),
            tag("format", {"attr": "vertical-align", "value": "center"}),
        ])])

    @staticmethod
    def _shelf(refs: list[Ref]) -> str:
        if not refs:
            return ""
        if len(refs) == 1:
            return refs[0].full
        return "(" + " / ".join(r.full for r in refs) + ")"

    def xml(self) -> str:
        view = [tag("datasources", None,
                    [tag("datasource", {"caption": self.source.caption, "name": self.source.name})]
                    + ([tag("datasource", {"name": "Parameters"})] if self.source.scoped else []))]
        view += self._dependencies()
        if self.source.scoped:
            level = self.scope_ref.instance
            view.append(tag("filter", {"class": "categorical", "column": self.scope_ref.full}, [
                tag("groupfilter", {"function": "member", "level": level, "member": "true",
                                    "user:ui-domain": "database", "user:ui-enumeration": "inclusive",
                                    "user:ui-marker": "enumerate"}),
            ]))
            view.append(tag("slices", None, [tag("column", None, escape(self.scope_ref.full))]))
        view.append(tag("aggregation", {"value": "true"}))

        encodings = []
        if self.color:
            encodings.append(tag("color", {"column": self.color.full}))
        if self.text:
            encodings.append(tag("text", {"column": self.text.full}))
        encodings += [tag("tooltip", {"column": r.full}) for r in self.tooltips]

        pane = [tag("view", None, [tag("breakdown", {"value": "auto"})]), tag("mark", {"class": self.mark})]
        if encodings:
            pane.append(tag("encodings", None, encodings))
        if self.text and not self.big_number:
            pane.append(tag("style", None, [tag("style-rule", {"element": "mark"}, [
                tag("format", {"attr": "mark-labels-show", "value": "true"}),
            ])]))

        table = tag("table", None, [
            tag("view", None, view),
            self._table_style(),
            tag("panes", None, [tag("pane", {"selection-relaxation-option": "selection-relaxation-allow"}, pane)]),
            tag("rows", None, escape(self._shelf(self.rows)) or None),
            tag("cols", None, escape(self._shelf(self.cols)) or None),
        ])
        title = tag("layout-options", None, [tag("title", None, [tag("formatted-text", None, [
            tag("run", {"bold": "true", "fontsize": "12"}, escape(self.title))])])])
        return tag("worksheet", {"name": self.name}, [title, table])


@dataclass
class Zone:
    kind: str  # sheet | text | param
    w: int  # width in pixels within its row
    sheet: str | None = None
    runs: list[tuple[str, dict]] = field(default_factory=list)
    show_title: bool = True


@dataclass
class Row:
    h: int  # height in pixels
    zones: list[Zone]


@dataclass
class Dashboard:
    """A fixed-size dashboard: a vertical stack of rows, each a horizontal row of zones."""

    name: str
    rows: list[Row]

    @property
    def zones(self) -> list[Zone]:
        return [z for r in self.rows for z in r.zones]

    def xml(self) -> str:
        ids = iter(range(2, 1000))

        def box(x: int, y: int, w: int, h: int) -> dict:
            return {"h": round(h * 100000 / DASH_H), "id": next(ids), "w": round(w * 100000 / DASH_W),
                    "x": round(x * 100000 / DASH_W), "y": round(y * 100000 / DASH_H)}

        def leaf(z: Zone, x: int, y: int, h: int, fixed: int) -> str:
            attrs = {**box(x, y, z.w, h), "fixed-size": fixed, "is-fixed": "true"}
            if z.kind == "sheet":
                return tag("zone", {**attrs, "name": z.sheet, "show-title": None if z.show_title else "false"})
            if z.kind == "param":
                return tag("zone", {**attrs, "mode": "compact", "param": PARAM, "type": "paramctrl"})
            runs = []
            for j, (text, style) in enumerate(z.runs):
                if j:
                    runs.append(tag("run", None, "Æ&#10;"))
                runs.append(tag("run", style, escape(text)))
            return tag("zone", {**attrs, "type": "text"}, [tag("formatted-text", None, runs)])

        rows, y = [], 0
        for row in self.rows:
            if sum(z.w for z in row.zones) != DASH_W:
                raise ValueError(f"{self.name}: row widths must add up to {DASH_W}")
            x, leaves = 0, []
            for z in row.zones:
                leaves.append(leaf(z, x, y, row.h, row.h if len(row.zones) == 1 else z.w))
                x += z.w
            if len(leaves) == 1:
                rows.append(leaves[0])
            else:
                rows.append(tag("zone", {**box(0, y, DASH_W, row.h), "fixed-size": row.h, "is-fixed": "true",
                                         "param": "horz", "type": "layout-flow"}, leaves))
            y += row.h
        if y != DASH_H:
            raise ValueError(f"{self.name}: row heights must add up to {DASH_H}")
        stack = tag("zone", {**box(0, 0, DASH_W, DASH_H), "param": "vert", "type": "layout-flow"}, rows)
        root = tag("zone", {"h": 100000, "id": 1, "type": "layout-basic", "w": 100000, "x": 0, "y": 0}, [stack])
        size = {"maxheight": DASH_H, "maxwidth": DASH_W, "minheight": DASH_H, "minwidth": DASH_W}
        return tag("dashboard", {"name": self.name}, [tag("style"), tag("size", size), tag("zones", None, [root])])


# --------------------------------------------------------------------------- parameter


_PARAM_ATTRS = {
    "caption": "Country", "datatype": "string", "name": "[Parameter 1]", "param-domain-type": "list",
    "role": "measure", "type": "nominal", "value": f'"{ALL_SCOPE}"',
}
_PARAM_CALC = tag("calculation", {"class": "tableau", "formula": f'"{ALL_SCOPE}"'})
# The copy of the parameter that each worksheet lists in its dependencies.
_PARAMETER_DEP = tag("column", _PARAM_ATTRS, [_PARAM_CALC])


def _parameter_xml(scopes: list[str]) -> str:
    """The Country parameter: "All countries" plus every country, largest first."""
    members = tag("members", None, [tag("member", {"value": f'"{s}"'}) for s in scopes])
    column = tag("column", _PARAM_ATTRS, [_PARAM_CALC, members])
    return tag("datasource", {"hasconnection": "false", "inline": "true", "name": "Parameters",
                              "version": VERSION}, [tag("aliases", {"enabled": "yes"}), column])


# --------------------------------------------------------------------------- the workbook


def _sources() -> dict[str, Source]:
    money = {k: GBP for k in ("gross_sales", "cancelled_value", "net_revenue", "revenue")}
    return {s.stem: s for s in [
        Source("kpi_by_country", "KPIs by country", scoped=True,
               formats={**money, "orders": INT, "customers": INT, "units_sold": INT},
               calcs=[
                   Col("Calculation_aov", "real", "measure", "quantitative", caption="Average order value",
                       fmt=GBP2, formula="SUM([gross_sales]) / SUM([orders])"),
                   Col("Calculation_cancel_rate", "real", "measure", "quantitative", caption="Cancellation rate",
                       fmt=PCT1, formula="-SUM([cancelled_value]) / SUM([gross_sales])"),
               ]),
        Source("monthly_by_country", "Monthly sales by country", scoped=True, dates=("month_start",),
               formats={**money, "orders": INT},
               calcs=[Col("Calculation_value_cancelled", "real", "measure", "quantitative",
                          caption="Value cancelled", fmt=GBP, formula="-SUM([cancelled_value])")]),
        Source("top_products_by_country", "Top products by country", scoped=True, dims=("product_rank",),
               formats={**money, "units_sold": INT}),
        Source("markets_outside_uk", "Markets outside the UK", dims=("market_rank",),
               formats={**money, "orders": INT, "customers": INT, "avg_order_value": GBP}),
        Source("order_timing", "Order timing", dims=("weekday_num", "hour_of_day"),
               formats={"orders": INT, "gross_sales": GBP}),
        Source("rfm_segments", "RFM segments", dims=("segment_rank",),
               formats={**money, "customers": INT, "revenue_share": PCT0}),
        Source("cohort_retention", "Cohort retention", dims=("months_since_first",),
               formats={"retention": PCT0, "cohort_size": INT, "active_customers": INT}),
        Source("new_vs_returning", "New vs returning", dates=("month_start",),
               formats={**money, "customers": INT}),
        Source("customer_pareto", "Customer concentration", dims=("top_customers_pct",),
               formats={**money, "customers": INT, "revenue_share": PCT0}),
    ]}


def _sheets(s: dict[str, Source]) -> list[Sheet]:
    kpi, mon, prod = s["kpi_by_country"], s["monthly_by_country"], s["top_products_by_country"]
    mk, tm, rfm = s["markets_outside_uk"], s["order_timing"], s["rfm_segments"]
    coh, nvr, par = s["cohort_retention"], s["new_vs_returning"], s["customer_pareto"]
    return [
        Sheet("KPI Net Revenue", "Net revenue", kpi, "Text", text=Ref(kpi, "net_revenue"), big_number=True),
        Sheet("KPI Orders", "Orders", kpi, "Text", text=Ref(kpi, "orders"), big_number=True),
        Sheet("KPI AOV", "Average order value", kpi, "Text", text=Ref(kpi, "Calculation_aov", "usr"),
              big_number=True),
        Sheet("KPI Cancellation Rate", "Cancellation rate", kpi, "Text",
              text=Ref(kpi, "Calculation_cancel_rate", "usr"), big_number=True),
        Sheet("KPI Customers", "Known customers", kpi, "Text", text=Ref(kpi, "customers"), big_number=True),
        Sheet("Monthly Net Revenue", "Net revenue by month (complete months)", mon, "Line",
              rows=[Ref(mon, "net_revenue")], cols=[Ref(mon, "month_start", "tmn")],
              tooltips=[Ref(mon, "orders"), Ref(mon, "gross_sales")]),
        Sheet("Top Products", "Top 15 products by net revenue", prod, "Bar",
              rows=[Ref(prod, "product_rank", "none"), Ref(prod, "description", "none")],
              cols=[Ref(prod, "net_revenue")], text=Ref(prod, "net_revenue"),
              tooltips=[Ref(prod, "units_sold")]),
        Sheet("RFM Segments", "Historical revenue by RFM segment (label = share of revenue)", rfm, "Bar",
              rows=[Ref(rfm, "segment_rank", "none"), Ref(rfm, "segment", "none")],
              cols=[Ref(rfm, "revenue")], text=Ref(rfm, "revenue_share"),
              tooltips=[Ref(rfm, "customers")]),
        Sheet("Revenue Concentration", "Share of revenue from the top X% of customers", par, "Bar",
              rows=[Ref(par, "revenue_share")],
              cols=[Ref(par, "top_customers_pct", "none")],
              text=Ref(par, "revenue_share"), tooltips=[Ref(par, "customers"), Ref(par, "net_revenue")]),
        Sheet("Cohort Retention", "Share of each monthly cohort buying again, by months since first purchase",
              coh, "Square",
              rows=[Ref(coh, "cohort_month", "none")], cols=[Ref(coh, "months_since_first", "none")],
              color=Ref(coh, "retention", "avg"), text=Ref(coh, "retention", "avg"),
              tooltips=[Ref(coh, "cohort_size"), Ref(coh, "active_customers")]),
        Sheet("New vs Returning", "Monthly net revenue: new customers (blue) vs returning (orange)", nvr, "Bar",
              rows=[Ref(nvr, "net_revenue")], cols=[Ref(nvr, "month_start", "tmn")],
              color=Ref(nvr, "customer_type", "none"), tooltips=[Ref(nvr, "customers")]),
        Sheet("Cancellations by Month", "Value cancelled by month (complete months)", mon, "Bar",
              rows=[Ref(mon, "Calculation_value_cancelled", "usr")], cols=[Ref(mon, "month_start", "tmn")],
              tooltips=[Ref(mon, "gross_sales")]),
        Sheet("Order Timing", "Orders by weekday and hour (UK time)", tm, "Square",
              rows=[Ref(tm, "weekday_num", "none"), Ref(tm, "day", "none")],
              cols=[Ref(tm, "hour_of_day", "none")], color=Ref(tm, "orders"),
              tooltips=[Ref(tm, "gross_sales")]),
        Sheet("Markets", "Top 15 markets outside the UK (whole period)", mk, "Bar",
              rows=[Ref(mk, "market_rank", "none"), Ref(mk, "country", "none")],
              cols=[Ref(mk, "net_revenue")], text=Ref(mk, "net_revenue"),
              tooltips=[Ref(mk, "customers"), Ref(mk, "orders"), Ref(mk, "avg_order_value")]),
    ]


def _title(text: str, sub: str) -> list[tuple[str, dict]]:
    return [(text, {"bold": "true", "fontcolor": "#0b0b0b", "fontsize": "18"}),
            (sub, {"fontcolor": "#52514e", "fontsize": "10"})]


def _note(text: str) -> list[tuple[str, dict]]:
    return [(text, {"fontcolor": "#52514e", "fontsize": "9"})]


def _dashboards() -> list[Dashboard]:
    kpis = ["KPI Net Revenue", "KPI Orders", "KPI AOV", "KPI Cancellation Rate", "KPI Customers"]
    overview = [
        Row(70, [Zone("text", 900, runs=_title("Online Retail: Sales Overview",
                                               "UK online giftware wholesaler, 1 Dec 2009 to 9 Dec 2011, GBP")),
                 Zone("param", 300)]),
        Row(110, [Zone("sheet", 240, sheet=name) for name in kpis]),
        Row(310, [Zone("sheet", 1200, sheet="Monthly Net Revenue")]),
        Row(420, [Zone("sheet", 1200, sheet="Top Products")]),
        Row(40, [Zone("text", 1200, runs=_note(SOURCE_LINE))]),
    ]
    customers = [
        Row(70, [Zone("text", 1200, runs=_title("Online Retail: Customers",
                                                "Known customers only (78% of lines carry a customer ID)"))]),
        Row(290, [Zone("sheet", 600, sheet="RFM Segments"), Zone("sheet", 600, sheet="Revenue Concentration")]),
        Row(320, [Zone("sheet", 1200, sheet="Cohort Retention")]),
        Row(270, [Zone("sheet", 800, sheet="New vs Returning"), Zone("text", 400, runs=[
            ("What the data says", {"bold": "true", "fontsize": "12"}),
            ("Top 1% of customers (59 accounts) = 31% of net revenue; top 20% = 77%.", {"fontsize": "10"}),
            ("813 'At risk' customers bought often but not recently: £1.52M of historical revenue.",
             {"fontsize": "10"}),
            ("Median next-month retention of a monthly cohort is about 20%.", {"fontsize": "10"}),
            ("Dec 2009 cohort includes customers who bought before the data starts.",
             {"fontcolor": "#52514e", "fontsize": "9"}),
        ])]),
    ]
    operations = [
        Row(70, [Zone("text", 900, runs=_title("Online Retail: Operations",
                                               "Cancellations, order timing and export markets")),
                 Zone("param", 300)]),
        Row(240, [Zone("sheet", 1200, sheet="Cancellations by Month")]),
        Row(230, [Zone("sheet", 1200, sheet="Order Timing")]),
        Row(370, [Zone("sheet", 1200, sheet="Markets")]),
        Row(40, [Zone("text", 1200, runs=_note(
            "Two bulk orders cancelled within minutes (Jan 2011, Dec 2011) are about a third of all cancelled "
            "value. Order timing and markets cover all countries and ignore the Country selector."))]),
    ]
    return [Dashboard("Sales Overview", overview), Dashboard("Customers", customers),
            Dashboard("Operations", operations)]


def _windows(sheets: list[Sheet], dashboards: list[Dashboard]) -> str:
    cards = tag("cards", None, [
        tag("edge", {"name": "left"}, [tag("strip", {"size": "160"}, [
            tag("card", {"type": "pages"}), tag("card", {"type": "filters"}), tag("card", {"type": "marks"})])]),
        tag("edge", {"name": "top"}, [
            tag("strip", {"size": "2147483647"}, [tag("card", {"type": "columns"})]),
            tag("strip", {"size": "2147483647"}, [tag("card", {"type": "rows"})]),
            tag("strip", {"size": "31"}, [tag("card", {"type": "title"})]),
        ]),
    ])
    fit = tag("zoom", {"type": "entire-view"})
    focus = FOCUS or dashboards[0].name
    windows = []
    for sheet in sheets:
        attrs = {"class": "worksheet", "hidden": None if sheet.name == focus else "true",
                 "maximized": "true" if sheet.name == focus else None, "name": sheet.name}
        windows.append(tag("window", attrs, [cards, tag("viewpoint", None, [fit])]))
    # Tableau's schema: a dashboard window is (viewpoints, active, device-preview).
    for d in dashboards:
        viewpoints = tag("viewpoints", None,
                         [tag("viewpoint", {"name": z.sheet}, [fit]) for z in d.zones if z.kind == "sheet"])
        windows.append(tag("window", {"class": "dashboard", "maximized": "true" if d.name == focus else None,
                                      "name": d.name}, [viewpoints, tag("active", {"id": "-1"}), *DEVICE_PREVIEW]))
    return tag("windows", {"source-height": "30"}, windows)


def build(data_dir: Path = TABLEAU_DATA_DIR, out_path: Path = WORKBOOK_PATH,
          extract_dir: Path | None = EXTRACT_DIR) -> Path:
    """Write the workbook. With ``extract_dir`` set, also write .hyper extracts and link them."""
    sources = _sources()
    for src in sources.values():
        src.load_columns(data_dir)
        if extract_dir is not None:
            hyper, csv = extract_dir / f"{src.stem}.hyper", data_dir / src.filename
            # Skip up-to-date extracts: Tableau locks the .hyper files while the workbook is open.
            if not hyper.exists() or hyper.stat().st_mtime < csv.stat().st_mtime:
                src.write_hyper(data_dir, extract_dir)
    scopes = pd.read_csv(data_dir / "kpi_by_country.csv")["scope"].tolist()
    if scopes[0] != ALL_SCOPE:
        raise ValueError(f"first scope must be {ALL_SCOPE!r}")

    sheets = _sheets(sources)
    dashboards = _dashboards()
    parts = [
        "<?xml version='1.0' encoding='utf-8' ?>",
        "<!-- Generated by python -m retail_bi.tableau_workbook. Edit the generator, not this file. -->",
        tag("workbook", {
            "original-version": VERSION, "source-build": "2020.2.0 (20202.20.0525.1210)",
            "source-platform": "win", "version": VERSION,
            "xmlns:user": "http://www.tableausoftware.com/xml/user",
        }, [
            tag("preferences", None, [
                tag("preference", {"name": "ui.encoding.shelf.height", "value": "24"}),
                tag("preference", {"name": "ui.shelf.height", "value": "26"}),
            ]),
            tag("datasources", None, [_parameter_xml(scopes)] + [s.xml(data_dir, extract_dir) for s in sources.values()]),
            tag("worksheets", None, [s.xml() for s in sheets]),
            tag("dashboards", None, [d.xml() for d in dashboards]),
            _windows(sheets, dashboards),
        ]),
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    log.info("wrote %s (%d sheets, %d dashboards)", out_path, len(sheets), len(dashboards))
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--no-data", action="store_true", help="reuse existing CSV extracts")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not args.no_data:
        from . import tableau_data

        tableau_data.build_all(config.DATABASE_PATH)
    build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
