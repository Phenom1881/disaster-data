"""Application service combining place, event, and climatology sources."""

from __future__ import annotations

from datetime import date

from .climatology import DailySummariesSource
from .events import StormEventsSource
from .places import PlaceCatalog


def parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO date such as 2025-01-31") from exc


class WeatherService:
    def __init__(
        self,
        places: PlaceCatalog | None = None,
        events: StormEventsSource | None = None,
        daily: DailySummariesSource | None = None,
    ):
        self.places = places or PlaceCatalog()
        self.events_source = events or StormEventsSource()
        self.daily_source = daily or DailySummariesSource()

    def search_places(self, query: str, limit: int = 10) -> dict:
        return {"results": [place.to_dict() for place in self.places.search(query, limit)]}

    def get_place(self, place_id: str) -> dict:
        return self.places.get(place_id).to_dict()

    def events(
        self,
        place_id: str,
        start_value: str,
        end_value: str,
        event_types: set[str] | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict:
        place = self.places.get(place_id)
        start, end = parse_date(start_value, "from"), parse_date(end_value, "to")
        if start > end:
            raise ValueError("from must be on or before to")
        if limit <= 0 or limit > 5000:
            raise ValueError("limit must be between 1 and 5000")
        if offset < 0:
            raise ValueError("offset must be zero or greater")
        result = self.events_source.events(place, start, end, event_types)
        all_events = result["events"]
        result["events"] = all_events[offset : offset + limit]
        result["page"] = {
            "total": len(all_events),
            "offset": offset,
            "limit": limit,
            "returned": len(result["events"]),
        }
        result["place"] = place.to_dict()
        result["period"] = {"from": start.isoformat(), "to": end.isoformat()}
        return result

    def climatology(
        self,
        place_id: str,
        start_value: str,
        end_value: str,
        radius_km: float = 40,
    ) -> dict:
        place = self.places.get(place_id)
        start, end = parse_date(start_value, "from"), parse_date(end_value, "to")
        if start > end:
            raise ValueError("from must be on or before to")
        if radius_km <= 0 or radius_km > 250:
            raise ValueError("radius_km must be greater than 0 and no more than 250")
        result = self.daily_source.climatology(place, start, end, radius_km)
        result["place"] = place.to_dict()
        result["period"] = {"from": start.isoformat(), "to": end.isoformat()}
        return result

    def profile(
        self,
        place_id: str,
        start_value: str,
        end_value: str,
        radius_km: float = 40,
    ) -> dict:
        events = self.events(place_id, start_value, end_value)
        climate = self.climatology(place_id, start_value, end_value, radius_km)
        return {
            "place": events["place"],
            "period": events["period"],
            "storm_events": {
                "summary": events["summary"],
                "events": events["events"],
                "coverage": events["coverage"],
            },
            "climatology": {
                "metrics": climate["metrics"],
                "coverage": climate["coverage"],
            },
            "interpretation": (
                "Use Storm Events for reported significant events and Daily Summaries for the "
                "observed local baseline. Declarations are intentionally not an inclusion filter."
            ),
        }
