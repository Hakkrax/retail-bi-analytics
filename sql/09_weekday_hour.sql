-- Question: When do customers place orders? (staffing and campaign timing)
-- Grain: one row per weekday x hour.
-- Notes: timestamps are UK local time as recorded. Only one Saturday in the
--        data has orders (2009-12-05, 30 invoices), so Saturday is effectively closed.
SELECT
    d.day_of_week,
    CAST(STRFTIME('%w', f.invoice_date) AS INTEGER)   AS weekday_num,   -- 0 = Sunday
    CAST(STRFTIME('%H', f.invoice_ts) AS INTEGER)     AS hour_of_day,
    COUNT(DISTINCT f.invoice)                         AS orders,
    ROUND(SUM(f.line_revenue), 2)                     AS gross_sales
FROM fact_sales_line AS f
JOIN dim_date AS d ON d.date = f.invoice_date
WHERE f.line_type = 'sale'
GROUP BY d.day_of_week, weekday_num, hour_of_day
ORDER BY weekday_num, hour_of_day;
