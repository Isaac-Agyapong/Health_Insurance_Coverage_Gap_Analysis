"""Export the tables the Power BI report imports to dashboard/data/*.csv.

The report reads small CSV extracts instead of connecting to PostgreSQL, so anyone who clones the repository
can open the dashboard without a database. Every number comes from the analytics views; nothing is recalculated
here beyond reshaping and ranking.
"""
from importlib import import_module
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "data"
OUT.mkdir(parents=True, exist_ok=True)
CONNINFO = import_module("02_load_postgres").CONNINFO


def q(conn, sql):
    cur = conn.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


def save(df, name):
    df.to_csv(OUT / f"{name}.csv", index=False)
    print(f"  {name:<24} {len(df):>6,} rows")


def main():
    with psycopg.connect(CONNINFO) as conn:
        save(q(conn, "SELECT analysis_group, year, uninsured, population, pct_uninsured FROM analytics.v_group_trend "
                     "ORDER BY analysis_group, year"), "group_trend")
        save(q(conn, """SELECT s.state_abbrev, s.state_name, s.analysis_group, s.expansion_year, s.in_study, f.year,
                               f.uninsured, f.population, f.pct_uninsured
                        FROM core.fact_state_coverage f JOIN core.dim_state s USING (state_fips)
                        WHERE f.agecat = 1 AND f.iprcat = 3 AND f.racecat = 0 ORDER BY 1, 6""")
             .astype({"expansion_year": "Int64"}), "state_year")
        # breakdowns for the "who is left out" page: 2013 and 2023 rates by group
        inc = q(conn, """SELECT 'Income' AS dimension, income_group AS category, analysis_group, year, pct_uninsured
                         FROM analytics.v_income_trend WHERE iprcat IN (3, 5)""")
        inc["category"] = inc.category.map({"<=138% FPL": "At or below 138% of poverty (eligible)",
                                            "138-400% FPL": "138-400% of poverty (not eligible)"})
        rur = q(conn, "SELECT 'Area' AS dimension, rurality AS category, analysis_group, year, pct_uninsured FROM analytics.v_rural_trend")
        race = q(conn, "SELECT 'Race and ethnicity' AS dimension, race_group AS category, analysis_group, year, pct_uninsured FROM analytics.v_race_trend")
        br = pd.concat([inc, rur, race])
        br = br[br.analysis_group.isin(["Expanded 2014", "Not expanded by 2023"])]
        # self-explanatory row labels in a fixed reading order for the dashboard table
        order = {"At or below 138% of poverty (eligible)": ("Lowest incomes (qualify for expanded Medicaid)", 1),
                 "138-400% of poverty (not eligible)": ("Low-to-middle incomes (do not qualify)", 2),
                 "Metro": ("Cities and suburbs", 3), "Rural, near a metro": ("Small towns near a city", 4),
                 "Remote rural": ("Remote rural areas", 5), "Hispanic": ("Hispanic", 6),
                 "Black (non-Hispanic)": ("Black (non-Hispanic)", 7), "White (non-Hispanic)": ("White (non-Hispanic)", 8)}
        br["row_label"] = br.category.map(lambda c: order[c][0])
        br["row_order"] = br.category.map(lambda c: order[c][1])
        save(br, "breakdown_trend")
        save(q(conn, "SELECT * FROM analytics.v_expansion_gap ORDER BY year"), "expansion_gap")
        cty = q(conn, """SELECT county_fips, county_name, state_abbrev, analysis_group, rurality, pct_uninsured,
                                uninsured, population FROM analytics.v_county_gap_2023""")
        save(cty, "county_2023")
        # "Find your county": every county with 2023 data (all states), its 2013 rate, and its state and US rates
        prof = q(conn, """
            WITH c AS (
                SELECT f.county_fips, f.year, f.uninsured, f.population, f.pct_uninsured
                FROM core.fact_county_coverage f WHERE f.agecat = 1 AND f.iprcat = 3 AND f.year IN (2013, 2023)
            ), st AS (
                SELECT state_fips, 100.0 * uninsured / population AS state_rate
                FROM core.fact_state_coverage WHERE agecat = 1 AND iprcat = 3 AND racecat = 0 AND year = 2023
            )
            SELECT d.county_fips, d.county_name, s.state_abbrev, s.state_name,
                   d.county_name || ', ' || s.state_abbrev                    AS county_label,
                   CASE WHEN s.analysis_group LIKE 'Expanded%' THEN 'Expanded Medicaid in ' || s.expansion_year
                        WHEN s.analysis_group LIKE 'Excluded%' THEN 'Covered low-income adults before 2014'
                        WHEN s.expansion_year IS NOT NULL THEN 'Expanded Medicaid in late 2023'
                        ELSE 'Has not expanded Medicaid' END                    AS medicaid_status,
                   coalesce(d.rurality, 'Not classified')                     AS rurality,
                   c23.uninsured AS uninsured_2023, c23.population AS low_income_adults_2023,
                   c23.pct_uninsured AS rate_2023, c13.pct_uninsured AS rate_2013, st.state_rate AS state_rate_2023,
                   (SELECT 100.0 * sum(uninsured) / sum(population) FROM core.fact_state_coverage
                     WHERE agecat = 1 AND iprcat = 3 AND racecat = 0 AND year = 2023) AS us_rate_2023
            FROM core.dim_county d
            JOIN core.dim_state s USING (state_fips)
            JOIN c c23 ON c23.county_fips = d.county_fips AND c23.year = 2023
            LEFT JOIN c c13 ON c13.county_fips = d.county_fips AND c13.year = 2013
            JOIN st ON st.state_fips = d.state_fips
            WHERE c23.pct_uninsured IS NOT NULL""")
    # national and within-state rankings: 1 = highest share uninsured
    r = prof.rate_2023.astype(float)
    prof["rank_us"] = r.rank(ascending=False, method="min").astype(int)
    prof["counties_ranked"] = len(prof)
    prof["rank_in_state"] = r.groupby(prof.state_abbrev).rank(ascending=False, method="min").astype(int)
    prof["counties_in_state"] = prof.groupby("state_abbrev").county_fips.transform("size")
    save(prof, "county_profile")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
