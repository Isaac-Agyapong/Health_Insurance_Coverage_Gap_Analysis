"""
Generate the Power BI Project (PBIP). The model imports the CSV extracts in dashboard/data/ (written by
07_export_powerbi.py from the PostgreSQL analytics views and the model outputs), so the report opens on any
machine without a database. The folder is a parameter (DataFolder).

    dashboard/Medicaid_Expansion.pbip                 open this in Power BI Desktop
    dashboard/Medicaid_Expansion.SemanticModel/       model (TMDL), columns read from the CSV headers
    dashboard/Medicaid_Expansion.Report/              6 pages + a state tooltip page (PBIR JSON)

Design: a bold infographic look, different from every other portfolio dashboard. Title band with a yellow
"sticker" credit, solid colour KPI blocks with white numbers and icons, floating rounded white cards with soft
shadows, chapter navigation along the bottom, Bahnschrift (DIN-style) typeface, and a generated background: a faint dot map of every
US county. Colour meanings: emerald = states that expanded / the estimated effect, rose = states that had not
expanded, sunflower = the highlighted finding, slate/grey = context.
"""
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
DATA = DASH / "data"
NAME = "Medicaid_Expansion"
SM = DASH / f"{NAME}.SemanticModel"
RPT = DASH / f"{NAME}.Report"

TABLES = ["group_trend", "state_year", "breakdown_trend", "county_2023", "what_if", "scenario_2023", "event_study", "model_metrics",
          "robustness", "ml_validation", "ml_state_predictions", "ml_county_predictions"]
HIDDEN = {"order", "rate", "quartile", "in_study", "row_order"}
SORT_BY = {("scenario_2023", "scenario"): "order", ("robustness", "label"): "order", ("ml_validation", "label"): "quartile", ("breakdown_trend", "row_label"): "row_order"}

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
S_PBIP = f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json"
S_PBISM = f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json"
S_PBIR = f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json"
S_VERSION = f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json"
S_REPORT = f"{SCHEMA}/item/report/definition/report/1.2.0/schema.json"
S_PAGES = f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json"
S_PAGE = f"{SCHEMA}/item/report/definition/page/1.3.0/schema.json"
S_VISUAL = f"{SCHEMA}/item/report/definition/visualContainer/1.4.0/schema.json"
BASE_THEME = "CY24SU10"
CUSTOM_THEME = "CoverageInfographicTheme.json"

# palette (same meanings as the matplotlib charts in viz_style.py)
EXP, EXP_2, EXP_L = "#0E9F6E", "#3DBB8F", "#9BDCC3"          # emerald: expanded / estimated effect
NONEXP, NONEXP_L = "#D63F6C", "#F2A7BD"                      # rose: had not expanded
SUN, SUN_L = "#F5B700", "#FBE3A0"                            # sunflower: the highlighted finding
GREY, GREY_LIGHT = "#8A94A0", "#CDD3DA"
SLATE, PAPER, INK, INK_2, RULE = "#1F2D3D", "#F5F6F1", "#1F2D3D", "#5B6B7C", "#E6EAE4"
PCT1, PTS, INT = "0.0%;-0.0%;0.0%", '+0.0" pts";-0.0" pts";0.0" pts"', "#,0"
FONT = "Bahnschrift"     # DIN-style condensed face that ships with Windows
# text colours that read well on each KPI block colour
ON = {EXP: ("#FFFFFF", "#DDF5EB"), NONEXP: ("#FFFFFF", "#FDE2EA"), SLATE: ("#FFFFFF", "#CBD5DF"), SUN: (SLATE, "#4A3B00")}


def tag(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "medicaid/" + "/".join(parts)))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path, obj):
    write(path, json.dumps(obj, indent=2) + "\n")


def q(name):
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def indent(text, tabs):
    return "\n".join("\t" * tabs + line if line else "" for line in text.splitlines())


# =====================================================================
# Measures: (home table, name, DAX, format, folder)
# =====================================================================
def metric(name, col="value"):
    return f'CALCULATE ( SUM ( model_metrics[{col}] ), model_metrics[metric] = "{name}" )'


EFFECT = "Effect of expansion (years 0-2)"
MEASURES = [
    # ---- coverage trend by expansion group
    ("group_trend", "Uninsured Rate", "DIVIDE ( SUM ( group_trend[uninsured] ), SUM ( group_trend[population] ) )", PCT1, "Trend"),
    ("group_trend", "Expanded in 2014", 'CALCULATE ( [Uninsured Rate], group_trend[analysis_group] = "Expanded 2014" )', PCT1, "Trend"),
    ("group_trend", "Not expanded", 'CALCULATE ( [Uninsured Rate], group_trend[analysis_group] = "Not expanded by 2023" )', PCT1, "Trend"),
    ("group_trend", "Exp Rate 2023", "CALCULATE ( [Expanded in 2014], group_trend[year] = 2023 )", "0%", "Trend"),
    ("group_trend", "Exp Rate 2013", "CALCULATE ( [Expanded in 2014], group_trend[year] = 2013 )", "0%", "Trend"),
    ("group_trend", "NonExp Rate 2023", "CALCULATE ( [Not expanded], group_trend[year] = 2023 )", "0%", "Trend"),
    ("group_trend", "NonExp Rate 2013", "CALCULATE ( [Not expanded], group_trend[year] = 2013 )", "0%", "Trend"),
    ("group_trend", "KPI Exp Context",
     '"down from " & FORMAT ( [Exp Rate 2013], "0%" ) & " in 2013"',
     None, "Context"),
    ("group_trend", "KPI NonExp Context",
     '"down from " & FORMAT ( [NonExp Rate 2013], "0%" ) & " in 2013"',
     None, "Context"),
    ("group_trend", "Uninsured 2023", "CALCULATE ( SUM ( group_trend[uninsured] ), group_trend[year] = 2023 )", INT, "Trend"),

    # ---- states
    ("state_year", "State Rate", "DIVIDE ( SUM ( state_year[uninsured] ), SUM ( state_year[population] ) )", "0%", "States"),
    ("state_year", "State Rate 2023", "CALCULATE ( [State Rate], state_year[year] = 2023 )", "0.0%", "States"),
    ("state_year", "State Rate 2013", "CALCULATE ( [State Rate], state_year[year] = 2013 )", "0.0%", "States"),
    ("state_year", "State Change", "( [State Rate 2023] - [State Rate 2013] ) * 100", PTS, "States"),
    ("state_year", "Top 10 Uninsured 2023",
     "// ranks every state, whatever is clicked on the map (REMOVEFILTERS, not ALLSELECTED)\n"
     "VAR _cur = [State Rate 2023]\n"
     "VAR _all = CALCULATETABLE ( ADDCOLUMNS ( VALUES ( state_year[state_name] ), \"@r\", [State Rate 2023] ),\n"
     "    REMOVEFILTERS ( state_year ), REMOVEFILTERS ( StateGrid ) )\n"
     "RETURN IF ( NOT ISBLANK ( _cur ) && COUNTROWS ( FILTER ( _all, [@r] > _cur ) ) < 10, _cur )", "0%", "States"),
    ("state_year", "Top 10 Drop",
     "VAR _cur = [State Change]\n"
     "VAR _all = CALCULATETABLE ( ADDCOLUMNS ( VALUES ( state_year[state_name] ), \"@c\", [State Change] ),\n"
     "    REMOVEFILTERS ( state_year ), REMOVEFILTERS ( StateGrid ) )\n"
     "RETURN IF ( NOT ISBLANK ( _cur ) && COUNTROWS ( FILTER ( _all, [@c] < _cur ) ) < 5, _cur )", PTS, "States"),
    ("state_year", "Top 10 Drop 2013", "IF ( NOT ISBLANK ( [Top 10 Drop] ), [State Rate 2013] )", "0%", "States"),
    ("state_year", "Top 10 Drop 2023", "IF ( NOT ISBLANK ( [Top 10 Drop] ), [State Rate 2023] )", "0%", "States"),
    ("state_year", "Status Colour",
     "SWITCH ( SELECTEDVALUE ( state_year[analysis_group] ),\n"
     f'    "Not expanded by 2023", "{NONEXP}",\n    "Excluded (early coverage)", "{GREY_LIGHT}",\n    "{EXP}" )', None, "States"),
    ("state_year", "Tile Label", "SELECTEDVALUE ( StateGrid[state_abbr] )", None, "Map"),
    ("state_year", "Rate Colour",
     "VAR _r = [State Rate 2023]\n"
     "RETURN SWITCH ( TRUE (),\n"
     '    ISBLANK ( SELECTEDVALUE ( StateGrid[state_abbr] ) ), "#FFFFFF",\n'
     '    ISBLANK ( _r ), "#E6EAE4",\n'
     '    _r < 0.12, "#EEEAF7",\n    _r < 0.16, "#D2C8EE",\n    _r < 0.20, "#A999DD",\n'
     '    _r < 0.25, "#7E6CC7",\n    _r < 0.30, "#5A48A8",\n    "#3B2B7A" )', None, "Map"),
    ("state_year", "Label Colour",
     'IF ( [State Rate 2023] >= 0.20, "#FFFFFF", "#1F2D3D" )', None, "Map"),
    ("state_year", "Border Colour",
     f'"{PAPER}"', None, "Map"),
    ("state_year", "Selected State", 'SELECTEDVALUE ( state_year[state_name], "All states" )', None, "Tooltip"),
    ("state_year", "Status Text",
     "VAR _g = SELECTEDVALUE ( state_year[analysis_group] )\nVAR _y = SELECTEDVALUE ( state_year[expansion_year] )\n"
     "RETURN SWITCH ( TRUE (),\n"
     '    _g = "Excluded (early coverage)", "Covered low-income adults before 2014",\n'
     '    _g = "Not expanded by 2023" && ISBLANK ( _y ), "Has not expanded Medicaid",\n'
     '    _g = "Not expanded by 2023", "Expanded in late 2023",\n'
     '    "Expansion in effect from " & _y )', None, "Tooltip"),
    ("state_year", "Rank Text",
     "VAR _cur = [State Rate 2023]\n"
     "VAR _all = CALCULATETABLE ( ADDCOLUMNS ( VALUES ( state_year[state_name] ), \"@r\", [State Rate 2023] ),\n"
     "    REMOVEFILTERS ( state_year ), REMOVEFILTERS ( StateGrid ) )\n"
     'RETURN IF ( HASONEVALUE ( state_year[state_name] ), "#" & COUNTROWS ( FILTER ( _all, [@r] > _cur ) ) + 1 & " of 51 for uninsured rate (2023)" )',
     None, "Tooltip"),

    # ---- who is left out
    ("breakdown_trend", "Rate Expanded 2023",
     'CALCULATE ( AVERAGE ( breakdown_trend[pct_uninsured] ), breakdown_trend[year] = 2023, breakdown_trend[analysis_group] = "Expanded 2014" ) / 100',
     "0%", "Breakdown"),
    ("breakdown_trend", "Rate Not Expanded 2023",
     'CALCULATE ( AVERAGE ( breakdown_trend[pct_uninsured] ), breakdown_trend[year] = 2023, breakdown_trend[analysis_group] = "Not expanded by 2023" ) / 100',
     "0%", "Breakdown"),
    ("breakdown_trend", "Gap 2023", "( [Rate Not Expanded 2023] - [Rate Expanded 2023] ) * 100", "0", "Breakdown"),
    ("breakdown_trend", "Gap Eligible",
     'CALCULATE ( AVERAGE ( breakdown_trend[pct_uninsured] ), breakdown_trend[analysis_group] = "Not expanded by 2023", breakdown_trend[category] = "At or below 138% of poverty (eligible)" )\n'
     '- CALCULATE ( AVERAGE ( breakdown_trend[pct_uninsured] ), breakdown_trend[analysis_group] = "Expanded 2014", breakdown_trend[category] = "At or below 138% of poverty (eligible)" )',
     '0" pts"', "Breakdown"),
    ("breakdown_trend", "Gap Not Eligible",
     'CALCULATE ( AVERAGE ( breakdown_trend[pct_uninsured] ), breakdown_trend[analysis_group] = "Not expanded by 2023", breakdown_trend[category] = "138-400% of poverty (not eligible)" )\n'
     '- CALCULATE ( AVERAGE ( breakdown_trend[pct_uninsured] ), breakdown_trend[analysis_group] = "Expanded 2014", breakdown_trend[category] = "138-400% of poverty (not eligible)" )',
     '0" pts"', "Breakdown"),
    ("county_2023", "County Uninsured", "SUM ( county_2023[uninsured] )", INT, "Counties"),
    ("county_2023", "County Rate", "DIVIDE ( SUM ( county_2023[uninsured] ), SUM ( county_2023[population] ) )", "0%", "Counties"),
    ("county_2023", "Top 10 County Uninsured",
     "VAR _cur = [County Uninsured]\n"
     "VAR _all = CALCULATETABLE ( ADDCOLUMNS ( VALUES ( county_2023[county_fips] ), \"@u\", [County Uninsured] ), REMOVEFILTERS ( county_2023 ) )\n"
     "RETURN IF ( HASONEVALUE ( county_2023[county_fips] ) && COUNTROWS ( FILTER ( _all, [@u] > _cur ) ) < 10, _cur )",
     INT, "Counties"),
    ("county_2023", "Top 10 County Rate", "IF ( NOT ISBLANK ( [Top 10 County Uninsured] ), [County Rate] )", "0%", "Counties"),

    # ---- causal effect
    ("event_study", "Effect", "SUM ( event_study[att] )", '0.0" pts"', "Causal"),
    ("event_study", "Effect Colour",
     f'IF ( SELECTEDVALUE ( event_study[years_since_expansion] ) < 0, "{GREY_LIGHT}", "{EXP}" )', None, "Causal"),
    ("model_metrics", "Effect Years 0-2", metric(EFFECT), '0.0" pts"', "Causal"),
    ("model_metrics", "Effect CI Text",
     f'"95% CI " & FORMAT ( {metric(EFFECT, "ci_low")}, "0.0" ) & " to " & FORMAT ( {metric(EFFECT, "ci_high")}, "0.0" ) & " points"',
     None, "Context"),
    ("model_metrics", "Adults Covered 2023", metric("Adults covered in 2023 because of expansion"), INT, "Causal"),
    ("model_metrics", "Covered Context",
     f'"likely between " & FORMAT ( ROUND ( {metric("Adults covered in 2023 because of expansion", "ci_low")}, -4 ), "#,0" ) & " and " & FORMAT ( {metric("Adults covered in 2023 because of expansion", "ci_high")} / 1000000, "0.0" ) & " million"',
     None, "Context"),
    ("model_metrics", "Placebo Effect", metric("Placebo: fake 2011 expansion date"), '+0.0" pts";-0.0" pts";0.0" pts"', "Causal"),
    ("model_metrics", "Placebo Context", '"a fake 2011 date shows no effect, as it should"', None, "Context"),
    ("robustness", "Estimate", "SUM ( robustness[value] )", '+0.0;-0.0;0.0', "Causal"),
    ("robustness", "Estimate Colour", f'IF ( SELECTEDVALUE ( robustness[order] ) = 1, "{EXP}", "{SUN}" )', None, "Causal"),

    # ---- machine learning
    ("model_metrics", "Adults Would Gain", metric("Adults who would gain coverage (10 states)"), INT, "ML"),
    ("model_metrics", "Gain Context",
     '"if the 10 remaining states expanded"', None, "Context"),
    ("model_metrics", "Forest Effect", metric("Causal forest average effect"), '0.0" pts"', "ML"),
    ("model_metrics", "Forest Context", f'"difference-in-differences: " & FORMAT ( [Effect Years 0-2], "0.0" ) & " pts"', None, "Context"),
    ("ml_validation", "Model Prediction", "SUM ( ml_validation[predicted] )", '0.0', "ML"),
    ("ml_validation", "Actual Result", "SUM ( ml_validation[actual_effect] )", '0.0', "ML"),
    ("ml_validation", "Top Quarter Actual", "CALCULATE ( [Actual Result], ml_validation[quartile] = 1 )", '0.0" pts"', "ML"),
    ("ml_validation", "Validation Context",
     '"predicted " & FORMAT ( CALCULATE ( [Model Prediction], ml_validation[quartile] = 1 ), "0.0" ) & "  ·  bottom quarter: " & FORMAT ( CALCULATE ( [Actual Result], ml_validation[quartile] = 4 ), "0.0" )',
     None, "Context"),
    ("ml_state_predictions", "State Adults Gaining",
     "CALCULATE ( SUM ( ml_state_predictions[adults_gaining_coverage] ), ml_state_predictions[expanded_late_2023] = FALSE () )", INT, "ML"),
    ("ml_county_predictions", "Adults Gaining", "SUM ( ml_county_predictions[adults_gaining_coverage] )", INT, "ML"),
    ("ml_county_predictions", "Predicted Drop", "SUM ( ml_county_predictions[predicted_effect_pts] )", '0.0" pts"', "ML"),
    ("ml_county_predictions", "Rate Now", "SUM ( ml_county_predictions[base_rate] ) / 100", "0%", "ML"),
    ("ml_county_predictions", "Rate After", "SUM ( ml_county_predictions[predicted_rate_after] ) / 100", "0%", "ML"),
]

PLAIN = [
    # ---- plain-language versions used on the report (no negative numbers, "in every 100" instead of "points")
    ("what_if", "With Expansion", "AVERAGE ( what_if[actual] ) / 100", "0%", "Plain"),
    ("what_if", "Without Expansion", "AVERAGE ( what_if[without_expansion] ) / 100", "0%", "Plain"),
    ("model_metrics", "Effect Plain", f"ABS ( {metric(EFFECT)} )", '0.0" in 100"', "Plain"),
    ("model_metrics", "Effect Range Text",
     f'"likely between " & FORMAT ( ABS ( {metric(EFFECT, "ci_high")} ), "0" ) & " and " & FORMAT ( ABS ( {metric(EFFECT, "ci_low")} ), "0" ) & " in every 100"',
     None, "Plain"),
    ("model_metrics", "Checks Passed", '"4 of 4"', None, "Plain"),
    ("model_metrics", "Checks Context", '"see the checklist below"', None, "Plain"),
    ("model_metrics", "Rate Change Text",
     f'FORMAT ( {metric("Uninsured rate today (10 states)")} / 100, "0%" ) & "  →  " & FORMAT ( {metric("Uninsured rate if expanded (10 states)")} / 100, "0%" )',
     None, "Plain"),
    ("model_metrics", "Texas Gain", metric("Texas adults gaining coverage"), "#,0", "Plain"),
    ("model_metrics", "Texas Context",
     f'FORMAT ( DIVIDE ( {metric("Texas adults gaining coverage")}, {metric("Adults who would gain coverage (10 states)")} ), "0%" ) & " of the total"',
     None, "Plain"),
    ("ml_validation", "Actual Drop", "SUM ( ml_validation[actual_drop] )", "0.0", "Plain"),
    ("ml_validation", "Validation Colour",
     f'SWITCH ( SELECTEDVALUE ( ml_validation[quartile] ), 1, "{EXP}", 2, "{EXP_2}", 3, "{EXP_L}", "{GREY_LIGHT}" )', None, "Plain"),
    ("state_year", "Top 5 Improvement", "IF ( NOT ISBLANK ( [Top 10 Drop] ), - [Top 10 Drop] )", "0.0", "Plain"),
    ("county_2023", "Top 8 County Uninsured",
     "VAR _cur = [County Uninsured]\n"
     "VAR _all = CALCULATETABLE ( ADDCOLUMNS ( VALUES ( county_2023[county_fips] ), \"@u\", [County Uninsured] ), REMOVEFILTERS ( county_2023 ) )\n"
     "RETURN IF ( HASONEVALUE ( county_2023[county_fips] ) && COUNTROWS ( FILTER ( _all, [@u] > _cur ) ) < 8, _cur )",
     "#,0", "Plain"),
    ("county_2023", "Top 8 County Rate", "IF ( NOT ISBLANK ( [Top 8 County Uninsured] ), [County Rate] )", "0%", "Plain"),
]
MEASURES += PLAIN
MEASURES += [
    # ---- "out of every 100" donuts on the overview (uninsured slice + insured slice)
    ("group_trend", "Exp Uninsured 2013", "[Exp Rate 2013]", "0%", "Donuts"),
    ("group_trend", "Exp Insured 2013", "1 - [Exp Rate 2013]", "0%", "Donuts"),
    ("group_trend", "Exp Uninsured 2023", "[Exp Rate 2023]", "0%", "Donuts"),
    ("group_trend", "Exp Insured 2023", "1 - [Exp Rate 2023]", "0%", "Donuts"),
    ("group_trend", "NonExp Uninsured 2013", "[NonExp Rate 2013]", "0%", "Donuts"),
    ("group_trend", "NonExp Insured 2013", "1 - [NonExp Rate 2013]", "0%", "Donuts"),
    ("group_trend", "NonExp Uninsured 2023", "[NonExp Rate 2023]", "0%", "Donuts"),
    ("group_trend", "NonExp Insured 2023", "1 - [NonExp Rate 2023]", "0%", "Donuts"),
    # ---- with vs without expansion (2023), two bars
    ("scenario_2023", "Scenario Rate", "SUM ( scenario_2023[rate] ) / 100", "0%", "Plain"),
    ("scenario_2023", "Scenario Colour", f'IF ( SELECTEDVALUE ( scenario_2023[order] ) = 1, "{EXP}", "#AEB6C0" )', None, "Plain"),
]

CALC_COLUMNS = [
    ("group_trend", "Coverage Group",
     "SWITCH ( group_trend[analysis_group],\n"
     '    "Not expanded by 2023", "Did not expand",\n'
     '    "Excluded (early coverage)", "Covered adults early",\n'
     '    "Expanded" )'),
]

# Tile-grid positions (column, row) for the 50 states + DC, arranged like a US map
STATE_GRID = {
    "AK": (0, 0), "ME": (10, 0),
    "WI": (5, 1), "VT": (9, 1), "NH": (10, 1),
    "WA": (0, 2), "ID": (1, 2), "MT": (2, 2), "ND": (3, 2), "MN": (4, 2), "IL": (5, 2), "MI": (6, 2),
    "NY": (8, 2), "MA": (9, 2),
    "OR": (0, 3), "NV": (1, 3), "WY": (2, 3), "SD": (3, 3), "IA": (4, 3), "IN": (5, 3), "OH": (6, 3),
    "PA": (7, 3), "NJ": (8, 3), "CT": (9, 3), "RI": (10, 3),
    "CA": (0, 4), "UT": (1, 4), "CO": (2, 4), "NE": (3, 4), "MO": (4, 4), "KY": (5, 4), "WV": (6, 4),
    "VA": (7, 4), "MD": (8, 4), "DE": (9, 4),
    "AZ": (1, 5), "NM": (2, 5), "KS": (3, 5), "AR": (4, 5), "TN": (5, 5), "NC": (6, 5), "SC": (7, 5), "DC": (8, 5),
    "OK": (3, 6), "LA": (4, 6), "MS": (5, 6), "AL": (6, 6), "GA": (7, 6),
    "HI": (0, 7), "TX": (3, 7), "FL": (8, 7),
}
assert len(STATE_GRID) == 51


def csv_columns(table):
    """Column names and types from the CSV extract (pandas infers the type)."""
    df = pd.read_csv(DATA / f"{table}.csv")
    out = []
    for col, dt in df.dtypes.items():
        if pd.api.types.is_bool_dtype(dt):
            out.append((col, "boolean", "type logical"))
        elif pd.api.types.is_integer_dtype(dt):
            out.append((col, "int64", "Int64.Type"))
        elif pd.api.types.is_float_dtype(dt):
            whole = df[col].dropna().mod(1).eq(0).all() and col in ("expansion_year",)
            out.append((col, "int64", "Int64.Type") if whole else (col, "double", "type number"))
        else:
            out.append((col, "string", "type text"))
    return out


def table_tmdl(table, columns):
    out = [f"table {table}", f"\tlineageTag: {tag(table)}", ""]
    for home, name, dax in CALC_COLUMNS:
        if home == table:
            out += [f"\tcolumn {q(name)} =", indent(dax, 3), "\t\tdataType: string",
                    f"\t\tlineageTag: {tag(table, 'calc', name)}", "\t\tsummarizeBy: none", "",
                    "\t\tannotation SummarizationSetBy = Automatic", ""]
    for home, name, dax, fmt, folder in MEASURES:
        if home != table:
            continue
        out += [f"\tmeasure {q(name)} =", indent(dax, 3)] if "\n" in dax else [f"\tmeasure {q(name)} = {dax}"]
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        out += [f"\t\tdisplayFolder: {folder}", f"\t\tlineageTag: {tag(table, 'm', name)}", ""]
    for col, dtype, _ in columns:
        out += [f"\tcolumn {col}", f"\t\tdataType: {dtype}"]
        if dtype == "double":
            out.append("\t\tformatString: #,0.00")
        elif dtype == "int64":
            out.append("\t\tformatString: 0")
        if col in HIDDEN:
            out.append("\t\tisHidden")
        if (table, col) in SORT_BY:
            out.append(f"\t\tsortByColumn: {SORT_BY[(table, col)]}")
        numeric_key = col in ("year", "years_since_expansion", "expansion_year", "quartile", "order", "row_order", "rucc_2013")
        out += [f"\t\tlineageTag: {tag(table, col)}",
                f"\t\tsummarizeBy: {'none' if dtype in ('string', 'boolean') or numeric_key else 'sum'}",
                f"\t\tsourceColumn: {col}", "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    types = ", ".join(f'{{"{c}", {m}}}' for c, _, m in columns)
    m = (f'let\n    Source = Csv.Document(File.Contents(DataFolder & "{table}.csv"), '
         '[Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),\n'
         '    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),\n'
         f'    Typed = Table.TransformColumnTypes(Promoted, {{{types}}}, "en-US")\nin\n    Typed')
    out += [f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource =", indent(m, 4), "",
            "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def check_names():
    """Power BI rejects a measure whose name matches any column (case-insensitive) or another measure."""
    cols = {c.lower() for t in TABLES for c, *_ in csv_columns(t)} | {n.lower() for _, n, _ in CALC_COLUMNS}
    names = [n.lower() for _, n, *_ in MEASURES]
    clash = sorted({n for n in names if n in cols} | {n for n in names if names.count(n) > 1})
    if clash:
        raise ValueError(f"measure names clash with columns or each other: {clash}")


def build_model():
    check_names()
    shutil.rmtree(SM, ignore_errors=True)
    d = SM / "definition"
    write_json(SM / "definition.pbism", {"$schema": S_PBISM, "version": "4.0", "settings": {}})
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1600\n")
    write(d / "model.tmdl", "\n".join([
        "model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull",
        "", "annotation __PBI_TimeIntelligenceEnabled = 0", "",
        *[f"ref table {t}" for t in TABLES + ["StateGrid"]], ""]))
    folder = str(DATA) + "\\"
    write(d / "expressions.tmdl", "\n".join([
        f'expression DataFolder = "{folder}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]',
        f"\tlineageTag: {tag('DataFolder')}", "", "\tannotation PBI_ResultType = Text", ""]))
    for t in TABLES:
        write(d / "tables" / f"{t}.tmdl", table_tmdl(t, csv_columns(t)))
    rows = ", ".join(f'{{ "{a}", {x}, {y} }}' for a, (x, y) in STATE_GRID.items())
    grid_cols = []
    for col, dtype in [("state_abbr", "string"), ("tile_x", "int64"), ("tile_y", "int64")]:
        grid_cols += [f"\tcolumn {col}", f"\t\tdataType: {dtype}", *(["\t\tisKey"] if col == "state_abbr" else []),
                      f"\t\tlineageTag: {tag('StateGrid', col)}", "\t\tsummarizeBy: none", "\t\tisNameInferred",
                      f"\t\tsourceColumn: [{col}]", "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    write(d / "tables" / "StateGrid.tmdl", "\n".join([
        "table StateGrid", f"\tlineageTag: {tag('StateGrid')}", "", *grid_cols,
        "\tpartition StateGrid = calculated", "\t\tmode: import", "\t\tsource =",
        indent(f'DATATABLE ( "state_abbr", STRING, "tile_x", INTEGER, "tile_y", INTEGER, {{ {rows} }} )', 4), ""]))
    write(d / "relationships.tmdl", f"relationship {tag('rel', 'stategrid')}\n\tfromColumn: state_year.state_abbrev\n"
                                    "\ttoColumn: StateGrid.state_abbr\n")


# =====================================================================
# Report helpers (PBIR JSON)
# =====================================================================
def lit(v):
    return {"expr": {"Literal": {"Value": v}}}


def s(text):
    return lit("'" + text.replace("'", "''") + "'")


def solid(hex_):
    return {"solid": {"color": s(hex_)}}


def field(entity, prop, measure=False):
    return {("Measure" if measure else "Column"): {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def C(entity, prop, name=None):
    return (entity, prop, False, name) if name else (entity, prop, False)


def M(prop):
    home = next(h for h, n, *_ in MEASURES if n == prop)
    return (home, prop, True)


def MN(prop, name):
    return (*M(prop), name)


def projections(fields):
    out = []
    for e, p, m, *name in fields:
        pr = {"field": field(e, p, m), "queryRef": f"{e}.{p}", "nativeQueryRef": p}
        if name:
            pr["displayName"] = name[0]
        out.append(pr)
    return {"projections": out}


def by_measure(table, m):
    return {"solid": {"color": {"expr": field(table, m, True)}}}


def tile(title=None, subtitle=None, background="#FFFFFF", border=True, tooltip_page=None, pad=(12, 10, 16, 16),
         shadow=True, radius=18):
    """Card formatting shared by every visual: floating rounded card with a soft shadow, DIN title, grey subtitle.
    (border=True keeps the old call signature; cards use a shadow instead of an outline.)"""
    objs = {
        "background": [{"properties": {"show": lit("true"), "color": solid(background), "transparency": lit("0D")}}],
        # Power BI only rounds corners when the border is on, so draw it in the card's own colour
        "border": [{"properties": {"show": lit("true"), "color": solid(background), "radius": lit(f"{radius}D")}}],
        "dropShadow": [{"properties": {
            "show": lit("true"), "color": solid(SLATE), "position": s("Outer"), "preset": s("Custom"),
            "transparency": lit("88D"), "shadowBlur": lit("14D"), "shadowSpread": lit("0D"),
            "shadowDistance": lit("4D"), "angle": lit("90D")}}] if shadow else [{"properties": {"show": lit("false")}}],
        "visualHeader": [{"properties": {"background": solid(background), "border": solid(background),
                                         "foreground": solid(INK_2)}}],
        "padding": [{"properties": {"top": lit(f"{pad[0]}D"), "bottom": lit(f"{pad[1]}D"),
                                    "left": lit(f"{pad[2]}D"), "right": lit(f"{pad[3]}D")}}],
        "title": [{"properties": {"show": lit("true" if title else "false"), **({
            "text": s(title), "fontColor": solid(INK), "fontSize": lit("14D"), "bold": lit("true"),
            "fontFamily": s(FONT)} if title else {})}}],
    }
    if subtitle:
        objs["subTitle"] = [{"properties": {"show": lit("true"), "text": s(subtitle), "fontColor": solid(INK_2),
                                            "fontSize": lit("11D"), "titleWrap": lit("true")}}]
    if tooltip_page:
        objs["visualTooltip"] = [{"properties": {"type": s("ReportPage"), "section": s(tooltip_page)}}]
    return objs


def axes(show_value=True, cat_size=11, inner_padding=None, label_area=None, categorical=False):
    cat = {"showAxisTitle": lit("false"), "labelColor": solid(INK_2), "fontSize": lit(f"{cat_size}D")}
    if inner_padding is not None:
        cat["innerPadding"] = lit(f"{inner_padding}L")
    if label_area is not None:          # max share of the visual the category labels may use (default 25%)
        cat["maxMarginFactor"] = lit(f"{label_area}L")
    if categorical:                     # every value on the axis, not a continuous scale
        cat["axisType"] = s("Categorical")
    return {"categoryAxis": [{"properties": cat}],
            "valueAxis": [{"properties": {"show": lit("true" if show_value else "false"), "showAxisTitle": lit("false"),
                                          "labelColor": solid(INK_2), "fontSize": lit("11D"),
                                          "gridlineShow": lit("true" if show_value else "false"),
                                          "gridlineColor": solid(RULE)}}]}


def labels(size=11, colour=INK, **extra):
    return {"labels": [{"properties": {"show": lit("true"), "color": solid(colour), "fontSize": lit(f"{size}D"),
                                       "bold": lit("true"), **extra}}]}


def series_colour(measure, hex_):
    home = next(h for h, n, *_ in MEASURES if n == measure)
    return {"properties": {"fill": solid(hex_)}, "selector": {"metadata": f"{home}.{measure}"}}


def fill_by(table, measure):
    """Conditional bar colour: every data point takes its colour from a measure."""
    return [{"properties": {"fill": by_measure(table, measure)},
             "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]


def chart(vtype, roles, title, subtitle=None, sort=None, objects=None, colours=None, tooltip_page=None):
    objects = dict(objects or {})
    if colours:
        objects["dataPoint"] = [series_colour(m, c) for m, c in colours.items()]
    if "legend" in objects:
        objects["legend"][0]["properties"].setdefault("fontSize", lit("11D"))
    v = {"visualType": vtype, "query": {"queryState": {r: projections(f) for r, f in roles.items()}},
         "visualContainerObjects": tile(title, subtitle, tooltip_page=tooltip_page), "drillFilterOtherVisuals": True}
    if sort:
        (e, p, m, *_), direction = sort
        v["query"]["sortDefinition"] = {"sort": [{"field": field(e, p, m), "direction": direction}], "isDefaultSort": False}
    if objects:
        v["objects"] = objects
    return v


def textbox(paragraphs, background=None, pad=(12, 10, 14, 14), border=False, align=None, shadow=False, radius=18):
    """paragraphs: list of (text, size, bold, colour[, font]) or lists of such runs for one line."""
    def run(t, size, bold, col, font=None):
        return {"value": t, "textStyle": {"fontSize": f"{size}pt", "color": col,
                                          **({"fontWeight": "bold"} if bold else {}),
                                          **({"fontFamily": font} if font else {})}}
    paras = [{"textRuns": [run(*r) for r in (p if isinstance(p, list) else [p])],
              **({"horizontalTextAlignment": align} if align else {})} for p in paragraphs if p]
    v = {"visualType": "textbox", "drillFilterOtherVisuals": True,
         "objects": {"general": [{"properties": {"paragraphs": paras}}]}}
    v["visualContainerObjects"] = tile(background=background, pad=pad, shadow=shadow, radius=radius) if background else \
        {"background": [{"properties": {"show": lit("false")}}]}
    return v


def block(colour, radius=0, shadow=False):
    return textbox([None], background=colour, pad=(0, 0, 0, 0), radius=radius, shadow=shadow)


def card(measure, label, value_colour=INK, size=28, show_label=True, background="#FFFFFF", pad=(4, 2, 14, 14), font=FONT,
         label_colour=INK_2):
    v = {"visualType": "card", "query": {"queryState": {"Values": projections([M(measure)])}},
         "objects": {
             "labels": [{"properties": {"color": solid(value_colour), "fontSize": lit(f"{size}D"), "fontFamily": s(font)}}],
             "categoryLabels": [{"properties": {"show": lit("true" if show_label else "false"),
                                                "color": solid(label_colour), "fontSize": lit("11D")}}]},
         "visualContainerObjects": tile(background=background, pad=pad, shadow=False),
         "drillFilterOtherVisuals": True}
    v["query"]["queryState"]["Values"]["projections"][0]["displayName"] = label
    return v


def slicer(entity, prop, title):
    return {"visualType": "slicer", "query": {"queryState": {"Values": projections([C(entity, prop)])}},
            "objects": {"data": [{"properties": {"mode": s("Dropdown")}}],
                        "header": [{"properties": {"text": s(title), "fontColor": solid(INK), "bold": lit("true"),
                                                   "fontSize": lit("11D")}}],
                        "items": [{"properties": {"fontSize": lit("11D")}}]},
            "visualContainerObjects": tile(pad=(8, 6, 12, 12)), "drillFilterOtherVisuals": True}


def navigator():
    state = lambda sid, props: {"properties": props, "selector": {"id": sid}}
    return {"visualType": "pageNavigator", "drillFilterOtherVisuals": True,
            "objects": {
                "layout": [{"properties": {"orientation": lit("2D"), "cellPadding": lit("6L")}}],     # 2 = one horizontal row
                "pages": [{"properties": {"showHiddenPages": lit("false"), "showTooltipPages": lit("false")}}],
                "shape": [{"properties": {"tileShape": s("rectangleRounded"), "rectangleRoundedCurve": lit("14L")}}],
                "fill": [state("default", {"show": lit("true"), "fillColor": solid(SLATE), "transparency": lit("0D")}),
                         state("hover", {"fillColor": solid("#2E4157")}),
                         state("selected", {"fillColor": solid(SUN)})],
                "text": [state("default", {"fontColor": solid("#C9D3DD"), "fontSize": lit("12D"), "fontFamily": s(FONT)}),
                         state("selected", {"fontColor": solid(SLATE), "bold": lit("true")})],
                "outline": [state("default", {"show": lit("false")})],
                "accentBar": [state("default", {"show": lit("false")})],
            },
            "visualContainerObjects": {"background": [{"properties": {"show": lit("false")}}]}}


class Page:
    def __init__(self, name, display, width=1280, height=720, kind=None):
        self.name, self.display, self.visuals = name, display, []
        self.no_filter = []
        self.width, self.height, self.kind = width, height, kind

    def add(self, vid, x, y, w, h, visual):
        n = len(self.visuals)
        self.visuals.append({"$schema": S_VISUAL, "name": vid, "visual": visual,
                             "position": {"x": x, "y": y, "z": n * 1000, "height": h, "width": w, "tabOrder": n * 1000}})

    def json(self):
        page = {"$schema": S_PAGE, "name": self.name, "displayName": self.display, "displayOption": "FitToPage",
                "height": self.height, "width": self.width,
                "objects": {"background": [{"properties": {"color": solid(PAPER), "transparency": lit("0D"),
                                                           "image": {"image": {
                                                               "name": s("page_background.png"),
                                                               "url": {"expr": {"ResourcePackageItem": {
                                                                   "PackageName": "RegisteredResources", "PackageType": 1,
                                                                   "ItemName": "page_background.png"}}},
                                                               "scaling": s("Fit")}}}}],
                            "outspace": [{"properties": {"color": solid(PAPER)}}]}}
        if self.no_filter:
            page["visualInteractions"] = [{"source": a, "target": b, "type": "NoFilter"} for a, b in self.no_filter]
        if self.kind == "Tooltip":
            page.update({"displayOption": "ActualSize", "visibility": "HiddenInViewMode", "type": "Tooltip",
                         "pageBinding": {"name": f"{self.name}Binding", "type": "Tooltip", "parameters": []}})
            page["objects"] = {"background": [{"properties": {"color": solid("#FFFFFF"), "transparency": lit("0D")}}]}
        return page


X0, W, TOP = 24, 1232, 128          # content area (y 128-640); chapter bar at the bottom


def chip(text, fill="#EEF1EC", colour=INK_2, bold=False):
    return textbox([(text, 9, bold, colour, FONT)], background=fill, radius=13, align="center", pad=(5, 0, 6, 6))


def frame(page, finding, sub):
    """App-bar header, section finding with an accent bar, source line and bottom chapter bar: same on every page."""
    page.add("appBar", 16, 10, 1248, 58, block("#FFFFFF", radius=16, shadow=True))
    page.add("logo", 28, 19, 40, 40, textbox([("✚", 17, True, "#FFFFFF")], background=EXP, radius=12,
                                             align="center", pad=(6, 0, 0, 0)))
    page.add("title", 78, 10, 600, 58, textbox(
        [("Health Insurance Coverage Gap", 18, True, SLATE, FONT),
         [("Medicaid Expansion Impact", 10, True, NONEXP, FONT), ("   ·   analytics and machine learning", 10, False, INK_2)]],
        pad=(0, 0, 4, 4)))
    page.add("chipCounties", 792, 26, 118, 26, chip("3,143 US counties"))
    page.add("chipYears", 918, 26, 92, 26, chip("2008 - 2023"))
    page.add("chipAuthor", 1018, 26, 234, 26, chip("Built by Isaac Agyapong", fill=SUN, colour=SLATE, bold=True))
    page.add("accent", X0, 82, 5, 38, block(EXP, radius=3))
    page.add("headline", X0 + 12, 76, W - 12, 52, textbox(
        [(finding, 15, True, INK, FONT), (sub, 10, False, INK_2)], pad=(0, 0, 4, 4)))
    page.add("source", X0 - 4, 640, W + 8, 26, textbox(
        [[("Source: ", 8, True, GREY), ("US Census Bureau SAHIE 2008-2023, SAIPE and population estimates; KFF Medicaid expansion tracker; "
                                        "USDA ERS rural-urban codes.  Low-income adults = ages 18-64 at or below 138% of the federal poverty level.", 8, False, GREY)]],
        pad=(2, 0, 4, 4)))
    page.add("chapterBar", 16, 664, 1248, 48, block(SLATE, radius=24, shadow=True))
    page.add("navigator", 28, 668, 1224, 40, navigator())


ICONS = {"Exp Rate 2023": "✔", "NonExp Rate 2023": "✖", "Effect Years 0-2": "▼", "Adults Would Gain": "★",
         "Effect Plain": "▼", "Checks Passed": "✔", "Rate Change Text": "↘", "Texas Gain": "★",
         "Adults Covered 2023": "♥", "Placebo Effect": "◎", "Forest Effect": "◆", "Top Quarter Actual": "✔"}


def kpi(page, i, x, y, w, measure, label, context, colour, h=116, size=30):
    """Solid colour block: big white number, label, context line and an icon badge."""
    text, soft = ON[colour]
    page.add(f"kpiTile{i}", x, y, w, h, block(colour, radius=18, shadow=True))
    page.add(f"kpi{i}", x + 4, y + 6, w - 8, h - 36 if context else h - 12,
             card(measure, label, value_colour=text, size=size, background=colour, label_colour=soft))
    if context:
        page.add(f"kpiContext{i}", x + 4, y + h - 30, w - 8, 26,
                 card(context, "", value_colour=soft, size=11, show_label=False, pad=(0, 0, 16, 14), font="Segoe UI",
                      background=colour))
    if measure in ICONS:
        page.add(f"kpiIcon{i}", x + w - 54, y + 12, 40, 40, textbox(
            [(ICONS[measure], 16, True, colour if colour != SUN else SUN)], background=text if colour != SUN else SLATE,
            radius=20, align="center", pad=(6, 0, 0, 0)))


def data_bar(table, measure, colour):
    return {"properties": {"dataBars": {"positiveColor": solid(colour), "negativeColor": solid(colour),
                                        "axisColor": solid("#FFFFFF"), "reverseDirection": lit("false"),
                                        "hideText": lit("false")}},
            "selector": {"metadata": f"{table}.{measure}"}}


TABLE_FMT = {"values": [{"properties": {"fontSize": lit("11D")}}],
             "columnHeaders": [{"properties": {"fontSize": lit("11D"), "bold": lit("true"), "fontColor": solid(INK),
                                               "fontFamily": s(FONT)}}],
             "total": [{"properties": {"totals": lit("false")}}],
             "grid": [{"properties": {"rowPadding": lit("1D")}}]}


def widths(**cols):
    """Fixed column widths; keys are queryRefs with '.' written as '__' (e.g. breakdown_trend__row_label=250)."""
    return {"columnWidth": [{"properties": {"value": lit(f"{w}D")}, "selector": {"metadata": k.replace("__", ".")}}
                            for k, w in cols.items()]}


# =====================================================================
# Pages
# =====================================================================
def facts():
    """Numbers quoted in titles, computed from the same extracts the visuals show (titles cannot drift from data)."""
    st = pd.read_csv(DATA / "state_year.csv").query("year == 2023")
    top10 = st.assign(r=st.uninsured / st.population).nlargest(10, "r")
    cty = pd.read_csv(DATA / "county_2023.csv").nlargest(10, "uninsured")
    gt = pd.read_csv(DATA / "group_trend.csv").query("year == 2023")
    ml = pd.read_csv(DATA / "ml_state_predictions.csv").query("~expanded_late_2023")
    mm = pd.read_csv(DATA / "model_metrics.csv").set_index("metric")["value"]
    words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "All 10"}
    cty8 = pd.read_csv(DATA / "county_2023.csv").nlargest(8, "uninsured")
    wi = pd.read_csv(DATA / "what_if.csv").set_index("year")
    gt_all = pd.read_csv(DATA / "group_trend.csv")
    rate = lambda d, g, y: 100 * d.query("analysis_group == @g and year == @y").eval("uninsured / population").iloc[0]
    return {
        "top10_nonexp": int((top10.analysis_group == "Not expanded by 2023").sum()),
        "tx_counties": words[int((cty.state_abbrev == "TX").sum())],
        "nonexp_share": gt.loc[gt.analysis_group == "Not expanded by 2023", "uninsured"].sum() / gt.uninsured.sum(),
        "tx_gain_share": ml.set_index("state").adults_gaining_coverage["TX"] / ml.adults_gaining_coverage.sum(),
        "gain": mm["Adults who would gain coverage (10 states)"],
        "effect": mm["Effect of expansion (years 0-2)"],
        "spill": mm["Adults 138-400% of poverty (not made eligible)"],
        "uninsured_total": gt.uninsured.sum(),
        "tx_counties8": words[int((cty8.state_abbrev == "TX").sum())],
        "actual_2023": wi.loc[2023, "actual"],
        "without_2023": wi.loc[2023, "without_expansion"],
        # differences of the rounded percentages the reader sees (37% - 16% = 21), not of unrounded values
        "drop_exp": round(rate(gt_all, "Expanded 2014", 2013)) - round(rate(gt_all, "Expanded 2014", 2023)),
        "drop_nonexp": round(rate(gt_all, "Not expanded by 2023", 2013)) - round(rate(gt_all, "Not expanded by 2023", 2023)),
    }


def small_donut(uninsured, insured, colour):
    """Donut with the uninsured slice in colour and the insured slice in light grey; only the uninsured % is labelled."""
    v = chart("donutChart", {"Y": [MN(uninsured, "Uninsured"), MN(insured, "Insured")]}, None,
              objects={"labels": [{"properties": {"show": lit("false")}}],
                       "legend": [{"properties": {"show": lit("false")}}],
                       "dataPoint": [series_colour(uninsured, colour), series_colour(insured, "#E4E8E2")]})
    v["visualContainerObjects"] = tile(background="#FFFFFF", pad=(0, 0, 0, 0), shadow=False)
    return v


def add_donut_panel(page, x, y, w, h, f):
    """Out of every 100 low-income adults, how many are uninsured: 2013 vs 2023, for each group."""
    page.add("donutCard", x, y, w, h, textbox(
        [("Out of every 100 low-income adults, how many have no health insurance?", 14, True, INK, FONT),
         ("2013 (before expansion) compared with 2023", 10, False, INK_2)],
        background="#FFFFFF", pad=(12, 10, 16, 16), shadow=True))
    cx = {"label": x + 16, "d13": x + 196, "arrow": x + 372, "d23": x + 420, "change": x + 600}
    page.add("hdr2013", cx["d13"], y + 60, 170, 30, textbox([("2013", 12, True, INK_2, FONT)], align="center", pad=(0, 0, 0, 0)))
    page.add("hdr2023", cx["d23"], y + 60, 170, 30, textbox([("2023", 12, True, INK_2, FONT)], align="center", pad=(0, 0, 0, 0)))
    rows = [("Exp", "States that expanded", "Medicaid in 2014", EXP, f["drop_exp"]),
            ("NonExp", "States that did not expand", "as of 2023", NONEXP, f["drop_nonexp"])]
    for i, (key, name, note, colour, drop) in enumerate(rows):
        ry = y + 90 + i * 146
        page.add(f"rowLabel{i}", cx["label"], ry + 40, 176, 72, textbox(
            [(name, 13, True, colour, FONT), (note, 10, False, INK_2)], pad=(0, 0, 0, 0)))
        for yr, dx in (("2013", cx["d13"]), ("2023", cx["d23"])):
            m = f"{key} Uninsured {yr}"
            page.add(f"donut{yr}_{i}", dx, ry, 170, 140, small_donut(m, f"{key} Insured {yr}", colour))
            page.add(f"pct{yr}_{i}", dx + 50, ry + 51, 70, 38,       # sits in the donut hole
                     card(m, "", value_colour=colour, size=17, show_label=False, pad=(0, 0, 0, 0)))
        page.add(f"arrow{i}", cx["arrow"] - 4, ry + 42, 52, 60, textbox([("→", 20, True, GREY)], align="center", pad=(8, 0, 0, 0)))
        page.add(f"change{i}", cx["change"], ry + 36, 184, 74, textbox(
            [(f"{drop:.0f} fewer", 20, True, colour, FONT), ("uninsured in every 100", 10, False, INK_2)],
            pad=(0, 0, 0, 0)))


def build_pages():
    f = facts()
    kx = [X0 + i * (W + 16) // 4 for i in range(4)]
    kw = (W - 48) // 4
    LOW_INCOME = "Low-income adults = people aged 18-64 earning about $20,000 a year or less (138% of the poverty line)"

    # ---------------------------------------------------------------- 1. Overview
    p1 = Page("overview", "01  Overview")
    frame(p1, "Where states expanded Medicaid, far fewer low-income adults are uninsured today", LOW_INCOME)
    kpi(p1, 1, kx[0], TOP, kw, "Exp Rate 2023", "Uninsured where Medicaid expanded", "KPI Exp Context", EXP)
    kpi(p1, 2, kx[1], TOP, kw, "NonExp Rate 2023", "Uninsured where it did not expand", "KPI NonExp Context", NONEXP)
    kpi(p1, 3, kx[2], TOP, kw, "Effect Plain", "fewer uninsured in the first 3 years", "Effect Range Text", EXP)
    kpi(p1, 4, kx[3], TOP, kw, "Adults Would Gain", "more adults could be insured", "Gain Context", SUN)
    add_donut_panel(p1, X0, TOP + 128, 800, 384, f)
    grp = field("group_trend", "Coverage Group")
    donut_colours = [{"properties": {"fill": solid(c)}, "selector": {"data": [{"scopeId": {"Comparison": {
        "ComparisonKind": 0, "Left": grp, "Right": {"Literal": {"Value": f"'{g}'"}}}}}]}}
        for g, c in {"Did not expand": NONEXP, "Expanded": EXP, "Covered adults early": GREY_LIGHT}.items()]
    p1.add("donut", X0 + 816, TOP + 128, W - 816, 384, chart(
        "donutChart", {"Category": [C("group_trend", "Coverage Group")], "Y": [MN("Uninsured 2023", "Uninsured low-income adults, 2023")]},
        f"{'Half' if round(f['nonexp_share'], 1) == 0.5 else format(f['nonexp_share'], '.0%')} of all uninsured low-income adults live in states that did not expand",
        f"Where the {f['uninsured_total'] / 1e6:.1f} million uninsured low-income adults lived in 2023",
        objects={"labels": [{"properties": {"show": lit("true"), "labelStyle": s("Percent of total"),
                                            "percentageLabelPrecision": lit("0L"), "fontSize": lit("14D"),
                                            "bold": lit("true"), "color": solid(INK)}}],
                 "legend": [{"properties": {"show": lit("true"), "position": s("Bottom"), "showTitle": lit("false")}}],
                 "dataPoint": donut_colours}))

    # ---------------------------------------------------------------- 2. States
    p2 = Page("states", "02  States")
    frame(p2, "Texas and the Southeast have the highest shares of uninsured low-income adults",
          "Share of low-income adults without health insurance in 2023  ·  hover over a state to see its details")
    every_cell = {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "state_year.Tile Label"}
    hidden_header = {"fontColor": solid("#FFFFFF"), "backColor": solid("#FFFFFF"), "fontSize": lit("6D")}
    tile_map = chart(
        "pivotTable", {"Rows": [C("StateGrid", "tile_y")], "Columns": [C("StateGrid", "tile_x")], "Values": [M("Tile Label")]},
        "Share uninsured by state, 2023", "Darker purple = more people without insurance", tooltip_page="stateTooltip",
        objects={
            "values": [{"properties": {"fontSize": lit("13D"), "bold": lit("true"),
                                       "backColorPrimary": solid("#FFFFFF"), "backColorSecondary": solid("#FFFFFF")}},
                       {"properties": {"backColor": by_measure("state_year", "Rate Colour"),
                                       "fontColor": by_measure("state_year", "Label Colour")}, "selector": every_cell}],
            "columnHeaders": [{"properties": hidden_header}],
            "rowHeaders": [{"properties": hidden_header}],
            "subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}],
            "grid": [{"properties": {"gridVertical": lit("true"), "gridVerticalColor": solid("#FFFFFF"),
                                     "gridVerticalWeight": lit("4D"), "gridHorizontal": lit("true"),
                                     "gridHorizontalColor": solid("#FFFFFF"), "gridHorizontalWeight": lit("4D"),
                                     "outlineColor": solid("#FFFFFF"), "rowPadding": lit("8D")}}]})
    tile_map["query"]["queryState"]["Values"]["projections"][0]["displayName"] = " "
    p2.add("tileMap", X0, TOP, 600, 512, tile_map)
    legend = [("Uninsured   ", 9, True, INK_2)]
    for colr, lab in [("#EEEAF7", "under 12%"), ("#D2C8EE", "12-16%"), ("#A999DD", "16-20%"), ("#7E6CC7", "20-25%"),
                      ("#5A48A8", "25-30%"), ("#3B2B7A", "30%+")]:
        legend += [("■ ", 12, False, colr), (lab + "   ", 9, False, INK_2)]
    p2.add("mapLegend", X0 + 16, TOP + 472, 568, 36, textbox([legend], pad=(4, 0, 0, 0)))
    p2.no_filter += [("tileMap", "top10"), ("tileMap", "drops"), ("top10", "drops"), ("drops", "top10")]
    p2.add("top10", X0 + 616, TOP, W - 616, 300, chart(
        "clusteredBarChart", {"Category": [C("state_year", "state_name", "State")], "Y": [MN("Top 10 Uninsured 2023", "Share uninsured, 2023")]},
        f"{f['top10_nonexp']} of the 10 states with the most uninsured did not expand Medicaid",
        "Pink = did not expand  ·  green = expanded", tooltip_page="stateTooltip", sort=(M("Top 10 Uninsured 2023"), "Descending"),
        objects={**axes(show_value=False, cat_size=10, inner_padding=18), **labels(10), "dataPoint": fill_by("state_year", "Status Colour")}))
    p2.add("drops", X0 + 616, TOP + 312, W - 616, 200, chart(
        "tableEx", {"Values": [C("state_year", "state_name", "State"), C("state_year", "analysis_group", "Medicaid"),
                               MN("Top 10 Drop 2013", "2013"), MN("Top 10 Drop 2023", "2023"), MN("Top 5 Improvement", "Fewer per 100")]},
        "Biggest improvements since 2013: all states that expanded", None, tooltip_page="stateTooltip",
        sort=(M("Top 5 Improvement"), "Descending"),
        objects={**TABLE_FMT, "columnFormatting": [data_bar("state_year", "Top 5 Improvement", EXP_L)]}))

    # ---------------------------------------------------------------- 3. Who is left out
    p3 = Page("leftOut", "03  Who Is Left Out")
    frame(p3, "Hispanic adults and people in states that did not expand are the most likely to be uninsured",
          "Share of low-income adults without health insurance in 2023")
    p3.add("breakdown", X0, TOP, 600, 512, chart(
        "tableEx", {"Values": [C("breakdown_trend", "row_label", "Group"),
                               MN("Rate Expanded 2023", "Expanded"), MN("Rate Not Expanded 2023", "Did not expand"),
                               MN("Gap 2023", "Gap (per 100)")]},
        "Every group is better off where Medicaid expanded",
        "Share uninsured in 2023, states that expanded in 2014 vs states that did not",
        sort=(C("breakdown_trend", "row_label"), "Ascending"),
        objects={**TABLE_FMT, "grid": [{"properties": {"rowPadding": lit("9D")}}],
                 "values": [{"properties": {"fontSize": lit("12D")}}],
                 "columnHeaders": [{"properties": {"fontSize": lit("12D"), "bold": lit("true"), "fontColor": solid(INK),
                                                   "fontFamily": s(FONT)}}],
                 **widths(breakdown_trend__row_label=250, **{"breakdown_trend__Rate Expanded 2023": 96,
                                                             "breakdown_trend__Rate Not Expanded 2023": 112,
                                                             "breakdown_trend__Gap 2023": 92}),
                 "columnFormatting": [data_bar("breakdown_trend", "Rate Expanded 2023", EXP_L),
                                      data_bar("breakdown_trend", "Rate Not Expanded 2023", NONEXP_L),
                                      data_bar("breakdown_trend", "Gap 2023", SUN_L)]}))
    p3.add("leftOutBars", X0 + 616, TOP, W - 616, 262, chart(
        "clusteredBarChart", {"Category": [C("breakdown_trend", "row_label", "Group")],
                              "Y": [MN("Rate Not Expanded 2023", "Share uninsured, states that did not expand")]},
        "In states that did not expand, nearly half of Hispanic low-income adults are uninsured",
        None, sort=(M("Rate Not Expanded 2023"), "Descending"),
        objects={**axes(show_value=False, cat_size=10, inner_padding=6, label_area=50), **labels(10),
                 "dataPoint": [{"properties": {"fill": solid(NONEXP)}}]}))
    p3.no_filter += [("breakdown", "counties"), ("leftOutBars", "counties")]
    p3.add("counties", X0 + 616, TOP + 274, W - 616, 238, chart(
        "tableEx", {"Values": [C("county_2023", "county_name", "County"), C("county_2023", "state_abbrev", "State"),
                               MN("Top 8 County Uninsured", "Uninsured adults"), MN("Top 8 County Rate", "Share uninsured")]},
        f"{f['tx_counties8']} of the 8 counties with the most uninsured adults are in Texas", None,
        sort=(M("Top 8 County Uninsured"), "Descending"),
        objects={**TABLE_FMT, "values": [{"properties": {"fontSize": lit("10D")}}],
                 "columnFormatting": [data_bar("county_2023", "Top 8 County Uninsured", NONEXP_L)]}))

    # ---------------------------------------------------------------- 4. Impact
    p4 = Page("impact", "04  Impact of Expansion")
    frame(p4, f"Medicaid expansion itself cut the share of uninsured low-income adults by about {abs(f['effect']):.0f} in every 100 in its first three years",
          "Measured against similar counties in states that did not expand, so changes that happened everywhere "
          "(like the 2014 insurance marketplaces) are not counted")
    kw3 = (W - 32) // 3
    kpi(p4, 1, X0, TOP, kw3, "Effect Plain", "fewer uninsured in the first 3 years", "Effect Range Text", EXP)
    kpi(p4, 2, X0 + kw3 + 16, TOP, kw3, "Adults Covered 2023", "more adults insured in 2023 because of expansion", "Covered Context", EXP)
    kpi(p4, 3, X0 + 2 * (kw3 + 16), TOP, kw3, "Checks Passed", "reliability checks passed", "Checks Context", SUN)
    p4.add("scenario", X0, TOP + 128, 780, 384, chart(
        "clusteredBarChart", {"Category": [C("scenario_2023", "scenario", " ")], "Y": [MN("Scenario Rate", "Share uninsured, 2023")]},
        f"In 2023, expansion still meant about {round(f['without_2023']) - round(f['actual_2023'])} fewer uninsured adults in every 100",
        "States that expanded in 2014: share of low-income adults without health insurance in 2023",
        sort=(C("scenario_2023", "scenario"), "Ascending"),
        objects={**axes(show_value=False, cat_size=13, inner_padding=35, label_area=40),
                 **labels(26, labelDisplayUnits=lit("1D")), "dataPoint": fill_by("scenario_2023", "Scenario Colour")}))
    check = lambda t: [("✓  ", 14, True, EXP), (t, 12, False, INK)]
    p4.add("checks", X0 + 796, TOP + 128, W - 796, 384, textbox(
        [("Can we trust this result?", 15, True, INK, FONT), ("", 6, False, INK),
         check("Before 2014, both groups of counties were on the same path, so the comparison is fair."),
         ("", 6, False, INK),
         check("Pretending expansion happened in 2011, when it did not, shows no effect, as it should."),
         ("", 6, False, INK),
         check(f"Adults who earn too much to qualify changed much less ({abs(f['spill']):.0f} in 100, not {abs(f['effect']):.0f})."),
         ("", 6, False, INK),
         check("A separate machine learning model gives the same answer."),
         ("", 10, False, INK),
         ("Method: difference-in-differences on 3,035 counties, 2008-2023. Details on the Data Notes page.", 9, False, INK_2)],
        background="#FFFFFF", pad=(18, 12, 20, 20), shadow=True))

    # ---------------------------------------------------------------- 5. If the rest expanded
    p5 = Page("predictions", "05  If the Rest Expanded")
    frame(p5, f"If the 10 remaining states expanded Medicaid, about {round(f['gain'], -4):,.0f} more adults would have health insurance",
          "Estimate from a machine learning model that learned from counties that expanded between 2014 and 2021")
    kpi(p5, 1, kx[0], TOP, kw, "Adults Would Gain", "more adults could be insured", "Gain Context", SUN)
    kpi(p5, 2, kx[1], TOP, kw, "Rate Change Text", "uninsured today → if they expanded", None, NONEXP)
    kpi(p5, 3, kx[2], TOP, kw, "Texas Gain", "of them in Texas alone", "Texas Context", NONEXP)
    p5.add("stateSlicer", kx[3], TOP, kw, 116, slicer("ml_county_predictions", "state", "Pick a state to see its counties"))
    p5.add("stateGain", X0, TOP + 128, 380, 384, chart(
        "clusteredBarChart", {"Category": [C("ml_state_predictions", "state", "State")], "Y": [MN("State Adults Gaining", "Adults who would gain coverage")]},
        "Texas would gain the most", "Adults who would gain health insurance, by state",
        sort=(M("State Adults Gaining"), "Descending"),
        objects={**axes(show_value=False), **labels(11, labelDisplayUnits=lit("1000D"), labelPrecision=lit("0L")),
                 "dataPoint": [{"properties": {"fill": solid(NONEXP)}}]}))
    p5.add("validation", X0 + 396, TOP + 128, 340, 384, chart(
        "clusteredColumnChart", {"Category": [C("ml_validation", "label", "Counties grouped by the model")],
                                 "Y": [MN("Actual Drop", "Fewer uninsured per 100 (what really happened)")]},
        "The model picked the right places", "Tested on states it had never seen: counties it expected to gain most really did (fewer uninsured per 100)",
        sort=(C("ml_validation", "label"), "Ascending"),
        objects={**axes(show_value=False, cat_size=10), **labels(12), "dataPoint": fill_by("ml_validation", "Validation Colour")}))
    p5.no_filter += [("stateGain", "validation"), ("stateSlicer", "validation"), ("stateSlicer", "stateGain")]
    p5.add("countyTable", X0 + 752, TOP + 128, W - 752, 384, chart(
        "tableEx", {"Values": [C("ml_county_predictions", "county_name", "County"), C("ml_county_predictions", "state", "State"),
                               MN("Rate Now", "Today"), MN("Rate After", "If expanded"), MN("Adults Gaining", "Would gain")]},
        "Counties that would gain the most", "Share uninsured today vs if the state expanded",
        sort=(M("Adults Gaining"), "Descending"),
        objects={**TABLE_FMT, "values": [{"properties": {"fontSize": lit("10D")}}],
                 **widths(ml_county_predictions__county_name=134, ml_county_predictions__state=50,
                          **{"ml_county_predictions__Rate Now": 58, "ml_county_predictions__Rate After": 82,
                             "ml_county_predictions__Adults Gaining": 92}),
                 "columnFormatting": [data_bar("ml_county_predictions", "Adults Gaining", SUN_L)]}))

    # ---------------------------------------------------------------- 6. Data notes
    p6 = Page("dataNotes", "06  Data Notes")
    frame(p6, "Data notes", "What the words mean, where the data comes from, and what to keep in mind")
    cols = [
        ("Words used here", [
            "Low-income adults: people aged 18-64 earning about $20,000 a year or less for one person "
            "(138% of the federal poverty line, the Medicaid expansion limit)",
            "Uninsured: has no health insurance of any kind",
            "Medicaid expansion: a state lets these adults get Medicaid; 40 states and DC have done it since 2014",
            "\"6 in 100\": for every 100 low-income adults, 6 fewer are uninsured",
            "Would gain coverage: our estimate of how many more adults would be insured if the state expanded"]),
        ("Where the data comes from", [
            "US Census Bureau Small Area Health Insurance Estimates (SAHIE), 2008-2023, every county",
            "KFF tracker of when each state expanded Medicaid",
            "Census poverty, income and population figures; USDA rural-urban codes",
            "Effect of expansion: difference-in-differences (Callaway & Sant'Anna), comparing each county with similar "
            "counties in states that did not expand; ranges from 499 resamples of states",
            "Predictions: causal forest machine learning model (EconML), tested on states it never saw"]),
        ("Keep in mind", [
            "Census figures are estimates with a margin of error (about 4 in 100 for a typical county)",
            "Five states that already covered these adults before 2014 (DE, DC, MA, NY, VT) are left out of the effect",
            "Connecticut changed its county system in 2022, so it is left out of county results",
            "States chose whether to expand; something else changing at the same time could affect the estimate",
            "Predictions assume expansion would work as it did in similar places; they are not enrollment forecasts"]),
    ]
    for i, ((heading, lines), colour) in enumerate(zip(cols, [EXP, SLATE, NONEXP])):
        x = X0 + i * (W + 16) // 3
        w = (W - 32) // 3
        p6.add(f"notes{i + 1}", x, TOP, w, 512, textbox(
            [(heading, 19, True, colour, FONT)] + [("•  " + t, 13, False, INK) for t in lines],
            background="#FFFFFF", pad=(18, 12, 20, 20), shadow=True))

    # ---------------------------------------------------------------- tooltip: state profile
    tt = Page("stateTooltip", "State Tooltip", width=320, height=240, kind="Tooltip")
    tt.add("ttHeader", 0, 0, 320, 70, block(SLATE))
    tt.add("ttName", 4, 2, 312, 38, card("Selected State", "", value_colour="#FFFFFF", size=16, show_label=False, background=SLATE))
    tt.add("ttStatus", 4, 38, 312, 28, card("Status Text", "", value_colour=SUN, size=10, show_label=False,
                                            background=SLATE, pad=(0, 0, 14, 14), font="Segoe UI"))
    tt.add("ttRate13", 8, 78, 148, 74, card("State Rate 2013", "Uninsured, 2013", value_colour=GREY, size=18))
    tt.add("ttRate23", 164, 78, 148, 74, card("State Rate 2023", "Uninsured, 2023", value_colour=INK, size=18))
    tt.add("ttChange", 8, 158, 148, 74, card("State Change", "Change since 2013", value_colour=INK, size=18))
    tt.add("ttRank", 164, 158, 148, 74, card("Rank Text", "", value_colour=INK_2, size=10, show_label=False, font="Segoe UI"))
    return [p1, p2, p3, p4, p5, p6, tt]


def find_base_theme():
    install = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-AppxPackage Microsoft.MicrosoftPowerBIDesktop | Sort-Object Version | Select-Object -Last 1).InstallLocation"],
        capture_output=True, text=True).stdout.strip()
    f = Path(install) / "bin/WebView2Resources/minerva/sharedresources/BaseThemes" / f"{BASE_THEME}.json"
    if install and f.exists():
        return f
    raise FileNotFoundError("Power BI Desktop (Microsoft Store version) base theme not found")


def build_report():
    shutil.rmtree(RPT, ignore_errors=True)
    d = RPT / "definition"
    write_json(RPT / "definition.pbir", {"$schema": S_PBIR, "version": "4.0",
                                         "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    write_json(d / "version.json", {"$schema": S_VERSION, "version": "2.0.0"})
    write_json(d / "report.json", {
        "$schema": S_REPORT,
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": "5.59", "type": "SharedResources"},
            "customTheme": {"name": CUSTOM_THEME, "reportVersionAtImport": "5.59", "type": "RegisteredResources"}},
        "layoutOptimization": "None",
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": CUSTOM_THEME, "path": CUSTOM_THEME, "type": "CustomTheme"},
                       {"name": "page_background.png", "path": "page_background.png", "type": "Image"}]}]})
    static = RPT / "StaticResources"
    (static / "SharedResources" / "BaseThemes").mkdir(parents=True, exist_ok=True)
    shutil.copy(find_base_theme(), static / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json")
    subprocess.run([sys.executable, str(ROOT / "Python" / "make_background.py")], check=True)
    (static / "RegisteredResources").mkdir(parents=True, exist_ok=True)
    shutil.copy(DASH / "assets" / "page_background.png", static / "RegisteredResources" / "page_background.png")
    write_json(static / "RegisteredResources" / CUSTOM_THEME, {
        "name": "Coverage Infographic",
        "dataColors": [EXP, NONEXP, SUN, GREY, EXP_2, EXP_L, NONEXP_L, SLATE],
        "foreground": INK, "background": "#FFFFFF", "tableAccent": EXP,
        "textClasses": {"title": {"fontFace": FONT, "color": INK}, "callout": {"fontFace": FONT}}})
    pages = build_pages()
    write_json(d / "pages" / "pages.json", {"$schema": S_PAGES, "pageOrder": [p.name for p in pages],
                                            "activePageName": pages[0].name})
    for p in pages:
        write_json(d / "pages" / p.name / "page.json", p.json())
        for v in p.visuals:
            write_json(d / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)


def main():
    build_model()
    build_report()
    write_json(DASH / f"{NAME}.pbip", {"$schema": S_PBIP, "version": "1.0",
                                       "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
                                       "settings": {"enableAutoRecovery": True}})
    print(f"wrote dashboard/{NAME}.pbip")


if __name__ == "__main__":
    main()
