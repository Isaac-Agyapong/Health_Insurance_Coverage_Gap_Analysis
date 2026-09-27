"""
Machine learning part: which counties gained the most from Medicaid expansion, and which counties in the
states that have not expanded would gain the most if they did.

Model: causal forest (EconML CausalForestDML, double machine learning). It estimates a separate effect for
every county from county traits, after removing what the traits predict about both the outcome and the
chance of being in an expansion state.

Design ("stacked" event windows, one per expansion year g in 2014-2021):
    rows     treated: counties in states that expanded in year g
             control: counties in states that had not expanded by 2023, over the same years
    outcome  average uninsured rate in years g, g+1, g+2 minus the rate in year g-1 (percentage points)
    X        what can make the effect bigger or smaller, all measured before expansion:
             uninsured rate in g-1, its change over the 3 years before, the 138-400% FPL uninsured rate,
             2013 poverty, income, race/ethnicity, share 65+, population, rurality
    W        expansion-year dummies (calendar-time differences), not used to explain differences in effect
    weights  low-income adult population in year g-1
    folds    grouped by state, so the nuisance models never learn from the state they predict for

Validation:
    1. The forest's average effect must agree with the difference-in-differences estimate (Python/05).
    2. Held-out states: train on 70% of states, rank the other 30% by predicted effect, and check that
       counties predicted to gain more really did (difference-in-differences inside each quartile).
Prediction:
    For counties in states that had not expanded by 2023: the expected drop in the uninsured rate if the
    state expanded, using their 2023 situation, and the number of adults that means.

Outputs: Data/clean/ml_*.csv, models/ml_results.json, models/causal_forest.joblib, Image/07-09_*.png
"""
import json
import warnings
from importlib import import_module
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from econml.dml import CausalForestDML
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

import viz_style as vs

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
CLEAN, MODELS = ROOT / "Data" / "clean", ROOT / "models"
CONNINFO = import_module("02_load_postgres").CONNINFO
COHORTS = [2014, 2015, 2016, 2017, 2019, 2020, 2021]
FEATURES = {
    "base_rate": "Uninsured rate before expansion",
    "pre_trend": "Change in uninsured rate over prior 3 years",
    "base_rate_138_400": "Uninsured rate, adults 138-400% of poverty",
    "poverty_pct_2013": "Poverty rate (2013)",
    "log_income_2013": "Median household income (log, 2013)",
    "pct_nh_black_2013": "Black (non-Hispanic) share",
    "pct_hispanic_2013": "Hispanic share",
    "pct_age_65plus_2013": "Share of residents 65+",
    "log_pop_2013": "Population (log)",
    "rucc_2013": "Rurality code (1 = big metro, 9 = remote)",
}
SEED = 20260927


def load():
    with psycopg.connect(CONNINFO) as conn:
        cur = conn.execute("SELECT * FROM analytics.mv_county_panel ORDER BY county_fips, year")
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    for c in ["pct_uninsured", "pct_uninsured_138_400", "poverty_pct_2013", "pct_nh_black_2013", "pct_hispanic_2013",
              "pct_age_65plus_2013", "median_income_2013", "population_2013", "population", "rucc_2013"]:
        df[c] = df[c].astype(float)
    df["g"] = df["expansion_year"].where(df["expansion_year"] <= 2023)
    return df


def county_traits(df):
    c = df[df.year == 2013].set_index("county_fips")
    return pd.DataFrame({
        "county_name": c.county_name, "state": c.state_abbrev, "analysis_group": c.analysis_group, "g": c.g,
        "rurality": c.rurality, "poverty_pct_2013": c.poverty_pct_2013, "log_income_2013": np.log(c.median_income_2013),
        "pct_nh_black_2013": c.pct_nh_black_2013, "pct_hispanic_2013": c.pct_hispanic_2013,
        "pct_age_65plus_2013": c.pct_age_65plus_2013, "log_pop_2013": np.log(c.population_2013),
        "rucc_2013": c.rucc_2013})


def window_rows(rate, rate_mid, pop, traits, county_ids, base_year, horizon_years, treat):
    """One row per county for an event window with base year `base_year`."""
    r = pd.DataFrame(index=county_ids)
    r["base_rate"] = rate.loc[county_ids, base_year]
    r["pre_trend"] = rate.loc[county_ids, base_year] - rate.loc[county_ids, base_year - 3]
    r["base_rate_138_400"] = rate_mid.loc[county_ids, base_year]
    for f in FEATURES:
        if f in traits:
            r[f] = traits.loc[county_ids, f]
    r["weight"] = pop.loc[county_ids, base_year]
    r["state"] = traits.loc[county_ids, "state"]
    r["T"] = treat
    if horizon_years is not None:
        r["y"] = rate.loc[county_ids, horizon_years].mean(axis=1) - r["base_rate"]
    return r


def build_stack(df, traits):
    rate = df.pivot(index="county_fips", columns="year", values="pct_uninsured")
    rate_mid = df.pivot(index="county_fips", columns="year", values="pct_uninsured_138_400")
    pop = df.pivot(index="county_fips", columns="year", values="population")
    never = traits.index[traits.g.isna()]
    rows = []
    for g in COHORTS:
        treated = traits.index[traits.g == g]
        horizon = [g, g + 1, g + 2]
        for ids, t in [(treated, 1), (never, 0)]:
            w = window_rows(rate, rate_mid, pop, traits, ids, g - 1, horizon, t)
            w["cohort"] = g
            rows.append(w)
    stack = pd.concat(rows).reset_index(names="county_fips")
    # prediction rows: non-expansion counties "expanding now", described by their 2023 situation
    pred = window_rows(rate, rate_mid, pop, traits, never, 2023, None, 0).reset_index(names="county_fips")
    pred["low_income_adults_2023"] = pop.loc[never, 2023].values
    pred["uninsured_2023"] = (rate.loc[never, 2023] * pop.loc[never, 2023] / 100).values
    return stack, pred


def forest():
    return CausalForestDML(
        model_y=HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, min_samples_leaf=40, random_state=SEED),
        model_t=HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, min_samples_leaf=40, random_state=SEED),
        discrete_treatment=True, cv=5, n_estimators=2000, min_samples_leaf=15, max_samples=0.45,
        honest=True, inference=True, random_state=SEED)


def design(d):
    X = d[list(FEATURES)].values
    W = pd.get_dummies(d["cohort"], prefix="c", drop_first=True, dtype=float).values
    return X, W


def did_by_group(d, groups):
    """Weighted difference-in-differences inside each group. Treated and control counties are compared within
    the same expansion-year window (same calendar years), then windows are averaged by treated population."""
    out = []
    for q, part in d.groupby(groups):
        effects, wts, n_t, n_c = [], [], 0, 0
        for _, win in part.groupby("cohort"):
            t, c = win[win["T"] == 1], win[win["T"] == 0]
            if len(t) < 3 or len(c) < 3:
                continue
            effects.append(np.average(t.y, weights=t.weight) - np.average(c.y, weights=c.weight))
            wts.append(t.weight.sum())
            n_t, n_c = n_t + len(t), n_c + len(c)
        if effects:
            out.append((q, np.average(effects, weights=wts), n_t, n_c))
    return pd.DataFrame(out, columns=["group", "actual_effect", "treated_counties", "control_rows"])


def validate(stack, rng):
    """Train on 70% of states, test on the other 30%; repeat over 5 random state splits."""
    states_t = stack.loc[stack["T"] == 1, "state"].unique()
    states_c = stack.loc[stack["T"] == 0, "state"].unique()
    results, rows = [], []
    for split in range(5):
        test_states = set(rng.choice(states_t, int(round(len(states_t) * 0.3)), replace=False)) | \
                      set(rng.choice(states_c, int(round(len(states_c) * 0.3)), replace=False))
        tr, te = stack[~stack.state.isin(test_states)], stack[stack.state.isin(test_states)].copy()
        m = forest()
        X, W = design(tr)
        m.fit(tr.y.values, tr["T"].values, X=X, W=W, sample_weight=tr.weight.values, groups=tr.state.values)
        Xte, _ = design(te)
        te["pred"] = m.effect(Xte)
        # quartiles defined on the treated counties' predictions; control rows are placed with the same cut points
        cuts = np.quantile(te.loc[te["T"] == 1, "pred"], [0.25, 0.5, 0.75])
        te["quartile"] = np.digitize(te.pred, cuts) + 1        # 1 = largest predicted drop
        q = did_by_group(te, "quartile")
        q["predicted"] = q.group.map(te.groupby("quartile").apply(lambda p: np.average(p.pred, weights=p.weight)))
        q["split"] = split
        rows.append(q)
        results.append({"split": split, "test_states": sorted(test_states),
                        "gap_top_vs_bottom_actual": float(q.actual_effect.iloc[0] - q.actual_effect.iloc[-1]),
                        "gap_top_vs_bottom_predicted": float(q.predicted.iloc[0] - q.predicted.iloc[-1])})
    return pd.concat(rows), results


def main():
    vs.apply()
    rng = np.random.default_rng(SEED)
    df = load()
    traits = county_traits(df)
    stack, pred = build_stack(df, traits)
    stack = stack.dropna(subset=list(FEATURES) + ["y"])
    print(f"training rows: {len(stack):,} ({int(stack['T'].sum()):,} treated county windows, "
          f"{int((1 - stack['T']).sum()):,} control county windows, {stack.state.nunique()} states)")

    # ---- 1. held-out-state validation
    val_rows, val = validate(stack, rng)
    val_rows.to_csv(CLEAN / "ml_validation_quartiles.csv", index=False)
    summary_q = val_rows.groupby("group")[["predicted", "actual_effect"]].mean()
    print("held-out states, by predicted-effect quartile (1 = largest predicted drop):\n", summary_q.round(2))

    # ---- 2. final model on all data
    m = forest()
    X, W = design(stack)
    m.fit(stack.y.values, stack["T"].values, X=X, W=W, sample_weight=stack.weight.values, groups=stack.state.values)
    tr = stack[stack["T"] == 1].copy()
    Xt, _ = design(tr)
    tr["cate"] = m.effect(Xt)
    lo, hi = m.effect_interval(Xt, alpha=0.05)
    tr["cate_lo"], tr["cate_hi"] = lo, hi
    ate_treated = float(np.average(tr.cate, weights=tr.weight))
    ate_inf = m.ate_inference(X=Xt)
    print(f"forest average effect on expansion counties: {ate_treated:.2f} pts")
    causal = json.loads((MODELS / "causal_results.json").read_text())
    print(f"difference-in-differences estimate (years 0-2): {causal['adjusted']['att_years_0_2']:.2f} pts")

    # feature importance (how much each trait is used to split on effect differences)
    imp = pd.Series(m.feature_importances_, index=[FEATURES[f] for f in FEATURES]).sort_values(ascending=False)

    # effect by county type among expansion counties
    tr["rurality"] = traits.loc[tr.county_fips, "rurality"].values
    tr["poverty_band"] = pd.qcut(tr.poverty_pct_2013, 4, labels=["Lowest poverty", "Low-mid", "Mid-high", "Highest poverty"])
    tr["base_band"] = pd.qcut(tr.base_rate, 4, labels=["Lowest", "Low-mid", "Mid-high", "Highest"])
    by = {k: tr.groupby(k, observed=True).apply(lambda p: np.average(p.cate, weights=p.weight)).round(2).to_dict()
          for k in ["rurality", "poverty_band", "base_band"]}
    print("effect by 2013 poverty quartile:", by["poverty_band"])
    print("effect by pre-expansion uninsured quartile:", by["base_band"])

    # ---- 3. predictions for counties in states that had not expanded by 2023
    Xp = pred[list(FEATURES)].values
    pred["predicted_effect_pts"] = m.effect(Xp)
    plo, phi = m.effect_interval(Xp, alpha=0.05)
    pred["effect_lo"], pred["effect_hi"] = plo, phi
    pred["adults_gaining_coverage"] = -pred.predicted_effect_pts / 100 * pred.low_income_adults_2023
    pred["county_name"] = traits.loc[pred.county_fips, "county_name"].values
    pred["rurality"] = traits.loc[pred.county_fips, "rurality"].values
    pred["predicted_rate_after"] = pred.base_rate + pred.predicted_effect_pts
    still_not = ~pred.state.isin(["NC", "SD"])            # NC and SD expanded in late 2023
    by_state = (pred.groupby("state").agg(counties=("county_fips", "size"), uninsured_2023=("uninsured_2023", "sum"),
                                           low_income_adults=("low_income_adults_2023", "sum"),
                                           adults_gaining_coverage=("adults_gaining_coverage", "sum"))
                .assign(rate_2023=lambda d: 100 * d.uninsured_2023 / d.low_income_adults,
                        predicted_rate_after=lambda d: 100 * (d.uninsured_2023 - d.adults_gaining_coverage) / d.low_income_adults,
                        expanded_late_2023=lambda d: d.index.isin(["NC", "SD"]))
                .sort_values("adults_gaining_coverage", ascending=False))
    total = float(pred.loc[still_not, "adults_gaining_coverage"].sum())
    print(f"10 states still not expanded: {total:,.0f} low-income adults would gain coverage")
    print(by_state.round(1))

    # ---- save
    cols = ["county_fips", "county_name", "state", "rurality", "base_rate", "predicted_effect_pts", "effect_lo",
            "effect_hi", "predicted_rate_after", "low_income_adults_2023", "uninsured_2023", "adults_gaining_coverage"]
    pred[cols].sort_values("adults_gaining_coverage", ascending=False).to_csv(CLEAN / "ml_nonexpansion_county_predictions.csv", index=False)
    by_state.reset_index().to_csv(CLEAN / "ml_nonexpansion_state_predictions.csv", index=False)
    tr[["county_fips", "state", "cohort", "rurality", "base_rate", "poverty_pct_2013", "cate", "cate_lo", "cate_hi", "y"]] \
        .rename(columns={"y": "observed_change"}).to_csv(CLEAN / "ml_expansion_county_effects.csv", index=False)
    joblib.dump(m, MODELS / "causal_forest.joblib", compress=3)
    out = {
        "training_rows": int(len(stack)), "treated_windows": int(stack["T"].sum()), "states": int(stack.state.nunique()),
        "forest_ate_expansion_counties": ate_treated,
        "forest_ate_ci": [float(x) for x in ate_inf.conf_int_mean()],
        "did_estimate_years_0_2": causal["adjusted"]["att_years_0_2"],
        "validation_splits": val,
        "validation_quartiles_mean": summary_q.reset_index().to_dict("records"),
        "feature_importance": imp.round(4).to_dict(),
        "effect_by": {k: {str(a): b for a, b in v.items()} for k, v in by.items()},
        "nonexpansion_total_adults_gaining": total,
        "nonexpansion_total_ci_note": "sum of county point estimates; county 95% intervals in ml_nonexpansion_county_predictions.csv",
        "nonexpansion_uninsured_2023": float(pred.loc[still_not, "uninsured_2023"].sum()),
        "nonexpansion_counties": int(still_not.sum()),
    }
    (MODELS / "ml_results.json").write_text(json.dumps(out, indent=2, default=float))
    charts(summary_q, imp, by_state, pred, total)


def charts(summary_q, imp, by_state, pred, total):
    # validation: predicted vs actual by quartile on held-out states
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = np.arange(len(summary_q))
    ax.bar(x - 0.19, summary_q.predicted, 0.36, color=vs.NAVY_LIGHT, label="Model's prediction")
    ax.bar(x + 0.19, summary_q.actual_effect, 0.36, color=vs.NAVY, label="What actually happened")
    for i, (p, a) in enumerate(summary_q[["predicted", "actual_effect"]].values):
        ax.text(i - 0.19, p + 0.25, f"{p:.1f}", ha="center", va="bottom", color=vs.INK, fontsize=10.5, fontweight="bold")
        ax.text(i + 0.19, a + 0.25, f"{a:.1f}", ha="center", va="bottom", color="white", fontsize=10.5, fontweight="bold")
    ax.set_xticks(x, ["Top quarter\n(largest predicted drop)", "Second", "Third", "Bottom quarter\n(smallest predicted drop)"])
    ax.axhline(0, color=vs.GREY, lw=0.8)
    ax.set_ylabel("Effect on uninsured rate (pts)")
    vs.title(ax, "Counties the model ranked highest really did gain the most",
             "Tested on states the model never saw (5 random 70/30 state splits, averaged)")
    ax.legend(loc="lower right")
    vs.source(fig, "Actual = difference-in-differences inside each quarter of held-out counties. Source: Census SAHIE; KFF.")
    vs.save(fig, "07_model_validation")

    # what drives differences in the effect
    fig, ax = plt.subplots(figsize=(9, 4.6))
    top = imp.head(8)[::-1]
    colors = [vs.GOLD if i == len(top) - 1 else vs.NAVY_LIGHT for i in range(len(top))]
    ax.barh(top.index, top.values, color=colors)
    for i, v in enumerate(top.values):
        ax.text(v + 0.004, i, f"{v:.0%}", va="center", fontsize=10)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    vs.title(ax, "The uninsured rate before expansion matters most",
             "What the causal forest uses to tell counties apart (share of splits on each county trait)")
    vs.save(fig, "08_effect_drivers")

    # predicted gains in the states still not expanded
    s = by_state[~by_state.expanded_late_2023].sort_values("adults_gaining_coverage")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.barh(s.index, s.adults_gaining_coverage, color=[vs.GOLD if i == len(s) - 1 else vs.ORANGE for i in range(len(s))])
    for i, (v, r0, r1) in enumerate(s[["adults_gaining_coverage", "rate_2023", "predicted_rate_after"]].values):
        ax.text(v + total * 0.004, i, f"{v:,.0f}   ({r0:.0f}% to {r1:.0f}% uninsured)", va="center", fontsize=9.5)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:,.0f}K"))
    ax.set_xlim(0, s.adults_gaining_coverage.max() * 1.55)
    vs.title(ax, f"Expanding in the 10 remaining states would cover about {round(total, -4):,.0f} more adults",
             "Predicted low-income adults gaining coverage, by state (causal forest, 2023 conditions)")
    vs.source(fig, "Adults 18-64 at or below 138% of poverty. Sum of county-level predictions. NC and SD expanded in late 2023 and are not shown.")
    vs.save(fig, "09_nonexpansion_predictions")


if __name__ == "__main__":
    main()
