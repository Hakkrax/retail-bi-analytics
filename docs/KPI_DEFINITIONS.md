# KPI definitions

One definition per KPI, written three ways so the SQL results, the Tableau dashboard and an optional Power BI build all agree. All money is GBP. All measures read from `fact_sales_line`.

**Base rules**

- A **sale line** has `line_type = 'sale'` (positive quantity). A **cancellation line** has `line_type = 'cancellation'` (invoice starts with `C`, negative quantity, negative `line_revenue`).
- `line_revenue = quantity × unit_price`, rounded to pence, signed.
- An **order** is a distinct sale invoice. Cancellation invoices are not orders.
- **Customer KPIs** use lines with a customer ID only (78% of lines).
- **Growth comparisons** use complete months only (`dim_date.is_complete_month = 1`); December 2011 has 9 days.

| KPI | Definition | SQL | Tableau calculated field | Power BI DAX measure |
|---|---|---|---|---|
| Gross Sales | Value of sale lines | `SUM(CASE WHEN line_type='sale' THEN line_revenue ELSE 0 END)` | `SUM(IF [Line Type]="sale" THEN [Line Revenue] END)` | `Gross Sales = CALCULATE(SUM(fact_sales_line[line_revenue]), fact_sales_line[line_type] = "sale")` |
| Cancelled Value | Value of cancellation lines (negative) | `SUM(CASE WHEN line_type='cancellation' THEN line_revenue ELSE 0 END)` | `SUM(IF [Line Type]="cancellation" THEN [Line Revenue] END)` | `Cancelled Value = CALCULATE(SUM(fact_sales_line[line_revenue]), fact_sales_line[line_type] = "cancellation")` |
| Net Revenue | Gross sales + cancelled value | `SUM(line_revenue)` | `SUM([Line Revenue])` | `Net Revenue = SUM(fact_sales_line[line_revenue])` |
| Orders | Distinct sale invoices | `COUNT(DISTINCT CASE WHEN line_type='sale' THEN invoice END)` | `COUNTD(IF [Line Type]="sale" THEN [Invoice] END)` | `Orders = CALCULATE(DISTINCTCOUNT(fact_sales_line[invoice]), fact_sales_line[line_type] = "sale")` |
| Average Order Value | Gross sales ÷ orders | `gross_sales / orders` | `[Gross Sales] / [Orders]` | `AOV = DIVIDE([Gross Sales], [Orders])` |
| Cancellation Rate | Cancelled value as % of gross sales | `-cancelled_value / gross_sales` | `-[Cancelled Value] / [Gross Sales]` | `Cancellation Rate = DIVIDE(-[Cancelled Value], [Gross Sales])` |
| Active Customers | Distinct customers with a sale | `COUNT(DISTINCT CASE WHEN line_type='sale' THEN customer_id END)` | `COUNTD(IF [Line Type]="sale" THEN [Customer Id] END)` | `Active Customers = CALCULATE(DISTINCTCOUNT(fact_sales_line[customer_id]), fact_sales_line[line_type] = "sale", NOT ISBLANK(fact_sales_line[customer_id]))` |
| Units Sold | Quantity on sale lines | `SUM(CASE WHEN line_type='sale' THEN quantity ELSE 0 END)` | `SUM(IF [Line Type]="sale" THEN [Quantity] END)` | `Units Sold = CALCULATE(SUM(fact_sales_line[quantity]), fact_sales_line[line_type] = "sale")` |
| MoM Growth % | Change vs previous month | `LAG(net_revenue) OVER (ORDER BY year_month)` | table calc: `(ZN([Net Revenue]) - LOOKUP(ZN([Net Revenue]), -1)) / ABS(LOOKUP(ZN([Net Revenue]), -1))` | `MoM % = VAR prev = CALCULATE([Net Revenue], DATEADD(dim_date[date], -1, MONTH)) RETURN DIVIDE([Net Revenue] - prev, prev)` |
| YoY Growth % | Change vs same month last year | `LAG(net_revenue, 12) OVER (...)` | table calc: as above with `LOOKUP(..., -12)` | `YoY % = VAR prev = CALCULATE([Net Revenue], SAMEPERIODLASTYEAR(dim_date[date])) RETURN DIVIDE([Net Revenue] - prev, prev)` |
| Revenue Share % | Item's net revenue ÷ total | `SUM(x) / SUM(SUM(x)) OVER ()` | quick table calc "Percent of Total" | `Share % = DIVIDE([Net Revenue], CALCULATE([Net Revenue], ALL(dim_product)))` |

## Customer models (computed in SQL, loaded as separate sources)

| Model | File | Definition |
|---|---|---|
| **RFM** | `sql/05_customer_rfm.sql` | Recency = days from last sale to 2011-12-10. Frequency = distinct sale invoices. Monetary = net revenue. Each scored 1–5 by quintile (`NTILE(5)`), recency reversed so recent = 5. Segments: Champions (R≥4, F≥4, M≥4), Loyal (R≥3, F≥3), New or promising (R≥4, F≤2), At risk (R≤2, F≥3), Hibernating (R≤2, F≤2), Needs attention (everything else). |
| **Cohort retention** | `sql/06_cohort_retention.sql` | Cohort = month of first sale. Retention at month *n* = customers in the cohort with a sale in month *n* ÷ cohort size. |
| **New vs returning** | `sql/07_new_vs_returning.sql` | "New" = line in the customer's cohort month; "Returning" = later month. |
| **Pareto** | `sql/10_customer_pareto.sql` | Customers ranked by net revenue; share of revenue from the top 1/5/10/20/50/100%. |

## KPIs deliberately left out

| KPI | Why |
|---|---|
| Gross profit, margin | No cost data in the source |
| Inventory turnover, stock cover | No stock levels in the source |
| Customer lifetime value (predictive) | Two years of data and no margin; RFM monetary value is shown instead, labelled as historical revenue |
