-- Question: How concentrated is revenue among customers? (the "80/20" check)
-- Grain: one row per revenue band of customers (top 1%, 5%, 10%, 20%, 50%, all).
WITH per_customer AS (
    SELECT customer_id, SUM(line_revenue) AS net_revenue
    FROM fact_sales_line
    WHERE customer_id IS NOT NULL
    GROUP BY customer_id
    HAVING SUM(line_revenue) > 0
),
ranked AS (
    SELECT
        net_revenue,
        ROW_NUMBER() OVER (ORDER BY net_revenue DESC) AS rn,
        COUNT(*) OVER ()                               AS n,
        SUM(net_revenue) OVER ()                       AS total
    FROM per_customer
),
bands(top_pct) AS (VALUES (1), (5), (10), (20), (50), (100))
SELECT
    b.top_pct                                              AS top_customers_pct,
    COUNT(r.rn)                                            AS customers,
    ROUND(SUM(r.net_revenue), 2)                           AS net_revenue,
    ROUND(100.0 * SUM(r.net_revenue) / MAX(r.total), 2)    AS revenue_share_pct
FROM bands AS b
-- integer ceiling of n * pct / 100 (SQLite's CEIL needs an optional build flag)
JOIN ranked AS r ON r.rn <= (r.n * b.top_pct + 99) / 100
GROUP BY b.top_pct
ORDER BY b.top_pct;
