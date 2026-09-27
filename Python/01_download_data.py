"""Download every source file used by the project and record URL, size and SHA-256 in Data/raw/manifest.json.

Sources (all public, no API key needed):
  - Census SAHIE (Small Area Health Insurance Estimates), county and state, 2008-2023
  - KFF tracker of state Medicaid expansion decisions (the table embedded in the page as CSV)
  - Census SAIPE 2013 county poverty and median household income (baseline controls)
  - Census population estimates by county, age, sex, race and Hispanic origin (2010-2019 vintage, used for 2013)
  - USDA ERS Rural-Urban Continuum Codes 2013
  - County boundaries (GeoJSON, FIPS keyed) for maps

Downloads use curl (resumable, retried); Python requests was much slower on Census/CMS servers in earlier projects.
"""
import csv
import hashlib
import io
import json
import re
import subprocess
import urllib.parse
from datetime import date
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "Data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

SAHIE = "https://www2.census.gov/programs-surveys/sahie/datasets/time-series/estimates-acs/sahie-{y}-csv.zip"
FILES = {f"sahie-{y}-csv.zip": SAHIE.format(y=y) for y in range(2008, 2024)}
FILES.update({
    "kff_expansion_status.html": "https://www.kff.org/affordable-care-act/issue-brief/status-of-state-medicaid-expansion-decisions/",
    "saipe_est13all.txt": "https://www2.census.gov/programs-surveys/saipe/datasets/2013/2013-state-and-county/est13all.txt",
    "cc-est2019-alldata.csv": "https://www2.census.gov/programs-surveys/popest/datasets/2010-2019/counties/asrh/cc-est2019-alldata.csv",
    "ruralurbancodes2013.xls": "https://ers.usda.gov/sites/default/files/_laserfiche/DataFiles/53251/ruralurbancodes2013.xls",
    "geojson-counties-fips.json": "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json",
})


def curl(url, out):
    subprocess.run(["curl", "-L", "--fail", "--retry", "5", "--silent", "--show-error", "-A", "Mozilla/5.0",
                    "-o", str(out), url], check=True)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kff_table(html_path):
    """KFF embeds its map data as a data:text/csv URI; pull it out and save a clean CSV."""
    t = html_path.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'data:text/csv;charset=utf-8,(State%2CState%20Abbrev\.%2CExpansion%20Status[^"]+)', t)
    if not m:
        raise RuntimeError("KFF page layout changed: embedded CSV not found")
    rows = list(csv.reader(io.StringIO(urllib.parse.unquote(m.group(1)))))
    out = RAW / "kff_expansion_status.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["state_name", "state_abbrev", "expansion_status", "implementation_note"])
        for r in rows[1:]:
            w.writerow([r[0].strip(), r[1].strip(" *"), r[2].strip(), " ".join(r[3].split())])
    return out


def main():
    manifest = {"downloaded": str(date.today()), "files": {}}
    for name, url in FILES.items():
        out = RAW / name
        if not out.exists() or out.stat().st_size == 0 or name.endswith(".html"):
            print("downloading", name)
            curl(url, out)
        manifest["files"][name] = {"url": url, "bytes": out.stat().st_size, "sha256": sha256(out)}
    k = kff_table(RAW / "kff_expansion_status.html")
    manifest["files"][k.name] = {"url": FILES["kff_expansion_status.html"] + " (embedded CSV)",
                                 "bytes": k.stat().st_size, "sha256": sha256(k)}
    (RAW / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"{len(manifest['files'])} files, {sum(v['bytes'] for v in manifest['files'].values()) / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
