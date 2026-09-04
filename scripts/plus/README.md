# DisasterData Plus national builder

This package is designed to be copied into the root of the `disaster-data`
repository. It works with the existing `plus/virginia/` folder in place.

## What the first version does

- Generates `/plus/index.html` as a national coverage directory.
- Generates `/plus/<state>/index.html` for all 50 states.
- Reads existing state-action CSVs from each state folder when available.
- Loads a state adapter only when `--collect` is requested.
- Marks missing or incomplete coverage explicitly instead of displaying a false
  zero-event result.
- Writes `/plus/coverage.json` and a `state-summary.json` inside each rebuilt
  state directory.

Only Virginia is marked as an implemented source adapter in this first release.
New York, New Jersey, and Pennsylvania are marked as planned. The remaining
states receive transparent placeholder pages until their source adapters are
implemented.

## Install

From the repository root:

```bash
python -m pip install -r scripts/plus/requirements.txt
```

The national page builder itself uses only the Python standard library. The
dependencies above are needed by the existing Virginia collection scripts.

## Generate all 50 pages

```bash
python scripts/plus/build-plus.py --states all
```

This command does not scrape state websites. It uses any cached files already
present and creates coverage-labeled pages for states without data.

## Rebuild selected states

```bash
python scripts/plus/build-plus.py --states VA,NY,NJ,PA
```

Names and slugs also work:

```bash
python scripts/plus/build-plus.py --states Virginia,new-york
```

## Refresh Virginia before building

The existing Virginia folder should contain:

- `virginia.py`
- `va_eo_scraper.py`
- `va_historical_eo_scraper.py`

Then run:

```bash
python scripts/plus/build-plus.py --states VA --collect
```

The builder calls `collect(workdir=plus/virginia,
scripts_dir=plus/virginia)`, so the Virginia files do not need to be moved.

To refresh the Virginia sources and then run its existing NOAA storm join and
forecast-zone resolver:

```bash
python scripts/plus/build-plus.py --states VA --collect --join-storms
```

`--join-storms` uses `eo_storm_join.py` in the state folder. When
`resolve_zones_to_counties.py` and a `bp*.dbx` crosswalk are present, it also
creates `severity_resolved.csv`. The same option will work for later state
adapters that use the common scripts and normalized input columns.

## Validate without writing

```bash
python scripts/plus/build-plus.py --states all --dry-run
```

Use `--strict` in automated checks when missing source coverage should cause a
nonzero exit code. Do not use `--strict` for the initial national placeholder
build because 49 state adapters are intentionally pending.

## State adapter contract

A state adapter belongs inside its public state directory, such as:

```text
plus/new-york/new_york.py
```

It must expose:

```python
def collect(workdir=".", scripts_dir=None):
    # collect and normalize the state's records
    return path_to_action_csv, coverage_note
```

The returned CSV should include, at minimum:

```text
eo_number,event_description,date_signed
```

Recommended additional fields are:

```text
declaration_id,governor,action_type,archive_record_url
```

The builder accepts equivalent generalized names such as `action_number`,
`title`, `issued_date`, and `source_url`.

## Important limitation

Page generation is national; source collection is state-specific. A generated
state page must not be interpreted as complete unless its coverage statement
confirms the archive period and source quality.
