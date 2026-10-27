-- Question: How is net revenue moving month to month and year over year?
-- Grain: one row per calendar month.
-- Notes: December 2011 only has 9 days of data; is_complete_month lets the
--        dashboard exclude it from growth comparisons.
WITH monthly AS (
    SELECT
        d.year_month,
        d.is_complete_month,
        SUM(CASE WHEN f.line_type = 'sale' THEN f.line_revenue ELSE 0 END)         AS gross_sales,
        SUM(CASE WHEN f.line_type = 'cancellation' THEN f.line_revenue ELSE 0 END) AS cancelled_value,
        SUM(f.line_revenue)                                                        AS net_revenue,
        COUNT(DISTINCT CASE WHEN f.line_type = 'sale' THEN f.invoice END)          AS orders,
        COUNT(DISTINCT CASE WHEN f.line_type = 'sale' THEN f.customer_id END)      AS active_customers
    FROM fact_sales_line AS f
    JOIN dim_date AS d ON d.date = f.invoice_date
    GROUP BY d.year_month, d.is_complete_month
)
SELECT
    year_month,
    is_complete_month,
    ROUND(gross_sales, 2)                                        AS gross_sales,
    ROUND(cancelled_value, 2)                                    AS cancelled_value,
    ROUND(net_revenue, 2)                                        AS net_revenue,
    orders,
    active_customers,
    ROUND(gross_sales / orders, 2)                               AS avg_order_value,
    ROUND(100.0 * (net_revenue - LAG(net_revenue) OVER w)
          / LAG(net_revenue) OVER w, 2)                          AS mom_growth_pct,
    ROUND(100.0 * (net_revenue - LAG(net_revenue, 12) OVER w)
          / LAG(net_revenue, 12) OVER w, 2)                      AS yoy_growth_pct
FROM monthly
WINDOW w AS (ORDER BY year_month)
ORDER BY year_month;
