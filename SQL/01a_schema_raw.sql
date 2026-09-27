-- =====================================================================
-- Raw layer: source files loaded as-is (every column text) with COPY.
-- Typing, cleaning and conforming happen in 02_transform.sql.
-- UNLOGGED: raw data can always be reloaded from Data/raw, and skipping the
-- write-ahead log keeps the C: drive (where WAL lives) from filling up.
-- =====================================================================

DROP SCHEMA IF EXISTS raw CASCADE;
CREATE SCHEMA raw;

-- Census SAHIE, one row per year x geography x age x race x sex x income group.
-- The loader keeps both-sexes rows only (sexcat = 0); everything else is loaded unchanged.
CREATE UNLOGGED TABLE raw.sahie (
    year text, version text, statefips text, countyfips text, geocat text,
    agecat text, racecat text, sexcat text, iprcat text,
    nipr text, nipr_moe text, nui text, nui_moe text, nic text, nic_moe text,
    pctui text, pctui_moe text, pctic text, pctic_moe text,
    state_name text, county_name text
);

-- KFF tracker of state expansion decisions (table embedded in the KFF page).
CREATE UNLOGGED TABLE raw.kff_expansion (
    state_name text, state_abbrev text, expansion_status text, implementation_note text
);

-- Census SAIPE 2013 (fixed-width file, parsed by position in the loader).
CREATE UNLOGGED TABLE raw.saipe_2013 (
    state_fips text, county_fips text, poverty_all_count text, poverty_all_pct text,
    median_hh_income text, area_name text, state_abbrev text
);

-- Census county population estimates, July 1 2013, by age group (AGEGRP 0 = all ages).
CREATE UNLOGGED TABLE raw.population_2013 (
    state_fips text, county_fips text, agegrp text, tot_pop text,
    nhwa_male text, nhwa_female text, nhba_male text, nhba_female text,
    h_male text, h_female text
);

-- USDA ERS Rural-Urban Continuum Codes 2013.
CREATE UNLOGGED TABLE raw.rucc_2013 (
    fips text, state text, county_name text, population_2010 text, rucc_2013 text, description text
);
