-- =====================================================================
-- Business questions (analytics part). Run by Python/03_run_sql_queries.py.
-- Outcome: uninsured rate of adults 18-64 at or below 138% of poverty
-- (the group Medicaid expansion made eligible), population-weighted.
-- =====================================================================

-- Q1: How did the uninsured rate change in each expansion group, 2013 vs 2016 vs 2023?
SELECT analysis_group,
       max(pct_uninsured) FILTER (WHERE year = 2013) AS pct_2013,
       max(pct_uninsured) FILTER (WHERE year = 2016) AS pct_2016,
       max(pct_uninsured) FILTER (WHERE year = 2023) AS pct_2023,
       max(pct_uninsured) FILTER (WHERE year = 2023) - max(pct_uninsured) FILTER (WHERE year = 2013) AS change_pts,
       max(uninsured) FILTER (WHERE year = 2023)     AS uninsured_2023
FROM analytics.v_group_trend
GROUP BY analysis_group ORDER BY pct_2023;

-- Q2: How wide is the gap between 2014 expansion states and non-expansion states each year?
--     LAG shows the year-over-year change in the gap.
SELECT year, expanded_2014, not_expanded, gap_pts,
       gap_pts - lag(gap_pts) OVER (ORDER BY year) AS gap_change
FROM analytics.v_expansion_gap ORDER BY year;

-- Q3: Naive before/after difference-in-differences (2013 -> 2016), 2014 expanders vs never-expanders.
--     A first look only; the causal models (Python/05) handle staggered timing and pre-trends.
WITH g AS (SELECT * FROM analytics.v_expansion_gap WHERE year IN (2013, 2016))
SELECT max(expanded_2014) FILTER (WHERE year = 2016) - max(expanded_2014) FILTER (WHERE year = 2013) AS change_expanded,
       max(not_expanded) FILTER (WHERE year = 2016) - max(not_expanded) FILTER (WHERE year = 2013)   AS change_not_expanded,
      (max(expanded_2014) FILTER (WHERE year = 2016) - max(expanded_2014) FILTER (WHERE year = 2013))
    - (max(not_expanded) FILTER (WHERE year = 2016) - max(not_expanded) FILTER (WHERE year = 2013))  AS naive_did_pts
FROM g;

-- Q4: Which states have the highest uninsured rate among low-income adults today?
SELECT rank_highest_2023 AS rank, state_abbrev, state_name, analysis_group, pct_2013, pct_2023, change_2013_2023,
       uninsured_2023
FROM analytics.v_state_scorecard
ORDER BY rank_highest_2023 LIMIT 12;

-- Q5: Which states cut the rate the most since 2013?
SELECT rank_biggest_drop AS rank, state_abbrev, analysis_group, expansion_year, pct_2013, pct_2023, change_2013_2023
FROM analytics.v_state_scorecard
ORDER BY rank_biggest_drop LIMIT 10;

-- Q6: Did people who were NOT newly eligible (138-400% of poverty) change as much? (placebo intuition)
SELECT income_group, analysis_group,
       max(pct_uninsured) FILTER (WHERE year = 2013) AS pct_2013,
       max(pct_uninsured) FILTER (WHERE year = 2016) AS pct_2016,
       max(pct_uninsured) FILTER (WHERE year = 2016) - max(pct_uninsured) FILTER (WHERE year = 2013) AS change_pts
FROM analytics.v_income_trend
WHERE analysis_group IN ('Expanded 2014', 'Not expanded by 2023') AND iprcat IN (3, 5)
GROUP BY income_group, analysis_group ORDER BY income_group, analysis_group;

-- Q7: Metro vs rural counties: where is the uninsured rate highest now, and where did it fall most?
SELECT rurality, analysis_group, max(counties) AS counties,
       max(pct_uninsured) FILTER (WHERE year = 2013) AS pct_2013,
       max(pct_uninsured) FILTER (WHERE year = 2023) AS pct_2023,
       max(pct_uninsured) FILTER (WHERE year = 2023) - max(pct_uninsured) FILTER (WHERE year = 2013) AS change_pts
FROM analytics.v_rural_trend
WHERE analysis_group IN ('Expanded 2014', 'Not expanded by 2023')
GROUP BY rurality, analysis_group ORDER BY rurality, analysis_group;

-- Q8: Race and ethnicity: uninsured rates by group, expansion vs non-expansion, 2013 and 2023
SELECT race_group, analysis_group,
       max(pct_uninsured) FILTER (WHERE year = 2013) AS pct_2013,
       max(pct_uninsured) FILTER (WHERE year = 2023) AS pct_2023,
       max(pct_uninsured) FILTER (WHERE year = 2023) - max(pct_uninsured) FILTER (WHERE year = 2013) AS change_pts
FROM analytics.v_race_trend
WHERE analysis_group IN ('Expanded 2014', 'Not expanded by 2023')
GROUP BY race_group, analysis_group ORDER BY race_group, analysis_group;

-- Q9: Where is the coverage gap concentrated today? Counties with the most uninsured low-income adults
SELECT county_name, state_abbrev, analysis_group, rurality, pct_uninsured, uninsured, percentile
FROM analytics.v_county_gap_2023
ORDER BY uninsured DESC LIMIT 15;

-- Q10: Share of the national coverage gap held by non-expansion states (2023)
SELECT analysis_group, sum(uninsured) AS uninsured_low_income_adults,
       round(100.0 * sum(uninsured) / sum(sum(uninsured)) OVER (), 1) AS share_of_us_total
FROM analytics.v_group_trend WHERE year = 2023
GROUP BY analysis_group ORDER BY 2 DESC;

-- Q11: The change around expansion, by years since the state expanded (event time)
SELECT event_time AS years_since_expansion, counties, change_vs_year_before
FROM analytics.v_event_time ORDER BY event_time;

-- Q12: Do counties with higher 2013 poverty see bigger drops? (correlation and slope across expansion counties)
WITH d AS (
    SELECT p.county_fips, p.poverty_pct_2013,
           max(p.pct_uninsured) FILTER (WHERE p.year = p.expansion_year - 1) - max(p.pct_uninsured) FILTER (WHERE p.year = p.expansion_year + 2) AS drop_pts
    FROM analytics.mv_county_panel p
    WHERE p.expansion_year BETWEEN 2014 AND 2020
    GROUP BY p.county_fips, p.poverty_pct_2013
)
SELECT count(*) AS counties,
       round(corr(poverty_pct_2013, drop_pts)::numeric, 3)        AS correlation,
       round(regr_slope(drop_pts, poverty_pct_2013)::numeric, 3)  AS pts_drop_per_poverty_pt
FROM d;
