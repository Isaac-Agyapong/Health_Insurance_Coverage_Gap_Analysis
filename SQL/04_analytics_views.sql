-- =====================================================================
-- Analytics layer: one view per business question. The notebook, the
-- causal/ML scripts and the Power BI report read these, never core directly.
--
-- Main outcome throughout: the uninsured rate of adults 18-64 with income at or
-- below 138% of the federal poverty level (agecat 1, iprcat 3), the group that
-- Medicaid expansion made eligible. Rates are population-weighted (sum of
-- uninsured / sum of people), never averages of county percentages.
-- =====================================================================

-- Q1. Uninsured rate over time by expansion group (states; all 50 + DC)
CREATE VIEW analytics.v_group_trend AS
SELECT s.analysis_group, f.year,
       sum(f.uninsured)                                           AS uninsured,
       sum(f.population)                                          AS population,
       round(100.0 * sum(f.uninsured) / sum(f.population), 2)     AS pct_uninsured
FROM core.fact_state_coverage f
JOIN core.dim_state s USING (state_fips)
WHERE f.agecat = 1 AND f.iprcat = 3 AND f.racecat = 0
GROUP BY s.analysis_group, f.year;

-- Q2. The expansion gap each year: expansion-2014 states vs states that had not expanded by 2023
CREATE VIEW analytics.v_expansion_gap AS
SELECT year,
       max(pct_uninsured) FILTER (WHERE analysis_group = 'Expanded 2014')          AS expanded_2014,
       max(pct_uninsured) FILTER (WHERE analysis_group = 'Not expanded by 2023')   AS not_expanded,
       max(pct_uninsured) FILTER (WHERE analysis_group = 'Not expanded by 2023')
     - max(pct_uninsured) FILTER (WHERE analysis_group = 'Expanded 2014')          AS gap_pts
FROM analytics.v_group_trend
GROUP BY year;

-- Q3. State scorecard: rate before (2013), after (2016, 2023), change and rank
CREATE VIEW analytics.v_state_scorecard AS
WITH r AS (
    SELECT f.state_fips, f.year, f.pct_uninsured, f.uninsured, f.population
    FROM core.fact_state_coverage f
    WHERE f.agecat = 1 AND f.iprcat = 3 AND f.racecat = 0
)
SELECT s.state_abbrev, s.state_name, s.analysis_group, s.expansion_year, s.in_study,
       max(r.pct_uninsured) FILTER (WHERE r.year = 2013)                             AS pct_2013,
       max(r.pct_uninsured) FILTER (WHERE r.year = 2016)                             AS pct_2016,
       max(r.pct_uninsured) FILTER (WHERE r.year = 2023)                             AS pct_2023,
       max(r.pct_uninsured) FILTER (WHERE r.year = 2023)
     - max(r.pct_uninsured) FILTER (WHERE r.year = 2013)                             AS change_2013_2023,
       max(r.uninsured) FILTER (WHERE r.year = 2023)                                 AS uninsured_2023,
       max(r.population) FILTER (WHERE r.year = 2023)                                AS low_income_adults_2023,
       rank() OVER (ORDER BY max(r.pct_uninsured) FILTER (WHERE r.year = 2023) DESC) AS rank_highest_2023,
       rank() OVER (ORDER BY max(r.pct_uninsured) FILTER (WHERE r.year = 2023)
                            - max(r.pct_uninsured) FILTER (WHERE r.year = 2013))    AS rank_biggest_drop
FROM r JOIN core.dim_state s USING (state_fips)
GROUP BY s.state_abbrev, s.state_name, s.analysis_group, s.expansion_year, s.in_study;

-- Q4. Who still lacks coverage: trend by income group and expansion status (placebo intuition:
--     people above 138% FPL were not newly eligible, so their gap should move much less)
CREATE VIEW analytics.v_income_trend AS
SELECT s.analysis_group, i.short AS income_group, f.iprcat, f.year,
       round(100.0 * sum(f.uninsured) / sum(f.population), 2) AS pct_uninsured
FROM core.fact_state_coverage f
JOIN core.dim_state s USING (state_fips)
JOIN core.dim_income_group i USING (iprcat)
WHERE f.agecat = 1 AND f.racecat = 0 AND f.iprcat IN (0, 3, 5) AND s.in_study
GROUP BY s.analysis_group, i.short, f.iprcat, f.year;

-- Q5. Metro vs rural counties (balanced county panel, study states)
CREATE VIEW analytics.v_rural_trend AS
SELECT s.analysis_group, c.rurality, f.year,
       count(*)                                               AS counties,
       round(100.0 * sum(f.uninsured) / sum(f.population), 2) AS pct_uninsured
FROM core.fact_county_coverage f
JOIN core.dim_county c USING (county_fips)
JOIN core.dim_state s ON s.state_fips = c.state_fips
WHERE f.agecat = 1 AND f.iprcat = 3 AND c.in_balanced_panel AND s.in_study AND c.rurality IS NOT NULL
GROUP BY s.analysis_group, c.rurality, f.year;

-- Q6. Race and ethnicity gaps (state estimates; SAHIE publishes race only for states)
CREATE VIEW analytics.v_race_trend AS
SELECT s.analysis_group,
       CASE f.racecat WHEN 1 THEN 'White (non-Hispanic)' WHEN 2 THEN 'Black (non-Hispanic)'
                      WHEN 3 THEN 'Hispanic' END                AS race_group,
       f.year,
       round(100.0 * sum(f.uninsured) / sum(f.population), 2)   AS pct_uninsured
FROM core.fact_state_coverage f
JOIN core.dim_state s USING (state_fips)
WHERE f.agecat = 1 AND f.iprcat = 3 AND f.racecat IN (1, 2, 3) AND s.in_study
GROUP BY s.analysis_group, f.racecat, f.year;

-- Q7. County panel used by the causal and machine learning models (materialized: read many times)
CREATE MATERIALIZED VIEW analytics.mv_county_panel AS
SELECT c.county_fips, c.county_name, s.state_abbrev, s.state_fips, s.analysis_group, s.expansion_year,
       f.year,
       f.year - s.expansion_year                                    AS event_time,
       (s.expansion_year IS NOT NULL AND f.year >= s.expansion_year) AS treated_now,
       f.pct_uninsured, f.pct_uninsured_moe, f.population, f.uninsured,
       mid.pct_uninsured                                            AS pct_uninsured_138_400,
       kid.pct_uninsured                                            AS pct_uninsured_children,
       c.rurality, c.rucc_2013, c.population_2013, c.pct_nh_white_2013, c.pct_nh_black_2013,
       c.pct_hispanic_2013, c.pct_age_65plus_2013, c.poverty_pct_2013, c.median_income_2013
FROM core.fact_county_coverage f
JOIN core.dim_county c USING (county_fips)
JOIN core.dim_state s ON s.state_fips = c.state_fips
LEFT JOIN core.fact_county_coverage mid
       ON mid.county_fips = f.county_fips AND mid.year = f.year AND mid.agecat = 1 AND mid.iprcat = 5
LEFT JOIN core.fact_county_coverage kid
       ON kid.county_fips = f.county_fips AND kid.year = f.year AND kid.agecat = 4 AND kid.iprcat = 0
WHERE f.agecat = 1 AND f.iprcat = 3 AND c.in_balanced_panel AND s.in_study;
CREATE UNIQUE INDEX ON analytics.mv_county_panel (county_fips, year);

-- Q8. Coverage gap today: counties with the most uninsured low-income adults in 2023
CREATE VIEW analytics.v_county_gap_2023 AS
SELECT p.county_fips, p.county_name, p.state_abbrev, p.analysis_group, p.rurality,
       p.pct_uninsured, p.uninsured, p.population,
       ntile(5) OVER (ORDER BY p.pct_uninsured)                                   AS rate_quintile,
       rank() OVER (PARTITION BY p.state_abbrev ORDER BY p.pct_uninsured DESC)    AS rank_in_state,
       round(100 * percent_rank() OVER (ORDER BY p.pct_uninsured)::numeric, 1)    AS percentile
FROM analytics.mv_county_panel p
WHERE p.year = 2023;

-- Q9. Change around expansion: average rate by years since expansion (expansion states only),
--     each county measured against its own last pre-expansion year (FIRST_VALUE over the window)
CREATE VIEW analytics.v_event_time AS
WITH w AS (
    SELECT county_fips, event_time, pct_uninsured, population,
           first_value(pct_uninsured) OVER (PARTITION BY county_fips
                                            ORDER BY (event_time = -1) DESC, year) AS base_rate
    FROM analytics.mv_county_panel
    WHERE expansion_year BETWEEN 2014 AND 2022
)
SELECT event_time, count(*) AS counties,
       round(sum((pct_uninsured - base_rate) * population) / sum(population), 2) AS change_vs_year_before
FROM w
WHERE event_time BETWEEN -5 AND 8
GROUP BY event_time;

-- Q10. Headline numbers for the dashboard cards
CREATE VIEW analytics.v_kpi AS
SELECT
    (SELECT pct_uninsured FROM analytics.v_group_trend WHERE analysis_group = 'Expanded 2014' AND year = 2013)        AS exp2014_rate_2013,
    (SELECT pct_uninsured FROM analytics.v_group_trend WHERE analysis_group = 'Expanded 2014' AND year = 2023)        AS exp2014_rate_2023,
    (SELECT pct_uninsured FROM analytics.v_group_trend WHERE analysis_group = 'Not expanded by 2023' AND year = 2013) AS nonexp_rate_2013,
    (SELECT pct_uninsured FROM analytics.v_group_trend WHERE analysis_group = 'Not expanded by 2023' AND year = 2023) AS nonexp_rate_2023,
    (SELECT sum(uninsured) FROM analytics.v_group_trend WHERE analysis_group = 'Not expanded by 2023' AND year = 2023) AS nonexp_uninsured_2023,
    (SELECT count(*) FROM core.dim_county WHERE in_balanced_panel)                                                     AS counties_in_panel;
