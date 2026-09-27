"""Build Python/04_analysis.ipynb with nbformat and execute it, so the outputs show on GitHub.

    python Python/04_build_notebook.py

The notebook reads the analytics views in PostgreSQL (part 1: analytics) and the saved outputs of
05_causal_effects.py and 06_ml_county_effects.py (part 2: causal effect and machine learning).
"""
import subprocess
import sys
from pathlib import Path

import nbformat as nbf

HERE = Path(__file__).resolve().parent
NB = HERE / "04_analysis.ipynb"

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Health Insurance Coverage Gap Analysis and Machine Learning Model for Medicaid Expansion Impact

**In short:** between 2014 and 2023, 40 states and DC expanded Medicaid so that adults earning up to 138% of the
poverty line could get free coverage. This notebook measures what happened to the share of low-income adults
without health insurance, how much of the drop the policy itself caused, and which places would gain the most
if the remaining states expanded.

* **Part 1, analytics:** trends, gaps between states, counties, income, rural areas and race (PostgreSQL views).
* **Part 2, causal effect and machine learning:** results of `05_causal_effects.py` (difference-in-differences)
  and `06_ml_county_effects.py` (causal forest).

Data: Census Small Area Health Insurance Estimates (SAHIE) 2008-2023 for 3,143 counties; KFF expansion dates;
Census poverty, income and population estimates; USDA rural-urban codes. Main outcome: the uninsured rate of
adults 18-64 with income at or below 138% of the federal poverty level (the group expansion made eligible).
""")

code("""
import json, warnings
from importlib import import_module
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from IPython.display import Image, display
from matplotlib.collections import PolyCollection

import viz_style as vs

warnings.filterwarnings("ignore")
vs.apply()
pd.set_option("display.float_format", "{:,.1f}".format)
ROOT = Path.cwd().parent
CONNINFO = import_module("02_load_postgres").CONNINFO
conn = psycopg.connect(CONNINFO)

def q(sql):
    cur = conn.execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
""")

md("## Part 1: Analytics\n\n### 1. The uninsured rate fell everywhere, but much faster where Medicaid expanded")
code("""
trend = q("SELECT * FROM analytics.v_group_trend ORDER BY year")
trend["pct_uninsured"] = trend.pct_uninsured.astype(float)
wide = trend.pivot(index="year", columns="analysis_group", values="pct_uninsured")

fig, ax = plt.subplots(figsize=(10, 5))
ax.axvspan(2013.5, 2023.4, color=vs.EXP, alpha=0.035, lw=0)
for grp, col in vs.GROUP_COLORS.items():
    main = grp in ("Expanded 2014", "Not expanded by 2023")
    ax.plot(wide.index, wide[grp], color=col, lw=2.8 if main else 1.4, alpha=1 if main else 0.9, zorder=3 if main else 2)
    nudge = {"Expanded 2014": 0.9, "Expanded 2015-2017": -0.9}.get(grp, 0)
    ax.text(2023.2, wide[grp].iloc[-1] + nudge, f"{grp}  {wide[grp].iloc[-1]:.0f}%", color=col, va="center",
            fontsize=10 if main else 9, fontweight="bold" if main else "normal")
ax.text(2013.6, 50.5, "ACA coverage starts (2014)", color=vs.INK_2, fontsize=9)
ax.set_xlim(2008, 2027.8)
ax.set_xticks(range(2008, 2024, 3))
drop_e = wide.loc[2013, "Expanded 2014"] - wide.loc[2016, "Expanded 2014"]
drop_n = wide.loc[2013, "Not expanded by 2023"] - wide.loc[2016, "Not expanded by 2023"]
ax.set_ylim(0, 52)
vs.pct(ax)
vs.title(ax, f"The uninsured rate fell {drop_e:.0f} points in states that expanded in 2014, {drop_n:.0f} elsewhere",
         "Share of low-income adults (18-64, at or below 138% of poverty) without health insurance; 2013 to 2016")
vs.source(fig)
vs.save(fig, "01_uninsured_trend_by_group")
display(Image(vs.IMAGE_DIR / "01_uninsured_trend_by_group.png"))
wide.loc[[2008, 2013, 2014, 2016, 2019, 2023]].round(1)
""")

md("### 2. Where the coverage gap is today (2023, every county)")
code("""
geo = json.loads((ROOT / "Data" / "raw" / "geojson-counties-fips.json").read_text())
gap = q("SELECT county_fips, pct_uninsured::float AS rate FROM core.fact_county_coverage "
        "WHERE year = 2023 AND agecat = 1 AND iprcat = 3").set_index("county_fips")["rate"]
states = q("SELECT state_fips, state_abbrev, analysis_group FROM core.dim_state")

def albers(lon, lat, lon0=-96, lat0=37.5, p1=29.5, p2=45.5):
    lon, lat, lon0, lat0, p1, p2 = map(np.radians, (lon, lat, lon0, lat0, p1, p2))
    n = (np.sin(p1) + np.sin(p2)) / 2
    c = np.cos(p1) ** 2 + 2 * n * np.sin(p1)
    rho = np.sqrt(c - 2 * n * np.sin(lat)) / n
    rho0 = np.sqrt(c - 2 * n * np.sin(lat0)) / n
    return rho * np.sin(n * (lon - lon0)), rho0 - rho * np.cos(n * (lon - lon0))

polys, vals = [], []
for f in geo["features"]:
    fips = {"46113": "46102"}.get(f["id"], f["id"])     # Shannon County SD is now Oglala Lakota (46102)
    if fips[:2] in ("02", "15", "72"):          # continental US only (Alaska, Hawaii shown in tables)
        continue
    g = f["geometry"]
    rings = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    for poly in rings:
        xy = np.array(poly[0])
        x, y = albers(xy[:, 0], xy[:, 1])
        polys.append(np.column_stack([x, y]))
        vals.append(gap.get(fips, np.nan))
vals = np.array(vals, dtype=float)

fig, ax = plt.subplots(figsize=(11, 6.6))
cmap = vs.INDIGO_SCALE.copy()
cmap.set_bad("#e6e3dc")
pc = PolyCollection(polys, array=np.ma.masked_invalid(vals), cmap=cmap, edgecolors=vs.PAPER, linewidths=0.08)
pc.set_clim(5, 50)
ax.add_collection(pc)
ax.autoscale_view()
ax.set_aspect("equal")
ax.axis("off")
cb = fig.colorbar(pc, ax=ax, orientation="horizontal", fraction=0.035, pad=0.02, aspect=40)
cb.set_label("Uninsured rate, low-income adults, 2023 (%)", color=vs.INK_2)
cb.outline.set_visible(False)
vs.title(ax, "The coverage gap is concentrated in Texas and the Southeast",
         "Share of low-income adults without health insurance in each county, 2023 (darker = more uninsured)")
vs.source(fig, "Source: Census SAHIE 2023. Continental US (Alaska and Hawaii in the tables). Connecticut in grey: its counties became planning regions in 2022.")
vs.save(fig, "02_county_map_2023")
display(Image(vs.IMAGE_DIR / "02_county_map_2023.png"))
""")

md("### 3. State scorecard: highest uninsured rates today and biggest drops since 2013")
code("""
sc = q("SELECT * FROM analytics.v_state_scorecard WHERE in_study OR analysis_group LIKE 'Excluded%' ORDER BY pct_2023 DESC")
for c in ["pct_2013", "pct_2016", "pct_2023", "change_2013_2023"]:
    sc[c] = sc[c].astype(float)
fig, ax = plt.subplots(figsize=(10, 11))
s = sc.sort_values("pct_2023")
colors = [vs.GROUP_COLORS[g] for g in s.analysis_group]
ax.barh(s.state_abbrev, s.pct_2023, color=colors, height=0.72)
for i, (v, ch) in enumerate(s[["pct_2023", "change_2013_2023"]].values):
    ax.text(v + 0.3, i, f"{v:.0f}%  ({ch:+.0f} pts since 2013)", va="center", fontsize=8.5, color=vs.INK_2)
ax.grid(axis="y", visible=False); ax.grid(axis="x", visible=True)
ax.set_ylim(-0.7, len(s) - 0.3)
ax.set_xlim(0, 52)
vs.pct(ax, "x")
ax.tick_params(axis="y", labelsize=8.5)
handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in vs.GROUP_COLORS.values()]
ax.legend(handles, vs.GROUP_COLORS.keys(), loc="lower right", fontsize=9)
n_top = int((sc.head(10).analysis_group == "Not expanded by 2023").sum())
vs.title(ax, f"{n_top} of the 10 highest uninsured rates are in states that had not expanded by 2023",
         "Uninsured rate of low-income adults in 2023, all states (change since 2013 in brackets)")
vs.source(fig)
vs.save(fig, "03_state_scorecard")
display(Image(vs.IMAGE_DIR / "03_state_scorecard.png"))
sc[["state_abbrev", "analysis_group", "pct_2013", "pct_2023", "change_2013_2023"]].head(10)
""")

md("""
### 4. The gap opened for the people expansion made eligible, much less for everyone else

Adults at 138-400% of poverty were not made eligible for Medicaid (they could get Marketplace subsidies in every
state), so the gap between expansion and non-expansion states should widen much less for them.
""")
code("""
inc = q("SELECT * FROM analytics.v_income_trend WHERE analysis_group IN ('Expanded 2014', 'Not expanded by 2023') ORDER BY year")
inc["pct_uninsured"] = inc.pct_uninsured.astype(float)
fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
for ax, (ipr, label) in zip(axes, [(3, "At or below 138% of poverty (made eligible)"), (5, "138-400% of poverty (not made eligible)")]):
    d = inc[inc.iprcat == ipr].pivot(index="year", columns="analysis_group", values="pct_uninsured")
    for grp in ["Expanded 2014", "Not expanded by 2023"]:
        ax.plot(d.index, d[grp], color=vs.GROUP_COLORS[grp], lw=2.4)
    ax.fill_between(d.index, d["Expanded 2014"], d["Not expanded by 2023"], where=d.index >= 2014, color=vs.SUN, alpha=0.18, lw=0)
    gap13 = d.loc[2013, "Not expanded by 2023"] - d.loc[2013, "Expanded 2014"]
    gap16 = d.loc[2016, "Not expanded by 2023"] - d.loc[2016, "Expanded 2014"]
    ax.set_title(label, fontsize=11, loc="left", pad=8)
    ax.text(2016.2, (d.loc[2016].mean()), f"gap {gap13:.0f} to {gap16:.0f} pts\\n(2013 to 2016)", color=vs.INK_2, fontsize=9.5)
    vs.pct(ax)
axes[0].text(2008.3, 44, "Not expanded", color=vs.NONEXP, fontweight="bold")
axes[0].text(2008.3, 33.5, "Expanded 2014", color=vs.EXP, fontweight="bold")
fig.suptitle("The gap nearly doubled for the eligible group; it widened far less for everyone else", x=0.01, ha="left",
             fontweight="bold", fontsize=15, color=vs.INK)
vs.source(fig, "Source: Census SAHIE. Adults 18-64. The 138-400% group is published from 2012.")
vs.save(fig, "04_income_groups")
display(Image(vs.IMAGE_DIR / "04_income_groups.png"))
""")

md("### 5. Rural and metro counties, race and ethnicity")
code("""
rural = q(open(ROOT / "SQL" / "05_business_questions.sql", encoding="utf-8-sig").read().split("-- Q7:")[1].split("-- Q8:")[0].split("\\n", 1)[1])
rural
""")
code("""
race = q(open(ROOT / "SQL" / "05_business_questions.sql", encoding="utf-8-sig").read().split("-- Q8:")[1].split("-- Q9:")[0].split("\\n", 1)[1])
race
""")
md("""
Remote rural counties had lower rates than big metros to begin with, and all county types in expansion states
fell by about 20-22 points. Hispanic low-income adults have the highest uninsured rates in both groups; in
non-expansion states nearly half (46%) are still uninsured.
""")

md("""
## Part 2: How much did expansion itself cause? (difference-in-differences)

The fall in part 1 mixes the effect of expansion with everything else that happened after 2014 (the ACA
Marketplace, a strong economy). `05_causal_effects.py` isolates expansion's effect by comparing each expansion
county's change with the change in similar counties in states that did not expand over the same years
(Callaway & Sant'Anna staggered difference-in-differences, population-weighted, state-clustered bootstrap).
""")
code("""
cr = json.loads((ROOT / "models" / "causal_results.json").read_text())
display(Image(vs.IMAGE_DIR / "05_event_study.png"))
pd.DataFrame({
    "estimate (pts)": [cr["adjusted"]["att_years_0_2"], cr["unadjusted"]["att_years_0_2"], cr["placebo_138_400"]["att_years_0_2"],
                       cr["placebo_fake_2011"]["att"], cr["adjusted"]["att_all_post_years"], cr["twfe"]],
    "95% CI": [f"{a:.1f} to {b:.1f}" for a, b in [cr["adjusted"]["ci"], cr["unadjusted"]["ci"], cr["placebo_138_400"]["ci"],
                                                  cr["placebo_fake_2011"]["ci"]]] + ["", ""],
}, index=["Main: covariate-adjusted, years 0-2", "Unadjusted, years 0-2", "Adults 138-400% FPL (not made eligible)",
          "Placebo: fake 2011 expansion", "Adjusted, all post years", "Two-way fixed effects (traditional)"])
""")
code("""
display(Image(vs.IMAGE_DIR / "06_robustness_checks.png"))
print(f"Low-income adults with coverage in 2023 because of expansion (study states): "
      f"{cr['people_covered_2023']['estimate']:,.0f} (95% CI {cr['people_covered_2023']['ci'][0]:,.0f} to {cr['people_covered_2023']['ci'][1]:,.0f})")
""")

md("""
## Part 3: Machine learning: which counties gain the most? (causal forest)

`06_ml_county_effects.py` trains a causal forest (EconML, double machine learning) on every expansion wave from
2014 to 2021, compared with counties in states that did not expand over the same years. It estimates a separate
effect for each county from its pre-expansion traits, and is checked two ways: its average must agree with the
difference-in-differences estimate, and on states held out of training, counties predicted to gain more must
really have gained more.
""")
code("""
mr = json.loads((ROOT / "models" / "ml_results.json").read_text())
print(f"Causal forest average effect on expansion counties: {mr['forest_ate_expansion_counties']:.2f} pts "
      f"(difference-in-differences: {mr['did_estimate_years_0_2']:.2f} pts)")
display(Image(vs.IMAGE_DIR / "07_model_validation.png"))
pd.DataFrame(mr["validation_splits"])[["split", "gap_top_vs_bottom_predicted", "gap_top_vs_bottom_actual"]]
""")
code("""
display(Image(vs.IMAGE_DIR / "08_effect_drivers.png"))
pd.DataFrame(mr["effect_by"]).T
""")
code("""
display(Image(vs.IMAGE_DIR / "09_nonexpansion_predictions.png"))
top = pd.read_csv(ROOT / "Data" / "clean" / "ml_nonexpansion_county_predictions.csv")
top = top[~top.state.isin(["NC", "SD"])]
top.head(15)[["county_name", "state", "rurality", "base_rate", "predicted_effect_pts", "effect_lo", "effect_hi", "adults_gaining_coverage"]]
""")
md("""
## Limitations

* SAHIE numbers are model-based estimates with margins of error (median about 4 points for a county's low-income
  adults); models weight counties by population so large, precise counties count more.
* States chose whether to expand. The design removes fixed differences between states and shared yearly
  changes, and pre-expansion trends match, but a state-specific shock at the same time as expansion would still bias
  the estimate.
* SAHIE measures income over a year; Medicaid uses monthly income, so some people above 138% were eligible part
  of the year. This is one reason the 138-400% group shows a small effect.
* Predictions for the remaining states assume expansion would work there as it did in similar counties that
  expanded, under 2023 conditions. They are estimates of the drop in the uninsured rate, not enrollment forecasts.
""")

nb = nbf.v4.new_notebook(cells=cells, metadata={"kernelspec": {"name": "python3", "display_name": "Python 3"}})
nbf.write(nb, NB)
subprocess.run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace", str(NB),
                "--ExecutePreprocessor.timeout=600"], check=True, cwd=HERE)
print("built and executed", NB.name)
