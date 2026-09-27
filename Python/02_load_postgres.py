"""
Load Data/raw/ into PostgreSQL (database medicaid_coverage) and build the star schema.

    1. SQL/01a_schema_raw.sql       raw schema                     (skipped with --skip-raw)
    2. raw.*                        bulk-load source files with COPY (skipped with --skip-raw)
    3. SQL/01b_schema_core.sql      core + analytics schemas
    4. SQL/02_transform.sql         raw -> core: type, clean, conform, build dimensions
    5. SQL/04_analytics_views.sql   views used by the notebook, the models and Power BI

    python Python/02_load_postgres.py              full rebuild (~3 min)
    python Python/02_load_postgres.py --skip-raw   rebuild core/analytics from the loaded raw layer
    python Python/02_load_postgres.py --raw-only   load the raw layer only (used for profiling)

Connection settings come from the standard PG* environment variables, defaulting to
postgres@localhost:5432. The password is read by libpq from pgpass.conf (never stored here).
"""
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "Data" / "raw"
SQL = ROOT / "SQL"
YEARS = range(2008, 2024)
DB = os.getenv("PGDATABASE", "medicaid_coverage")


def conninfo(db=DB):
    return " ".join([f"host={os.getenv('PGHOST', 'localhost')}", f"port={os.getenv('PGPORT', '5432')}",
                     f"user={os.getenv('PGUSER', 'postgres')}", f"dbname={db}"])


CONNINFO = conninfo()
SAHIE_COLS = ["year", "version", "statefips", "countyfips", "geocat", "agecat", "racecat", "sexcat", "iprcat",
              "nipr", "nipr_moe", "nui", "nui_moe", "nic", "nic_moe", "pctui", "pctui_moe", "pctic", "pctic_moe",
              "state_name", "county_name"]


def copy_frame(cur, table, df):
    """COPY a DataFrame of strings into a table (columns matched by name)."""
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    buf.seek(0)
    with cur.copy(f"COPY {table} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv)") as cp:
        while data := buf.read(1 << 20):
            cp.write(data)


def run_sql_file(conn, name):
    t = time.time()
    conn.execute((SQL / name).read_text(encoding="utf-8-sig"))
    conn.commit()
    print(f"  ran {name} ({time.time() - t:.0f}s)")


def ensure_database():
    """Create the tablespace and database on first run (needs superuser)."""
    with psycopg.connect(conninfo("postgres"), autocommit=True) as admin:
        if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,)).fetchone():
            return
        print("creating database", DB)
        for stmt in (SQL / "00_create_database.sql").read_text(encoding="utf-8-sig").split(";"):
            body = "\n".join(l for l in stmt.splitlines() if not l.strip().startswith("--")).strip()
            if body:
                admin.execute(body)
        admin.execute("ALTER SYSTEM SET max_wal_size = '256MB'")
        admin.execute("SELECT pg_reload_conf()")


def read_sahie(year):
    """SAHIE CSVs start with a ~80-line text layout; the data starts at the line beginning 'year,'."""
    with zipfile.ZipFile(RAW / f"sahie-{year}-csv.zip") as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        lines = z.read(name).decode("latin-1").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("year,"))
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), dtype=str, keep_default_na=False)
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]
    df.columns = [c.lower() for c in df.columns]
    df = df[df["sexcat"].str.strip() == "0"]                    # both sexes only
    df = df[[c for c in SAHIE_COLS]]
    return df.apply(lambda s: s.str.strip())


def load_raw(conn):
    with conn.cursor() as cur:
        for y in YEARS:
            t = time.time()
            df = read_sahie(y)
            copy_frame(cur, "raw.sahie", df)
            conn.commit()
            print(f"  raw.sahie {y}: {len(df):>8,} rows ({time.time() - t:.0f}s)")

        kff = pd.read_csv(RAW / "kff_expansion_status.csv", dtype=str, keep_default_na=False)
        copy_frame(cur, "raw.kff_expansion", kff)
        print(f"  raw.kff_expansion: {len(kff)} rows")

        rows = []
        for l in (RAW / "saipe_est13all.txt").read_text(encoding="latin-1").splitlines():
            rows.append({"state_fips": l[0:2], "county_fips": l[3:6].strip().zfill(3), "poverty_all_count": l[7:15].strip(),
                         "poverty_all_pct": l[34:38].strip(), "median_hh_income": l[133:139].strip(),
                         "area_name": l[193:238].strip(), "state_abbrev": l[239:241]})
        copy_frame(cur, "raw.saipe_2013", pd.DataFrame(rows))
        print(f"  raw.saipe_2013: {len(rows)} rows")

        keep = ["STATE", "COUNTY", "YEAR", "AGEGRP", "TOT_POP", "NHWA_MALE", "NHWA_FEMALE", "NHBA_MALE",
                "NHBA_FEMALE", "H_MALE", "H_FEMALE"]
        pop = pd.read_csv(RAW / "cc-est2019-alldata.csv", dtype=str, encoding="latin-1", usecols=keep)
        pop = pop[pop["YEAR"] == "6"].drop(columns="YEAR")      # YEAR 6 = July 1, 2013 estimate
        pop.columns = ["state_fips", "county_fips", "agegrp", "tot_pop", "nhwa_male", "nhwa_female",
                       "nhba_male", "nhba_female", "h_male", "h_female"]
        copy_frame(cur, "raw.population_2013", pop)
        print(f"  raw.population_2013: {len(pop):,} rows")

        rucc = pd.read_excel(RAW / "ruralurbancodes2013.xls", dtype=str)
        rucc.columns = ["fips", "state", "county_name", "population_2010", "rucc_2013", "description"]
        copy_frame(cur, "raw.rucc_2013", rucc.fillna(""))
        print(f"  raw.rucc_2013: {len(rucc):,} rows")
        conn.commit()


def main():
    start = time.time()
    ensure_database()
    with psycopg.connect(CONNINFO) as conn:
        if "--skip-raw" not in sys.argv:
            print("raw layer")
            run_sql_file(conn, "01a_schema_raw.sql")
            load_raw(conn)
        if "--raw-only" in sys.argv:
            return
        print("core layer")
        run_sql_file(conn, "01b_schema_core.sql")
        run_sql_file(conn, "02_transform.sql")
        print("analytics layer")
        run_sql_file(conn, "04_analytics_views.sql")
        for table in ["core.dim_state", "core.dim_county", "core.fact_county_coverage", "core.fact_state_coverage"]:
            n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"  {table:<28} {n:>10,} rows")
    print(f"done in {(time.time() - start) / 60:.1f} min")


if __name__ == "__main__":
    main()
