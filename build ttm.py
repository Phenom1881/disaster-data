#!/usr/bin/env python3
"""
build_ttm.py
Time to Money: builds the analytic table for the FEMA Public Assistance
obligation timing study.

Unit of analysis: one row per county-disaster pair where PA was declared.
Event: earliest obligation date for that county under that disaster.
Censoring: counties with no obligation as of the snapshot date are right
censored at snapshot date minus declaration date.

This script does data construction only. No modeling. It prints the
diagnostics that decide whether the design survives contact with the data.

Usage:
    python build_ttm.py --start-year 2015 --outdir ttm

Requires: requests, pandas
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone

import pandas as pd
import requests

BASE = "https://www.fema.gov/api/open"
PAGE = 5000
PAUSE = 0.4

FEMA_REGION = {
    "CT": 1, "ME": 1, "MA": 1, "NH": 1, "RI": 1, "VT": 1,
    "NJ": 2, "NY": 2, "PR": 2, "VI": 2,
    "DE": 3, "DC": 3, "MD": 3, "PA": 3, "VA": 3, "WV": 3,
    "AL": 4, "FL": 4, "GA": 4, "KY": 4, "MS": 4, "NC": 4, "SC": 4, "TN": 4,
    "IL": 5, "IN": 5, "MI": 5, "MN": 5, "OH": 5, "WI": 5,
    "AR": 6, "LA": 6, "NM": 6, "OK": 6, "TX": 6,
    "IA": 7, "KS": 7, "MO": 7, "NE": 7,
    "CO": 8, "MT": 8, "ND": 8, "SD": 8, "UT": 8, "WY": 8,
    "AZ": 9, "CA": 9, "HI": 9, "NV": 9, "AS": 9, "GU": 9, "MP": 9,
    "FM": 9, "MH": 9, "PW": 9,
    "AK": 10, "ID": 10, "OR": 10, "WA": 10,
}

PERMANENT_WORK = {"C", "D", "E", "F", "G"}


def fetch(dataset, version, select, filt=None, page=PAGE):
    """Page through an OpenFEMA endpoint and return a list of records."""
    url = "%s/v%d/%s" % (BASE, version, dataset)
    rows, skip = [], 0
    while True:
        params = {
            "$select": ",".join(select),
            "$top": page,
            "$skip": skip,
            "$metadata": "off",
        }
        if filt:
            params["$filter"] = filt
        r = requests.get(url, params=params, timeout=180)
        r.raise_for_status()
        payload = r.json()
        batch = None
        for value in payload.values():
            if isinstance(value, list):
                batch = value
                break
        if batch is None:
            raise RuntimeError("no record list in response for %s" % dataset)
        rows.extend(batch)
        sys.stderr.write("  %s: %d rows\n" % (dataset, len(rows)))
        if len(batch) < page:
            return rows
        skip += page
        time.sleep(PAUSE)


def snapshot(rows, dataset, outdir, stamp, manifest):
    """Write the raw pull to disk and record its hash so a skeptic can rerun."""
    raw = os.path.join(outdir, "raw")
    os.makedirs(raw, exist_ok=True)
    path = os.path.join(raw, "%s_%s.json.gz" % (dataset, stamp))
    blob = json.dumps(rows, sort_keys=True).encode("utf-8")
    with gzip.open(path, "wb") as fh:
        fh.write(blob)
    manifest[dataset] = {
        "file": os.path.basename(path),
        "rows": len(rows),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "pulled": stamp,
    }
    return path


def norm_county(name):
    """Return (normalized name, is_independent_city)."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return None, False
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper().strip()
    city = False
    if "(CITY)" in s:
        city = True
        s = s.replace("(CITY)", " ")
    for paren in ("(COUNTY)", "(PARISH)", "(BOROUGH)", "(MUNICIPALITY)"):
        s = s.replace(paren, " ")
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("CITY OF "):
        city = True
        s = s[8:]
    if s.startswith("CITY AND BOROUGH OF "):
        s = s[20:]
    if s.startswith("MUNICIPALITY OF "):
        s = s[16:]
    for suffix in (
        " CITY AND BOROUGH", " CENSUS AREA", " MUNICIPALITY", " MUNICIPIO",
        " COUNTY", " PARISH", " BOROUGH",
    ):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if s.endswith(" CITY"):
        city = True
        s = s[:-5]
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return (s or None), city


def build(start_year, outdir):
    os.makedirs(outdir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    snap_date = pd.Timestamp(datetime.now(timezone.utc).date())
    cutoff = "%d-01-01T00:00:00.000Z" % start_year
    manifest = {"snapshotDate": stamp, "startYear": start_year}

    sys.stderr.write("pulling declarations\n")
    dds = fetch(
        "DisasterDeclarationsSummaries", 2,
        ["disasterNumber", "state", "declarationDate", "incidentBeginDate",
         "incidentEndDate", "incidentType", "declarationType", "declarationTitle",
         "fipsStateCode", "fipsCountyCode", "designatedArea",
         "paProgramDeclared", "iaProgramDeclared", "ihProgramDeclared"],
        "declarationType eq 'DR' and declarationDate ge '%s'" % cutoff,
    )
    snapshot(dds, "DisasterDeclarationsSummaries", outdir, stamp, manifest)

    sys.stderr.write("pulling request dates\n")
    web = fetch(
        "FemaWebDisasterDeclarations", 1,
        ["disasterNumber", "declarationRequestDate", "declarationDate"],
        "declarationDate ge '%s'" % cutoff,
    )
    snapshot(web, "FemaWebDisasterDeclarations", outdir, stamp, manifest)

    sys.stderr.write("pulling obligations\n")
    pa = fetch(
        "PublicAssistanceGrantAwardActivities", 2,
        ["disasterNumber", "stateAbbreviation", "county", "applicantId",
         "pnpStatus", "damageCategoryCode", "federalShareObligated",
         "dateObligated", "pwNumber", "versionNumber", "fundingStatus",
         "eligibilityStatus", "declarationDate"],
        "declarationDate ge '%s'" % cutoff,
    )
    snapshot(pa, "PublicAssistanceGrantAwardActivities", outdir, stamp, manifest)

    with open(os.path.join(outdir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)

    # ---- risk set -------------------------------------------------------
    d = pd.DataFrame(dds)
    for col in ("declarationDate", "incidentBeginDate", "incidentEndDate"):
        d[col] = pd.to_datetime(d[col], errors="coerce", utc=True).dt.tz_localize(None)
    d["paProgramDeclared"] = d["paProgramDeclared"].astype(str).isin(["1", "True", "true"])
    d = d[d["paProgramDeclared"]]
    d = d[d["fipsCountyCode"].astype(str).str.zfill(3) != "000"]
    d["countyFips"] = (
        d["fipsStateCode"].astype(str).str.zfill(2)
        + d["fipsCountyCode"].astype(str).str.zfill(3)
    )
    d[["normArea", "isCity"]] = d["designatedArea"].apply(
        lambda v: pd.Series(norm_county(v))
    )
    d = d.dropna(subset=["normArea"])
    d = d.drop_duplicates(subset=["disasterNumber", "countyFips"])
    d["region"] = d["state"].map(FEMA_REGION)
    d["iaDeclared"] = d["iaProgramDeclared"].astype(str).isin(["1", "True", "true"])

    # ---- request date ---------------------------------------------------
    w = pd.DataFrame(web)
    w["declarationRequestDate"] = pd.to_datetime(
        w["declarationRequestDate"], errors="coerce", utc=True
    ).dt.tz_localize(None)
    w = w.groupby("disasterNumber", as_index=False)["declarationRequestDate"].min()
    d = d.merge(w, on="disasterNumber", how="left")

    # ---- queue congestion ----------------------------------------------
    ev = d[["disasterNumber", "state", "region", "declarationDate"]].drop_duplicates(
        subset=["disasterNumber"]
    )
    nat, reg = [], []
    for _, row in ev.iterrows():
        lo = row["declarationDate"] - pd.Timedelta(days=90)
        window = ev[
            (ev["declarationDate"] < row["declarationDate"])
            & (ev["declarationDate"] >= lo)
        ]
        nat.append(len(window))
        reg.append(len(window[window["region"] == row["region"]]))
    ev = ev.assign(priorDecl90dNational=nat, priorDecl90dRegion=reg)
    d = d.merge(
        ev[["disasterNumber", "priorDecl90dNational", "priorDecl90dRegion"]],
        on="disasterNumber", how="left",
    )

    # ---- events ---------------------------------------------------------
    p = pd.DataFrame(pa)
    p["dateObligated"] = pd.to_datetime(
        p["dateObligated"], errors="coerce", utc=True
    ).dt.tz_localize(None)
    p = p[p["fundingStatus"].astype(str).str.upper().str.startswith("O")]
    p = p.dropna(subset=["dateObligated"])
    p["federalShareObligated"] = pd.to_numeric(
        p["federalShareObligated"], errors="coerce"
    ).fillna(0.0)
    p[["normArea", "isCity"]] = p["county"].apply(
        lambda v: pd.Series(norm_county(v))
    )
    p = p.rename(columns={"stateAbbreviation": "state"})

    total_ob = len(p)
    p_named = p.dropna(subset=["normArea"])
    no_county = total_ob - len(p_named)

    exact = d[["disasterNumber", "state", "normArea", "isCity", "countyFips"]]
    m = p_named.merge(exact, on=["disasterNumber", "state", "normArea", "isCity"],
                      how="left")

    loose = d.groupby(["disasterNumber", "state", "normArea"])["countyFips"].agg(
        ["first", "nunique"]
    ).reset_index()
    loose = loose[loose["nunique"] == 1][
        ["disasterNumber", "state", "normArea", "first"]
    ].rename(columns={"first": "fipsLoose"})
    m = m.merge(loose, on=["disasterNumber", "state", "normArea"], how="left")
    m["countyFips"] = m["countyFips"].fillna(m["fipsLoose"])
    unmatched = int(m["countyFips"].isna().sum())
    m = m.dropna(subset=["countyFips"])

    first = m.groupby(["disasterNumber", "countyFips"]).agg(
        firstObligationDate=("dateObligated", "min"),
        obligatedPWs=("pwNumber", "nunique"),
        federalShareObligated=("federalShareObligated", "sum"),
    ).reset_index()

    perm = m[m["damageCategoryCode"].astype(str).str.upper().str[:1].isin(PERMANENT_WORK)]
    perm = perm.groupby(["disasterNumber", "countyFips"]).agg(
        firstPermanentObligationDate=("dateObligated", "min"),
    ).reset_index()

    out = d.merge(first, on=["disasterNumber", "countyFips"], how="left")
    out = out.merge(perm, on=["disasterNumber", "countyFips"], how="left")

    # ---- durations ------------------------------------------------------
    day = lambda a, b: (a - b).dt.days
    out["daysIncidentToRequest"] = day(out["declarationRequestDate"], out["incidentBeginDate"])
    out["daysRequestToDeclaration"] = day(out["declarationDate"], out["declarationRequestDate"])
    out["daysIncidentToDeclaration"] = day(out["declarationDate"], out["incidentBeginDate"])
    out["daysDeclToFirstObligation"] = day(out["firstObligationDate"], out["declarationDate"])
    out["daysDeclToFirstPermanent"] = day(out["firstPermanentObligationDate"], out["declarationDate"])
    out["eventObserved"] = out["firstObligationDate"].notna().astype(int)
    out["snapshotDate"] = snap_date
    out["timeToEventDays"] = out["daysDeclToFirstObligation"].fillna(
        day(out["snapshotDate"], out["declarationDate"])
    ).astype(int)
    out["eventObservedPermanent"] = out["firstPermanentObligationDate"].notna().astype(int)
    out["timeToPermanentDays"] = out["daysDeclToFirstPermanent"].fillna(
        day(out["snapshotDate"], out["declarationDate"])
    ).astype(int)
    out["obligatedPWs"] = out["obligatedPWs"].fillna(0).astype(int)
    out["federalShareObligated"] = out["federalShareObligated"].fillna(0.0)

    keep = [
        "disasterNumber", "declarationTitle", "state", "region", "countyFips",
        "designatedArea", "incidentType", "iaDeclared",
        "incidentBeginDate", "incidentEndDate", "declarationRequestDate",
        "declarationDate", "snapshotDate",
        "daysIncidentToRequest", "daysRequestToDeclaration",
        "daysIncidentToDeclaration",
        "firstObligationDate", "daysDeclToFirstObligation",
        "eventObserved", "timeToEventDays",
        "firstPermanentObligationDate", "daysDeclToFirstPermanent",
        "eventObservedPermanent", "timeToPermanentDays",
        "obligatedPWs", "federalShareObligated",
        "priorDecl90dNational", "priorDecl90dRegion",
    ]
    out = out[keep].sort_values(["disasterNumber", "countyFips"])
    path = os.path.join(outdir, "ttm_analytic.csv")
    out.to_csv(path, index=False)

    # ---- diagnostics ----------------------------------------------------
    n = len(out)
    obs = int(out["eventObserved"].sum())
    med = out.loc[out["eventObserved"] == 1, "daysDeclToFirstObligation"].median()
    permobs = int(out["eventObservedPermanent"].sum())
    print("")
    print("snapshot            %s" % stamp)
    print("start year          %d" % start_year)
    print("risk set rows       %d county-disaster pairs" % n)
    print("observed events     %d (%.1f%%)" % (obs, 100.0 * obs / max(n, 1)))
    print("censored            %d (%.1f%%)" % (n - obs, 100.0 * (n - obs) / max(n, 1)))
    print("crude median days   %.0f (declaration to first obligation, observed only)"
          % (med if pd.notna(med) else float("nan")))
    print("permanent work obs  %d (%.1f%%)" % (permobs, 100.0 * permobs / max(n, 1)))
    print("request date known  %.1f%% of pairs"
          % (100.0 * out["declarationRequestDate"].notna().mean()))
    print("")
    print("join quality")
    print("  obligation rows            %d" % total_ob)
    print("  no county on record        %d (%.1f%%)"
          % (no_county, 100.0 * no_county / max(total_ob, 1)))
    print("  county named but unmatched %d (%.1f%%)"
          % (unmatched, 100.0 * unmatched / max(total_ob, 1)))
    print("")
    print("wrote %s" % path)
    print("wrote %s" % os.path.join(outdir, "manifest.json"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--outdir", default="ttm")
    args = ap.parse_args()
    build(args.start_year, args.outdir)
