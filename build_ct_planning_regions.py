#!/usr/bin/env python3
"""
build_ct_planning_regions.py

Writes ct-planning-regions.json: Connecticut's 169 towns, grouped by county
and then by planning region.

Since 2022 the Census Bureau has used Connecticut's nine planning regions in
place of its eight counties. The CDC SVI 2022 and the FEMA National Risk
Index report Connecticut only by planning region (FIPS 09110 to 09190), while
FEMA declarations still name the eight counties (FIPS 09001 to 09015). A
county page therefore has no SVI or NRI row of its own;
gen-jurisdiction-pages.py uses this file to show the rows of the regions its
towns are in.

Source: the CT Data Collaborative's 2022 census block crosswalk, which gives
every census block's town, its county (2020 Census geography) and its
planning region (2022 Census geography), built from the Census Bureau's
TIGER/Line files. Town boundaries did not change between the two, so every
town lies in exactly one county and exactly one region; this script checks
that.

  https://github.com/CT-Data-Collaborative/2022-block-crosswalk
  file used: 2022blockcrosswalk.csv at commit
  026d683a09320de2dd0b6f3a771f0f4574cc8fcf (SHA-256
  8b7c7e60bc50f9d6dc3cbc7e2bcb8354f9e33ecd136e6f8574e9b197e55e2157)

Usage:
  python build_ct_planning_regions.py 2022blockcrosswalk.csv

Stdlib only.
"""

import argparse
import csv
import json
import sys

OUTPUT_FILE = "ct-planning-regions.json"
SOURCE_URL = "https://github.com/CT-Data-Collaborative/2022-block-crosswalk"
SOURCE_COMMIT = "026d683a09320de2dd0b6f3a771f0f4574cc8fcf"

EXPECTED_TOWNS = 169
EXPECTED_COUNTIES = 8
EXPECTED_REGIONS = 9


def short_region_name(name):
    """'Capitol Planning Region' -> 'Capitol', as the NRI writes it."""
    suffix = " Planning Region"
    return name[: -len(suffix)] if name.endswith(suffix) else name


def read_towns(path):
    """{town code: (town, county FIPS, county, region FIPS, region)} from
    the block crosswalk. Raises ValueError if a town is assigned to more than
    one county or region."""
    towns = {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = row["town_fips_2020"].strip()[-5:]
            if row["town_fips_2022"].strip()[-5:] != code:
                raise ValueError("town code changed between 2020 and 2022: %s" % row["town_name"])
            town = (
                row["town_name"].strip(),
                row["county_fips_2020"].strip().zfill(5),
                row["county_name"].strip(),
                row["ce_fips_2022"].strip().zfill(5),
                row["ce_name_2022"].strip(),
            )
            if towns.setdefault(code, town) != town:
                raise ValueError("town %s has blocks in two counties or regions: %r and %r"
                                 % (code, towns[code], town))
    return towns


def build(towns):
    counties = {}
    for _, (town, county_fips, county, region_fips, region) in sorted(towns.items()):
        entry = counties.setdefault(county_fips, {"name": county + " County", "towns": 0, "regions": {}})
        entry["towns"] += 1
        group = entry["regions"].setdefault(region_fips, {
            "fips": region_fips,
            "name": region,
            "short_name": short_region_name(region),
            "towns": [],
        })
        group["towns"].append(town)

    for entry in counties.values():
        for group in entry["regions"].values():
            group["towns"].sort()
        # The region holding most of the county's towns first.
        entry["regions"] = sorted(entry["regions"].values(), key=lambda g: (-len(g["towns"]), g["name"]))

    regions = {g["fips"] for entry in counties.values() for g in entry["regions"]}
    if (len(towns), len(counties), len(regions)) != (EXPECTED_TOWNS, EXPECTED_COUNTIES, EXPECTED_REGIONS):
        raise ValueError("expected %d towns, %d counties and %d regions; found %d, %d and %d"
                         % (EXPECTED_TOWNS, EXPECTED_COUNTIES, EXPECTED_REGIONS,
                            len(towns), len(counties), len(regions)))

    return {
        "source": "CT Data Collaborative, 2022 census block crosswalk (Census TIGER/Line 2020 and 2022)",
        "source_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "counties": dict(sorted(counties.items())),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("crosswalk", help="path to 2022blockcrosswalk.csv")
    parser.add_argument("--out", default=OUTPUT_FILE)
    args = parser.parse_args(argv)

    data = build(read_towns(args.crosswalk))

    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
        handle.write("\n")

    for fips, entry in data["counties"].items():
        print("%s %s: %d towns in %s" % (
            fips, entry["name"], entry["towns"],
            ", ".join("%s (%d)" % (g["short_name"], len(g["towns"])) for g in entry["regions"])))
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
