-- Question: Which customers are most valuable, which are slipping away?
-- Method: RFM (recency, frequency, monetary), each scored 1-5 by quintile.
-- Grain: one row per known customer with positive net spend.
-- Notes: recency is measured from the day after the last invoice in the data
--        (2011-12-10), not from today. Guest lines (no customer ID) are excluded.
WITH snapshot AS (
    SELECT DATE(MAX(invoice_date), '+1 day') AS as_of FROM fact_sales_line
),
per_customer AS (
    SELECT
        f.customer_id,
        CAST(JULIANDAY(s.as_of) - JULIANDAY(MAX(CASE WHEN f.line_type = 'sale'
                                                     THEN f.invoice_date END)) AS INTEGER) AS recency_days,
        COUNT(DISTINCT CASE WHEN f.line_type = 'sale' THEN f.invoice END)                  AS frequency,
        SUM(f.line_revenue)                                                                AS monetary
    FROM fact_sales_line AS f
    CROSS JOIN snapshot AS s
    WHERE f.customer_id IS NOT NULL
    GROUP BY f.customer_id
    HAVING SUM(f.line_revenue) > 0 AND frequency > 0
),
scored AS (
    SELECT
        *,
        6 - NTILE(5) OVER (ORDER BY recency_days)  AS r_score,   -- recent = 5
        NTILE(5) OVER (ORDER BY frequency)         AS f_score,
        NTILE(5) OVER (ORDER BY monetary)          AS m_score
    FROM per_customer
)
SELECT
    customer_id,
    recency_days,
    frequency,
    ROUND(monetary, 2) AS monetary,
    r_score,
    f_score,
    m_score,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Champions'
        WHEN r_score >= 3 AND f_score >= 3                  THEN 'Loyal'
        WHEN r_score >= 4 AND f_score <= 2                  THEN 'New or promising'
        WHEN r_score <= 2 AND f_score >= 3                  THEN 'At risk'
        WHEN r_score <= 2 AND f_score <= 2                  THEN 'Hibernating'
        ELSE 'Needs attention'
    END AS segment
FROM scored
ORDER BY monetary DESC;
