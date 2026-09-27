"""
Generate the Power BI Project (PBIP). The model imports the CSV extracts in dashboard/data/ (written by
07_export_powerbi.py from the PostgreSQL analytics views and the model outputs), so the report opens on any
machine without a database. The folder is a parameter (DataFolder).

    dashboard/Medicaid_Expansion.pbip                 open this in Power BI Desktop
    dashboard/Medicaid_Expansion.SemanticModel/       model (TMDL), columns read from the CSV headers
    dashboard/Medicaid_Expansion.Report/              6 pages + a state tooltip page (PBIR JSON)

Design: a policy-brief look, different from the other portfolio dashboards. Navy masthead across the top with
a serif title, page tabs underneath, ivory paper canvas, square white cards with hairline borders, footer credit.
Colour meanings: navy = expansion states / the estimated effect, orange = states that had not expanded,
gold = the highlighted finding, grey = context.
"""
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard"
DATA = DASH / "data"
NAME = "Medicaid_Expansion"
SM = DASH / f"{NAME}.SemanticModel"
RPT = DASH / f"{NAME}.Report"

TABLES = ["group_trend", "state_year", "breakdown_trend", "county_2023", "event_study", "model_metrics",
          "robustness", "ml_validation", "ml_state_predictions", "ml_county_predictions"]
HIDDEN = {"order", "quartile", "in_study", "row_order"}
SORT_BY = {("robustness", "label"): "order", ("ml_validation", "label"): "quartile", ("breakdown_trend", "row_label"): "row_order"}

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
CUSTOM_THEME = "PolicyBriefTheme.json"

# palette (same meanings as the matplotlib charts in viz_style.py)
NAVY, NAVY_2, NAVY_LIGHT, ORANGE, GOLD = "#1D4E89", "#4F7CB3", "#9FB6D4", "#D1603D", "#D99A1E"
GREY, GREY_LIGHT = "#8A8780", "#CFCCC4"
MAST, PAPER, CARD_BORDER, INK, INK_2, RULE = "#14335C", "#F7F5EF", "#DEDAD0", "#1B1B1B", "#55524C", "#E9E5DA"
PCT1, PTS, INT = "0.0%;-0.0%;0.0%", '+0.0" pts";-0.0" pts";0.0" pts"', "#,0"
SERIF = "Georgia"


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
     '"was " & FORMAT ( [Exp Rate 2013], "0%" ) & " in 2013  ·  down " & FORMAT ( ( [Exp Rate 2013] - [Exp Rate 2023] ) * 100, "0" ) & " points"',
     None, "Context"),
    ("group_trend", "KPI NonExp Context",
     '"was " & FORMAT ( [NonExp Rate 2013], "0%" ) & " in 2013  ·  down " & FORMAT ( ( [NonExp Rate 2013] - [NonExp Rate 2023] ) * 100, "0" ) & " points"',
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
     f'    "Not expanded by 2023", "{ORANGE}",\n    "Excluded (early coverage)", "{GREY_LIGHT}",\n    "{NAVY}" )', None, "States"),
    ("state_year", "Tile Label", "SELECTEDVALUE ( StateGrid[state_abbr] )", None, "Map"),
    ("state_year", "Rate Colour",
     "VAR _r = [State Rate 2023]\n"
     "RETURN SWITCH ( TRUE (),\n"
     '    ISBLANK ( SELECTEDVALUE ( StateGrid[state_abbr] ) ), "#FFFFFF",\n'
     '    ISBLANK ( _r ), "#E6E3DC",\n'
     '    _r < 0.12, "#FFF1CF",\n    _r < 0.16, "#FDD89A",\n    _r < 0.20, "#F9B461",\n'
     '    _r < 0.25, "#E8843A",\n    _r < 0.30, "#C4561D",\n    "#8A3510" )', None, "Map"),
    ("state_year", "Label Colour",
     'IF ( [State Rate 2023] >= 0.25, "#FFFFFF", "#1B1B1B" )', None, "Map"),
    ("state_year", "Border Colour",
     # a navy or orange underline would need a second visual; the tooltip carries the status instead
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
    ("breakdown_trend", "Gap 2023", "( [Rate Not Expanded 2023] - [Rate Expanded 2023] ) * 100", '0" pts"', "Breakdown"),
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
     f'IF ( SELECTEDVALUE ( event_study[years_since_expansion] ) < 0, "{GREY_LIGHT}", "{NAVY}" )', None, "Causal"),
    ("model_metrics", "Effect Years 0-2", metric(EFFECT), '0.0" pts"', "Causal"),
    ("model_metrics", "Effect CI Text",
     f'"95% CI " & FORMAT ( {metric(EFFECT, "ci_low")}, "0.0" ) & " to " & FORMAT ( {metric(EFFECT, "ci_high")}, "0.0" ) & " points"',
     None, "Context"),
    ("model_metrics", "Adults Covered 2023", metric("Adults covered in 2023 because of expansion"), INT, "Causal"),
    ("model_metrics", "Covered Context",
     f'"95% CI " & FORMAT ( {metric("Adults covered in 2023 because of expansion", "ci_low")}, "#,0" ) & " to " & FORMAT ( {metric("Adults covered in 2023 because of expansion", "ci_high")}, "#,0" )',
     None, "Context"),
    ("model_metrics", "Placebo Effect", metric("Placebo: fake 2011 expansion date"), '+0.0" pts";-0.0" pts";0.0" pts"', "Causal"),
    ("model_metrics", "Placebo Context", '"a fake 2011 date shows no effect, as it should"', None, "Context"),
    ("robustness", "Estimate", "SUM ( robustness[value] )", '+0.0;-0.0;0.0', "Causal"),
    ("robustness", "Estimate Colour", f'IF ( SELECTEDVALUE ( robustness[order] ) = 1, "{NAVY}", "{GOLD}" )', None, "Causal"),

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

CALC_COLUMNS = [
    ("group_trend", "Coverage Group",
     "SWITCH ( group_trend[analysis_group],\n"
     '    "Not expanded by 2023", "Not expanded",\n'
     '    "Excluded (early coverage)", "Covered before 2014",\n'
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


def tile(title=None, subtitle=None, background="#FFFFFF", border=True, tooltip_page=None, pad=(12, 10, 14, 14)):
    """Card formatting shared by every visual: white square card, hairline border, serif title, grey subtitle."""
    objs = {
        "background": [{"properties": {"show": lit("true"), "color": solid(background), "transparency": lit("0D")}}],
        "border": [{"properties": {"show": lit("true" if border else "false"), "color": solid(CARD_BORDER),
                                   "radius": lit("2D")}}],
        "dropShadow": [{"properties": {"show": lit("false")}}],
        "padding": [{"properties": {"top": lit(f"{pad[0]}D"), "bottom": lit(f"{pad[1]}D"),
                                    "left": lit(f"{pad[2]}D"), "right": lit(f"{pad[3]}D")}}],
        "title": [{"properties": {"show": lit("true" if title else "false"), **({
            "text": s(title), "fontColor": solid(INK), "fontSize": lit("14D"), "bold": lit("true"),
            "fontFamily": s(SERIF)} if title else {})}}],
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


def textbox(paragraphs, background=None, pad=(12, 10, 14, 14), border=False, align=None):
    """paragraphs: list of (text, size, bold, colour[, font]) or lists of such runs for one line."""
    def run(t, size, bold, col, font=None):
        return {"value": t, "textStyle": {"fontSize": f"{size}pt", "color": col,
                                          **({"fontWeight": "bold"} if bold else {}),
                                          **({"fontFamily": font} if font else {})}}
    paras = [{"textRuns": [run(*r) for r in (p if isinstance(p, list) else [p])],
              **({"horizontalTextAlignment": align} if align else {})} for p in paragraphs if p]
    v = {"visualType": "textbox", "drillFilterOtherVisuals": True,
         "objects": {"general": [{"properties": {"paragraphs": paras}}]}}
    v["visualContainerObjects"] = tile(background=background, border=border, pad=pad) if background else \
        {"background": [{"properties": {"show": lit("false")}}]}
    return v


def block(colour):
    return textbox([None], background=colour, pad=(0, 0, 0, 0))


def card(measure, label, value_colour=INK, size=28, show_label=True, background="#FFFFFF", pad=(4, 2, 14, 14), font=SERIF):
    v = {"visualType": "card", "query": {"queryState": {"Values": projections([M(measure)])}},
         "objects": {
             "labels": [{"properties": {"color": solid(value_colour), "fontSize": lit(f"{size}D"), "fontFamily": s(font)}}],
             "categoryLabels": [{"properties": {"show": lit("true" if show_label else "false"),
                                                "color": solid(INK_2), "fontSize": lit("11D")}}]},
         "visualContainerObjects": tile(background=background, border=False, pad=pad),
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
                "layout": [{"properties": {"orientation": lit("2D"), "cellPadding": lit("4L")}}],     # 2 = one horizontal row
                "pages": [{"properties": {"showHiddenPages": lit("false"), "showTooltipPages": lit("false")}}],
                "shape": [{"properties": {"tileShape": s("rectangle")}}],
                "fill": [state("default", {"show": lit("true"), "fillColor": solid(PAPER), "transparency": lit("0D")}),
                         state("hover", {"fillColor": solid("#EDE8DC")}),
                         state("selected", {"fillColor": solid("#FFFFFF")})],
                "text": [state("default", {"fontColor": solid(INK_2), "fontSize": lit("12D")}),
                         state("selected", {"fontColor": solid(MAST), "bold": lit("true")})],
                "outline": [state("default", {"show": lit("false")})],
                "accentBar": [state("default", {"show": lit("false")}),
                              state("selected", {"show": lit("true"), "position": s("Bottom"),
                                                 "color": solid(GOLD), "width": lit("4D")})],
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
                "objects": {"background": [{"properties": {"color": solid(PAPER), "transparency": lit("0D")}}],
                            "outspace": [{"properties": {"color": solid(PAPER)}}]}}
        if self.no_filter:
            page["visualInteractions"] = [{"source": a, "target": b, "type": "NoFilter"} for a, b in self.no_filter]
        if self.kind == "Tooltip":
            page.update({"displayOption": "ActualSize", "visibility": "HiddenInViewMode", "type": "Tooltip",
                         "pageBinding": {"name": f"{self.name}Binding", "type": "Tooltip", "parameters": []}})
            page["objects"] = {"background": [{"properties": {"color": solid("#FFFFFF"), "transparency": lit("0D")}}]}
        return page


TITLE = "Health Insurance Coverage Gap & Medicaid Expansion Impact"
X0, W, TOP = 24, 1232, 170          # content area


def frame(page, finding, sub):
    """Masthead, tabs, section headline and footer: identical on every page."""
    page.add("masthead", 0, 0, 1280, 66, block(MAST))
    page.add("mastTitle", 16, 2, 920, 64, textbox(
        [(TITLE, 19, True, "#FFFFFF", SERIF),
         ("ANALYTICS + MACHINE LEARNING   ·   3,143 US COUNTIES   ·   2008-2023", 9, True, GOLD)], pad=(2, 0, 8, 8)))
    page.add("mastCredit", 940, 8, 324, 54, textbox(
        [("Built by Isaac Agyapong", 10, True, "#FFFFFF"), ("Census SAHIE  ·  KFF  ·  PostgreSQL  ·  EconML", 8, False, "#C9D4E3")],
        align="right", pad=(2, 0, 8, 8)))
    page.add("mastRule", 0, 66, 1280, 3, block(GOLD))
    page.add("navigator", 16, 74, 1248, 38, navigator())
    page.add("navRule", X0, 113, W, 1, block(CARD_BORDER))
    page.add("headline", X0 - 4, 115, W + 8, 56, textbox(
        [(finding, 15, True, INK, SERIF), (sub, 10, False, INK_2)], pad=(0, 0, 4, 4)))
    page.add("footer", X0 - 4, 688, W + 8, 30, textbox(
        [[("Source: ", 8, True, GREY), ("US Census Bureau SAHIE 2008-2023, SAIPE and population estimates; KFF Medicaid expansion tracker; "
                                        "USDA ERS rural-urban codes.  Low-income adults = ages 18-64 at or below 138% of the federal poverty level.", 8, False, GREY)]],
        pad=(0, 0, 4, 4)))


def kpi(page, i, x, y, w, measure, label, context, colour, h=116, size=27):
    page.add(f"kpiTile{i}", x, y, w, h, textbox([None], background="#FFFFFF", border=True))
    page.add(f"kpiRule{i}", x, y, w, 4, block(colour))
    page.add(f"kpi{i}", x + 2, y + 6, w - 4, h - 36 if context else h - 12, card(measure, label, value_colour=colour, size=size))
    if context:
        page.add(f"kpiContext{i}", x + 2, y + h - 30, w - 4, 26,
                 card(context, "", value_colour=INK_2, size=11, show_label=False, pad=(0, 0, 14, 14), font="Segoe UI"))


def data_bar(table, measure, colour):
    return {"properties": {"dataBars": {"positiveColor": solid(colour), "negativeColor": solid(colour),
                                        "axisColor": solid("#FFFFFF"), "reverseDirection": lit("false"),
                                        "hideText": lit("false")}},
            "selector": {"metadata": f"{table}.{measure}"}}


TABLE_FMT = {"values": [{"properties": {"fontSize": lit("11D")}}],
             "columnHeaders": [{"properties": {"fontSize": lit("11D"), "bold": lit("true"), "fontColor": solid(INK)}}],
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
    return {
        "top10_nonexp": int((top10.analysis_group == "Not expanded by 2023").sum()),
        "tx_counties": words[int((cty.state_abbrev == "TX").sum())],
        "nonexp_share": gt.loc[gt.analysis_group == "Not expanded by 2023", "uninsured"].sum() / gt.uninsured.sum(),
        "tx_gain_share": ml.set_index("state").adults_gaining_coverage["TX"] / ml.adults_gaining_coverage.sum(),
        "gain": mm["Adults who would gain coverage (10 states)"],
        "effect": mm["Effect of expansion (years 0-2)"],
    }


def build_pages():
    f = facts()
    kx = [X0 + i * (W + 16) // 4 for i in range(4)]
    kw = (W - 48) // 4

    # ---------------------------------------------------------------- 1. Overview
    p1 = Page("overview", "Overview")
    frame(p1, f"Where Medicaid expanded, the uninsured rate fell further; expansion itself cut it by about {abs(f['effect']):.0f} points",
          "Uninsured rate of adults 18-64 at or below 138% of the poverty line, the group expansion made eligible for Medicaid")
    kpi(p1, 1, kx[0], TOP, kw, "Exp Rate 2023", "Uninsured, 2014 expansion states", "KPI Exp Context", NAVY)
    kpi(p1, 2, kx[1], TOP, kw, "NonExp Rate 2023", "Uninsured, non-expansion states", "KPI NonExp Context", ORANGE)
    kpi(p1, 3, kx[2], TOP, kw, "Effect Years 0-2", "Drop caused by expansion", "Effect CI Text", NAVY)
    kpi(p1, 4, kx[3], TOP, kw, "Adults Would Gain", "Adults who would gain coverage", "Gain Context", GOLD)
    p1.add("trend", X0, TOP + 128, 800, 384, chart(
        "lineChart", {"Category": [C("group_trend", "year")],
                      "Y": [MN("Expanded in 2014", "States that expanded in 2014"), MN("Not expanded", "States that had not expanded")]},
        "The gap between the two groups nearly doubled after 2014",
        "Share of low-income adults without health insurance", sort=(C("group_trend", "year"), "Ascending"),
        objects={**axes(), "legend": [{"properties": {"show": lit("true"), "position": s("Top")}}],
                 "lineStyles": [{"properties": {"strokeWidth": lit("3D"), "showMarker": lit("true"), "markerSize": lit("4D")}}]},
        colours={"Expanded in 2014": NAVY, "Not expanded": ORANGE}))
    grp = field("group_trend", "Coverage Group")
    donut_colours = [{"properties": {"fill": solid(c)}, "selector": {"data": [{"scopeId": {"Comparison": {
        "ComparisonKind": 0, "Left": grp, "Right": {"Literal": {"Value": f"'{g}'"}}}}}]}}
        for g, c in {"Not expanded": ORANGE, "Expanded": NAVY, "Covered before 2014": GREY_LIGHT}.items()]
    p1.add("donut", X0 + 816, TOP + 128, W - 816, 384, chart(
        "donutChart", {"Category": [C("group_trend", "Coverage Group")], "Y": [MN("Uninsured 2023", "Uninsured low-income adults, 2023")]},
        f"{f['nonexp_share']:.0%} of the uninsured live in the states that had not expanded",
        "Uninsured low-income adults in 2023 (12 non-expansion states hold about a quarter of the population)",
        objects={"labels": [{"properties": {"show": lit("true"), "labelStyle": s("Percent of total"),
                                            "percentageLabelPrecision": lit("0L"), "fontSize": lit("14D"),
                                            "bold": lit("true"), "color": solid(INK)}}],
                 "legend": [{"properties": {"show": lit("true"), "position": s("Bottom"), "showTitle": lit("false")}}],
                 "dataPoint": donut_colours}))

    # ---------------------------------------------------------------- 2. States
    p2 = Page("states", "States")
    frame(p2, "The highest uninsured rates are in Texas and the Southeast, mostly states that had not expanded",
          "Uninsured rate of low-income adults by state, 2023  ·  hover over a state for its profile")
    every_cell = {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "state_year.Tile Label"}
    hidden_header = {"fontColor": solid("#FFFFFF"), "backColor": solid("#FFFFFF"), "fontSize": lit("6D")}
    tile_map = chart(
        "pivotTable", {"Rows": [C("StateGrid", "tile_y")], "Columns": [C("StateGrid", "tile_x")], "Values": [M("Tile Label")]},
        "Uninsured rate by state, 2023", "Darker = more low-income adults uninsured", tooltip_page="stateTooltip",
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
    for colr, lab in [("#FFF1CF", "under 12%"), ("#FDD89A", "12-16%"), ("#F9B461", "16-20%"), ("#E8843A", "20-25%"),
                      ("#C4561D", "25-30%"), ("#8A3510", "30%+")]:
        legend += [("■ ", 12, False, colr), (lab + "   ", 9, False, INK_2)]
    p2.add("mapLegend", X0 + 16, TOP + 472, 568, 36, textbox([legend], pad=(4, 0, 0, 0)))
    p2.no_filter += [("tileMap", "top10"), ("tileMap", "drops"), ("top10", "drops"), ("drops", "top10")]
    p2.add("top10", X0 + 616, TOP, W - 616, 300, chart(
        "clusteredBarChart", {"Category": [C("state_year", "state_name")], "Y": [MN("Top 10 Uninsured 2023", "Uninsured rate, 2023")]},
        f"{f['top10_nonexp']} of the 10 highest rates are in states that had not expanded", "Orange = had not expanded by 2023  ·  navy = expanded",
        tooltip_page="stateTooltip", sort=(M("Top 10 Uninsured 2023"), "Descending"),
        objects={**axes(show_value=False, cat_size=10, inner_padding=18), **labels(10), "dataPoint": fill_by("state_year", "Status Colour")}))
    p2.add("drops", X0 + 616, TOP + 312, W - 616, 200, chart(
        "tableEx", {"Values": [C("state_year", "state_name", "State"), C("state_year", "analysis_group", "Status"),
                               MN("Top 10 Drop 2013", "2013"), MN("Top 10 Drop 2023", "2023"), MN("Top 10 Drop", "Change")]},
        "The 5 biggest drops since 2013 were all in expansion states", None, tooltip_page="stateTooltip",
        sort=(M("Top 10 Drop"), "Ascending"),
        objects={**TABLE_FMT, "columnFormatting": [data_bar("state_year", "Top 10 Drop", NAVY_LIGHT)]}))

    # ---------------------------------------------------------------- 3. Who is left out
    p3 = Page("leftOut", "Who Is Left Out")
    frame(p3, "Hispanic adults and people in non-expansion states are the most likely to be uninsured today",
          "Uninsured rate in 2023: states that expanded in 2014 vs states that had not expanded by 2023")
    p3.add("breakdown", X0, TOP, 600, 512, chart(
        "tableEx", {"Values": [C("breakdown_trend", "row_label", "Low-income adults 18-64"),
                               MN("Rate Expanded 2023", "Expanded"), MN("Rate Not Expanded 2023", "Not expanded"),
                               MN("Gap 2023", "Gap")]},
        "The gap is wide in every group", "Uninsured rate in 2023 (low-income adults unless stated)",
        sort=(C("breakdown_trend", "row_label"), "Ascending"),
        objects={**TABLE_FMT, "grid": [{"properties": {"rowPadding": lit("9D")}}],
                 "values": [{"properties": {"fontSize": lit("12D")}}],
                 "columnHeaders": [{"properties": {"fontSize": lit("12D"), "bold": lit("true"), "fontColor": solid(INK)}}],
                 **widths(breakdown_trend__row_label=262, **{"breakdown_trend__Rate Expanded 2023": 92,
                                                             "breakdown_trend__Rate Not Expanded 2023": 112,
                                                             "breakdown_trend__Gap 2023": 84}),
                 "columnFormatting": [data_bar("breakdown_trend", "Rate Expanded 2023", NAVY_LIGHT),
                                      data_bar("breakdown_trend", "Rate Not Expanded 2023", "#EFB7A3"),
                                      data_bar("breakdown_trend", "Gap 2023", "#F2D49B")]}))
    p3.add("incomeGap", X0 + 616, TOP, W - 616, 186, chart(
        "lineChart", {"Category": [C("breakdown_trend", "year")],
                      "Y": [MN("Gap Eligible", "Made eligible (at or below 138%)"), MN("Gap Not Eligible", "Not made eligible (138-400%)")]},
        "The gap opened for the people expansion made eligible",
        "Points between non-expansion and 2014 expansion states", sort=(C("breakdown_trend", "year"), "Ascending"),
        objects={**axes(), "legend": [{"properties": {"show": lit("true"), "position": s("Top")}}],
                 "lineStyles": [{"properties": {"strokeWidth": lit("3D")}}]},
        colours={"Gap Eligible": GOLD, "Gap Not Eligible": GREY}))
    p3.no_filter += [("breakdown", "counties"), ("incomeGap", "counties")]
    p3.add("counties", X0 + 616, TOP + 198, W - 616, 314, chart(
        "tableEx", {"Values": [C("county_2023", "county_name", "County"), C("county_2023", "state_abbrev", "State"),
                               MN("Top 10 County Uninsured", "Uninsured"), MN("Top 10 County Rate", "Rate")]},
        f"{f['tx_counties']} of the 10 counties with the most uninsured are in Texas", "Low-income adults without insurance, 2023",
        sort=(M("Top 10 County Uninsured"), "Descending"),
        objects={**TABLE_FMT, "values": [{"properties": {"fontSize": lit("10D")}}],
                 "columnFormatting": [data_bar("county_2023", "Top 10 County Uninsured", "#EFB7A3")]}))

    # ---------------------------------------------------------------- 4. Impact (causal)
    p4 = Page("impact", "Impact of Expansion")
    frame(p4, f"Expansion itself cut the uninsured rate by about {abs(f['effect']):.0f} points, measured against similar counties that did not expand",
          "Difference-in-differences (Callaway & Sant'Anna) on 3,035 counties in 45 states, 2008-2023, 499 state-level bootstrap draws")
    kw3 = (W - 32) // 3
    kpi(p4, 1, X0, TOP, kw3, "Effect Years 0-2", "Effect of expansion, first 3 years", "Effect CI Text", NAVY)
    kpi(p4, 2, X0 + kw3 + 16, TOP, kw3, "Adults Covered 2023", "Adults insured in 2023 because of expansion", "Covered Context", NAVY)
    kpi(p4, 3, X0 + 2 * (kw3 + 16), TOP, kw3, "Placebo Effect", "Placebo test (fake expansion in 2011)", "Placebo Context", GOLD)
    p4.add("eventStudy", X0, TOP + 128, 780, 384, chart(
        "columnChart", {"Category": [C("event_study", "years_since_expansion", "Years since expansion")],
                        "Y": [MN("Effect", "Effect on uninsured rate (pts)")]},
        "No difference before expansion, a clear drop after",
        "Estimated effect by years since the state expanded (grey = before expansion, a check that trends matched)",
        sort=(C("event_study", "years_since_expansion"), "Ascending"),
        objects={**axes(show_value=False, categorical=True), **labels(10), "dataPoint": fill_by("event_study", "Effect Colour")}))
    p4.add("robust", X0 + 796, TOP + 128, W - 796, 384, chart(
        "clusteredBarChart", {"Category": [C("robustness", "label", "Check")], "Y": [MN("Estimate", "Estimate (pts)")]},
        "The effect holds up to checks", "Main estimate vs tests; the fake-date placebo should be about zero",
        sort=(C("robustness", "label"), "Ascending"),
        objects={**axes(show_value=False, cat_size=11, label_area=55), **labels(12), "dataPoint": fill_by("robustness", "Estimate Colour")}))

    # ---------------------------------------------------------------- 5. Predictions (machine learning)
    p5 = Page("predictions", "If the Rest Expanded")
    frame(p5, f"A machine learning model predicts about {round(f['gain'], -4):,.0f} more adults would be insured if the 10 remaining states expanded",
          "Causal forest (EconML) trained on every expansion wave 2014-2021; predictions use each county's 2023 situation")
    kpi(p5, 1, kx[0], TOP, kw, "Adults Would Gain", "Adults who would gain coverage", "Gain Context", GOLD)
    kpi(p5, 2, kx[1], TOP, kw, "Forest Effect", "Model's average effect", "Forest Context", NAVY)
    kpi(p5, 3, kx[2], TOP, kw, "Top Quarter Actual", "Actual drop, top-ranked quarter", "Validation Context", NAVY)
    p5.add("stateSlicer", kx[3], TOP, kw, 116, slicer("ml_county_predictions", "state", "Filter counties by state"))
    p5.add("stateGain", X0, TOP + 128, 380, 384, chart(
        "clusteredBarChart", {"Category": [C("ml_state_predictions", "state", "State")], "Y": [MN("State Adults Gaining", "Adults gaining coverage")]},
        f"Texas alone accounts for {f['tx_gain_share']:.0%}", "Predicted adults gaining coverage by state",
        sort=(M("State Adults Gaining"), "Descending"),
        objects={**axes(show_value=False), **labels(11, labelDisplayUnits=lit("1000D"), labelPrecision=lit("0L")),
                 "dataPoint": [{"properties": {"fill": solid(ORANGE)}}]}))
    p5.add("validation", X0 + 396, TOP + 128, 340, 384, chart(
        "clusteredColumnChart", {"Category": [C("ml_validation", "label", "Model's ranking")],
                                 "Y": [MN("Model Prediction", "Predicted"), MN("Actual Result", "Actual")]},
        "Tested on unseen states, the ranking holds", "Effect by predicted quarter (pts), held-out states",
        sort=(C("ml_validation", "label"), "Ascending"),
        objects={**axes(show_value=False, cat_size=10), **labels(10), "legend": [{"properties": {"show": lit("true"), "position": s("Top")}}]},
        colours={"Model Prediction": NAVY_LIGHT, "Actual Result": NAVY}))
    p5.no_filter += [("stateGain", "validation"), ("stateSlicer", "validation"), ("stateSlicer", "stateGain")]
    p5.add("countyTable", X0 + 752, TOP + 128, W - 752, 384, chart(
        "tableEx", {"Values": [C("ml_county_predictions", "county_name", "County"), C("ml_county_predictions", "state", "State"),
                               MN("Rate Now", "Now"), MN("Rate After", "After"), MN("Adults Gaining", "Adults gaining")]},
        "Counties with the largest predicted gains", "Uninsured rate now and predicted after expansion",
        sort=(M("Adults Gaining"), "Descending"),
        objects={**TABLE_FMT, "columnFormatting": [data_bar("ml_county_predictions", "Adults Gaining", "#F2D49B")]}))

    # ---------------------------------------------------------------- 6. Data notes
    p6 = Page("dataNotes", "Data Notes")
    frame(p6, "Data notes", "Sources, definitions, methods and limitations")
    cols = [
        ("Sources", [
            "US Census Bureau Small Area Health Insurance Estimates (SAHIE), 2008-2023, every county and state",
            "KFF tracker of state Medicaid expansion decisions (implementation dates)",
            "Census SAIPE poverty and income, and county population estimates (2013 baseline)",
            "USDA ERS Rural-Urban Continuum Codes 2013",
            "Loaded into PostgreSQL (raw, core, analytics layers); this report imports extracts of the analytics views"]),
        ("Definitions and methods", [
            "Low-income adults = ages 18-64 with income at or below 138% of the federal poverty level",
            "Expansion year = first calendar year with at least 6 months of expansion coverage",
            "Rates are population-weighted: total uninsured / total people",
            "Effect: staggered difference-in-differences vs counties in states that had not expanded, adjusted for "
            "county traits; 95% intervals from 499 state-level bootstrap draws",
            "Predictions: causal forest (double machine learning) validated on held-out states"]),
        ("Limitations", [
            "SAHIE figures are model-based estimates with margins of error (median about 4 points per county)",
            "DE, DC, MA, NY and VT are excluded from the effect estimate: they covered adults before 2014",
            "Connecticut counties changed in 2022, so Connecticut is left out of county-level results",
            "States chose whether to expand; a state-specific change at the same time would bias the estimate",
            "Predictions assume expansion would work as it did in similar counties; they are not enrollment forecasts"]),
    ]
    for i, (heading, lines) in enumerate(cols):
        x = X0 + i * (W + 16) // 3
        w = (W - 32) // 3
        p6.add(f"notes{i + 1}", x, TOP, w, 512, textbox(
            [(heading, 19, True, INK, SERIF)] + [("•  " + t, 13, False, INK) for t in lines],
            background="#FFFFFF", border=True, pad=(18, 12, 18, 18)))
        p6.add(f"notesRule{i + 1}", x, TOP, w, 4, block(NAVY if i < 2 else GOLD))

    # ---------------------------------------------------------------- tooltip: state profile
    tt = Page("stateTooltip", "State Tooltip", width=320, height=240, kind="Tooltip")
    tt.add("ttHeader", 0, 0, 320, 70, block(MAST))
    tt.add("ttName", 4, 2, 312, 38, card("Selected State", "", value_colour="#FFFFFF", size=16, show_label=False, background=MAST))
    tt.add("ttStatus", 4, 38, 312, 28, card("Status Text", "", value_colour=GOLD, size=10, show_label=False,
                                            background=MAST, pad=(0, 0, 14, 14), font="Segoe UI"))
    tt.add("ttRate13", 8, 78, 148, 74, card("State Rate 2013", "Uninsured, 2013", value_colour=GREY, size=18))
    tt.add("ttRate23", 164, 78, 148, 74, card("State Rate 2023", "Uninsured, 2023", value_colour=NAVY, size=18))
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
             "items": [{"name": CUSTOM_THEME, "path": CUSTOM_THEME, "type": "CustomTheme"}]}]})
    static = RPT / "StaticResources"
    (static / "SharedResources" / "BaseThemes").mkdir(parents=True, exist_ok=True)
    shutil.copy(find_base_theme(), static / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json")
    write_json(static / "RegisteredResources" / CUSTOM_THEME, {
        "name": "Policy Brief",
        "dataColors": [NAVY, ORANGE, GOLD, GREY, NAVY_2, NAVY_LIGHT, "#EFB7A3", "#6B6860"],
        "foreground": INK, "background": "#FFFFFF", "tableAccent": NAVY,
        "textClasses": {"title": {"fontFace": SERIF, "color": INK}}})
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
