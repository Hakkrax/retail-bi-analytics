-- Question: How do markets compare on revenue, order size and customer base?
-- Grain: one row per country (as recorded on the invoice).
SELECT
    country,
    ROUND(SUM(line_revenue), 2)                                               AS net_revenue,
    ROUND(100.0 * SUM(line_revenue) / SUM(SUM(line_revenue)) OVER (), 2)      AS revenue_share_pct,
    COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN invoice END)             AS orders,
    COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN customer_id END)         AS customers,
    ROUND(SUM(CASE WHEN line_type = 'sale' THEN line_revenue ELSE 0 END)
          / COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN invoice END), 2) AS avg_order_value,
    ROUND(100.0 * -SUM(CASE WHEN line_type = 'cancellation' THEN line_revenue ELSE 0 END)
          / SUM(CASE WHEN line_type = 'sale' THEN line_revenue ELSE 0 END), 2) AS cancellation_rate_pct
FROM fact_sales_line
GROUP BY country
HAVING COUNT(DISTINCT CASE WHEN line_type = 'sale' THEN invoice END) > 0
ORDER BY net_revenue DESC;
