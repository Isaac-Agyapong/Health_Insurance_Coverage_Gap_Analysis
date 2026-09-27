-- =====================================================================
-- raw -> core. Every cleaning rule below fixes a problem found while
-- profiling the raw layer (see README "Data problems found and fixed").
-- =====================================================================

-- ---------------------------------------------------------------------
-- County code changes during 2008-2023. Two counties were renamed with new
-- FIPS codes; they are mapped to the current code so each has one history.
-- (Other boundary changes, like Connecticut's 2022 switch to planning regions,
-- cannot be mapped one-to-one; those units drop out of the balanced panel.)
-- ---------------------------------------------------------------------
CREATE TEMP TABLE fips_map (old_fips char(5) PRIMARY KEY, new_fips char(5) NOT NULL);
INSERT INTO fips_map VALUES
    ('46113', '46102'),     -- Shannon County SD renamed Oglala Lakota County (2015)
    ('02270', '02158');     -- Wade Hampton Census Area AK renamed Kusilvak Census Area (2015)

CREATE TEMP VIEW sahie_typed AS
SELECT s.year::smallint                                     AS year,
       s.statefips                                          AS state_fips,
       coalesce(m.new_fips, s.statefips || s.countyfips)    AS county_fips,
       s.geocat::smallint                                   AS geocat,
       s.agecat::smallint                                   AS agecat,
       s.racecat::smallint                                  AS racecat,
       s.iprcat::smallint                                   AS iprcat,
       nullif(s.nipr, '.')::integer                         AS population,     -- '.' marks missing values
       nullif(s.nui, '.')::integer                          AS uninsured,
       nullif(s.pctui, '.')::numeric(5,2)                   AS pct_uninsured,
       nullif(s.pctui_moe, '.')::numeric(5,2)               AS pct_uninsured_moe,
       s.county_name
FROM raw.sahie s
LEFT JOIN fips_map m ON m.old_fips = s.statefips || s.countyfips
WHERE s.sexcat = '0'
  AND coalesce(s.version, '') IN ('', 'Updated');           -- 2013 was re-released; keep the updated version

-- ---------------------------------------------------------------------
-- dim_state: KFF expansion status. The effective expansion year is the first
-- calendar year with at least six months of expansion coverage (a July-December
-- start counts from the next year), because SAHIE measures coverage over the year.
-- ---------------------------------------------------------------------
INSERT INTO core.dim_state
WITH k AS (
    SELECT trim(k.state_name) AS state_name, trim(k.state_abbrev) AS state_abbrev,
           trim(k.expansion_status) AS expansion_status,
           to_date(substring(k.implementation_note FROM '\d{1,2}/\d{1,2}/\d{4}'), 'MM/DD/YYYY') AS implementation_date
    FROM raw.kff_expansion k
), fips AS (
    SELECT DISTINCT statefips AS state_fips, trim(state_name) AS state_name
    FROM raw.sahie WHERE geocat = '40'
), typed AS (
    SELECT f.state_fips, k.state_abbrev, k.state_name, k.expansion_status, k.implementation_date,
           CASE WHEN k.implementation_date IS NULL THEN NULL
                WHEN extract(month FROM k.implementation_date) <= 6 THEN extract(year FROM k.implementation_date)
                ELSE extract(year FROM k.implementation_date) + 1 END::smallint AS expansion_year,
           -- States that already covered low-income adults broadly before 2014 are excluded, as in
           -- the published literature (e.g. Miller, Johnson & Wherry 2021): their "before" period is already treated.
           CASE WHEN k.state_abbrev IN ('DE', 'DC', 'MA', 'NY', 'VT')
                THEN 'Covered low-income adults broadly before 2014' END AS excluded_reason
    FROM k JOIN fips f USING (state_name)
)
SELECT state_fips, state_abbrev, state_name, expansion_status, implementation_date, expansion_year,
       CASE WHEN excluded_reason IS NOT NULL THEN 'Excluded (early coverage)'
            WHEN expansion_year = 2014 THEN 'Expanded 2014'
            WHEN expansion_year BETWEEN 2015 AND 2017 THEN 'Expanded 2015-2017'
            WHEN expansion_year BETWEEN 2018 AND 2023 THEN 'Expanded 2019-2022'
            ELSE 'Not expanded by 2023' END,
       excluded_reason IS NULL,
       excluded_reason
FROM typed;

-- ---------------------------------------------------------------------
-- dim_age_group / dim_income_group (SAHIE code lists)
-- ---------------------------------------------------------------------
INSERT INTO core.dim_age_group VALUES
    (0, 'Under 65'), (1, 'Adults 18-64'), (2, 'Adults 40-64'), (3, 'Adults 50-64'),
    (4, 'Children under 19'), (5, 'Adults 21-64');

INSERT INTO core.dim_income_group VALUES
    (0, 'All income levels', 'All incomes'),
    (1, 'At or below 200% of poverty', '<=200% FPL'),
    (2, 'At or below 250% of poverty', '<=250% FPL'),
    (3, 'At or below 138% of poverty (Medicaid expansion eligible)', '<=138% FPL'),
    (4, 'At or below 400% of poverty', '<=400% FPL'),
    (5, 'Between 138% and 400% of poverty (Marketplace subsidy range)', '138-400% FPL');

-- ---------------------------------------------------------------------
-- dim_county: every county that appears in SAHIE, with 2013 baseline traits
-- ---------------------------------------------------------------------
INSERT INTO core.dim_county (county_fips, state_fips, county_name)
SELECT DISTINCT ON (county_fips) county_fips, state_fips, trim(county_name)
FROM sahie_typed
WHERE geocat = 50
ORDER BY county_fips, year DESC;                            -- latest name (e.g. Oglala Lakota County)

UPDATE core.dim_county c
SET rucc_2013 = r.rucc_2013::smallint,
    rurality  = CASE WHEN r.rucc_2013 IN ('1', '2', '3') THEN 'Metro'
                     WHEN r.rucc_2013 IN ('4', '6', '8') THEN 'Rural, near a metro'
                     WHEN r.rucc_2013 IN ('5', '7', '9') THEN 'Remote rural' END
FROM raw.rucc_2013 r
LEFT JOIN fips_map m ON m.old_fips = lpad(r.fips, 5, '0')
WHERE c.county_fips = coalesce(m.new_fips, lpad(r.fips, 5, '0'));

UPDATE core.dim_county c
SET population_2013     = p.tot,
    pct_nh_white_2013   = round(100.0 * p.nhwa / nullif(p.tot, 0), 2),
    pct_nh_black_2013   = round(100.0 * p.nhba / nullif(p.tot, 0), 2),
    pct_hispanic_2013   = round(100.0 * p.hisp / nullif(p.tot, 0), 2),
    pct_age_65plus_2013 = round(100.0 * p.age65 / nullif(p.tot, 0), 2)
FROM (
    SELECT coalesce(m.new_fips, lpad(state_fips, 2, '0') || lpad(county_fips, 3, '0')) AS fips,
           sum(tot_pop::int) FILTER (WHERE agegrp = '0')                                         AS tot,
           sum(nhwa_male::int + nhwa_female::int) FILTER (WHERE agegrp = '0')                    AS nhwa,
           sum(nhba_male::int + nhba_female::int) FILTER (WHERE agegrp = '0')                    AS nhba,
           sum(h_male::int + h_female::int) FILTER (WHERE agegrp = '0')                          AS hisp,
           sum(tot_pop::int) FILTER (WHERE agegrp::int BETWEEN 14 AND 18)                        AS age65
    FROM raw.population_2013 p
    LEFT JOIN fips_map m ON m.old_fips = lpad(state_fips, 2, '0') || lpad(county_fips, 3, '0')
    GROUP BY 1
) p
WHERE c.county_fips = p.fips;

UPDATE core.dim_county c
SET poverty_pct_2013   = nullif(s.poverty_all_pct, '.')::numeric,
    median_income_2013 = nullif(s.median_hh_income, '.')::integer
FROM raw.saipe_2013 s
LEFT JOIN fips_map m ON m.old_fips = s.state_fips || s.county_fips
WHERE s.county_fips <> '000'
  AND c.county_fips = coalesce(m.new_fips, s.state_fips || s.county_fips);

-- ---------------------------------------------------------------------
-- Facts
-- ---------------------------------------------------------------------
INSERT INTO core.fact_county_coverage
SELECT county_fips, year, agecat, iprcat, population, uninsured, pct_uninsured, pct_uninsured_moe
FROM sahie_typed
WHERE geocat = 50 AND racecat = 0;

INSERT INTO core.fact_state_coverage
SELECT state_fips, year, agecat, racecat, iprcat, population, uninsured, pct_uninsured, pct_uninsured_moe
FROM sahie_typed
WHERE geocat = 40 AND racecat BETWEEN 0 AND 3;              -- race groups 4-7 only exist from 2021

-- A county is in the balanced panel if the main outcome (adults 18-64 at or below 138% FPL)
-- is present in all 16 years. Excludes Kalawao HI (always missing), Connecticut (counties
-- replaced by planning regions in 2022), Bedford city VA (merged 2013) and split Alaska areas.
UPDATE core.dim_county c
SET in_balanced_panel = true
WHERE (SELECT count(*) FROM core.fact_county_coverage f
       WHERE f.county_fips = c.county_fips AND f.agecat = 1 AND f.iprcat = 3
         AND f.pct_uninsured IS NOT NULL) = 16;

CREATE INDEX ON core.fact_county_coverage (agecat, iprcat, year);
CREATE INDEX ON core.dim_county (state_fips);
ANALYZE core.fact_county_coverage;
ANALYZE core.fact_state_coverage;
ANALYZE core.dim_county;
