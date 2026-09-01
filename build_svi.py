import csv
import json

INPUT_FILE = "SVI_2022_US_COUNTY(1).csv"
OUTPUT_FILE = "county-svi.js"


def clean_rank(value):
    """
    CDC SVI percentile rankings should be between 0 and 1.
    Negative values are CDC sentinel values for unavailable data.
    """
    try:
        number = float(value)

        if 0 <= number <= 1:
            return number

        return None

    except (TypeError, ValueError):
        return None


county_svi = {}

with open(INPUT_FILE, "r", encoding="utf-8-sig", newline="") as csvfile:
    reader = csv.DictReader(csvfile)

    for row in reader:

        fips = str(row.get("FIPS", "")).strip().zfill(5)

        if len(fips) != 5 or not fips.isdigit():
            continue

        county_svi[fips] = {
            "county": row.get("COUNTY", "").strip(),
            "state": row.get("ST_ABBR", "").strip(),

            # Overall Social Vulnerability Index
            "overall": clean_rank(row.get("RPL_THEMES")),

            # Theme 1 — Socioeconomic Status
            "socioeconomic": clean_rank(row.get("RPL_THEME1")),

            # Theme 2 — Household Characteristics
            "household": clean_rank(row.get("RPL_THEME2")),

            # Theme 3 — Racial & Ethnic Minority Status
            "minority": clean_rank(row.get("RPL_THEME3")),

            # Theme 4 — Housing Type & Transportation
            "housingTransportation": clean_rank(row.get("RPL_THEME4"))
        }


with open(OUTPUT_FILE, "w", encoding="utf-8") as outfile:

    outfile.write(
        "// CDC/ATSDR Social Vulnerability Index (SVI) 2022 — County Level\n"
    )

    outfile.write(
        "// Generated from SVI_2022_US_COUNTY.csv\n"
    )

    outfile.write(
        "// Keys are 5-digit county FIPS/GEOID values.\n"
    )

    outfile.write("window.COUNTY_SVI = ")

    json.dump(
        county_svi,
        outfile,
        separators=(",", ":"),
        ensure_ascii=False
    )

    outfile.write(";\n")


print()
print("SVI build complete.")
print(f"Counties: {len(county_svi):,}")
print(f"Created: {OUTPUT_FILE}")
print()

# Quick validation
print("Autauga County test:")
print(json.dumps(county_svi.get("01001"), indent=2))