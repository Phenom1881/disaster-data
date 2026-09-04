"""Resolve NCEI county/zone areas to Virginia counties and independent cities.

The strongest key is NCEI's CZ_FIPS when CZ_TYPE is ``Z``.  It maps directly
to the NWS crosswalk's three-digit ZONE field.  Name matching is retained as a
fallback for older summary files that do not contain CZ_TYPE and CZ_FIPS.

The output includes explicit audit columns so a successful same-name mapping
cannot be confused with an unresolved pass-through:

  resolution_status, resolved_zone_id, resolved_zone_name, resolved_counties

Usage:
  python resolve_zones_to_counties.py \
    --input eo_storm_severity_summary.csv \
    --zone-file bp16ap26.dbx \
    --out severity_resolved.csv
"""

import argparse
import re

import pandas as pd


ZONE_COLUMNS = [
    "STATE",
    "ZONE",
    "CWA",
    "NAME",
    "STATE_ZONE",
    "COUNTY",
    "FIPS",
    "TIME_ZONE",
    "FE_AREA",
    "LAT",
    "LON",
]


def normalize_zone_code(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return f"{int(float(text)):03d}"
    except ValueError:
        digits = re.sub(r"\D", "", text)
        return digits.zfill(3) if digits else None


def normalize_name(value):
    text = str(value).strip().upper()
    # NCEI abbreviates "Central" as "CST" in at least one Virginia name.
    text = re.sub(r"\bCST\b", "CENTRAL", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def make_record(group, state):
    first = group.iloc[0]
    zone = normalize_zone_code(first["ZONE"])
    counties = sorted(
        {
            str(value).strip()
            for value in group["COUNTY"]
            if not pd.isna(value) and str(value).strip()
        }
    )
    return {
        "zone_code": zone,
        "zone_id": f"{state.upper()}{zone}",
        "zone_name": str(first["NAME"]).strip(),
        "counties": counties,
    }


def load_zone_crosswalk(zone_file, state="VA"):
    frame = pd.read_csv(
        zone_file,
        sep="|",
        names=ZONE_COLUMNS,
        header=None,
        dtype=str,
        keep_default_na=False,
    )
    if len(frame) and frame.iloc[0]["STATE"].strip().upper() == "STATE":
        frame = frame.iloc[1:]
    frame = frame[frame["STATE"].str.strip().str.upper() == state.upper()].copy()
    frame["ZONE"] = frame["ZONE"].apply(normalize_zone_code)

    records = [
        make_record(group, state)
        for _, group in frame.groupby("ZONE", sort=False, dropna=False)
    ]
    by_code = {record["zone_code"]: record for record in records}

    by_name = {}
    by_component = {}
    for record in records:
        by_name.setdefault(normalize_name(record["zone_name"]), []).append(record)
        for component in re.split(r"/", record["zone_name"]):
            by_component.setdefault(normalize_name(component), []).append(record)

    return {"by_code": by_code, "by_name": by_name, "by_component": by_component}


def unique_candidate(records):
    if not records:
        return None
    unique = {record["zone_id"]: record for record in records}
    return next(iter(unique.values())) if len(unique) == 1 else None


def resolved_result(record, status):
    return pd.Series(
        {
            "resolution_status": status,
            "resolved_zone_id": record["zone_id"],
            "resolved_zone_name": record["zone_name"],
            "resolved_counties": "; ".join(record["counties"]),
        }
    )


def resolve_row(row, indexes):
    original_name = str(row.get("CZ_NAME", "")).strip()
    cz_type = str(row.get("CZ_TYPE", "")).strip().upper()
    area_type = str(row.get("area_type", "")).strip().lower()
    zone_record = None

    # An explicit county record is already at the requested geography.
    if cz_type == "C" or "county/county-equivalent" in area_type:
        return pd.Series(
            {
                "resolution_status": "county_passthrough",
                "resolved_zone_id": "",
                "resolved_zone_name": "",
                "resolved_counties": original_name,
            }
        )

    zone_code = normalize_zone_code(row.get("CZ_FIPS"))
    if zone_code and (cz_type == "Z" or "forecast zone" in area_type):
        zone_record = indexes["by_code"].get(zone_code)
        if zone_record:
            return resolved_result(zone_record, "matched_zone_code")

    normalized = normalize_name(original_name)
    zone_record = unique_candidate(indexes["by_name"].get(normalized, []))
    if zone_record:
        return resolved_result(zone_record, "matched_normalized_name")

    # Handles legacy NCEI labels such as ARLINGTON for the modern zone name
    # Arlington/Falls Church/Alexandria.
    zone_record = unique_candidate(indexes["by_component"].get(normalized, []))
    if zone_record:
        return resolved_result(zone_record, "matched_zone_component")

    status = "marine_or_other_passthrough" if cz_type == "M" else "unresolved"
    return pd.Series(
        {
            "resolution_status": status,
            "resolved_zone_id": "",
            "resolved_zone_name": "",
            "resolved_counties": original_name,
        }
    )


def main():
    parser = argparse.ArgumentParser(description="Resolve NCEI areas to counties")
    parser.add_argument("--input", required=True, help="CSV containing CZ_NAME")
    parser.add_argument("--zone-file", required=True, help="NWS bp*.dbx file")
    parser.add_argument("--out", required=True)
    parser.add_argument("--state", default="VA")
    args = parser.parse_args()

    indexes = load_zone_crosswalk(args.zone_file, args.state)
    frame = pd.read_csv(args.input, dtype={"CZ_FIPS": str})
    if "CZ_NAME" not in frame.columns:
        raise ValueError("Input CSV must contain a CZ_NAME column")

    resolution = frame.apply(lambda row: resolve_row(row, indexes), axis=1)
    output = pd.concat([frame, resolution], axis=1)
    output.to_csv(args.out, index=False)
    print(f"Wrote {len(output)} resolved rows to {args.out}")

    print("\nResolution status:")
    for status, count in output["resolution_status"].value_counts().items():
        print(f"  {status}: {count}")

    unresolved = output[output["resolution_status"] == "unresolved"]
    if unresolved.empty:
        print("\nAll forecast-zone names resolved.")
    else:
        print(f"\n{unresolved['CZ_NAME'].nunique()} unresolved CZ_NAME values:")
        for name in sorted(set(unresolved["CZ_NAME"])):
            print(f"  {name}")


if __name__ == "__main__":
    main()
