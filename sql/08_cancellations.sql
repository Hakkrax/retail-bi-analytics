-- Question: Which products lose the most value to cancellations, relative to what they sell?
-- Grain: one row per product, top 20 by cancelled value.
-- Notes: products with under 1,000 of sales are left out so tiny items with one
--        cancellation don't top the rate ranking.
WITH product AS (
    SELECT
        stock_code,
        SUM(CASE WHEN line_type = 'sale' THEN line_revenue ELSE 0 END)          AS gross_sales,
        -SUM(CASE WHEN line_type = 'cancellation' THEN line_revenue ELSE 0 END) AS cancelled_value,
        COUNT(DISTINCT CASE WHEN line_type = 'cancellation' THEN invoice END)   AS cancellation_invoices
    FROM fact_sales_line
    GROUP BY stock_code
)
SELECT
    p.stock_code,
    d.description,
    ROUND(p.gross_sales, 2)                                AS gross_sales,
    ROUND(p.cancelled_value, 2)                            AS cancelled_value,
    p.cancellation_invoices,
    ROUND(100.0 * p.cancelled_value / p.gross_sales, 2)    AS cancellation_rate_pct
FROM product AS p
JOIN dim_product AS d ON d.stock_code = p.stock_code
WHERE p.gross_sales >= 1000 AND p.cancelled_value > 0
ORDER BY p.cancelled_value DESC
LIMIT 20;
