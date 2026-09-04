"""Cross-reference Virginia emergency declarations with NCEI Storm Events.

For each declaration, this script finds Virginia events whose begin date falls
within a configurable window around the signing date.  NCEI can report an event
against a county/county-equivalent (CZ_TYPE=C), an NWS public forecast zone
(CZ_TYPE=Z), or a marine zone (CZ_TYPE=M).  The output preserves that distinction
so a forecast zone is not silently presented as a legal locality.

Required input columns:
  eo_number,event_description,date_signed

Historical inventories may also supply declaration_id, governor, and
archive_record_url.  Those fields are retained in both outputs.  A stable
declaration_id is important because EO numbers repeat across administrations.

Usage:
  python eo_storm_join.py --declarations declarations_for_join.csv --out matches.csv
"""

import argparse
import gzip
import io
import re
import sys
from datetime import timedelta

import pandas as pd
import requests


INDEX_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
FILE_PATTERN = re.compile(
    r"StormEvents_details-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz"
)
DEFAULT_WINDOW_DAYS = 3

AREA_TYPE_LABELS = {
    "C": "county/county-equivalent",
    "Z": "NWS forecast zone",
    "M": "marine zone",
}

DECLARATION_COLUMNS = [
    "declaration_id",
    "eo_number",
    "governor",
    "event_description",
    "date_signed",
    "archive_record_url",
]

EVENT_COLUMNS = [
    "EVENT_ID",
    "EPISODE_ID",
    "BEGIN_DATE_TIME",
    "END_DATE_TIME",
    "CZ_TYPE",
    "area_type",
    "CZ_FIPS",
    "CZ_NAME",
    "EVENT_TYPE",
    "MAGNITUDE",
    "MAGNITUDE_TYPE",
    "DEATHS_DIRECT",
    "INJURIES_DIRECT",
    "DAMAGE_PROPERTY",
    "DAMAGE_CROPS",
    "SOURCE",
    "EPISODE_NARRATIVE",
    "EVENT_NARRATIVE",
]

HAZARD_EVENT_TYPES = {
    "drought": {"Drought"},
    "fire": {"Wildfire", "Drought", "High Wind", "Strong Wind"},
    "flood": {
        "Flash Flood",
        "Flood",
        "Coastal Flood",
        "Lakeshore Flood",
        "Heavy Rain",
        "Debris Flow",
        "Landslide",
    },
    "severe_storm": {
        "Tornado",
        "Thunderstorm Wind",
        "Hail",
        "Lightning",
        "Heavy Rain",
        "Flash Flood",
    },
    "tropical": {
        "Hurricane (Typhoon)",
        "Tropical Storm",
        "Storm Surge/Tide",
        "Coastal Flood",
        "High Wind",
        "Strong Wind",
        "Flash Flood",
        "Flood",
        "Heavy Rain",
        "Tornado",
        "Thunderstorm Wind",
    },
    "wind": {"High Wind", "Strong Wind", "Thunderstorm Wind"},
    "winter": {
        "Winter Storm",
        "Winter Weather",
        "Ice Storm",
        "Heavy Snow",
        "Blizzard",
        "Sleet",
        "Cold/Wind Chill",
        "Extreme Cold/Wind Chill",
        "Frost/Freeze",
        "High Wind",
        "Strong Wind",
    },
}

_year_cache = {}


def get_latest_filenames_by_year():
    """Return the most recently certified details filename for each year."""
    response = requests.get(INDEX_URL, timeout=30)
    response.raise_for_status()
    latest = {}
    for match in FILE_PATTERN.finditer(response.text):
        year, certification_date = match.group(1), match.group(2)
        filename = match.group(0)
        if year not in latest or certification_date > latest[year][1]:
            latest[year] = (filename, certification_date)
    return {year: filename for year, (filename, _) in latest.items()}


def download_year_details(filename):
    response = requests.get(INDEX_URL + filename, timeout=60)
    response.raise_for_status()
    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as archive:
        frame = pd.read_csv(archive, low_memory=False)
    # NCEI stores values such as "24-JAN-26 21:00:00".
    frame["BEGIN_DATE_TIME"] = pd.to_datetime(
        frame["BEGIN_DATE_TIME"], format="%d-%b-%y %H:%M:%S", errors="coerce"
    )
    frame["END_DATE_TIME"] = pd.to_datetime(
        frame["END_DATE_TIME"], format="%d-%b-%y %H:%M:%S", errors="coerce"
    )
    return frame


def get_year_events(year, filenames, state):
    year_text = str(year)
    cache_key = (year_text, state.upper())
    if cache_key in _year_cache:
        return _year_cache[cache_key]
    if year_text not in filenames:
        print(f"No NCEI file published yet for {year_text}.", file=sys.stderr)
        _year_cache[cache_key] = pd.DataFrame()
        return _year_cache[cache_key]
    frame = download_year_details(filenames[year_text])
    # Historical runs span more than two decades.  Retaining only the selected
    # state's records keeps the cache small while still downloading each year once.
    frame = frame[frame["STATE"].fillna("").str.upper() == state.upper()].copy()
    _year_cache[cache_key] = frame
    return _year_cache[cache_key]


def compatible_event_types(description):
    """Infer plausible NCEI event types from an executive-order title."""
    text = str(description).lower()
    categories = []
    if "drought" in text:
        categories.append("drought")
    if re.search(r"\b(?:wildfire|forest fire|brush fire)s?\b", text):
        categories.append("fire")
    if re.search(r"\b(?:flood|flooding|rainfall|heavy rain|mudslide|landslide)", text):
        categories.append("flood")
    if re.search(r"\b(?:hurricane|tropical storm|tropical depression|tropical weather)", text):
        categories.append("tropical")
    if re.search(r"\b(?:winter|snow|ice|icing|sleet|blizzard|cold|freeze|freezing)", text):
        categories.append("winter")
    if re.search(r"\b(?:tornado|severe storm|severe weather|thunderstorm|hail|lightning)", text):
        categories.append("severe_storm")
    if re.search(r"\b(?:wind|winds|wind damage)", text):
        categories.append("wind")
    allowed = set()
    for category in categories:
        allowed.update(HAZARD_EVENT_TYPES[category])
    return allowed


def events_near_date(
    state,
    center_date,
    window_days,
    filenames,
    description="",
    hazard_filter=True,
):
    start = center_date - timedelta(days=window_days)
    end = center_date + timedelta(days=window_days)
    frames = [
        get_year_events(year, filenames, state)
        for year in range(start.year, end.year + 1)
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()
    events = pd.concat(frames, ignore_index=True)
    mask = (
        (events["BEGIN_DATE_TIME"].dt.date >= start)
        & (events["BEGIN_DATE_TIME"].dt.date <= end)
    )
    matches = events.loc[mask]
    allowed_types = compatible_event_types(description) if hazard_filter else set()
    if allowed_types:
        matches = matches[matches["EVENT_TYPE"].isin(allowed_types)]
    return matches


def parse_damage(value):
    """Convert NCEI damage values such as 200K or 1.5M to dollars."""
    if pd.isna(value):
        return 0.0
    text = str(value).strip().upper()
    if not text:
        return 0.0
    multipliers = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}
    multiplier = multipliers.get(text[-1], 1.0)
    if text[-1] in multipliers:
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return 0.0


def build_severity_summary(result):
    """Aggregate reported human and monetary impacts by NCEI area."""
    frame = result.copy()
    frame["damage_property_usd"] = frame["DAMAGE_PROPERTY"].apply(parse_damage)
    frame["damage_crops_usd"] = frame["DAMAGE_CROPS"].apply(parse_damage)
    declaration_fields = [
        column for column in DECLARATION_COLUMNS if column in frame.columns
    ]
    summary = (
        frame.groupby(
            declaration_fields
            + [
                "CZ_TYPE",
                "area_type",
                "CZ_FIPS",
                "CZ_NAME",
            ],
            dropna=False,
        )
        .agg(
            deaths_direct=("DEATHS_DIRECT", "sum"),
            injuries_direct=("INJURIES_DIRECT", "sum"),
            damage_property_usd=("damage_property_usd", "sum"),
            damage_crops_usd=("damage_crops_usd", "sum"),
            event_types=("EVENT_TYPE", lambda values: ", ".join(sorted(set(values)))),
            event_count=("EVENT_TYPE", "count"),
        )
        .reset_index()
    )
    summary["total_damage_usd"] = (
        summary["damage_property_usd"] + summary["damage_crops_usd"]
    )
    return summary.sort_values(
        ["date_signed", "declaration_id", "deaths_direct", "injuries_direct", "total_damage_usd"],
        ascending=[True, True, False, False, False],
    )


def validate_declarations(frame):
    required = {"eo_number", "event_description", "date_signed"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError("Declaration CSV is missing: " + ", ".join(missing))


def main():
    parser = argparse.ArgumentParser(
        description="Match Virginia declarations to NCEI Storm Events"
    )
    parser.add_argument("--declarations", required=True)
    parser.add_argument("--state", default="VIRGINIA")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--out", default="eo_storm_matches.csv")
    parser.add_argument("--severity-out", default="eo_storm_severity_summary.csv")
    parser.add_argument(
        "--no-hazard-filter",
        action="store_true",
        help="match every NCEI event in the date window, including unrelated hazards",
    )
    parser.add_argument(
        "--print-all-areas",
        action="store_true",
        help="print every matched area; normally the complete list stays in the CSV",
    )
    args = parser.parse_args()

    declarations = pd.read_csv(args.declarations)
    validate_declarations(declarations)
    declarations["date_signed"] = pd.to_datetime(
        declarations["date_signed"], format="%Y-%m-%d", errors="raise"
    ).dt.date
    if "declaration_id" not in declarations.columns:
        declarations["declaration_id"] = (
            declarations["eo_number"].astype(str)
            + "-"
            + declarations["date_signed"].astype(str)
        )
    for column in ["governor", "archive_record_url"]:
        if column not in declarations.columns:
            declarations[column] = ""

    filenames = get_latest_filenames_by_year()
    all_matches = []
    for _, declaration in declarations.iterrows():
        matches = events_near_date(
            args.state,
            declaration["date_signed"],
            args.window_days,
            filenames,
            description=declaration["event_description"],
            hazard_filter=not args.no_hazard_filter,
        )
        if matches.empty:
            print(
                f"{declaration['declaration_id']}: no matching storm events found "
                "in the date window."
            )
            continue

        matches = matches.copy()
        for column in DECLARATION_COLUMNS:
            matches[column] = declaration[column]
        matches["area_type"] = matches["CZ_TYPE"].map(AREA_TYPE_LABELS).fillna(
            "unknown NCEI area type"
        )
        all_matches.append(matches.reindex(columns=DECLARATION_COLUMNS + EVENT_COLUMNS))

    if not all_matches:
        print("No matches found for any declaration.")
        return

    result = pd.concat(all_matches, ignore_index=True).sort_values(
        ["date_signed", "declaration_id", "CZ_TYPE", "CZ_NAME", "BEGIN_DATE_TIME"]
    )
    result.to_csv(args.out, index=False)
    print(f"Wrote {len(result)} matched NCEI event rows to {args.out}")

    severity = build_severity_summary(result)
    severity.to_csv(args.severity_out, index=False)
    print(
        f"Wrote severity summary ({len(severity)} reported areas) "
        f"to {args.severity_out}"
    )

    notable = severity[
        (severity["deaths_direct"] > 0)
        | (severity["injuries_direct"] > 0)
        | (severity["total_damage_usd"] > 0)
    ]
    print("\nAreas with reported deaths, injuries, or damage:")
    if notable.empty:
        print("  None in the matched NCEI records.")
    else:
        notable_for_print = notable.sort_values(
            ["deaths_direct", "injuries_direct", "total_damage_usd"],
            ascending=False,
        )
        if not args.print_all_areas:
            notable_for_print = notable_for_print.head(25)
        for _, area in notable_for_print.iterrows():
            print(
                f"  {area['declaration_id']} {area['CZ_NAME']} "
                f"[{area['area_type']}]: deaths={int(area['deaths_direct'])}, "
                f"injuries={int(area['injuries_direct'])}, "
                f"damage=${area['total_damage_usd']:,.0f} "
                f"({area['event_types']})"
            )
        if not args.print_all_areas and len(notable) > len(notable_for_print):
            print(
                f"  Showing the 25 highest-consequence areas; all {len(notable)} "
                f"are retained in {args.severity_out}."
            )

    if args.print_all_areas:
        print("\nNCEI-reported areas per declaration:")
        for (declaration_id, eo_number, governor, description), group in result.groupby(
            ["declaration_id", "eo_number", "governor", "event_description"],
            sort=False,
            dropna=False,
        ):
            governor_label = f", {governor}" if governor else ""
            print(f"  {declaration_id}: {eo_number}{governor_label} ({description})")
            for area_type, area_group in group.groupby("area_type", sort=False):
                areas = sorted(set(area_group["CZ_NAME"].dropna()))
                print(f"    {area_type}: {', '.join(areas)}")
    else:
        print(f"\nComplete matched-area lists are in {args.severity_out}.")


if __name__ == "__main__":
    main()
