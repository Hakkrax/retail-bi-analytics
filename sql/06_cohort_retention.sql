-- Question: Of the customers who first bought in a given month, what share
--           come back in each following month?
-- Grain: one row per (cohort_month, months_since_first).
-- Notes: activity = at least one sale invoice in that month. Known customers only.
WITH activity AS (
    SELECT DISTINCT
        f.customer_id,
        SUBSTR(f.invoice_date, 1, 7) AS active_month
    FROM fact_sales_line AS f
    WHERE f.customer_id IS NOT NULL
      AND f.line_type = 'sale'
),
with_cohort AS (
    SELECT
        a.customer_id,
        c.cohort_month,
        a.active_month,
        (CAST(SUBSTR(a.active_month, 1, 4) AS INTEGER) - CAST(SUBSTR(c.cohort_month, 1, 4) AS INTEGER)) * 12
          + (CAST(SUBSTR(a.active_month, 6, 2) AS INTEGER) - CAST(SUBSTR(c.cohort_month, 6, 2) AS INTEGER))
          AS months_since_first
    FROM activity AS a
    JOIN dim_customer AS c ON c.customer_id = a.customer_id
    WHERE c.cohort_month IS NOT NULL
),
counts AS (
    SELECT cohort_month, months_since_first, COUNT(DISTINCT customer_id) AS active_customers
    FROM with_cohort
    GROUP BY cohort_month, months_since_first
)
SELECT
    c.cohort_month,
    c.months_since_first,
    c.active_customers,
    base.active_customers                                         AS cohort_size,
    ROUND(100.0 * c.active_customers / base.active_customers, 2)  AS retention_pct
FROM counts AS c
JOIN counts AS base
  ON base.cohort_month = c.cohort_month AND base.months_since_first = 0
ORDER BY c.cohort_month, c.months_since_first;
