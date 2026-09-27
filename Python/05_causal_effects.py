"""
Causal effect of Medicaid expansion on the uninsured rate of low-income adults (18-64, <=138% FPL).

Method: staggered difference-in-differences (Callaway & Sant'Anna 2021), implemented directly so every
step is visible.
  * ATT(g, t): for counties in states that expanded in year g, the change in the uninsured rate from
    year g-1 to year t, minus the same change in counties of states that never expanded (through 2023).
    Pre-expansion cells use the previous year as the base ("varying base"), so they test for pre-trends.
  * Covariate-adjusted version: the comparison group's change is predicted from 2013 county traits
    (outcome-regression DiD, Sant'Anna & Zhao 2020), so treated counties are compared with similar counties.
  * Aggregation: event study by years since expansion, and an overall effect for years 0-2.
  * Weights: each county counts in proportion to its 2013 low-income adult population.
  * Uncertainty: cluster bootstrap over states (the level at which the policy was decided), 499 draws.
Checks:
  * Pre-trends: event-study estimates before expansion should be close to zero.
  * Comparison outcome: adults at 138-400% of poverty were not made eligible; their effect should be much
    smaller (some spill-over is expected: incomes change during the year and outreach reaches whole families).
  * Placebo date: pretend the 2014 states expanded in 2011 and use only 2008-2013 data; effect should be ~0.
  * Comparison with the traditional two-way fixed-effects regression, which is biased with staggered timing.

Outputs: Data/clean/causal_*.csv, models/causal_results.json, Image/05-07_*.png
"""
import json
import warnings
from importlib import import_module
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg

import viz_style as vs

warnings.filterwarnings("ignore", category=UserWarning)
ROOT = Path(__file__).resolve().parents[1]
CLEAN, MODELS = ROOT / "Data" / "clean", ROOT / "models"
CLEAN.mkdir(parents=True, exist_ok=True)
MODELS.mkdir(exist_ok=True)
CONNINFO = import_module("02_load_postgres").CONNINFO
YEARS = np.arange(2008, 2024)
NEVER = 9999
B = 499
RNG = np.random.default_rng(20260927)
COVARIATES = ["poverty_pct_2013", "log_income_2013", "pct_nh_black_2013", "pct_hispanic_2013",
              "pct_age_65plus_2013", "log_pop_2013", "rural_near", "rural_remote"]


def load_panel():
    with psycopg.connect(CONNINFO) as conn:
        cur = conn.execute("SELECT * FROM analytics.mv_county_panel ORDER BY county_fips, year")
        df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
    num = ["pct_uninsured", "pct_uninsured_138_400", "pct_uninsured_children", "poverty_pct_2013",
           "pct_nh_black_2013", "pct_hispanic_2013", "pct_age_65plus_2013", "median_income_2013", "population_2013"]
    df[num] = df[num].astype(float)
    # States that expanded after the data ends (NC, SD in late 2023) are "not yet treated" for every year observed
    df["g"] = df["expansion_year"].fillna(NEVER).astype(int).where(lambda s: s <= 2023, NEVER)
    return df


def county_table(df):
    """One row per county: cohort, state, weight, covariates; plus outcome matrices (county x year)."""
    c = df[df["year"] == 2013].set_index("county_fips")
    X = pd.DataFrame({
        "poverty_pct_2013": c["poverty_pct_2013"],
        "log_income_2013": np.log(c["median_income_2013"]),
        "pct_nh_black_2013": c["pct_nh_black_2013"],
        "pct_hispanic_2013": c["pct_hispanic_2013"],
        "pct_age_65plus_2013": c["pct_age_65plus_2013"],
        "log_pop_2013": np.log(c["population_2013"]),
        "rural_near": (c["rurality"] == "Rural, near a metro").astype(float),
        "rural_remote": (c["rurality"] == "Remote rural").astype(float),
    })
    info = pd.DataFrame({"state": c["state_abbrev"], "g": c["g"], "w": c["population"].astype(float)})
    Y = {col: df.pivot(index="county_fips", columns="year", values=col).reindex(info.index)
         for col in ["pct_uninsured", "pct_uninsured_138_400"]}
    return info, X, Y


class DiD:
    """Callaway-Sant'Anna ATT(g,t) on a county x year outcome matrix, never-treated comparison group."""

    def __init__(self, Y, g, w, X=None, years=YEARS):
        self.Y, self.g, self.w, self.X, self.years = np.asarray(Y, float), np.asarray(g), np.asarray(w, float), X, years
        self.col = {y: i for i, y in enumerate(years)}

    def att_gt(self, rows=None):
        rows = np.arange(len(self.g)) if rows is None else rows
        Y, g, w = self.Y[rows], self.g[rows], self.w[rows]
        X = None if self.X is None else np.column_stack([np.ones(len(rows)), self.X[rows]])
        ctrl = g == NEVER
        out = []
        for gg in sorted(set(g) - {NEVER}):
            tr = g == gg
            for t in self.years:
                base = gg - 1 if t >= gg else t - 1
                if base not in self.col or t not in self.col or t == base:
                    continue
                d = Y[:, self.col[t]] - Y[:, self.col[base]]
                ok = ~np.isnan(d)
                tr_i, c_i = tr & ok, ctrl & ok
                if tr_i.sum() == 0 or c_i.sum() < 10:
                    continue
                if X is None:
                    counterfactual = np.average(d[c_i], weights=w[c_i])
                    att = np.average(d[tr_i], weights=w[tr_i]) - counterfactual
                else:   # outcome regression: predict each treated county's change from similar comparison counties
                    sw = np.sqrt(w[c_i])
                    beta = np.linalg.lstsq(X[c_i] * sw[:, None], d[c_i] * sw, rcond=None)[0]
                    att = np.average(d[tr_i] - X[tr_i] @ beta, weights=w[tr_i])
                out.append((gg, t, t - gg, att, w[tr_i].sum()))
        return pd.DataFrame(out, columns=["g", "t", "e", "att", "weight"])

    @staticmethod
    def aggregate(cells, emin=-5, emax=8):
        es = (cells[(cells.e >= emin) & (cells.e <= emax)].groupby("e")
              .apply(lambda d: np.average(d.att, weights=d.weight), include_groups=False))
        post = cells[(cells.e >= 0) & (cells.e <= 2) & (cells.g <= 2021)]
        overall = np.average(post.att, weights=post.weight)
        return es, overall

    @staticmethod
    def all_post(cells):
        """Average over every post-expansion cell (same window the two-way fixed effects model uses)."""
        post = cells[cells.e >= 0]
        return np.average(post.att, weights=post.weight)


def bootstrap(info, make_did, stat, B=B):
    """Cluster bootstrap over states: resample whole states with replacement and recompute."""
    states = info["state"].unique()
    idx_by_state = {s: np.flatnonzero(info["state"].values == s) for s in states}
    draws = []
    for _ in range(B):
        pick = RNG.choice(states, size=len(states), replace=True)
        rows = np.concatenate([idx_by_state[s] for s in pick])
        draws.append(stat(make_did.att_gt(rows)))
    return draws


def twfe(df):
    """Traditional two-way fixed effects: y_it = county FE + year FE + beta * treated_now (population weights)."""
    d = df[["county_fips", "year", "pct_uninsured", "treated_now", "population"]].dropna().copy()
    w = d.groupby("county_fips")["population"].transform("first").astype(float)   # constant weight per county
    d["D"] = d["treated_now"].astype(float)
    for v in ["pct_uninsured", "D"]:
        d[v + "_dm"] = d[v] - d.groupby("county_fips")[v].transform("mean")
    yd = pd.get_dummies(d["year"], drop_first=True, dtype=float)
    yd = yd - yd.groupby(d["county_fips"]).transform("mean")
    Xm = np.column_stack([d["D_dm"], yd.values])
    sw = np.sqrt(w.values)
    beta = np.linalg.lstsq(Xm * sw[:, None], d["pct_uninsured_dm"].values * sw, rcond=None)[0]
    return beta[0]


def main():
    vs.apply()
    df = load_panel()
    info, X, Y = county_table(df)
    g, w = info["g"].values, info["w"].values
    Xs = ((X - X.mean()) / X.std()).values
    print(f"{len(info):,} counties in {info.state.nunique()} states; cohorts:",
          info.groupby("g").size().rename(index={NEVER: "never"}).to_dict())

    results = {}
    tables = {}
    for name, did in {"unadjusted": DiD(Y["pct_uninsured"], g, w),
                      "adjusted": DiD(Y["pct_uninsured"], g, w, Xs)}.items():
        cells = did.att_gt()
        es, overall = DiD.aggregate(cells)
        draws = bootstrap(info, did, lambda c: DiD.aggregate(c))
        es_draws = pd.DataFrame([d[0] for d in draws])
        ov_draws = np.array([d[1] for d in draws])
        tab = pd.DataFrame({"e": es.index, "att": es.values,
                            "lo": es_draws.quantile(0.025).reindex(es.index).values,
                            "hi": es_draws.quantile(0.975).reindex(es.index).values})
        pre = tab[tab.e < -1]
        results[name] = {"att_years_0_2": overall, "ci": [float(np.quantile(ov_draws, .025)), float(np.quantile(ov_draws, .975))],
                         "mean_pre_trend": float(pre.att.mean()), "max_abs_pre_trend": float(pre.att.abs().max())}
        tables[name] = tab
        results[name]["att_all_post_years"] = float(DiD.all_post(cells))
        cells.to_csv(CLEAN / f"causal_att_gt_{name}.csv", index=False)
        tab.to_csv(CLEAN / f"causal_event_study_{name}.csv", index=False)
        print(f"{name:>10}: ATT years 0-2 = {overall:.2f} pts (95% CI {results[name]['ci'][0]:.2f} to "
              f"{results[name]['ci'][1]:.2f}); mean pre-trend {results[name]['mean_pre_trend']:.2f}")

    # --- people covered because of expansion, 2023: ATT(g, 2023) x low-income adults in cohort-g counties in 2023
    did_adj = DiD(Y["pct_uninsured"], g, w, Xs)
    pop23 = df[df.year == 2023].set_index("county_fips")["population"].reindex(info.index).astype(float).values

    def people_2023(cells):
        c = cells[cells.t == 2023]
        return float(sum(r.att / 100 * pop23[(g == r.g)].sum() for r in c.itertuples()))
    ppl = people_2023(did_adj.att_gt())
    ppl_draws = bootstrap(info, did_adj, people_2023, B=199)
    results["people_covered_2023"] = {"estimate": -ppl, "ci": [-float(np.quantile(ppl_draws, .975)), -float(np.quantile(ppl_draws, .025))]}
    print(f"people with coverage in 2023 because of expansion: {-ppl:,.0f}")

    # --- placebo 1: adults 138-400% FPL were not newly eligible (data start 2012, so the event window is short)
    yrs = np.arange(2012, 2024)
    Yp = Y["pct_uninsured_138_400"][yrs].values
    did_p = DiD(Yp, g, w, Xs, years=yrs)
    cells_p = did_p.att_gt()
    _, ov_p = DiD.aggregate(cells_p)
    dp = bootstrap(info, did_p, lambda c: DiD.aggregate(c)[1], B=199)
    results["placebo_138_400"] = {"att_years_0_2": ov_p, "ci": [float(np.quantile(dp, .025)), float(np.quantile(dp, .975))]}
    print(f"placebo 138-400% FPL: {ov_p:.2f} ({results['placebo_138_400']['ci'][0]:.2f} to {results['placebo_138_400']['ci'][1]:.2f})")

    # --- placebo 2: fake expansion in 2011 for the 2014 states, using 2008-2013 only
    yrs_f = np.arange(2008, 2014)
    keep = (g == 2014) | (g == NEVER)
    g_fake = np.where(g == 2014, 2011, g)
    did_f = DiD(Y["pct_uninsured"][yrs_f].values[keep], g_fake[keep], w[keep], Xs[keep], years=yrs_f)
    cells_f = did_f.att_gt()
    ov_f = np.average(cells_f[cells_f.e >= 0].att, weights=cells_f[cells_f.e >= 0].weight)
    info_f = info[keep]
    df_draws = bootstrap(info_f, did_f, lambda c: np.average(c[c.e >= 0].att, weights=c[c.e >= 0].weight), B=199)
    results["placebo_fake_2011"] = {"att": float(ov_f), "ci": [float(np.quantile(df_draws, .025)), float(np.quantile(df_draws, .975))]}
    print(f"placebo fake 2011 date: {ov_f:.2f} ({results['placebo_fake_2011']['ci'][0]:.2f} to {results['placebo_fake_2011']['ci'][1]:.2f})")

    # --- traditional TWFE for comparison
    results["twfe"] = float(twfe(df.assign(treated_now=df["g"].le(df["year"]))))
    print(f"two-way fixed effects: {results['twfe']:.2f}  vs Callaway-Sant'Anna, all post years: "
          f"{results['adjusted']['att_all_post_years']:.2f}")

    # --- cohort-specific effects in the 3rd year (e = 2)
    cells_adj = pd.read_csv(CLEAN / "causal_att_gt_adjusted.csv")
    coh = cells_adj[cells_adj.e == 2][["g", "att"]].rename(columns={"g": "expansion_year", "att": "att_year_2"})
    coh["counties"] = coh.expansion_year.map(info.groupby("g").size())
    coh.to_csv(CLEAN / "causal_by_cohort.csv", index=False)
    results["by_cohort_year_2"] = coh.to_dict("records")
    results["counties"] = int(len(info))
    results["states"] = int(info.state.nunique())
    results["covariates"] = COVARIATES
    results["bootstrap_draws"] = B
    (MODELS / "causal_results.json").write_text(json.dumps(results, indent=2, default=float))

    charts(tables["adjusted"], tables["unadjusted"], results)


def charts(es, es_u, r):
    # event study
    fig, ax = plt.subplots(figsize=(9.5, 5))
    ax.axhline(0, color=vs.GREY, lw=0.8)
    ax.axvspan(-0.5, 8.5, color=vs.NAVY, alpha=0.04, lw=0)
    ax.fill_between(es.e, es.lo, es.hi, color=vs.NAVY, alpha=0.15, lw=0, label="95% confidence interval")
    ax.plot(es.e, es.att, color=vs.NAVY, marker="o", ms=5, label="Estimated effect of expansion")
    ax.plot(es_u.e, es_u.att, color=vs.GREY, lw=1.2, ls="--", label="Same, without adjusting for county traits")
    for e, v in es[es.e.isin([0, 2, 8])][["e", "att"]].values:
        ax.annotate(f"{v:.1f} pts", (e, v), xytext=(10, 12), textcoords="offset points", color=vs.NAVY,
                    fontsize=10, fontweight="bold", bbox=dict(boxstyle="round,pad=0.2", fc=vs.PAPER, ec="none"))
    ax.text(-4.8, 1.2, "Before expansion:\nno difference in trends", color=vs.INK_2, fontsize=9.5)
    ax.text(3.2, -4, "After expansion", color=vs.NAVY, fontsize=9.5)
    ax.set_xlabel("Years since the state expanded Medicaid")
    ax.set_ylabel("Change in uninsured rate (percentage points)")
    ax.set_xticks(range(-5, 9))
    vs.title(ax, f"Expansion cut the uninsured rate by {abs(r['adjusted']['att_years_0_2']):.1f} points on average in its first three years",
             "Low-income adults, expansion counties vs similar counties in states that did not expand")
    ax.legend(loc="lower left", fontsize=9)
    vs.source(fig, "Callaway & Sant'Anna difference-in-differences, 3,035 counties, 95% CI from 499 state-level bootstrap draws. "
                   "Source: Census SAHIE; KFF.")
    vs.save(fig, "05_event_study")

    # robustness summary
    rows = [("Main estimate (adjusted, years 0-2)", r["adjusted"]["att_years_0_2"], r["adjusted"]["ci"], vs.NAVY),
            ("Without county adjustment", r["unadjusted"]["att_years_0_2"], r["unadjusted"]["ci"], vs.NAVY_LIGHT),
            ("Adults 138-400% of poverty\n(not made eligible)", r["placebo_138_400"]["att_years_0_2"], r["placebo_138_400"]["ci"], vs.GOLD),
            ("Placebo: fake 2011 expansion date", r["placebo_fake_2011"]["att"], r["placebo_fake_2011"]["ci"], vs.GOLD)]
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    for i, (lab, v, ci, col) in enumerate(rows[::-1]):
        ax.plot(ci, [i, i], color=col, lw=3, alpha=0.5, solid_capstyle="round")
        ax.plot(v, i, "o", color=col, ms=9)
        ax.text(v, i + 0.22, f"{v:+.1f}", ha="center", color=col, fontsize=10, fontweight="bold")
    ax.axvline(0, color=vs.GREY, lw=0.8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r_[0] for r_ in rows[::-1]], fontsize=10)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", visible=True)
    ax.set_xlabel("Effect on uninsured rate (percentage points, 95% CI)")
    vs.title(ax, "The effect is concentrated where the policy applied",
             "No effect before expansion; a much smaller spill-over for people who were not made eligible")
    vs.source(fig, "Placebo 138-400% uses 2012-2023 (first year available). Fake date uses 2008-2013 only.")
    vs.save(fig, "06_robustness_checks")


if __name__ == "__main__":
    main()
