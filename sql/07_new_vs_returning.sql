-- Question: How much monthly revenue comes from first-time vs returning customers?
-- Grain: one row per month per customer type.
-- Notes: "new" = the month of the customer's first sale in this dataset.
--        Customers active in Dec 2009 may have bought before the data starts,
--        so the first month overstates "new" revenue.
--        Cancellations dated before a customer's first sale in the data refer
--        to orders placed before Dec 2009; they get their own label rather
--        than being counted as "returning". Customers with no sale at all in
--        the period (cohort_month IS NULL) are excluded.
SELECT
    SUBSTR(f.invoice_date, 1, 7)                                      AS year_month,
    CASE
        WHEN SUBSTR(f.invoice_date, 1, 7) = c.cohort_month THEN 'New'
        WHEN SUBSTR(f.invoice_date, 1, 7) > c.cohort_month THEN 'Returning'
        ELSE 'Before first purchase'
    END                                                               AS customer_type,
    COUNT(DISTINCT f.customer_id)                                     AS customers,
    ROUND(SUM(f.line_revenue), 2)                                     AS net_revenue
FROM fact_sales_line AS f
JOIN dim_customer AS c ON c.customer_id = f.customer_id
WHERE c.cohort_month IS NOT NULL
GROUP BY year_month, customer_type
ORDER BY year_month, customer_type;
