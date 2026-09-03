"""Nationwide place and county lookup backed by Census Gazetteer files."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import urlencode

from .http import HttpClient


GAZETTEER_BASE = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/"
)
COUNTIES_URL = GAZETTEER_BASE + "2024_Gaz_counties_national.zip"
PLACES_URL = GAZETTEER_BASE + "2024_Gaz_place_national.zip"
CENSUS_GEOCODER_URL = (
    "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
)
NWS_POINTS_URL = "https://api.weather.gov/points"


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    kind: str
    state: str
    latitude: float
    longitude: float
    geoid: str
    county_fips: tuple[str, ...] = ()
    county_names: tuple[str, ...] = ()
    forecast_zone_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        value = asdict(self)
        value["county_fips"] = list(self.county_fips)
        value["county_names"] = list(self.county_names)
        value["event_search_ready"] = bool(self.county_fips)
        return value


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _zip_rows(payload: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".txt"))
        text = archive.read(member).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text), dialect="excel-tab")
    return [
        {str(key).strip(): str(value).strip() for key, value in row.items()}
        for row in reader
    ]


class PlaceCatalog:
    """Search Census counties and incorporated/statistical places.

    Gazetteer place records do not carry their containing county, so a selected
    city is resolved by its internal point through the Census geocoder. A city
    spanning multiple counties is therefore represented by its primary internal
    point in this first release; callers can supply county place IDs separately.
    """

    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient()
        self._places: list[Place] | None = None

    def _load(self) -> list[Place]:
        if self._places is not None:
            return self._places
        counties = _zip_rows(self.http.get_bytes(COUNTIES_URL, 30 * 24 * 3600))
        places = _zip_rows(self.http.get_bytes(PLACES_URL, 30 * 24 * 3600))
        records: list[Place] = []
        for row in counties:
            geoid = row["GEOID"].zfill(5)
            records.append(
                Place(
                    id=f"county:{geoid}",
                    name=row["NAME"],
                    kind="county",
                    state=row["USPS"],
                    latitude=float(row["INTPTLAT"]),
                    longitude=float(row["INTPTLONG"]),
                    geoid=geoid,
                    county_fips=(geoid,),
                    county_names=(row["NAME"],),
                )
            )
        for row in places:
            geoid = row["GEOID"].zfill(7)
            records.append(
                Place(
                    id=f"place:{geoid}",
                    name=row["NAME"],
                    kind="place",
                    state=row["USPS"],
                    latitude=float(row["INTPTLAT"]),
                    longitude=float(row["INTPTLONG"]),
                    geoid=geoid,
                )
            )
        self._places = records
        return records

    def search(self, query: str, limit: int = 10) -> list[Place]:
        terms = normalize_text(query).split()
        if not terms:
            return []

        def score(place: Place) -> tuple[int, int, str]:
            haystack = normalize_text(f"{place.name} {place.state}")
            exact = normalize_text(query) == haystack
            starts = haystack.startswith(normalize_text(query))
            return (0 if exact else 1 if starts else 2, len(haystack), haystack)

        matches = [
            place
            for place in self._load()
            if all(term in normalize_text(f"{place.name} {place.state}") for term in terms)
        ]
        return sorted(matches, key=score)[: max(1, min(limit, 50))]

    def get(self, place_id: str, resolve_county: bool = True) -> Place:
        try:
            place = next(item for item in self._load() if item.id == place_id)
        except StopIteration as exc:
            raise KeyError(f"Unknown place_id: {place_id}") from exc
        if not resolve_county:
            return place
        if not place.county_fips:
            place = self._resolve_county(place)
        if not place.forecast_zone_ids:
            place = self._resolve_forecast_zone(place)
        return place

    def _resolve_county(self, place: Place) -> Place:
        parameters = urlencode(
            {
                "x": place.longitude,
                "y": place.latitude,
                "benchmark": "Public_AR_Current",
                "vintage": "Current_Current",
                "layers": "Counties",
                "format": "json",
            }
        )
        payload = self.http.get_json(
            f"{CENSUS_GEOCODER_URL}?{parameters}", 30 * 24 * 3600
        )
        geographies = payload.get("result", {}).get("geographies", {})
        counties: Iterable[dict] = geographies.get("Counties", [])
        county = next(iter(counties), None)
        if not county:
            return place
        geoid = str(county.get("GEOID") or "").zfill(5)
        return Place(
            **{
                **asdict(place),
                "county_fips": (geoid,),
                "county_names": (str(county.get("NAME") or ""),),
            }
        )

    def _resolve_forecast_zone(self, place: Place) -> Place:
        try:
            payload = self.http.get_json(
                f"{NWS_POINTS_URL}/{place.latitude},{place.longitude}",
                7 * 24 * 3600,
            )
            zone_url = str(payload.get("properties", {}).get("forecastZone") or "")
            zone_id = zone_url.rstrip("/").rsplit("/", 1)[-1].upper()
            if not re.fullmatch(r"[A-Z]{2}Z\d{3}", zone_id):
                return place
            return Place(**{**asdict(place), "forecast_zone_ids": (zone_id,)})
        except Exception:
            # County-based event retrieval remains useful when weather.gov is
            # temporarily unavailable; the response coverage notes the gap.
            return place
