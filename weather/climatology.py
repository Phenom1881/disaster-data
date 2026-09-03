"""NCEI Daily Summaries adapter and descriptive climate statistics."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from urllib.parse import urlencode

from .http import HttpClient
from .places import Place


DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
SEARCH_URL = "https://www.ncei.noaa.gov/access/services/search/v1/data"
METRICS = {
    "PRCP": {"name": "precipitation", "unit": "in"},
    "SNOW": {"name": "snowfall", "unit": "in"},
    "SNWD": {"name": "snow_depth", "unit": "in"},
    "TMAX": {"name": "maximum_temperature", "unit": "F"},
    "TMIN": {"name": "minimum_temperature", "unit": "F"},
    "AWND": {"name": "average_wind_speed", "unit": "mph"},
    "WSF2": {"name": "fastest_2_minute_wind", "unit": "mph"},
    "WSF5": {"name": "fastest_5_second_wind", "unit": "mph"},
}


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _rounded(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def summarize_daily_rows(rows: list[dict]) -> dict:
    observations: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    stations = set()
    dates = set()
    for row in rows:
        station = str(row.get("STATION") or "")
        observed = str(row.get("DATE") or "")
        if station:
            stations.add(station)
        if observed:
            dates.add(observed[:10])
        for code in METRICS:
            raw = row.get(code)
            if raw in (None, ""):
                continue
            try:
                observations[code].append((float(raw), observed, station))
            except (TypeError, ValueError):
                continue
    metrics = {}
    for code, values_with_context in observations.items():
        values = [item[0] for item in values_with_context]
        maximum = max(values_with_context, key=lambda item: item[0])
        minimum = min(values_with_context, key=lambda item: item[0])
        definition = METRICS[code]
        metrics[definition["name"]] = {
            "source_code": code,
            "unit": definition["unit"],
            "observation_count": len(values),
            "p50": _rounded(percentile(values, 0.50)),
            "p90": _rounded(percentile(values, 0.90)),
            "p95": _rounded(percentile(values, 0.95)),
            "p99": _rounded(percentile(values, 0.99)),
            "maximum": {"value": maximum[0], "date": maximum[1], "station": maximum[2]},
            "minimum": {"value": minimum[0], "date": minimum[1], "station": minimum[2]},
        }
    return {
        "metrics": metrics,
        "coverage": {
            "station_count": len(stations),
            "date_count": len(dates),
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
        },
    }


class DailySummariesSource:
    def __init__(self, http: HttpClient | None = None):
        self.http = http or HttpClient()

    def climatology(
        self,
        place: Place,
        start: date,
        end: date,
        radius_km: float = 40,
    ) -> dict:
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / max(1.0, 111.0 * math.cos(math.radians(place.latitude)))
        # NCEI bbox order is north, west, south, east.
        bbox = ",".join(
            str(round(value, 5))
            for value in (
                place.latitude + lat_delta,
                place.longitude - lon_delta,
                place.latitude - lat_delta,
                place.longitude + lon_delta,
            )
        )
        stations = self._stations(place, start, end, bbox)
        if not stations:
            return {
                "metrics": {},
                "coverage": {
                    "source": "NOAA NCEI Daily Summaries",
                    "search_radius_km": radius_km,
                    "stations_selected": [],
                    "station_count": 0,
                    "date_count": 0,
                    "first_date": None,
                    "last_date": None,
                    "warning": "No Daily Summaries stations were found in the search area.",
                },
            }
        parameters = urlencode(
            {
                "dataset": "daily-summaries",
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "stations": ",".join(stations),
                "dataTypes": ",".join(METRICS),
                "format": "json",
                "units": "standard",
                "includeAttributes": "false",
                "includeStationName": "true",
            }
        )
        rows = self.http.get_json(f"{DATA_URL}?{parameters}", 24 * 3600)
        if not isinstance(rows, list):
            raise ValueError("NCEI Daily Summaries returned an unexpected response")
        summary = summarize_daily_rows(rows)
        summary["coverage"].update(
            {
                "source": "NOAA NCEI Daily Summaries",
                "search_radius_km": radius_km,
                "stations_selected": stations,
                "warning": (
                    "Statistics describe available station observations within the search area; "
                    "they are not recurrence-interval estimates or operational failure thresholds."
                ),
            }
        )
        return summary

    def _stations(
        self,
        place: Place,
        start: date,
        end: date,
        bbox: str,
        maximum: int = 5,
    ) -> list[str]:
        parameters = urlencode(
            {
                "dataset": "daily-summaries",
                "startDate": f"{start.isoformat()}T00:00:00",
                "endDate": f"{end.isoformat()}T23:59:59",
                "bbox": bbox,
                "dataTypes": ",".join(METRICS),
                "limit": 50,
                "offset": 0,
            }
        )
        payload = self.http.get_json(f"{SEARCH_URL}?{parameters}", 24 * 3600)
        candidates = []
        for result in payload.get("results", []):
            coordinates = result.get("location", {}).get("coordinates") or result.get("centroid")
            if not coordinates or len(coordinates) < 2:
                continue
            station_records = result.get("stations") or []
            if not station_records:
                continue
            station = station_records[0]
            station_id = str(station.get("id") or "")
            if not station_id:
                continue
            available = {
                item.get("id") for item in station.get("dataTypes", []) if item.get("id")
            }
            distance = _distance_km(
                place.latitude,
                place.longitude,
                float(coordinates[1]),
                float(coordinates[0]),
            )
            candidates.append((distance, station_id, available))
        candidates.sort(key=lambda item: item[0])

        # Preserve at least one nearby station for each major capability when
        # possible, then fill the remaining slots by distance.
        capabilities = [
            {"SNOW", "SNWD"},
            {"WSF2", "WSF5", "AWND"},
            {"TMAX", "TMIN"},
            {"PRCP"},
        ]
        selected: list[str] = []
        for capability in capabilities:
            match = next(
                (item for item in candidates if item[2] & capability and item[1] not in selected),
                None,
            )
            if match:
                selected.append(match[1])
        for _, station_id, _ in candidates:
            if station_id not in selected:
                selected.append(station_id)
            if len(selected) >= maximum:
                break
        return selected[:maximum]


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))
