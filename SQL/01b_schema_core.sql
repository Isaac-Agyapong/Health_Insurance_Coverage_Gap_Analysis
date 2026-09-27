-- =====================================================================
-- Core layer: typed star schema.
--
--   dim_state            expansion date, effective year, analysis group
--   dim_county           2013 baseline characteristics (rurality, poverty, income, race)
--   dim_age_group        SAHIE age categories
--   dim_income_group     SAHIE income-to-poverty categories
--   fact_county_coverage county x year x age x income  (both sexes, all races)
--   fact_state_coverage  state  x year x age x race x income (both sexes)
-- =====================================================================

DROP SCHEMA IF EXISTS analytics CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
CREATE SCHEMA core;
CREATE SCHEMA analytics;

CREATE TABLE core.dim_state (
    state_fips          char(2) PRIMARY KEY,
    state_abbrev        char(2) NOT NULL UNIQUE,
    state_name          text    NOT NULL,
    expansion_status    text    NOT NULL,          -- as published by KFF
    implementation_date date,                      -- first date in the KFF note
    expansion_year      smallint,                  -- first calendar year with >= 6 months of expansion
    analysis_group      text    NOT NULL,          -- used in charts and the dashboard
    in_study            boolean NOT NULL,          -- false for states with comparable coverage before 2014
    excluded_reason     text
);

CREATE TABLE core.dim_county (
    county_fips         char(5) PRIMARY KEY,
    state_fips          char(2) NOT NULL REFERENCES core.dim_state,
    county_name         text    NOT NULL,
    rucc_2013           smallint,
    rurality            text,                      -- Metro / Rural near a metro / Remote rural
    population_2013     integer,
    pct_nh_white_2013   numeric(5,2),
    pct_nh_black_2013   numeric(5,2),
    pct_hispanic_2013   numeric(5,2),
    pct_age_65plus_2013 numeric(5,2),
    poverty_pct_2013    numeric(5,2),
    median_income_2013  integer,
    in_balanced_panel   boolean NOT NULL DEFAULT false   -- present in every year 2008-2023
);

CREATE TABLE core.dim_age_group (
    agecat   smallint PRIMARY KEY,
    label    text NOT NULL
);

CREATE TABLE core.dim_income_group (
    iprcat   smallint PRIMARY KEY,
    label    text NOT NULL,
    short    text NOT NULL
);

CREATE TABLE core.fact_county_coverage (
    county_fips     char(5)  NOT NULL REFERENCES core.dim_county,
    year            smallint NOT NULL,
    agecat          smallint NOT NULL REFERENCES core.dim_age_group,
    iprcat          smallint NOT NULL REFERENCES core.dim_income_group,
    population      integer,                  -- people in the age x income group
    uninsured       integer,
    pct_uninsured   numeric(5,2),
    pct_uninsured_moe numeric(5,2),           -- 90% margin of error
    PRIMARY KEY (county_fips, year, agecat, iprcat)
);

CREATE TABLE core.fact_state_coverage (
    state_fips      char(2)  NOT NULL REFERENCES core.dim_state,
    year            smallint NOT NULL,
    agecat          smallint NOT NULL REFERENCES core.dim_age_group,
    racecat         smallint NOT NULL,        -- 0 all, 1 White NH, 2 Black NH, 3 Hispanic
    iprcat          smallint NOT NULL REFERENCES core.dim_income_group,
    population      integer,
    uninsured       integer,
    pct_uninsured   numeric(5,2),
    pct_uninsured_moe numeric(5,2),
    PRIMARY KEY (state_fips, year, agecat, racecat, iprcat)
);
