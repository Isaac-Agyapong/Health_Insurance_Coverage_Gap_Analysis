"""Export the tables the Power BI report imports to dashboard/data/*.csv.

The report reads small CSV extracts instead of connecting to PostgreSQL, so anyone who clones the repository
can open the dashboard without a database. Every number comes from the analytics views (part 1) or the saved
model outputs (part 2); nothing is recalculated here beyond reshaping.
"""
import json
from importlib import import_module
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "data"
OUT.mkdir(parents=True, exist_ok=True)
CLEAN, MODELS = ROOT / "Data" / "clean", ROOT / "models"
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
        # "what happened vs what would have happened": actual rate in the 2014 expansion counties, and the same
        # rate with the estimated effect of expansion added back (the counterfactual) from 2014 on
        actual = q(conn, """SELECT year, 100.0 * sum(uninsured) / sum(population) AS actual
                            FROM analytics.mv_county_panel WHERE expansion_year = 2014 GROUP BY year""")
    att = pd.read_csv(CLEAN / "causal_att_gt_adjusted.csv").query("g == 2014 and e >= 0")[["t", "att"]]
    wi = actual.astype(float).merge(att.rename(columns={"t": "year"}), on="year", how="left")
    wi["without_expansion"] = wi.actual - wi.att.fillna(0)
    wi["year"] = wi.year.astype(int)
    save(wi[["year", "actual", "without_expansion"]], "what_if")

    # ---- causal results (difference-in-differences)
    es = pd.read_csv(CLEAN / "causal_event_study_adjusted.csv").rename(columns={"e": "years_since_expansion"})
    es["period"] = es.years_since_expansion.map(lambda e: "Before expansion" if e < 0 else "After expansion")
    save(es, "event_study")
    cr = json.loads((MODELS / "causal_results.json").read_text())
    mr = json.loads((MODELS / "ml_results.json").read_text())
    metrics = pd.DataFrame([
        ("Effect of expansion (years 0-2)", cr["adjusted"]["att_years_0_2"], *cr["adjusted"]["ci"]),
        ("Effect without county adjustment", cr["unadjusted"]["att_years_0_2"], *cr["unadjusted"]["ci"]),
        ("Adults 138-400% of poverty (not made eligible)", cr["placebo_138_400"]["att_years_0_2"], *cr["placebo_138_400"]["ci"]),
        ("Placebo: fake 2011 expansion date", cr["placebo_fake_2011"]["att"], *cr["placebo_fake_2011"]["ci"]),
        ("Adults covered in 2023 because of expansion", cr["people_covered_2023"]["estimate"], *cr["people_covered_2023"]["ci"]),
        ("Causal forest average effect", mr["forest_ate_expansion_counties"], *mr["forest_ate_ci"]),
        ("Adults who would gain coverage (10 states)", mr["nonexpansion_total_adults_gaining"], None, None),
        ("Uninsured low-income adults (10 states, 2023)", mr["nonexpansion_uninsured_2023"], None, None),
    ], columns=["metric", "value", "ci_low", "ci_high"])
    save(metrics, "model_metrics")
    rob = metrics.iloc[:4].copy()
    rob["order"] = range(1, 5)
    rob["label"] = ["Main estimate", "No county adjustment", "Not made eligible (138-400%)", "Fake 2011 date (placebo)"]
    save(rob, "robustness")

    # ---- machine learning outputs
    val = pd.DataFrame(mr["validation_quartiles_mean"]).rename(columns={"group": "quartile"})
    val["label"] = val.quartile.map({1: "Biggest expected gain", 2: "Second", 3: "Third", 4: "Smallest expected gain"})
    val["actual_drop"] = -val.actual_effect          # shown as a positive "fewer uninsured per 100" number
    save(val, "ml_validation")
    st = pd.read_csv(CLEAN / "ml_nonexpansion_state_predictions.csv")
    save(st, "ml_state_predictions")
    ten = st[~st.expanded_late_2023]
    extra = pd.DataFrame([
        ("Uninsured rate today (10 states)", 100 * ten.uninsured_2023.sum() / ten.low_income_adults.sum(), None, None),
        ("Uninsured rate if expanded (10 states)",
         100 * (ten.uninsured_2023.sum() - ten.adults_gaining_coverage.sum()) / ten.low_income_adults.sum(), None, None),
        ("Texas adults gaining coverage", ten.set_index("state").adults_gaining_coverage["TX"], None, None),
    ], columns=["metric", "value", "ci_low", "ci_high"]).astype({"ci_low": float, "ci_high": float})
    save(pd.concat([metrics, extra]), "model_metrics")
    ct = pd.read_csv(CLEAN / "ml_nonexpansion_county_predictions.csv")
    ct = ct[~ct.state.isin(["NC", "SD"])]      # expanded in late 2023
    save(ct, "ml_county_predictions")
    imp = pd.Series(mr["feature_importance"]).rename_axis("trait").reset_index(name="importance")
    save(imp, "ml_drivers")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
