#!/usr/bin/env python3
"""
DisasterData.io Build, Validation & Release Gate
=================================================

Run this LAST, after the normal DisasterData build/generator steps have completed.

    python build.py
    # ...your existing generators (jurisdictions, map events, etc.)...
    python release.py

What this script does in one pass:
  1. Validates the generated DisasterData files and cross-file totals.
  2. Refuses to stamp a release when a critical validation fails.
  3. Assigns a human-readable release number: YYYY.MM.DD.N.
  4. Writes a public machine-readable data-status.json.
  5. Writes a public status.html page from the same source of truth.
  6. Writes build-report.json with every PASS/WARN/FAIL check.
  7. Tracks the last successful release in release-state.json.

No third-party Python packages are required.

Optional strictness environment variables:
  DD_REQUIRE_CONTEXT=1        Missing/invalid county-svi.js or county-nri.js is fatal.
  DD_REQUIRE_JURISDICTIONS=1  Missing/invalid generated jurisdiction pages is fatal.
  DD_REQUIRE_CITATIONS=1      Missing Cite-this-profile blocks is fatal.
  DD_RELEASE=2026.09.01.1     Override the automatically generated release number.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(os.environ.get("DD_ROOT", ".")).resolve()
TODAY = _dt.date.today()
TODAY_ISO = TODAY.isoformat()
NOW_UTC = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

REQUIRE_CONTEXT = os.environ.get("DD_REQUIRE_CONTEXT", "").strip().lower() in {"1", "true", "yes", "on"}
REQUIRE_JURISDICTIONS = os.environ.get("DD_REQUIRE_JURISDICTIONS", "").strip().lower() in {"1", "true", "yes", "on"}
REQUIRE_CITATIONS = os.environ.get("DD_REQUIRE_CITATIONS", "").strip().lower() in {"1", "true", "yes", "on"}

PUBLIC_STATUS = ROOT / "data-status.json"
STATUS_HTML = ROOT / "status.html"
BUILD_REPORT = ROOT / "build-report.json"
RELEASE_STATE = ROOT / "release-state.json"

CHECKS: List[Dict[str, Any]] = []


def _status_for(ok: bool, severity: str) -> str:
    if ok:
        return "pass"
    return "fail" if severity == "error" else "warn"


def check(
    name: str,
    ok: bool,
    detail: str,
    *,
    severity: str = "error",
    category: str = "General",
    metrics: Optional[Dict[str, Any]] = None,
) -> bool:
    """Record one validation check and return the original truth value."""
    CHECKS.append(
        {
            "name": name,
            "category": category,
            "status": _status_for(bool(ok), severity),
            "severity": severity,
            "detail": detail,
            "metrics": metrics or {},
        }
    )
    return bool(ok)


def warning(
    name: str,
    ok: bool,
    detail: str,
    *,
    category: str = "General",
    metrics: Optional[Dict[str, Any]] = None,
) -> bool:
    return check(
        name,
        ok,
        detail,
        severity="warning",
        category=category,
        metrics=metrics,
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def grab_js(text: str, name: str, default: Any = None) -> Any:
    """Decode a JSON value assigned as window.NAME = ... in a JS data file."""
    m = re.search(r"window\." + re.escape(name) + r"\s*=\s*", text)
    if not m:
        return default

    try:
        return json.JSONDecoder().raw_decode(text, m.end())[0]
    except Exception:
        return default


def js_file(path: Path, name: str, default: Any = None) -> Any:
    if not path.exists():
        return default

    try:
        return grab_js(read_text(path), name, default)
    except Exception:
        return default


def file_hash(path: Path, n: int = 16) -> str:
    if not path.exists() or not path.is_file():
        return ""

    h = hashlib.sha256()

    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()[:n]


def safe_num(v: Any) -> Optional[float]:
    try:
        x = float(v)

        if x != x or x in (float("inf"), float("-inf")):
            return None

        return x

    except (TypeError, ValueError):
        return None


def valid_iso_day(v: Any) -> bool:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return False

    try:
        _dt.date.fromisoformat(v)
        return True
    except ValueError:
        return False


def flatten_values(obj: Any) -> Iterable[Any]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield from flatten_values(v)

    elif isinstance(obj, list):
        for v in obj:
            yield from flatten_values(v)

    else:
        yield obj


def validate_nonnegative_rollup(
    path: Path,
    fields: Tuple[str, ...],
    label: str,
) -> Tuple[bool, int, int]:
    """Validate numeric rollup fields inside state -> jurisdiction -> record JSON."""

    data = load_json(path, None)

    if not isinstance(data, dict):
        return False, 0, 0

    rows = 0
    bad = 0

    for state_rows in data.values():

        if not isinstance(state_rows, dict):
            bad += 1
            continue

        for rec in state_rows.values():
            rows += 1

            if not isinstance(rec, dict):
                bad += 1
                continue

            for fld in fields:

                if fld not in rec:
                    continue

                n = safe_num(rec.get(fld))

                if n is None or n < 0:
                    bad += 1

    return bad == 0 and rows > 0, rows, bad


def parse_locality_index(path: Path) -> Optional[List[Any]]:
    return js_file(path, "LOCALITY_INDEX", None)


def detect_static_release(path: Path, fallback: str = "") -> str:
    """Best-effort release label from the first few comments of a static JS file."""

    if not path.exists():
        return fallback

    try:
        head = "\n".join(read_text(path).splitlines()[:30])
    except Exception:
        return fallback

    patterns = [
        r"\b(20\d{2})\b",
        r"\b(?:release|version|updated|published)\s*[:=-]?\s*([^\n*/]+)",
    ]

    for pat in patterns:
        m = re.search(pat, head, re.I)

        if m:
            return m.group(1).strip()

    return fallback


def next_release() -> Tuple[str, int]:
    override = os.environ.get("DD_RELEASE", "").strip()

    if override:

        m = re.fullmatch(
            r"(\d{4})\.(\d{2})\.(\d{2})\.(\d+)",
            override,
        )

        if not m:
            raise SystemExit(
                "DD_RELEASE must look like YYYY.MM.DD.N"
            )

        return override, int(m.group(4))

    state = load_json(RELEASE_STATE, {}) or {}

    same_day = state.get("date") == TODAY_ISO

    previous_build = (
        int(state.get("build", 0) or 0)
        if same_day
        else 0
    )

    build_no = previous_build + 1

    return f"{TODAY:%Y.%m.%d}.{build_no}", build_no


def previous_metrics() -> Dict[str, Any]:
    prior = load_json(PUBLIC_STATUS, {}) or {}

    return (
        prior.get("metrics", {})
        if isinstance(prior, dict)
        else {}
    )


def delta(current: Any, previous: Any) -> Optional[float]:
    a = safe_num(current)
    b = safe_num(previous)

    if a is None or b is None:
        return None

    return a - b


def delta_text(
    value: Optional[float],
    money: bool = False,
) -> str:

    if value is None:
        return ""

    sign = "+" if value > 0 else ""

    if money:
        return f"{sign}${value:,.0f}"

    if float(value).is_integer():
        return f"{sign}{int(value):,}"

    return f"{sign}{value:,.1f}"


def fingerprint(paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    found = False

    for p in sorted(
        paths,
        key=lambda x: str(x),
    ):

        if not p.exists() or not p.is_file():
            continue

        found = True

        h.update(
            str(
                p.relative_to(ROOT)
            ).encode(
                "utf-8",
                errors="replace",
            )
        )

        with p.open("rb") as fh:

            for chunk in iter(
                lambda: fh.read(1024 * 1024),
                b"",
            ):
                h.update(chunk)

    return (
        h.hexdigest()[:20]
        if found
        else ""
    )


def validate() -> Dict[str, Any]:
    """Run the release gate against files produced by the DisasterData build."""

    data_path = ROOT / "data.js"
    map_path = ROOT / "map-data.js"
    latest_path = ROOT / "latest-data.js"
    index_path = ROOT / "index.html"
    svi_path = ROOT / "county-svi.js"
    nri_path = ROOT / "county-nri.js"
    locality_index_path = ROOT / "locality-index.js"
    jurisdiction_landing = ROOT / "jurisdiction.html"

    # ------------------------------------------------------------
    # data.js / canonical declaration data
    # ------------------------------------------------------------

    data_ok = check(
        "data.js exists",
        data_path.exists()
        and data_path.stat().st_size > 1024,
        (
            f"{data_path.name} is present and non-trivial"
            if data_path.exists()
            else "data.js is missing"
        ),
        category="Core build",
    )

    data_text = (
        read_text(data_path)
        if data_ok
        else ""
    )

    browse = grab_js(
        data_text,
        "BROWSE",
        None,
    )

    locality = grab_js(
        data_text,
        "LOCALITY_DATA",
        None,
    )

    state_names = grab_js(
        data_text,
        "STATE_NAMES",
        None,
    )

    totals = grab_js(
        data_text,
        "NATIONAL_TOTALS",
        None,
    )

    denials = grab_js(
        data_text,
        "DENIALS",
        [],
    )

    pa_national = grab_js(
        data_text,
        "PA_NATIONAL",
        {},
    )

    pa_county = grab_js(
        data_text,
        "PA_BY_COUNTY",
        {},
    )

    data_date = grab_js(
        data_text,
        "DATA_DATE",
        "",
    )

    check(
        "BROWSE parsed",
        isinstance(browse, list)
        and len(browse) > 0,
        (
            f"Parsed {len(browse):,} unique declarations"
            if isinstance(browse, list)
            else "window.BROWSE could not be parsed"
        ),
        category="Declarations",
    )

    check(
        "LOCALITY_DATA parsed",
        isinstance(locality, dict)
        and len(locality) > 0,
        (
            f"Parsed locality data for {len(locality):,} states/territories"
            if isinstance(locality, dict)
            else "window.LOCALITY_DATA could not be parsed"
        ),
        category="Jurisdictions",
    )

    check(
        "STATE_NAMES parsed",
        isinstance(state_names, dict)
        and len(state_names) >= 50,
        (
            f"Parsed {len(state_names):,} state/territory labels"
            if isinstance(state_names, dict)
            else "window.STATE_NAMES could not be parsed"
        ),
        category="Core build",
    )

    check(
        "NATIONAL_TOTALS parsed",
        isinstance(totals, dict)
        and "current" in totals
        and "completed" in totals,
        (
            "Canonical current and completed-FY totals are present"
            if isinstance(totals, dict)
            else "window.NATIONAL_TOTALS could not be parsed"
        ),
        category="Declarations",
    )

    check(
        "DATA_DATE is valid",
        valid_iso_day(data_date),
        (
            f"Data date: {data_date}"
            if data_date
            else "window.DATA_DATE is missing or invalid"
        ),
        category="Freshness",
    )

    browse_ids: List[str] = []
    blank_ids = 0
    bad_dates = 0
    bad_types: Dict[str, int] = {}

    if isinstance(browse, list):

        for r in browse:

            if not isinstance(r, dict):
                blank_ids += 1
                continue

            fid = str(
                r.get("femaDeclarationString")
                or r.get("id")
                or ""
            ).strip()

            if not fid:
                blank_ids += 1
            else:
                browse_ids.append(fid)

            d = str(
                r.get("declarationDate")
                or r.get("date")
                or ""
            )[:10]

            if d and not valid_iso_day(d):
                bad_dates += 1

            ty = str(
                r.get("declarationType")
                or r.get("dt")
                or ""
            ).strip()

            if ty and ty not in {
                "DR",
                "EM",
                "FM",
            }:
                bad_types[ty] = (
                    bad_types.get(
                        ty,
                        0,
                    )
                    + 1
                )

        dupes = (
            len(browse_ids)
            - len(set(browse_ids))
        )

        check(
            "Declaration IDs are unique",
            dupes == 0
            and blank_ids == 0,
            (
                f"{len(browse_ids):,} IDs; "
                f"{dupes:,} duplicate(s); "
                f"{blank_ids:,} blank ID(s)"
            ),
            category="Declarations",
            metrics={
                "duplicates": dupes,
                "blankIds": blank_ids,
            },
        )

        warning(
            "Declaration dates parse",
            bad_dates == 0,
            (
                f"{bad_dates:,} malformed declaration date(s)"
                if bad_dates
                else "All populated declaration dates use YYYY-MM-DD"
            ),
            category="Declarations",
        )

        warning(
            "Declaration types recognized",
            not bad_types,
            (
                "Only DR, EM, and FM types found"
                if not bad_types
                else f"Unexpected types: {bad_types}"
            ),
            category="Declarations",
        )

    if (
        isinstance(totals, dict)
        and isinstance(browse, list)
    ):

        current_total = (
            (
                totals.get("current")
                or {}
            ).get("total")
        )

        check(
            "Canonical current total reconciles",
            current_total == len(browse),
            (
                f"NATIONAL_TOTALS current={current_total:,}; "
                f"BROWSE={len(browse):,}"
                if isinstance(
                    current_total,
                    int,
                )
                else "Canonical current total is missing"
            ),
            category="Declarations",
        )

        completed = (
            (
                totals.get("completed")
                or {}
            ).get("total")
        )

    else:
        current_total = None
        completed = None

    # ------------------------------------------------------------
    # Map
    # ------------------------------------------------------------

    map_data = js_file(
        map_path,
        "MAP_DATA",
        None,
    )

    check(
        "map-data.js parsed",
        isinstance(
            map_data,
            dict,
        ),
        (
            "County map data parsed successfully"
            if isinstance(
                map_data,
                dict,
            )
            else "map-data.js is missing or invalid"
        ),
        category="Map",
    )

    map_counties = 0
    map_event_total = None
    invalid_fips: List[str] = []

    if isinstance(
        map_data,
        dict,
    ):

        labels = (
            map_data.get(
                "countyLabels"
            )
            or {}
        )

        map_counties = (
            len(labels)
            if isinstance(
                labels,
                dict,
            )
            else 0
        )

        if isinstance(
            labels,
            dict,
        ):
            invalid_fips = [
                str(k)
                for k in labels.keys()
                if not re.fullmatch(
                    r"\d{5}",
                    str(k),
                )
            ]

        check(
            "County FIPS keys valid",
            not invalid_fips
            and map_counties > 0,
            (
                f"{map_counties:,} county/county-equivalent FIPS keys; "
                f"{len(invalid_fips):,} invalid"
            ),
            category="Map",
        )

        map_event_total = (
            (
                map_data.get(
                    "declarationEventTotals"
                )
                or {}
            ).get("overall")
        )

        if isinstance(
            browse,
            list,
        ):

            check(
                "Map declaration total reconciles",
                map_event_total
                == len(browse),
                (
                    f"Map={map_event_total:,}; "
                    f"BROWSE={len(browse):,}"
                    if isinstance(
                        map_event_total,
                        int,
                    )
                    else "Map declaration total missing"
                ),
                category="Map",
            )

    # ------------------------------------------------------------
    # Latest declarations + homepage
    # ------------------------------------------------------------

    latest = js_file(
        latest_path,
        "LATEST_DECLARATIONS",
        None,
    )

    check(
        "latest-data.js parsed",
        isinstance(latest, list)
        and len(latest) > 0,
        (
            f"{len(latest):,} latest declarations available"
            if isinstance(latest, list)
            else "latest-data.js is missing or invalid"
        ),
        category="Website",
    )

    index_ok = check(
        "Homepage exists",
        index_path.exists()
        and index_path.stat().st_size > 1024,
        (
            "index.html is present"
            if index_path.exists()
            else "index.html is missing"
        ),
        category="Website",
    )

    if index_ok:

        idx = read_text(index_path)

        check(
            "Homepage update stamp matches build",
            data_date
            and data_date in idx,
            (
                f"Homepage contains build date {data_date}"
                if data_date
                and data_date in idx
                else (
                    "Homepage does not contain current "
                    f"data date {data_date}"
                )
            ),
            category="Freshness",
        )

    # ------------------------------------------------------------
    # Optional OpenFEMA rollups
    # ------------------------------------------------------------

    pa_total_obl = 0
    pa_total_proj = 0

    if isinstance(
        pa_national,
        dict,
    ):

        nums = [
            safe_num(v)
            for v in flatten_values(
                pa_national
            )
        ]

        nums = [
            v
            for v in nums
            if v is not None
        ]

        warning(
            "Public Assistance output present",
            bool(pa_national),
            (
                "PA_NATIONAL is populated"
                if pa_national
                else (
                    "PA_NATIONAL is empty "
                    "(upstream PA may have been unavailable)"
                )
            ),
            category="Assistance",
        )

        for key in (
            "totalObligated",
            "federalShareObligated",
            "obl",
            "total",
        ):

            n = (
                safe_num(
                    pa_national.get(
                        key
                    )
                )
                if isinstance(
                    pa_national,
                    dict,
                )
                else None
            )

            if (
                n is not None
                and n >= 0
            ):
                pa_total_obl = n
                break

        for key in (
            "totalProjects",
            "projects",
            "projectCount",
            "proj",
        ):

            n = (
                safe_num(
                    pa_national.get(
                        key
                    )
                )
                if isinstance(
                    pa_national,
                    dict,
                )
                else None
            )

            if (
                n is not None
                and n >= 0
            ):
                pa_total_proj = int(n)
                break

    if (
        isinstance(
            pa_county,
            dict,
        )
        and pa_county
    ):

        pa_bad = 0
        pa_jurisdictions = 0

        for state_rows in pa_county.values():

            if not isinstance(
                state_rows,
                dict,
            ):
                pa_bad += 1
                continue

            for vals in state_rows.values():

                pa_jurisdictions += 1

                if (
                    not isinstance(
                        vals,
                        list,
                    )
                    or len(vals) < 2
                ):
                    pa_bad += 1
                    continue

                obl = safe_num(
                    vals[0]
                )

                proj = safe_num(
                    vals[1]
                )

                if (
                    obl is None
                    or obl < 0
                    or proj is None
                    or proj < 0
                ):
                    pa_bad += 1

        check(
            "PA county rollups are nonnegative",
            pa_bad == 0,
            (
                f"{pa_jurisdictions:,} PA jurisdiction rollups; "
                f"{pa_bad:,} invalid"
            ),
            category="Assistance",
        )

    else:

        warning(
            "PA county rollups available",
            False,
            "PA_BY_COUNTY is empty",
            category="Assistance",
        )

        pa_jurisdictions = 0

    rollups = [
        (
            ROOT / "pa-timing.json",
            (),
            "PA obligation timing",
        ),
        (
            ROOT / "hma.json",
            (
                "fed",
                "n",
                "props",
            ),
            "Hazard Mitigation Assistance",
        ),
        (
            ROOT / "ia.json",
            (
                "reg",
                "app",
                "ihp",
                "rr",
                "rent",
                "ona",
            ),
            "Individual Assistance",
        ),
    ]

    rollup_counts: Dict[str, int] = {}

    for path, fields, label in rollups:

        if not path.exists():

            warning(
                f"{label} output available",
                False,
                (
                    f"{path.name} is absent; "
                    "this feature will degrade gracefully"
                ),
                category="Assistance",
            )

            rollup_counts[
                path.name
            ] = 0

            continue

        if not fields:

            obj = load_json(
                path,
                None,
            )

            ok = (
                isinstance(
                    obj,
                    dict,
                )
                and bool(obj)
            )

            count_rows = (
                sum(
                    len(v)
                    for v in obj.values()
                    if isinstance(
                        v,
                        dict,
                    )
                )
                if isinstance(
                    obj,
                    dict,
                )
                else 0
            )

            warning(
                f"{label} output parses",
                ok,
                (
                    f"{count_rows:,} jurisdiction rollups"
                    if ok
                    else f"{path.name} is invalid or empty"
                ),
                category="Assistance",
            )

            rollup_counts[
                path.name
            ] = count_rows

        else:

            ok, rows, bad = (
                validate_nonnegative_rollup(
                    path,
                    fields,
                    label,
                )
            )

            warning(
                f"{label} values valid",
                ok,
                (
                    f"{rows:,} jurisdiction rollups; "
                    f"{bad:,} invalid numeric record(s)"
                ),
                category="Assistance",
            )

            rollup_counts[
                path.name
            ] = rows

    # ------------------------------------------------------------
    # SVI / NRI context
    # ------------------------------------------------------------

    svi = js_file(
        svi_path,
        "COUNTY_SVI",
        None,
    )

    context_severity = (
        "error"
        if REQUIRE_CONTEXT
        else "warning"
    )

    check(
        "CDC SVI file available",
        isinstance(svi, dict)
        and len(svi) > 0,
        (
            f"{len(svi):,} county records in county-svi.js"
            if isinstance(
                svi,
                dict,
            )
            else "county-svi.js is missing or invalid"
        ),
        severity=context_severity,
        category="Risk context",
    )

    svi_bad_fips = 0
    svi_bad_values = 0

    if isinstance(
        svi,
        dict,
    ):

        for fips, rec in svi.items():

            if not re.fullmatch(
                r"\d{5}",
                str(fips),
            ):
                svi_bad_fips += 1

            if not isinstance(
                rec,
                dict,
            ):
                svi_bad_values += 1
                continue

            for fld in (
                "overall",
                "socioeconomic",
                "household",
                "minority",
                "housingTransportation",
            ):

                if (
                    fld in rec
                    and rec[fld] is not None
                ):

                    n = safe_num(
                        rec[fld]
                    )

                    if (
                        n is None
                        or n < 0
                        or n > 1
                    ):
                        svi_bad_values += 1

        check(
            "CDC SVI values valid",
            svi_bad_fips == 0
            and svi_bad_values == 0,
            (
                f"{svi_bad_fips:,} invalid FIPS; "
                f"{svi_bad_values:,} percentile value issue(s)"
            ),
            severity=context_severity,
            category="Risk context",
        )

    nri = js_file(
        nri_path,
        "COUNTY_NRI",
        None,
    )

    check(
        "FEMA NRI file available",
        isinstance(nri, dict)
        and len(nri) > 0,
        (
            f"{len(nri):,} county records in county-nri.js"
            if isinstance(
                nri,
                dict,
            )
            else "county-nri.js is missing or invalid"
        ),
        severity=context_severity,
        category="Risk context",
    )

    nri_bad_fips = 0
    nri_bad_values = 0

    if isinstance(
        nri,
        dict,
    ):

        for fips, rec in nri.items():

            if not re.fullmatch(
                r"\d{5}",
                str(fips),
            ):
                nri_bad_fips += 1

            if not isinstance(
                rec,
                dict,
            ):
                nri_bad_values += 1
                continue

            for fld in (
                "riskScore",
                "ealScore",
                "soviScore",
                "reslScore",
            ):

                if (
                    fld in rec
                    and rec[fld] is not None
                    and safe_num(
                        rec[fld]
                    ) is None
                ):
                    nri_bad_values += 1

        check(
            "FEMA NRI values parse",
            nri_bad_fips == 0
            and nri_bad_values == 0,
            (
                f"{nri_bad_fips:,} invalid FIPS; "
                f"{nri_bad_values:,} score parse issue(s)"
            ),
            severity=context_severity,
            category="Risk context",
        )

    # ------------------------------------------------------------
    # Jurisdiction pages
    # ------------------------------------------------------------

    loc_index = parse_locality_index(
        locality_index_path
    )

    jur_severity = (
        "error"
        if REQUIRE_JURISDICTIONS
        else "warning"
    )

    check(
        "Jurisdiction search index available",
        isinstance(
            loc_index,
            list,
        )
        and len(loc_index) > 0,
        (
            f"{len(loc_index):,} generated jurisdiction entries"
            if isinstance(
                loc_index,
                list,
            )
            else "locality-index.js is missing or invalid"
        ),
        severity=jur_severity,
        category="Jurisdiction pages",
    )

    jurisdiction_count = 0
    missing_pages = 0
    duplicate_urls = 0
    citation_missing = 0

    if isinstance(
        loc_index,
        list,
    ):

        jurisdiction_count = len(
            loc_index
        )

        seen_urls = set()

        for row in loc_index:

            if (
                not isinstance(
                    row,
                    list,
                )
                or len(row) < 4
            ):
                missing_pages += 1
                continue

            url = str(
                row[3]
                or ""
            ).lstrip("/")

            if not url:
                missing_pages += 1
                continue

            if url in seen_urls:
                duplicate_urls += 1

            seen_urls.add(url)

            p = ROOT / url

            if not p.exists():
                missing_pages += 1
                continue

            if (
                REQUIRE_CITATIONS
                or p.exists()
            ):

                try:
                    page = read_text(p)
                except Exception:
                    citation_missing += 1
                    continue

                if (
                    "Cite this profile"
                    not in page
                    and 'id="cite"'
                    not in page
                    and 'class="citation"'
                    not in page
                ):
                    citation_missing += 1

        check(
            "Jurisdiction URLs are unique",
            duplicate_urls == 0,
            (
                f"{jurisdiction_count:,} entries; "
                f"{duplicate_urls:,} duplicate URL(s)"
            ),
            severity=jur_severity,
            category="Jurisdiction pages",
        )

        check(
            "Jurisdiction pages exist",
            missing_pages == 0,
            (
                f"{jurisdiction_count - missing_pages:,}/"
                f"{jurisdiction_count:,} indexed jurisdiction files found"
            ),
            severity=jur_severity,
            category="Jurisdiction pages",
        )

        citation_severity = (
            "error"
            if REQUIRE_CITATIONS
            else "warning"
        )

        check(
            "Jurisdiction citation blocks present",
            citation_missing == 0,
            (
                f"{jurisdiction_count - citation_missing:,}/"
                f"{jurisdiction_count:,} pages contain a citation block"
            ),
            severity=citation_severity,
            category="Jurisdiction pages",
        )

    # ------------------------------------------------------------
    # Old Example County placeholder
    # ------------------------------------------------------------

    if jurisdiction_landing.exists():

        landing = read_text(
            jurisdiction_landing
        )

        check(
            "No Example County placeholder",
            "Example County"
            not in landing,
            (
                "jurisdiction.html contains no Example County placeholder"
                if "Example County"
                not in landing
                else (
                    "Example County placeholder text "
                    "found in jurisdiction.html"
                )
            ),
            category="Website",
        )

    else:

        warning(
            "Jurisdiction landing page available",
            False,
            "jurisdiction.html is missing",
            category="Website",
        )

    # ------------------------------------------------------------
    # Sitemap
    # ------------------------------------------------------------

    sitemap = ROOT / "sitemap.xml"

    if sitemap.exists():

        sm = read_text(
            sitemap
        )

        locs = re.findall(
            r"<loc>(.*?)</loc>",
            sm,
            flags=re.S,
        )

        dup_sitemap = (
            len(locs)
            - len(set(locs))
        )

        check(
            "Sitemap has no duplicate URLs",
            dup_sitemap == 0,
            (
                f"{len(locs):,} sitemap URLs; "
                f"{dup_sitemap:,} duplicate(s)"
            ),
            category="Website",
        )

    else:

        warning(
            "Sitemap available",
            False,
            "sitemap.xml is missing",
            category="Website",
        )

    # ------------------------------------------------------------
    # Freshness
    # ------------------------------------------------------------

    age_days = None

    if valid_iso_day(
        data_date
    ):

        age_days = (
            TODAY
            - _dt.date.fromisoformat(
                data_date
            )
        ).days

        check(
            "Data freshness acceptable",
            0 <= age_days <= 8,
            (
                f"Data date is {age_days} day(s) old; "
                "weekly target is <= 8 days"
            ),
            category="Freshness",
        )

    states_territories = (
        len(locality)
        if isinstance(
            locality,
            dict,
        )
        else 0
    )

    localities = (
        sum(
            len(v)
            for v in locality.values()
            if isinstance(
                v,
                list,
            )
        )
        if isinstance(
            locality,
            dict,
        )
        else 0
    )

    denial_count = (
        len(denials)
        if isinstance(
            denials,
            list,
        )
        else 0
    )

    # ------------------------------------------------------------
    # Best-effort PA totals from build.py schema
    # ------------------------------------------------------------

    if isinstance(
        pa_national,
        dict,
    ):

        for path in (
            ("totalObligated",),
            ("federalShareObligated",),
            (
                "summary",
                "totalObligated",
            ),
            (
                "summary",
                "federalShareObligated",
            ),
            (
                "totals",
                "obl",
            ),
        ):

            cur: Any = pa_national

            for part in path:

                if (
                    not isinstance(
                        cur,
                        dict,
                    )
                    or part not in cur
                ):
                    cur = None
                    break

                cur = cur[part]

            n = safe_num(cur)

            if (
                n is not None
                and n >= 0
            ):
                pa_total_obl = n
                break

        for path in (
            ("totalProjects",),
            ("projectCount",),
            ("projects",),
            (
                "summary",
                "projects",
            ),
            (
                "totals",
                "proj",
            ),
        ):

            cur = pa_national

            for part in path:

                if (
                    not isinstance(
                        cur,
                        dict,
                    )
                    or part not in cur
                ):
                    cur = None
                    break

                cur = cur[part]

            n = safe_num(cur)

            if (
                n is not None
                and n >= 0
            ):
                pa_total_proj = int(n)
                break

    return {
        "dataDate": data_date,
        "ageDays": age_days,
        "declarationsCurrent": current_total,
        "declarationsCompletedFY": completed,
        "denials": denial_count,
        "statesTerritories": states_territories,
        "localities": localities,
        "mapCounties": map_counties,
        "mapDeclarationEvents": map_event_total,
        "jurisdictionPages": jurisdiction_count,
        "paJurisdictions": pa_jurisdictions,
        "paTotalObligated": pa_total_obl,
        "paProjects": pa_total_proj,
        "paTimingJurisdictions": rollup_counts.get(
            "pa-timing.json",
            0,
        ),
        "hmaJurisdictions": rollup_counts.get(
            "hma.json",
            0,
        ),
        "iaJurisdictions": rollup_counts.get(
            "ia.json",
            0,
        ),
        "sviCounties": (
            len(svi)
            if isinstance(
                svi,
                dict,
            )
            else 0
        ),
        "nriCounties": (
            len(nri)
            if isinstance(
                nri,
                dict,
            )
            else 0
        ),
        "sviRelease": detect_static_release(
            svi_path,
            (
                "2022"
                if svi_path.exists()
                else ""
            ),
        ),
        "nriRelease": detect_static_release(
            nri_path,
            "",
        ),
    }


def build_sources(
    metrics: Dict[str, Any],
) -> List[Dict[str, Any]]:

    def source(
        name: str,
        file: str,
        records: Any,
        required: bool,
        release: str = "",
        note: str = "",
    ) -> Dict[str, Any]:

        p = (
            ROOT / file
            if file
            else None
        )

        present = (
            bool(
                p
                and p.exists()
            )
            if file
            else True
        )

        n = safe_num(
            records
        )

        populated = (
            present
            and (
                n is None
                or n > 0
            )
        )

        if populated:
            state = "current"

        elif required:
            state = "unavailable"

        else:
            state = "warning"

        return {
            "name": name,
            "status": state,
            "file": file,
            "records": records,
            "release": release,
            "hash": (
                file_hash(p)
                if p
                else ""
            ),
            "note": note,
        }

    return [
        source(
            "FEMA Disaster Declarations Summaries",
            "data.js",
            metrics.get(
                "declarationsCurrent"
            ),
            True,
            "OpenFEMA v2",
            (
                "Federal declaration history "
                "and jurisdiction assignments."
            ),
        ),

        source(
            "FEMA Declaration Denials",
            "data.js",
            metrics.get(
                "denials"
            ),
            False,
            "OpenFEMA v1",
            (
                "Turndown/denial records; the build can continue "
                "if the upstream endpoint is unavailable."
            ),
        ),

        source(
            "FEMA Public Assistance",
            "data.js",
            metrics.get(
                "paJurisdictions"
            ),
            False,
            "OpenFEMA v2",
            (
                "Public Assistance project "
                "and county rollups."
            ),
        ),

        source(
            "FEMA PA Grant Award Activities",
            "pa-timing.json",
            metrics.get(
                "paTimingJurisdictions"
            ),
            False,
            "OpenFEMA v2",
            (
                "Obligation timing used "
                "on jurisdiction profiles."
            ),
        ),

        source(
            "FEMA Hazard Mitigation Assistance",
            "hma.json",
            metrics.get(
                "hmaJurisdictions"
            ),
            False,
            "OpenFEMA v4",
            (
                "Funded mitigation project rollups."
            ),
        ),

        source(
            "FEMA Individual Assistance",
            "ia.json",
            metrics.get(
                "iaJurisdictions"
            ),
            False,
            "OpenFEMA v2",
            (
                "Housing Assistance owner/renter rollups."
            ),
        ),

        source(
            "CDC/ATSDR Social Vulnerability Index",
            "county-svi.js",
            metrics.get(
                "sviCounties"
            ),
            REQUIRE_CONTEXT,
            (
                metrics.get(
                    "sviRelease"
                )
                or ""
            ),
            (
                "Static county context joined "
                "by five-digit FIPS/GEOID."
            ),
        ),

        source(
            "FEMA National Risk Index",
            "county-nri.js",
            metrics.get(
                "nriCounties"
            ),
            REQUIRE_CONTEXT,
            (
                metrics.get(
                    "nriRelease"
                )
                or ""
            ),
            (
                "Static county risk context joined "
                "by five-digit FIPS/GEOID."
            ),
        ),
    ]


def render_status_html(
    status: Dict[str, Any],
) -> str:

    e = html.escape

    release = e(
        str(
            status[
                "release"
            ]
        )
    )

    overall = status[
        "status"
    ]

    metrics = status.get(
        "metrics",
        {},
    )

    sources = status.get(
        "sources",
        [],
    )

    checks = (
        status.get(
            "validation",
            {},
        ).get(
            "checks",
            [],
        )
    )

    badge_class = (
        "ok"
        if overall == "passed"
        else "warn"
    )

    badge_text = (
        "All critical checks passed"
        if overall == "passed"
        else "Passed with warnings"
    )

    def fmt(
        v: Any,
    ) -> str:

        if (
            v is None
            or v == ""
        ):
            return "—"

        if isinstance(
            v,
            float,
        ):
            return (
                f"{v:,.0f}"
                if v.is_integer()
                else f"{v:,.1f}"
            )

        if isinstance(
            v,
            int,
        ):
            return f"{v:,}"

        return e(
            str(v)
        )

    source_rows = []

    for s in sources:

        st = s.get(
            "status",
            "warning",
        )

        dot = "●"

        source_rows.append(
            "<tr>"
            f"<td><span class='dot {e(st)}'>{dot}</span>"
            f"{e(str(s.get('name','')))}</td>"
            f"<td>{e(str(s.get('release') or '—'))}</td>"
            f"<td>{fmt(s.get('records'))}</td>"
            f"<td>{e(st.title())}</td>"
            "</tr>"
        )

    check_rows = []

    for c in checks:

        st = c.get(
            "status",
            "warn",
        )

        check_rows.append(
            "<tr>"
            f"<td><span class='dot {e(st)}'>●</span>"
            f"{e(str(c.get('name','')))}</td>"
            f"<td>{e(str(c.get('category','')))}</td>"
            f"<td>{e(str(c.get('detail','')))}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Disaster Data | Data Status</title>
<meta name="description" content="Current DisasterData.io release, source status, and automated build validation results.">
<link rel="canonical" href="https://disasterdata.io/status.html">
<style>
:root{{--paper:#f6f1e7;--card:#fffdf7;--ink:#1d1813;--muted:#6b6357;--rule:#ddd3bf;--teal:#004c53;--green:#2e6a45;--amber:#9a661e;--red:#9e3b32}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--paper);color:var(--ink);font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.55}}
a{{color:var(--teal)}}
.wrap{{max-width:1000px;margin:auto;padding:42px 22px 64px}}
.eyebrow{{font-size:.74rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--teal)}}
h1{{font-family:Georgia,serif;font-weight:500;font-size:clamp(2.1rem,6vw,3.8rem);line-height:1;margin:.4rem 0 .8rem;color:var(--teal)}}
.lede{{max-width:70ch;color:var(--muted);font-size:1.05rem}}
.release{{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:24px 0}}
.pill{{border-radius:999px;padding:7px 12px;font-size:.82rem;font-weight:700;background:#d7e9ea;color:var(--teal)}}
.pill.ok{{background:#dcebdd;color:var(--green)}}
.pill.warn{{background:#f6e8c9;color:var(--amber)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:25px 0 35px}}
.metric{{background:var(--card);border:1px solid var(--rule);border-radius:12px;padding:15px}}
.metric b{{display:block;font-family:Georgia,serif;font-size:1.55rem;color:var(--teal)}}
.metric span{{font-size:.78rem;color:var(--muted)}}
h2{{font-family:Georgia,serif;color:var(--teal);margin-top:36px}}
.table{{overflow:auto;border:1px solid var(--rule);border-radius:12px;background:var(--card)}}
table{{border-collapse:collapse;width:100%;min-width:650px;font-size:.88rem}}
th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid var(--rule);vertical-align:top}}
th{{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);background:#faf6ec}}
tr:last-child td{{border-bottom:0}}
.dot{{margin-right:8px}}
.dot.current,.dot.pass{{color:var(--green)}}
.dot.warning,.dot.warn{{color:var(--amber)}}
.dot.unavailable,.dot.fail{{color:var(--red)}}
footer{{margin-top:42px;padding-top:20px;border-top:1px solid var(--rule);font-size:.82rem;color:var(--muted)}}
</style>
</head>
<body>
<script src="/nav.js"></script>

<main class="wrap">

<div class="eyebrow">
Build, validation &amp; release
</div>

<h1>
Data status
</h1>

<p class="lede">
This page is generated from the same automated release gate that validates DisasterData.io before a successful data build is stamped for publication.
</p>

<div class="release">

<span class="pill">
Release {release}
</span>

<span class="pill {badge_class}">
{e(badge_text)}
</span>

<span class="pill">
Built {e(str(status.get('builtAt','')))}
</span>

</div>

<div class="grid">

<div class="metric">
<b>{fmt(metrics.get('declarationsCurrent'))}</b>
<span>current declarations</span>
</div>

<div class="metric">
<b>{fmt(metrics.get('jurisdictionPages') or metrics.get('localities'))}</b>
<span>jurisdiction profiles/index entries</span>
</div>

<div class="metric">
<b>{fmt(metrics.get('mapCounties'))}</b>
<span>county map geographies</span>
</div>

<div class="metric">
<b>{fmt(metrics.get('sviCounties'))}</b>
<span>SVI county records</span>
</div>

<div class="metric">
<b>{fmt(metrics.get('nriCounties'))}</b>
<span>NRI county records</span>
</div>

</div>

<h2>
Source status
</h2>

<div class="table">

<table>

<thead>
<tr>
<th>Dataset</th>
<th>Release / API</th>
<th>Records</th>
<th>Status</th>
</tr>
</thead>

<tbody>
{''.join(source_rows)}
</tbody>

</table>

</div>

<h2>
Automated validation
</h2>

<div class="table">

<table>

<thead>
<tr>
<th>Check</th>
<th>Area</th>
<th>Result</th>
</tr>
</thead>

<tbody>
{''.join(check_rows)}
</tbody>

</table>

</div>

<footer>
Disaster Data &middot;
Release {release} &middot;
<a href="/about.html">About and methodology</a>
&middot;
<a href="/data-status.json">Machine-readable status JSON</a>
</footer>

</main>

</body>
</html>"""


def main() -> int:

    print(
        "\n════════ DISASTERDATA RELEASE GATE ════════"
    )

    print(
        f"Root: {ROOT}"
    )

    metrics = validate()

    failed = [
        c
        for c in CHECKS
        if c["status"] == "fail"
    ]

    warned = [
        c
        for c in CHECKS
        if c["status"] == "warn"
    ]

    passed = [
        c
        for c in CHECKS
        if c["status"] == "pass"
    ]

    # Always write the diagnostic report.
    # A failed CI run should not publish a new
    # data-status.json/release-state.json,
    # but its artifact/log can still explain why.

    candidate, candidate_build = next_release()

    report = {
        "schemaVersion": 1,
        "releaseCandidate": candidate,
        "builtAt": NOW_UTC,
        "status": (
            "failed"
            if failed
            else (
                "passed-with-warnings"
                if warned
                else "passed"
            )
        ),
        "summary": {
            "passed": len(passed),
            "warnings": len(warned),
            "failed": len(failed),
        },
        "metrics": metrics,
        "checks": CHECKS,
    }

    BUILD_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    for c in CHECKS:

        icon = {
            "pass": "PASS",
            "warn": "WARN",
            "fail": "FAIL",
        }[
            c["status"]
        ]

        print(
            f"[{icon}] "
            f"{c['name']}: "
            f"{c['detail']}"
        )

    print(
        "──────────────────────────────────────────"
    )

    print(
        f"PASS {len(passed)}  "
        f"WARN {len(warned)}  "
        f"FAIL {len(failed)}"
    )

    if failed:

        print(
            "\nRELEASE REFUSED. "
            "Fix the failed checks above; "
            "release-state.json and the public "
            "status files were not advanced."
        )

        return 1

    release = candidate
    build_no = candidate_build

    previous = previous_metrics()

    changes = {
        "declarationsCurrent": delta(
            metrics.get(
                "declarationsCurrent"
            ),
            previous.get(
                "declarationsCurrent"
            ),
        ),

        "jurisdictionPages": delta(
            metrics.get(
                "jurisdictionPages"
            ),
            previous.get(
                "jurisdictionPages"
            ),
        ),

        "mapCounties": delta(
            metrics.get(
                "mapCounties"
            ),
            previous.get(
                "mapCounties"
            ),
        ),

        "sviCounties": delta(
            metrics.get(
                "sviCounties"
            ),
            previous.get(
                "sviCounties"
            ),
        ),

        "nriCounties": delta(
            metrics.get(
                "nriCounties"
            ),
            previous.get(
                "nriCounties"
            ),
        ),
    }

    key_files = [
        ROOT / "data.js",
        ROOT / "map-data.js",
        ROOT / "latest-data.js",
        ROOT / "pa-timing.json",
        ROOT / "hma.json",
        ROOT / "ia.json",
        ROOT / "county-svi.js",
        ROOT / "county-nri.js",
        ROOT / "locality-index.js",
        ROOT / "sitemap.xml",
    ]

    fp = fingerprint(
        key_files
    )

    status = {
        "schemaVersion": 1,
        "release": release,
        "status": (
            "passed"
            if not warned
            else "passed-with-warnings"
        ),
        "builtAt": NOW_UTC,
        "dataDate": metrics.get(
            "dataDate"
        ),
        "fingerprint": fp,
        "metrics": metrics,
        "changesFromPreviousRelease": changes,
        "sources": build_sources(
            metrics
        ),
        "validation": {
            "passed": len(passed),
            "warnings": len(warned),
            "failed": 0,
            "checks": CHECKS,
        },
    }

    PUBLIC_STATUS.write_text(
        json.dumps(
            status,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    STATUS_HTML.write_text(
        render_status_html(
            status
        ),
        encoding="utf-8",
    )

    RELEASE_STATE.write_text(
        json.dumps(
            {
                "release": release,
                "date": TODAY_ISO,
                "build": build_no,
                "builtAt": NOW_UTC,
                "fingerprint": fp,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"\nRELEASE APPROVED: {release}"
    )

    print(
        "  data-status.json  "
        "-> public machine-readable status"
    )

    print(
        "  status.html       "
        "-> public human-readable status page"
    )

    print(
        "  build-report.json "
        "-> complete validation report"
    )

    print(
        "  release-state.json "
        "-> successful release counter/state"
    )

    if (
        changes.get(
            "declarationsCurrent"
        )
        is not None
    ):

        print(
            "  change vs previous: "
            "declarations "
            f"{delta_text(changes['declarationsCurrent'])}"
        )

    print(
        "══════════════════════════════════════════\n"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )