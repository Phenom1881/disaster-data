"""Certified NCEI Storm Events bulk-data adapter."""

from __future__ import annotations

import csv
import gzip
import io
import re
from collections import Counter
from datetime import date, datetime
from typing import Iterable

from .http import HttpClient
from .places import Place, normalize_text


INDEX_URL = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
DETAIL_PATTERN = re.compile(
    r"StormEvents_details-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz"
)


def _digits(value: object, width: int) -> str:
    text = str(value or "").strip()
    try:
        return f"{int(float(text)):0{width}d}"
    except ValueError:
        return ""


def _event_date(value: str) -> date | None:
    for pattern in ("%d-%b-%y %H:%M:%S", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except (TypeError, ValueError):
            pass
    return None


def filter_event_rows(
    rows: Iterable[dict[str, str]],
    place: Place,
    start: date,
    end: date,
    event_types: set[str] | None = None,
) -> list[dict]:
    county_codes = {value[-3:] for value in place.county_fips}
    state_codes = {value[:2] for value in place.county_fips}
    forecast_zone_codes = {
        value[-3:] for value in place.forecast_zone_ids if len(value) >= 3
    }
    county_names = {
        normalize_text(
            re.sub(
                r"\b(county|parish|borough|municipality)\b",
                "",
                name,
                flags=re.IGNORECASE,
            )
        )
        for name in place.county_names
    }
    output = []
    for row in rows:
        occurred = _event_date(row.get("BEGIN_DATE_TIME", ""))
        if occurred is None or occurred < start or occurred > end:
            continue
        if state_codes and _digits(row.get("STATE_FIPS"), 2) not in state_codes:
            continue
        if event_types and row.get("EVENT_TYPE") not in event_types:
            continue
        area_type = row.get("CZ_TYPE", "").strip().upper()
        area_code = _digits(row.get("CZ_FIPS"), 3)
        area_name = normalize_text(row.get("CZ_NAME", ""))
        direct_county = area_type == "C" and area_code in county_codes
        current_forecast_zone = area_type == "Z" and area_code in forecast_zone_codes
        same_named_zone = area_type == "Z" and area_name in county_names
        if not direct_county and not current_forecast_zone and not same_named_zone:
            continue
        output.append(
            {
                "event_id": _digits(row.get("EVENT_ID"), 0) or row.get("EVENT_ID"),
                "episode_id": _digits(row.get("EPISODE_ID"), 0) or row.get("EPISODE_ID"),
                "event_type": row.get("EVENT_TYPE"),
                "begin": row.get("BEGIN_DATE_TIME"),
                "end": row.get("END_DATE_TIME"),
                "area_type": {"C": "county", "Z": "forecast_zone", "M": "marine_zone"}.get(area_type, "other"),
                "area_name": row.get("CZ_NAME"),
                "area_code": area_code,
                "geography_match": (
                    "county_fips"
                    if direct_county
                    else "current_forecast_zone"
                    if current_forecast_zone
                    else "same_named_forecast_zone"
                ),
                "magnitude": row.get("MAGNITUDE"),
                "magnitude_type": row.get("MAGNITUDE_TYPE"),
                "begin_location": row.get("BEGIN_LOCATION"),
                "begin_latitude": row.get("BEGIN_LAT"),
                "begin_longitude": row.get("BEGIN_LON"),
                "end_location": row.get("END_LOCATION"),
                "end_latitude": row.get("END_LAT"),
                "end_longitude": row.get("END_LON"),
                "source": row.get("SOURCE"),
                "deaths_direct": int(float(row.get("DEATHS_DIRECT") or 0)),
                "deaths_indirect": int(float(row.get("DEATHS_INDIRECT") or 0)),
                "injuries_direct": int(float(row.get("INJURIES_DIRECT") or 0)),
                "injuries_indirect": int(float(row.get("INJURIES_INDIRECT") or 0)),
                "damage_property": row.get("DAMAGE_PROPERTY"),
                "damage_crops": row.get("DAMAGE_CROPS"),
                "episode_narrative": row.get("EPISODE_NARRATIVE"),
                "event_narrative": row.get("EVENT_NARRATIVE"),
                "wfo": row.get("WFO"),
            }
        )
    return output


class StormEventsSource:
    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient()

    def _files(self) -> dict[int, str]:
        index = self.http.get_text(INDEX_URL, 6 * 3600)
        latest: dict[int, tuple[str, str]] = {}
        for match in DETAIL_PATTERN.finditer(index):
            year, certified = int(match.group(1)), match.group(2)
            if year not in latest or certified > latest[year][1]:
                latest[year] = (match.group(0), certified)
        return {year: value[0] for year, value in latest.items()}

    def events(
        self,
        place: Place,
        start: date,
        end: date,
        event_types: set[str] | None = None,
    ) -> dict:
        files = self._files()
        matches: list[dict] = []
        missing_years: list[int] = []
        for year in range(start.year, end.year + 1):
            filename = files.get(year)
            if not filename:
                missing_years.append(year)
                continue
            payload = self.http.get_bytes(INDEX_URL + filename)
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as archive:
                text = io.TextIOWrapper(archive, encoding="utf-8-sig", errors="replace")
                matches.extend(
                    filter_event_rows(csv.DictReader(text), place, start, end, event_types)
                )
        matches.sort(
            key=lambda item: (
                _event_date(item["begin"] or "") or date.min,
                item["event_type"] or "",
            )
        )
        counts = Counter(item["event_type"] for item in matches)
        return {
            "events": matches,
            "summary": {
                "event_count": len(matches),
                "by_event_type": dict(sorted(counts.items())),
            },
            "coverage": {
                "source": "NOAA NCEI Storm Events",
                "certified_records": True,
                "missing_years": missing_years,
                "county_matching": "FIPS",
                "forecast_zone_matching": (
                    "current NWS zone at the selected place's internal point, plus same-name fallback"
                ),
                "warning": (
                    "Storm Events is a report catalog, not a record of every weather occurrence. "
                    "The current zone at one representative point may not cover an entire county "
                    "or reflect historical zone boundaries."
                ),
            },
        }
