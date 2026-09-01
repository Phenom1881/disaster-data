import csv
import json

INPUT_FILE = "NRI_Table_Counties.csv"
OUTPUT_FILE = "county-nri.js"

HAZARDS = {
    "AVLN": "Avalanche",
    "CFLD": "Coastal Flooding",
    "CWAV": "Cold Wave",
    "DRGT": "Drought",
    "ERQK": "Earthquake",
    "HAIL": "Hail",
    "HWAV": "Heat Wave",
    "HRCN": "Hurricane",
    "ISTM": "Ice Storm",
    "IFLD": "Inland Flooding",
    "LNDS": "Landslide",
    "LTNG": "Lightning",
    "SWND": "Strong Wind",
    "TRND": "Tornado",
    "TSUN": "Tsunami",
    "VLCN": "Volcanic Activity",
    "WFIR": "Wildfire",
    "WNTW": "Winter Weather",
}


def number(value):
    """Convert FEMA numeric values to numbers; blanks become None."""
    if value is None or str(value).strip() == "":
        return None

    try:
        return float(value)
    except ValueError:
        return None


county_nri = {}

with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as f:
    reader = csv.DictReader(f)

    for row in reader:
        # FEMA stores some FIPS codes without the leading zero.
        # Example: 1001 becomes 01001.
        fips = str(row["STCOFIPS"]).strip().split(".")[0].zfill(5)

        hazards = {}

        for prefix in HAZARDS:
            hazards[prefix] = {
                "score": number(row.get(f"{prefix}_RISKS")),
                "rating": row.get(f"{prefix}_RISKR") or None,
            }

        county_nri[fips] = {
            "county": row["COUNTY"],
            "state": row["STATEABBRV"],

            "riskScore": number(row["RISK_SCORE"]),
            "riskRating": row["RISK_RATNG"] or None,

            "ealValue": number(row["EAL_VALT"]),
            "ealScore": number(row["EAL_SCORE"]),
            "ealRating": row["EAL_RATNG"] or None,

            "soviScore": number(row["SOVI_SCORE"]),
            "soviRating": row["SOVI_RATNG"] or None,

            "reslScore": number(row["RESL_SCORE"]),
            "reslRating": row["RESL_RATNG"] or None,

            "hazards": hazards,

            "version": row["NRI_VER"] or None,
        }


with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("// FEMA National Risk Index — County Level\n")
    f.write("// Generated from NRI_Table_Counties.csv\n")
    f.write("// Keys are 5-digit county FIPS/GEOID values.\n")

    f.write("window.NRI_HAZARDS = ")

    json.dump(
        HAZARDS,
        f,
        ensure_ascii=False,
        separators=(",", ":")
    )

    f.write(";\n")

    f.write("window.COUNTY_NRI = ")

    json.dump(
        county_nri,
        f,
        ensure_ascii=False,
        separators=(",", ":")
    )

    f.write(";\n")


print(f"Created {OUTPUT_FILE}")
print(f"County records: {len(county_nri):,}")
print(f"Hazards: {len(HAZARDS)}")