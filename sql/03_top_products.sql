-- Question: Which products generate the most net revenue, and how concentrated is it?
-- Grain: one row per product, top 25 by net revenue.
WITH product_revenue AS (
    SELECT
        f.stock_code,
        SUM(f.line_revenue)                                              AS net_revenue,
        SUM(CASE WHEN f.line_type = 'sale' THEN f.quantity ELSE 0 END)   AS units_sold,
        COUNT(DISTINCT CASE WHEN f.line_type = 'sale' THEN f.invoice END) AS orders,
        COUNT(DISTINCT f.customer_id)                                    AS customers
    FROM fact_sales_line AS f
    GROUP BY f.stock_code
),
ranked AS (
    SELECT
        pr.*,
        RANK() OVER (ORDER BY net_revenue DESC)                          AS revenue_rank,
        100.0 * net_revenue / SUM(net_revenue) OVER ()                   AS revenue_share_pct,
        100.0 * SUM(net_revenue) OVER (ORDER BY net_revenue DESC
                                       ROWS UNBOUNDED PRECEDING)
              / SUM(net_revenue) OVER ()                                 AS cumulative_share_pct
    FROM product_revenue AS pr
)
SELECT
    r.revenue_rank,
    r.stock_code,
    p.description,
    ROUND(r.net_revenue, 2)           AS net_revenue,
    r.units_sold,
    r.orders,
    r.customers,
    ROUND(r.revenue_share_pct, 3)     AS revenue_share_pct,
    ROUND(r.cumulative_share_pct, 2)  AS cumulative_share_pct
FROM ranked AS r
JOIN dim_product AS p ON p.stock_code = r.stock_code
WHERE r.revenue_rank <= 25
ORDER BY r.revenue_rank;
