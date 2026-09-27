-- =====================================================================
-- Data quality checks. Run by Python/03_run_sql_queries.py; results in
-- SQL/query_results.md. Each check states what a pass looks like.
-- =====================================================================

-- Q1: Row counts by layer (raw rows kept vs typed core rows)
SELECT 'raw.sahie (both sexes)' AS layer, count(*) AS rows FROM raw.sahie
UNION ALL SELECT 'core.fact_county_coverage', count(*) FROM core.fact_county_coverage
UNION ALL SELECT 'core.fact_state_coverage', count(*) FROM core.fact_state_coverage
UNION ALL SELECT 'core.dim_county', count(*) FROM core.dim_county
UNION ALL SELECT 'core.dim_county (balanced panel)', count(*) FROM core.dim_county WHERE in_balanced_panel
UNION ALL SELECT 'analytics.mv_county_panel (county-years)', count(*) FROM analytics.mv_county_panel;

-- Q2: Missing values ('.' in the source). Pass: Kalawao County HI (population ~80, flagged N/A by the
--     Census) plus a few small subgroups in Loving County TX (population ~60); neither is in the panel outcome
SELECT c.county_fips, c.county_name, count(*) AS missing_rows
FROM core.fact_county_coverage f JOIN core.dim_county c USING (county_fips)
WHERE f.pct_uninsured IS NULL
GROUP BY c.county_fips, c.county_name;

-- Q3: Counties that change during 2008-2023 (why the balanced panel has fewer counties than the source)
SELECT c.county_fips, c.county_name, min(f.year) AS first_year, max(f.year) AS last_year, count(DISTINCT f.year) AS years
FROM core.fact_county_coverage f JOIN core.dim_county c USING (county_fips)
WHERE NOT c.in_balanced_panel
GROUP BY c.county_fips, c.county_name
ORDER BY c.county_fips;

-- Q4: Duplicate keys after the FIPS renames. Pass: 0 rows
SELECT county_fips, year, agecat, iprcat, count(*)
FROM core.fact_county_coverage
GROUP BY 1, 2, 3, 4 HAVING count(*) > 1;

-- Q5: Internal consistency: uninsured / population = published rate. Pass: mismatches only in tiny groups,
--     where the Census rounds counts and rates separately
SELECT CASE WHEN population < 100 THEN 'group under 100 people' ELSE 'group of 100+ people' END AS group_size,
       count(*) FILTER (WHERE abs(100.0 * uninsured / population - pct_uninsured) > 1) AS rows_off_by_1pt,
       count(*) AS rows_checked
FROM core.fact_county_coverage
WHERE population > 0
GROUP BY 1;

-- Q6: Counties add up to states: sum of county uninsured vs the state estimate (adults 18-64, <=138% FPL)
--     Pass: county sums within a few percent of the state figure (SAHIE models counties and states separately)
WITH cty AS (
    SELECT c.state_fips, f.year, sum(f.uninsured) AS county_sum
    FROM core.fact_county_coverage f JOIN core.dim_county c USING (county_fips)
    WHERE f.agecat = 1 AND f.iprcat = 3
    GROUP BY 1, 2
)
SELECT s.year,
       sum(cty.county_sum)                                              AS county_total,
       sum(s.uninsured)                                                 AS state_total,
       round(100.0 * (sum(cty.county_sum) - sum(s.uninsured)) / sum(s.uninsured), 2) AS pct_difference,
       max(abs(100.0 * (cty.county_sum - s.uninsured) / s.uninsured))::numeric(6,2)   AS worst_state_pct_diff
FROM core.fact_state_coverage s JOIN cty USING (state_fips, year)
WHERE s.agecat = 1 AND s.iprcat = 3 AND s.racecat = 0
GROUP BY s.year ORDER BY s.year;

-- Q7: Reconcile with the Census press release for SAHIE 2023 (CB25-TPS.56, July 31 2025):
--     "The median county uninsured rate of working-age adults living at or below 138% of poverty was
--     17.7%, down from 18.6% in 2022 and 20.3% in 2021" (this project's main outcome);
--     "The median county uninsured rate in 2023 was 9.3%, compared to 9.4% in 2022 and 10.4% in 2021";
--     "1,455 or 46.3% of U.S. counties had an estimated uninsured rate below 10% in 2023, up from 45.2%
--     in 2022 and 39.2% in 2021". Pass: medians match exactly; the county count matches closely when
--     "below 10%" is read as the whole 90% confidence interval being below 10%.
WITH main AS (
    SELECT year, percentile_cont(0.5) WITHIN GROUP (ORDER BY pct_uninsured) AS median_low_income_adults
    FROM core.fact_county_coverage
    WHERE agecat = 1 AND iprcat = 3 AND pct_uninsured IS NOT NULL
    GROUP BY year
)
SELECT f.year,
       round(max(m.median_low_income_adults)::numeric, 1)                       AS median_low_income_adults,
       CASE f.year WHEN 2021 THEN 20.3 WHEN 2022 THEN 18.6 WHEN 2023 THEN 17.7 END AS published_1,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY f.pct_uninsured)             AS median_all_under65,
       CASE f.year WHEN 2021 THEN 10.4 WHEN 2022 THEN 9.4 WHEN 2023 THEN 9.3 END   AS published_2,
       round(100.0 * count(*) FILTER (WHERE f.pct_uninsured + f.pct_uninsured_moe < 10) / count(*), 1) AS pct_counties_below_10,
       CASE f.year WHEN 2021 THEN 39.2 WHEN 2022 THEN 45.2 WHEN 2023 THEN 46.3 END AS published_3
FROM core.fact_county_coverage f JOIN main m USING (year)
WHERE f.agecat = 0 AND f.iprcat = 0 AND f.year IN (2021, 2022, 2023) AND f.pct_uninsured IS NOT NULL
GROUP BY f.year ORDER BY f.year;

-- Q8: Every state matched a KFF expansion record and got a group. Pass: 51 states, no NULL groups
SELECT analysis_group, count(*) AS states, string_agg(state_abbrev, ', ' ORDER BY state_abbrev) AS members
FROM core.dim_state GROUP BY analysis_group ORDER BY analysis_group;

-- Q9: Baseline county traits joined for every panel county. Pass: 0 missing in each column
SELECT count(*) FILTER (WHERE rurality IS NULL)           AS missing_rurality,
       count(*) FILTER (WHERE poverty_pct_2013 IS NULL)   AS missing_poverty,
       count(*) FILTER (WHERE median_income_2013 IS NULL) AS missing_income,
       count(*) FILTER (WHERE population_2013 IS NULL)    AS missing_population,
       count(*)                                           AS panel_counties
FROM core.dim_county WHERE in_balanced_panel;

-- Q10: Precision of the main outcome: median 90% margin of error by county size.
--      Small counties have wide margins, so the models weight by population.
SELECT CASE WHEN c.population_2013 < 10000 THEN '1. under 10k'
            WHEN c.population_2013 < 50000 THEN '2. 10k-50k'
            WHEN c.population_2013 < 250000 THEN '3. 50k-250k'
            ELSE '4. 250k+' END                                           AS county_size,
       count(DISTINCT c.county_fips)                                      AS counties,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY f.pct_uninsured_moe)   AS median_moe_pts
FROM core.fact_county_coverage f JOIN core.dim_county c USING (county_fips)
WHERE f.agecat = 1 AND f.iprcat = 3 AND c.in_balanced_panel
GROUP BY 1 ORDER BY 1;
