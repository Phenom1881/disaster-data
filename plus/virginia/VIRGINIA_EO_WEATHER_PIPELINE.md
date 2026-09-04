# Virginia weather emergency pipeline

## Coverage

The Library of Virginia's Executive Orders Digital Collection supplies the
completed administrations beginning with Mark R. Warner in January 2002:

- Mark R. Warner (2002-2006)
- Timothy M. Kaine (2006-2010)
- Robert F. McDonnell (2010-2014)
- Terry McAuliffe (2014-2018)
- Ralph S. Northam (2018-2022)
- Glenn Youngkin (2022-2026)

The current governor's CSV is appended separately.  The resulting inventory
currently includes Abigail D. Spanberger EO-11 and therefore covers 2002 to the
present.  James S. Gilmore's 2000-2001 orders are outside this structured LVA
collection and require a separate legacy-archive pass if those two years are
needed.

## Build the declaration inventory

```sh
python va_historical_eo_scraper.py \
  --current-csv declarations_for_join.csv
```

The scraper writes four audit levels:

- `va_eo_archive_all.csv`: every archived EO and directive.
- `va_emergency_actions_2002_2026.csv`: declarations and related emergency actions.
- `va_weather_emergency_actions_2002_2026.csv`: weather-related emergency actions,
  including modifications and interstate-assistance records for review.
- `declarations_for_join_2002_present.csv`: consolidated initial Virginia weather
  declarations ready for NCEI matching.

Each declaration has a stable `declaration_id` containing governor, order number,
and year.  Do not use `eo_number` alone as a database key because numbers repeat
across administrations.

## Match declarations to NCEI events

```sh
python eo_storm_join.py \
  --declarations declarations_for_join_2002_present.csv \
  --out eo_storm_matches_2002_present.csv \
  --severity-out eo_storm_severity_2002_present.csv
```

The default date window is three days on either side of the signing date.  The
join also limits results to event types compatible with the declaration's stated
hazard.  Use `--window-days 7` for declarations signed well after an event, and
review those wider-window results manually.  `--no-hazard-filter` is an audit
option, not the recommended production setting.

## Interpretation rules

- A matched row means NCEI recorded a compatible hazard in that area during the
  declaration window.  It is evidence of impact, not proof that the executive
  order legally designated that locality.
- `CZ_TYPE=C` is a county or independent city; `CZ_TYPE=Z` is an NWS forecast
  zone.  Preserve that distinction until a date-appropriate zone crosswalk is
  applied.
- Zero NCEI matches does not prove that no impact occurred.  Drought, wildfire,
  highway damage, declarations signed several days after an event, and incomplete
  reporting require manual review or an additional source.
- Damage, death, and injury fields are reported values and should not be treated
  as a complete loss estimate.

