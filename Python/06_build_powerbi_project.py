"""
Generate the Power BI Project (PBIP). The model imports the CSV extracts in dashboard/data/ (written by
05_export_powerbi.py from the PostgreSQL analytics views), so the report opens on any
machine without a database. The folder is a parameter (DataFolder).

    dashboard/Medicaid_Expansion.pbip                 open this in Power BI Desktop
    dashboard/Medicaid_Expansion.SemanticModel/       model (TMDL), columns read from the CSV headers
    dashboard/Medicaid_Expansion.Report/              5 pages + a state tooltip page (PBIR JSON)

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

TABLES = ["group_trend", "state_year", "breakdown_trend", "county_2023", "county_profile"]
HIDDEN = {"order", "rate", "county_fips", "counties_ranked", "quartile", "in_study", "row_order"}
SORT_BY = {("breakdown_trend", "row_label"): "row_order"}

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
SLATE, PAPER, INK, INK_2, RULE = "#1F2D3D", "#DFE5DD", "#1F2D3D", "#5B6B7C", "#E6EAE4"
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

]

PLAIN = [
    # ---- plain-language versions used on the report (no negative numbers, "in every 100" instead of "points")
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
    ("group_trend", "Waffle Square", 'IF ( NOT ISEMPTY ( Waffle ), "■" )', None, "Waffle"),
    # fill from the bottom row up, like a glass filling: cells 90-99 first
    ("group_trend", "Waffle Exp Colour",
     f'IF ( ( 99 - MIN ( Waffle[cell] ) ) < ROUND ( [Exp Rate 2023] * 100, 0 ), "{EXP}", "#D5DCD3" )', None, "Waffle"),
    ("group_trend", "Waffle NonExp Colour",
     f'IF ( ( 99 - MIN ( Waffle[cell] ) ) < ROUND ( [NonExp Rate 2023] * 100, 0 ), "{NONEXP}", "#D5DCD3" )', None, "Waffle"),
]
ONE = "HASONEVALUE ( county_profile[county_label] )"
MEASURES += [
    ("county_profile", "Profile Name", f'IF ( {ONE}, SELECTEDVALUE ( county_profile[county_label] ), "Pick a county" )', None, "County"),
    ("county_profile", "Profile Status",
     f'IF ( {ONE}, SELECTEDVALUE ( county_profile[medicaid_status] ) & "   ·   " & SELECTEDVALUE ( county_profile[rurality] )'
     ' & "   ·   #" & FORMAT ( SUM ( county_profile[rank_us] ), "#,0" ) & " of " & FORMAT ( MAX ( county_profile[counties_ranked] ), "#,0" )'
     ' & " counties for share uninsured", "Type a county name in the search box" )', None, "County"),
    ("county_profile", "Profile Uninsured", f"IF ( {ONE}, SUM ( county_profile[uninsured_2023] ) )", "#,0", "County"),
    ("county_profile", "Profile Adults Context",
     f'IF ( {ONE}, "out of " & FORMAT ( SUM ( county_profile[low_income_adults_2023] ), "#,0" ) & " low-income adults" )', None, "County"),
    ("county_profile", "Profile Rate", f"IF ( {ONE}, SUM ( county_profile[rate_2023] ) / 100 )", "0%", "County"),
    ("county_profile", "Profile Rate Context",
     f'IF ( {ONE}, "state average " & FORMAT ( SUM ( county_profile[state_rate_2023] ) / 100, "0%" ) & "   ·   US " & FORMAT ( MAX ( county_profile[us_rate_2023] ) / 100, "0%" ) )',
     None, "County"),
    ("county_profile", "Profile Change",
     f"VAR _d = SUM ( county_profile[rate_2013] ) - SUM ( county_profile[rate_2023] )\n"
     f'RETURN IF ( {ONE} && NOT ISBLANK ( SUM ( county_profile[rate_2013] ) ), FORMAT ( ABS ( _d ), "0" ) & IF ( _d >= 0, " fewer", " more" ) )',
     None, "County"),
    ("county_profile", "Profile Change Context",
     f'IF ( {ONE}, "share uninsured was " & FORMAT ( SUM ( county_profile[rate_2013] ) / 100, "0%" ) & " in 2013" )', None, "County"),
    ("county_profile", "Compare Rate",
     "SWITCH ( SELECTEDVALUE ( Compare[order] ),\n"
     "    1, [Profile Rate],\n"
     f"    2, IF ( {ONE}, SUM ( county_profile[state_rate_2023] ) / 100 ),\n"
     "    3, MAX ( county_profile[us_rate_2023] ) / 100 )", "0%", "County"),
    ("county_profile", "Compare Colour", f'IF ( SELECTEDVALUE ( Compare[order] ) = 1, "{SUN}", "#B8C0C9" )', None, "County"),
    ("county_profile", "Profile Sentence",
     "VAR _n = SELECTEDVALUE ( county_profile[county_name] )\n"
     "VAR _st = SELECTEDVALUE ( county_profile[state_name] )\n"
     "VAR _r = SUM ( county_profile[rate_2023] )\n"
     "VAR _s = SUM ( county_profile[state_rate_2023] )\n"

     f"RETURN IF ( {ONE},\n"
     '    "About " & FORMAT ( ROUND ( SUM ( county_profile[uninsured_2023] ), -2 ), "#,0" ) & " low-income adults in " & _n\n'
     '        & " have no health insurance: " & FORMAT ( _r, "0" ) & " in every 100. That is "\n'
     '        & IF ( _r > _s + 0.5, "higher than", IF ( _r < _s - 0.5, "lower than", "about the same as" ) )\n'
     '        & " the " & _st & " average (" & FORMAT ( _s, "0" ) & " in 100).",\n'
     '    "Pick a county in the search box to see what its numbers mean." )', None, "County"),
]
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
]

MEASURES += [
    ("group_trend", "US Uninsured 2023", "CALCULATE ( SUM ( group_trend[uninsured] ), group_trend[year] = 2023 ) / 1000000", '0.0"M"', "Overview"),
    ("group_trend", "US Uninsured Context",
     '"down from " & FORMAT ( CALCULATE ( SUM ( group_trend[uninsured] ), group_trend[year] = 2013 ) / 1000000, "0.0" ) & "M in 2013"',
     None, "Overview"),
    ("state_year", "Highest State Rate", "MAXX ( ALL ( state_year[state_name] ), [State Rate 2023] )", "0%", "Overview"),
    ("state_year", "Highest State Context",
     'VAR _t = TOPN ( 1, ADDCOLUMNS ( ALL ( state_year[state_name] ), "@r", [State Rate 2023],\n'
     '    "@u", CALCULATE ( SUM ( state_year[uninsured] ), state_year[year] = 2023 ) ), [@r], DESC )\n'
     'RETURN "about " & FORMAT ( ROUND ( MAXX ( _t, [@u] ), -4 ), "#,0" ) & " people"', None, "Overview"),
    ("county_profile", "Profile State Rank",
     f'IF ( {ONE}, "#" & SUM ( county_profile[rank_in_state] ) & " of " & MAX ( county_profile[counties_in_state] ) )', None, "County"),
    ("county_profile", "Profile State Rank Context",
     f'IF ( {ONE}, "counties in " & SELECTEDVALUE ( county_profile[state_name] ) & " (1 = most uninsured)" )', None, "County"),
]
MEASURES = [m for m in MEASURES if m[0] in TABLES]

CALC_COLUMNS = [
    ("group_trend", "Coverage Group",
     "SWITCH ( group_trend[analysis_group],\n"
     '    "Not expanded by 2023", "Did not expand",\n'
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
        *[f"ref table {t}" for t in TABLES + ["StateGrid", "Compare", "Waffle"]], ""]))
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
    cmp_cols = []
    for col, dtype in [("order", "int64"), ("place", "string")]:
        cmp_cols += [f"\tcolumn {col}", f"\t\tdataType: {dtype}", *(["\t\tisHidden"] if col == "order" else []),
                     *(["\t\tsortByColumn: order"] if col == "place" else []),
                     f"\t\tlineageTag: {tag('Compare', col)}", "\t\tsummarizeBy: none", "\t\tisNameInferred",
                     f"\t\tsourceColumn: [{col}]", "", "\t\tannotation SummarizationSetBy = Automatic", ""]
    write(d / "tables" / "Compare.tmdl", "\n".join([
        "table Compare", f"\tlineageTag: {tag('Compare')}", "", *cmp_cols,
        "\tpartition Compare = calculated", "\t\tmode: import", "\t\tsource =",
        indent('DATATABLE ( "order", INTEGER, "place", STRING, { { 1, "This county" }, { 2, "Its state" }, { 3, "United States" } } )', 4), ""]))
    wf_cols = []
    for col in ("cell", "grid_row", "grid_col"):
        wf_cols += [f"\tcolumn {col}", "\t\tdataType: int64", "\t\tisHidden", f"\t\tlineageTag: {tag('Waffle', col)}",
                    "\t\tsummarizeBy: none", "\t\tisNameInferred", f"\t\tsourceColumn: [{col}]", "",
                    "\t\tannotation SummarizationSetBy = Automatic", ""]
    write(d / "tables" / "Waffle.tmdl", "\n".join([
        "table Waffle", f"\tlineageTag: {tag('Waffle')}", "", *wf_cols,
        "\tpartition Waffle = calculated", "\t\tmode: import", "\t\tsource =",
        indent('SELECTCOLUMNS ( GENERATESERIES ( 0, 99, 1 ), "cell", [Value], "grid_row", INT ( [Value] / 10 ), "grid_col", MOD ( [Value], 10 ) )', 4),
        ""]))
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


def county_search(default="Harris County, TX"):
    v = slicer("county_profile", "county_label", "Find a county")
    v["objects"]["selection"] = [{"properties": {"singleSelect": lit("true")}}]
    v["objects"]["general"] = [{"properties": {
        "selfFilterEnabled": lit("true"),                     # search box in the dropdown
        "filter": {"filter": {"Version": 2, "From": [{"Name": "c", "Entity": "county_profile", "Type": 0}],
                              "Where": [{"Condition": {"In": {
                                  "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "c"}},
                                                              "Property": "county_label"}}],
                                  "Values": [[{"Literal": {"Value": f"'{default}'"}}]]}}}]}}}}]
    v["objects"]["header"][0]["properties"]["fontSize"] = lit("13D")
    return v


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
    page.add("appBar", 16, 8, 1248, 64, block("#FFFFFF", radius=16, shadow=True))
    page.add("logo", 30, 20, 40, 40, textbox([("✚", 17, True, "#FFFFFF")], background=EXP, radius=12,
                                             align="center", pad=(6, 0, 0, 0)))
    page.add("title", 240, 6, 800, 72, textbox(          # centred title
        [("Health Insurance Coverage Gap", 24, True, SLATE, FONT),
         [("MEDICAID EXPANSION IMPACT", 10, True, NONEXP, FONT),
          ("   ·   analytics dashboard   ·   3,143 US counties   ·   2008-2023", 10, False, INK_2)]],
        align="center", pad=(0, 0, 4, 4)))
    page.add("chipAuthor", 1062, 27, 190, 26, chip("Built by Isaac Agyapong", fill=SUN, colour=SLATE, bold=True))
    page.add("accent", X0, 82, 5, 38, block(EXP, radius=3))
    page.add("headline", X0 + 12, 76, W - 12, 52, textbox(
        [(finding, 15, True, INK, FONT), (sub, 10, False, INK_2)], pad=(0, 0, 4, 4)))
    page.add("source", X0 - 4, 640, W + 8, 26, textbox(
        [[("Source: ", 8, True, GREY), ("US Census Bureau SAHIE 2008-2023, SAIPE and population estimates; KFF Medicaid expansion tracker; "
                                        "USDA ERS rural-urban codes.  Low-income adults = ages 18-64 at or below 138% of the federal poverty level.", 8, False, GREY)]],
        pad=(2, 0, 4, 4)))
    page.add("chapterBar", 16, 664, 1248, 48, block(SLATE, radius=24, shadow=True))
    page.add("navigator", 28, 668, 1224, 40, navigator())


ICONS = {"US Uninsured 2023": "●", "Highest State Rate": "▲", "Profile State Rank": "#", "Exp Rate 2023": "✔", "NonExp Rate 2023": "✖", "Profile Uninsured": "●", "Profile Rate": "%", "Profile Change": "↘"}


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
    words = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "All 10"}
    cty8 = pd.read_csv(DATA / "county_2023.csv").nlargest(8, "uninsured")
    gt_all = pd.read_csv(DATA / "group_trend.csv")
    rate = lambda d, g, y: 100 * d.query("analysis_group == @g and year == @y").eval("uninsured / population").iloc[0]
    return {
        "top10_nonexp": int((top10.analysis_group == "Not expanded by 2023").sum()),
        "top_state": top10.iloc[0].state_name,
        "tx_counties": words[int((cty.state_abbrev == "TX").sum())],
        "nonexp_share": gt.loc[gt.analysis_group == "Not expanded by 2023", "uninsured"].sum() / gt.uninsured.sum(),
        "uninsured_total": gt.uninsured.sum(),
        "tx_counties8": words[int((cty8.state_abbrev == "TX").sum())],
        "exp_2023": rate(gt_all, "Expanded 2014", 2023),
        "nonexp_2023": rate(gt_all, "Not expanded by 2023", 2023),
        # differences of the rounded percentages the reader sees (37% - 16% = 21), not of unrounded values
        "drop_exp": round(rate(gt_all, "Expanded 2014", 2013)) - round(rate(gt_all, "Expanded 2014", 2023)),
        "drop_nonexp": round(rate(gt_all, "Not expanded by 2023", 2013)) - round(rate(gt_all, "Not expanded by 2023", 2023)),
    }


def waffle(colour_measure):
    """10 x 10 grid of squares from a matrix: one square per person out of every 100."""
    every_cell = {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "group_trend.Waffle Square"}
    hidden = {"fontColor": solid("#FFFFFF"), "backColor": solid("#FFFFFF"), "fontSize": lit("1D")}
    v = chart("pivotTable", {"Rows": [C("Waffle", "grid_row")], "Columns": [C("Waffle", "grid_col")], "Values": [M("Waffle Square")]},
              None, objects={
                  "values": [{"properties": {"fontSize": lit("13D"), "backColorPrimary": solid("#FFFFFF"),
                                             "backColorSecondary": solid("#FFFFFF")}},
                             {"properties": {"fontColor": by_measure("group_trend", colour_measure)}, "selector": every_cell}],
                  "columnHeaders": [{"properties": hidden}], "rowHeaders": [{"properties": hidden}],
                  "subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}],
                  "grid": [{"properties": {"gridVertical": lit("false"), "gridHorizontal": lit("false"),
                                           "outlineColor": solid("#FFFFFF"), "rowPadding": lit("0D")}}]})
    v["query"]["queryState"]["Values"]["projections"][0]["displayName"] = " "
    v["visualContainerObjects"] = tile(pad=(0, 0, 0, 0), shadow=False)
    return v


def add_waffle_panel(page, x, y, w, h, f):
    """Out of every 100 low-income adults, how many are uninsured today: two 10x10 grids."""
    ratio = f["nonexp_2023"] / f["exp_2023"]
    how = "almost twice" if 1.7 <= ratio < 2 else f"{ratio:.1f} times"
    page.add("waffleCard", x, y, w, h, textbox(
        [(f"In states that did not expand, adults are {how} as likely to be uninsured", 14, True, INK, FONT),
         ("Each square is 1 of every 100 low-income adults. Coloured squares = no health insurance (2023).", 10, False, INK_2)],
        background="#FFFFFF", pad=(12, 10, 16, 16), shadow=True))
    for i, (key, name, colour, rate) in enumerate([("Exp", "States that expanded Medicaid", EXP, f["exp_2023"]),
                                                    ("NonExp", "States that did not expand", NONEXP, f["nonexp_2023"])]):
        gx = x + 40 + i * 390
        page.add(f"waffle{i}", gx, y + 62, 330, 256, waffle(f"Waffle {key} Colour"))
        page.add(f"waffleLabel{i}", gx + 20, y + 318, 290, 60, textbox(
            [[(f"{round(rate)} in 100", 20, True, colour, FONT), ("  uninsured", 12, False, INK_2)],
             (name, 12, True, colour, FONT)], align="center", pad=(0, 0, 0, 0)))


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
    kpi(p1, 3, kx[2], TOP, kw, "US Uninsured 2023", "uninsured low-income adults in the US", "US Uninsured Context", SLATE)
    kpi(p1, 4, kx[3], TOP, kw, "Highest State Rate", f"uninsured in {f['top_state']}, highest in the US", "Highest State Context", SUN)
    add_waffle_panel(p1, X0, TOP + 128, 800, 384, f)
    grp = field("group_trend", "Coverage Group")
    donut_colours = [{"properties": {"fill": solid(c)}, "selector": {"data": [{"scopeId": {"Comparison": {
        "ComparisonKind": 0, "Left": grp, "Right": {"Literal": {"Value": f"'{g}'"}}}}}]}}
        for g, c in {"Did not expand": NONEXP, "Expanded": EXP, "Covered before 2014": GREY_LIGHT}.items()]
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

    # ---------------------------------------------------------------- 4. Find your county    # ---------------------------------------------------------------- 6. Find your county
    pc = Page("county", "04  Find Your County")
    frame(pc, "Look up any US county: how many low-income adults are uninsured, and what it means for local hospitals",
          "Search for a county by name. " + LOW_INCOME)
    pc.add("search", X0, TOP, 400, 92, county_search())
    pc.add("countyName", X0 + 416, TOP, W - 416, 92, textbox([None], background="#FFFFFF", shadow=True))
    pc.add("countyTitle", X0 + 428, TOP + 6, W - 440, 48, card("Profile Name", "", value_colour=SLATE, size=22, show_label=False,
                                                              pad=(0, 0, 8, 8)))
    pc.add("countyStatus", X0 + 428, TOP + 52, W - 440, 34, card("Profile Status", "", value_colour=INK_2, size=11,
                                                                 show_label=False, pad=(0, 0, 8, 8), font="Segoe UI"))
    ky = TOP + 104
    kpi(pc, 1, kx[0], ky, kw, "Profile Uninsured", "low-income adults without insurance", "Profile Adults Context", SLATE)
    kpi(pc, 2, kx[1], ky, kw, "Profile Rate", "of low-income adults are uninsured", "Profile Rate Context", SLATE)
    kpi(pc, 3, kx[2], ky, kw, "Profile Change", "uninsured in every 100 than in 2013", "Profile Change Context", EXP)
    kpi(pc, 4, kx[3], ky, kw, "Profile State Rank", "in its state for share uninsured", "Profile State Rank Context", SUN)
    cy = ky + 128
    pc.add("compare", X0, cy, 480, 640 - cy, chart(
        "clusteredBarChart", {"Category": [C("Compare", "place", " ")], "Y": [MN("Compare Rate", "Share uninsured, 2023")]},
        "How the county compares", "Share of low-income adults without insurance, 2023",
        sort=(C("Compare", "place"), "Ascending"),
        objects={**axes(show_value=False, cat_size=12, inner_padding=30, label_area=35), **labels(16),
                 "dataPoint": fill_by("county_profile", "Compare Colour")}))
    pc.add("meaning", X0 + 496, cy, W - 496, 640 - cy, textbox([None], background="#FFFFFF", shadow=True))
    pc.add("meaningTitle", X0 + 512, cy + 8, W - 528, 36, textbox([("What this means for a local hospital", 15, True, INK, FONT)],
                                                                   pad=(0, 0, 0, 0)))
    pc.add("meaningText", X0 + 508, cy + 44, W - 520, 92, card("Profile Sentence", "", value_colour=INK, size=12, show_label=False,
                                                                pad=(0, 0, 4, 4), font="Segoe UI"))
    action = lambda t, b: [("●  ", 11, True, SUN), (t, 11, True, INK), (b, 11, False, INK_2)]
    pc.add("actions", X0 + 512, cy + 140, W - 528, 640 - cy - 146, textbox(
        [action("Help patients enroll. ", "Many uninsured low-income adults qualify for Medicaid or low-cost Marketplace plans but are not signed up."),
         action("Reach Hispanic residents in Spanish. ", "They are the group most likely to be uninsured."),
         action("Plan for unpaid care. ", "More uninsured adults nearby means more patients who cannot pay their bills.")],
        pad=(0, 0, 0, 0)))

    # ---------------------------------------------------------------- 5. Data notes
    p6 = Page("dataNotes", "05  Data Notes")
    frame(p6, "Data notes", "What the words mean, where the data comes from, and what to keep in mind")
    cols = [
        ("Words used here", [
            "Low-income adults: people aged 18-64 earning about $20,000 a year or less for one person "
            "(138% of the federal poverty line, the Medicaid expansion limit)",
            "Uninsured: has no health insurance of any kind",
            "Medicaid expansion: a state lets these adults get Medicaid; 40 states and DC have done it since 2014",
            "\"16 in 100\": out of every 100 low-income adults, 16 have no health insurance",
            "States that did not expand: the 12 states that had not expanded Medicaid by the end of 2023"]),
        ("Where the data comes from", [
            "US Census Bureau Small Area Health Insurance Estimates (SAHIE), 2008-2023, every county",
            "KFF tracker of when each state expanded Medicaid",
            "Census poverty, income and population figures; USDA rural-urban codes",
            "Loaded into PostgreSQL and checked: county totals match state totals, and medians match the Census's "
            "published 2023 figures exactly",
            "How much expansion itself caused, and predictions for the remaining states: see the companion machine "
            "learning project (Medicaid_Expansion_Impact_Model)"]),
        ("Keep in mind", [
            "Census figures are estimates with a margin of error (about 4 in 100 for a typical county)",
            "Five states covered these adults before 2014 (DE, DC, MA, NY, VT); they are shown separately",
            "Connecticut changed its county system in 2022, so it is left out of county results",
            "Differences between states that did and did not expand are not all caused by expansion; the companion "
            "project measures the part that is",
            "Small counties have wider margins of error than large ones"]),
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
    return [p1, p2, p3, pc, p6, tt]


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
