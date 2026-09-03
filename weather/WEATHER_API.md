# DisasterData Weather API

This is the declaration-independent foundation for nationwide local weather
profiles. It combines:

- NOAA/NCEI certified Storm Events bulk records.
- NOAA/NCEI Daily Summaries from stations near a selected place.
- U.S. Census Gazetteer place and county identifiers.

Emergency declarations are intentionally not used as an event inclusion filter.

## Run locally

Python 3.10 or newer is sufficient; the first version has no third-party runtime
dependencies.

```sh
python3 -m disasterdata_weather --port 8080
```

The first place search downloads and caches the national Census county and place
gazetteers. The first weather request for a year similarly caches that year's
versioned NCEI Storm Events file. Set `WEATHER_CACHE_DIR` to move the cache.

## API sequence

Search for a place:

```text
GET /v1/places/search?q=Buffalo%2C%20NY
```

Resolve the selected place to its county:

```text
GET /v1/places/detail?place_id=place%3A3611000
```

Retrieve certified reports without requiring a declaration:

```text
GET /v1/weather/events?place_id=place%3A3611000&from=2020-01-01&to=2025-12-31
```

Multiple exact NCEI event filters may be supplied:

```text
GET /v1/weather/events?...&event_type=High%20Wind&event_type=Winter%20Storm
```

Build a station-observation summary:

```text
GET /v1/weather/climatology?place_id=place%3A3611000&from=2000-01-01&to=2025-12-31&radius_km=40
```

Or retrieve the combined profile:

```text
GET /v1/weather/profile?place_id=place%3A3611000&from=2000-01-01&to=2025-12-31
```

## Interpretation and current limits

- Storm Events is a catalog of reported significant events, not every weather
  occurrence.
- County event rows are matched by state and county FIPS.
- Version 0.1 includes the current NWS forecast zone at the selected place's
  internal point, plus zones whose name matches the county. A single point may
  not represent an entire county, and date-effective national NWS zone geometry
  remains the next coverage improvement.
- A selected Census place is assigned the county containing its internal point.
  Cities spanning multiple counties need explicit multi-county support in a
  subsequent release.
- Daily-summary percentiles describe the retrieved station observations. They are
  computed across up to five nearby stations selected to represent snow, wind,
  temperature, and precipitation when those capabilities are available. They are
  not return-period calculations and do not predict an organization's failure
  threshold.
- Upstream NOAA and Census availability affects uncached requests.

Every response includes source and coverage metadata so clients can preserve
these qualifications.

## Tests

```sh
python3 -m unittest discover -s tests -v
```
