-- Question: What are the headline numbers for the whole period?
-- Grain: one row.
-- Notes: net revenue = sale lines + cancellation lines (cancellations are negative).
--        Orders and AOV count sale invoices only.
WITH sales AS (
    SELECT
        SUM(CASE WHEN line_type = 'sale' THEN line_revenue ELSE 0 END)          AS gross_sales,
        SUM(CASE WHEN line_type = 'cancellation' THEN line_revenue ELSE 0 END)  AS cancelled_value,
        SUM(line_revenue)                                                       AS net_revenue,
        COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN invoice END)           AS orders,
        COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN customer_id END)       AS customers,
        COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN stock_code END)        AS products_sold,
        COUNT(DISTINCT country)                                                 AS countries,
        SUM(CASE WHEN line_type = 'sale' THEN quantity ELSE 0 END)              AS units_sold,
        MIN(invoice_date)                                                       AS first_date,
        MAX(invoice_date)                                                       AS last_date
    FROM fact_sales_line
)
SELECT
    ROUND(gross_sales, 2)                                       AS gross_sales,
    ROUND(cancelled_value, 2)                                   AS cancelled_value,
    ROUND(net_revenue, 2)                                       AS net_revenue,
    orders,
    customers,
    products_sold,
    countries,
    units_sold,
    ROUND(gross_sales / orders, 2)                              AS avg_order_value,
    ROUND(100.0 * -cancelled_value / gross_sales, 2)            AS cancellation_rate_pct,
    first_date,
    last_date
FROM sales;
