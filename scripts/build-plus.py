#!/usr/bin/env python3
"""Build DisasterData Plus coverage pages for one or more states.

This builder is deliberately safe to run nationally. It creates a page for
every selected state, reads any state pipeline outputs already present under
``plus/<state-slug>/``, and labels incomplete coverage honestly. It does not
pretend that a missing state adapter means the state has no emergencies.

Three layers are shown per state, kept visually and structurally distinct:
  1. Federal FEMA declarations, read from data/decl-index/<ABBR>.json
  2. State-issued emergency actions, read from the state's own action CSV
  3. NOAA/NWS Storm Events evidence, read from the state's eo_storm_join.py
     output (individual matched events, not just counts)

A combined event crosswalk then joins state actions to their NOAA matches and,
where one exists within the matching window, a federal declaration. When no
federal declaration falls in that window the crosswalk says so explicitly
("No corresponding federal declaration found") rather than leaving a blank
cell, since silence would be read as "not checked" rather than "checked, none
found."

The crosswalk here is an automated proximity match on date and state, exactly
like eo_storm_join.py's own NOAA matching. It is not the same thing as an
accepted, human-reviewed link, and the page says so. If a stricter
reviewed-only crosswalk is wanted later, gate this section on an accepted
review file the way the original state-evidence design proposed, rather than
publishing every automated candidate as-is.

Examples (run from the repository root):

    python scripts/plus/build-plus.py --states all
    python scripts/plus/build-plus.py --states VA,NY,NJ,PA
    python scripts/plus/build-plus.py --states VA --collect --join-storms

An optional state adapter lives in the corresponding state directory and must
expose ``collect(workdir, scripts_dir) -> (csv_path, coverage_note)``. Virginia's
existing ``plus/virginia/virginia.py`` already follows that contract.
"""

from __future__ import annotations

import argparse
import csv
import html
import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = SCRIPT_DIR / "state-manifest.json"

# How far a state action's signing date may sit from a federal declaration's
# incident window and still be offered as a candidate match. Wider than
# eo_storm_join.py's own NOAA window (3 days) because a federal declaration
# is often filed weeks after the state emergency that preceded it.
FEDERAL_MATCH_WINDOW_DAYS = 21


def load_manifest(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    states = payload.get("states", [])
    if len(states) != 50:
        raise ValueError(f"Expected 50 states in {path}; found {len(states)}")
    required = {"abbreviation", "name", "slug", "adapter_status"}
    seen = set()
    for state in states:
        missing = required.difference(state)
        if missing:
            raise ValueError(
                f"Manifest entry is missing {', '.join(sorted(missing))}: {state}"
            )
        abbreviation = state["abbreviation"].upper()
        if abbreviation in seen:
            raise ValueError(f"Duplicate state abbreviation in manifest: {abbreviation}")
        seen.add(abbreviation)
    return states


def select_states(states: list[dict], requested: str) -> list[dict]:
    if requested.strip().lower() == "all":
        return states
    lookup = {}
    for state in states:
        lookup[state["abbreviation"].upper()] = state
        lookup[state["name"].lower()] = state
        lookup[state["slug"].lower()] = state
    selected = []
    unknown = []
    for token in requested.split(","):
        key = token.strip()
        if not key:
            continue
        state = lookup.get(key.upper()) or lookup.get(key.lower())
        if state is None:
            unknown.append(key)
        elif state not in selected:
            selected.append(state)
    if unknown:
        raise ValueError("Unknown state selection: " + ", ".join(unknown))
    if not selected:
        raise ValueError("No states selected")
    return selected


def import_adapter(path: Path):
    module_name = "disasterdata_plus_adapter_" + path.parent.name.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "collect"):
        raise RuntimeError(f"Adapter does not expose collect(): {path}")
    return module


def candidate_action_files(state: dict) -> list[str]:
    configured = state.get("action_files", [])
    defaults = [
        "declarations_for_join_2002_present.csv",
        "declarations_for_join.csv",
        f"{state['abbreviation'].lower()}_weather_emergency_actions_2002_2026.csv",
        f"{state['abbreviation'].lower()}_weather_emergency_actions.csv",
        "state_actions.csv",
    ]
    return list(dict.fromkeys(configured + defaults))


def locate_first(state_dir: Path, names: list[str]) -> Path | None:
    for name in names:
        path = state_dir / name
        if path.exists() and path.is_file():
            return path
    return None


def read_csv_rows(path: Path | None) -> list[dict]:
    if path is None:
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean(value) -> str:
    return str(value or "").strip()


def normalized_action(row: dict, abbreviation: str) -> dict:
    action_number = clean(
        row.get("action_number")
        or row.get("eo_number")
        or row.get("order_number")
        or row.get("proclamation_number")
    )
    signed = clean(
        row.get("date_signed")
        or row.get("issued_date")
        or row.get("date")
    )
    title = clean(
        row.get("event_description")
        or row.get("title")
        or row.get("subject")
        or row.get("short_title")
    )
    source_url = clean(
        row.get("archive_record_url")
        or row.get("source_url")
        or row.get("detail_url")
        or row.get("document_url")
    )
    declaration_id = clean(row.get("declaration_id"))
    if not declaration_id:
        declaration_id = "-".join(
            part for part in [abbreviation, action_number, signed] if part
        )
    return {
        "state": abbreviation,
        "declaration_id": declaration_id,
        "action_number": action_number,
        "title": title,
        "date_signed": signed,
        "action_type": clean(row.get("action_type") or "declaration"),
        "governor": clean(row.get("governor")),
        "source_url": source_url,
    }


def load_state_actions(state: dict, state_dir: Path) -> tuple[list[dict], Path | None]:
    path = locate_first(state_dir, candidate_action_files(state))
    rows = [normalized_action(row, state["abbreviation"]) for row in read_csv_rows(path)]
    unique = {}
    for row in rows:
        key = row["declaration_id"] or json.dumps(row, sort_keys=True)
        unique[key] = row
    actions = sorted(
        unique.values(), key=lambda row: row.get("date_signed", ""), reverse=True
    )
    return actions, path


def ensure_declaration_id_column(action_path: Path, abbreviation: str) -> Path:
    """Guarantee the CSV handed to eo_storm_join.py has an explicit
    declaration_id column, computed with the exact same formula
    normalized_action() uses above.

    Without this, a state whose source CSV has no declaration_id column ends
    up with TWO independently-synthesized ids: this file's own
    normalized_action() produces one shape (state-prefixed, e.g.
    "NJ-EO-5-2026-03-10"), while eo_storm_join.py's own internal fallback
    (declarations['eo_number'] + '-' + declarations['date_signed'], with no
    state prefix) produces a different one ("EO-5-2026-03-10"). Those never
    match, so build_crosswalk()'s lookup by declaration_id silently finds
    zero NOAA matches for every action in that state, even when
    eo_storm_join.py genuinely found real ones. Virginia is unaffected today
    only because its own CSV already supplies a real declaration_id column;
    this only matters once a state adapter's output does not.

    Writes a sibling file rather than mutating the original, and returns the
    original path unchanged if a declaration_id column is already present.
    """
    rows = read_csv_rows(action_path)
    if not rows or "declaration_id" in rows[0]:
        return action_path
    for row in rows:
        row["declaration_id"] = normalized_action(row, abbreviation)["declaration_id"]
    enriched_path = action_path.with_name(action_path.stem + "_with_id.csv")
    with enriched_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return enriched_path


def count_rows(path: Path | None) -> int:
    return len(read_csv_rows(path)) if path else 0


def load_federal_declarations(repo_root: Path, abbreviation: str) -> list[dict]:
    path = repo_root / "data" / "decl-index" / f"{abbreviation.upper()}.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    records = payload if isinstance(payload, list) else payload.get("declarations", [])
    return sorted(records, key=lambda row: row.get("date", "") or row.get("begin", ""), reverse=True)


def parse_iso_date(value) -> date | None:
    text = clean(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_storm_match_rows(state_dir: Path) -> tuple[list[dict], Path | None]:
    path = locate_first(
        state_dir,
        [
            "eo_storm_matches_2002_present_filtered.csv",
            "eo_storm_matches.csv",
            "matches.csv",
        ],
    )
    return read_csv_rows(path), path


def load_severity_rows(state_dir: Path) -> tuple[list[dict], Path | None]:
    path = locate_first(
        state_dir,
        [
            "eo_storm_severity_2002_present_filtered.csv",
            "eo_storm_severity_summary.csv",
            "severity_resolved.csv",
        ],
    )
    return read_csv_rows(path), path


def group_by_declaration(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        key = clean(row.get("declaration_id"))
        if not key:
            continue
        grouped.setdefault(key, []).append(row)
    return grouped


def state_metrics(
    state: dict,
    actions: list[dict],
    federal_declarations: list[dict],
    storm_rows: list[dict],
    severity_rows: list[dict],
) -> dict:
    return {
        "action_count": len(actions),
        "federal_declaration_count": len(federal_declarations),
        "storm_match_rows": len(storm_rows),
        "severity_rows": len(severity_rows),
    }


def find_federal_match(action: dict, federal_declarations: list[dict]) -> dict | None:
    signed = parse_iso_date(action.get("date_signed"))
    if signed is None or not federal_declarations:
        return None
    window = timedelta(days=FEDERAL_MATCH_WINDOW_DAYS)
    best = None
    best_gap = None
    for declaration in federal_declarations:
        begin = parse_iso_date(declaration.get("begin")) or parse_iso_date(declaration.get("date"))
        end = parse_iso_date(declaration.get("end")) or begin
        if begin is None:
            continue
        if begin - window <= signed <= end + window:
            gap = min(abs((signed - begin).days), abs((signed - end).days))
            if best_gap is None or gap < best_gap:
                best, best_gap = declaration, gap
    return best


def build_crosswalk(
    actions: list[dict],
    federal_declarations: list[dict],
    storm_rows_by_declaration: dict[str, list[dict]],
) -> list[dict]:
    rows = []
    for action in actions:
        matches = storm_rows_by_declaration.get(action["declaration_id"], [])
        areas = sorted({clean(row.get("CZ_NAME")) for row in matches if clean(row.get("CZ_NAME"))})
        federal = find_federal_match(action, federal_declarations)
        rows.append(
            {
                "action": action,
                "noaa_match_count": len(matches),
                "noaa_areas": areas,
                "federal_declaration": federal,
                "federal_status": (
                    "matched" if federal is not None else "no_federal_declaration_found"
                ),
            }
        )
    return rows


def run_storm_pipeline(state: dict, state_dir: Path, action_path: Path) -> str:
    join_script = state_dir / "eo_storm_join.py"
    if not join_script.exists():
        return "Storm join skipped: eo_storm_join.py is not installed in the state folder"
    matches = state_dir / "eo_storm_matches.csv"
    severity = state_dir / "eo_storm_severity_summary.csv"
    cmd = [
        sys.executable,
        str(join_script),
        "--declarations",
        str(action_path),
        "--state",
        state["name"].upper(),
        "--out",
        str(matches),
        "--severity-out",
        str(severity),
    ]
    result = subprocess.run(cmd, cwd=str(state_dir), capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return f"Storm join failed with exit code {result.returncode}"

    resolver = state_dir / "resolve_zones_to_counties.py"
    zone_files = sorted(state_dir.glob("bp*.dbx"))
    if resolver.exists() and zone_files and severity.exists():
        resolved = state_dir / "severity_resolved.csv"
        resolve_cmd = [
            sys.executable,
            str(resolver),
            "--input",
            str(severity),
            "--zone-file",
            str(zone_files[-1]),
            "--out",
            str(resolved),
            "--state",
            state["abbreviation"],
        ]
        resolve_result = subprocess.run(
            resolve_cmd, cwd=str(state_dir), capture_output=True, text=True
        )
        if resolve_result.stdout:
            print(resolve_result.stdout)
        if resolve_result.returncode != 0:
            if resolve_result.stderr:
                print(resolve_result.stderr, file=sys.stderr)
            return f"Storm join completed; zone resolution failed with exit code {resolve_result.returncode}"
        return "Storm join and forecast-zone resolution completed"
    return "Storm join completed; forecast-zone resolution skipped because its script or crosswalk was unavailable"


def coverage_label(state: dict, actions: list[dict], collection_note: str) -> str:
    if collection_note:
        return collection_note
    if actions and state["adapter_status"] == "implemented":
        return state.get("coverage_note") or "State-action data available"
    if actions:
        return "Imported state-action data available; adapter validation pending"
    if state["adapter_status"] == "implemented":
        return "Adapter available; no cached action file found"
    if state["adapter_status"] == "planned":
        return "State-source adapter planned; state-action coverage not yet available"
    return "State-source adapter not yet implemented"


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def action_rows(actions: list[dict]) -> str:
    if not actions:
        return (
            '<tr><td colspan="5" class="empty">No verified state-action records '
            "have been loaded for this state yet.</td></tr>"
        )
    output = []
    for action in actions[:100]:
        source = esc(action["source_url"])
        title = esc(action["title"] or "Untitled action")
        title_cell = f'<a href="{source}">{title}</a>' if source else title
        output.append(
            "<tr>"
            f"<td>{esc(action['date_signed'])}</td>"
            f"<td>{esc(action['action_number'])}</td>"
            f"<td>{title_cell}</td>"
            f"<td>{esc(action['action_type'])}</td>"
            f"<td>{esc(action['governor'])}</td>"
            "</tr>"
        )
    return "\n".join(output)


def federal_declaration_rows(federal_declarations: list[dict]) -> str:
    if not federal_declarations:
        return (
            '<tr><td colspan="6" class="empty">No federal FEMA declarations are loaded '
            "for this state yet.</td></tr>"
        )
    output = []
    for declaration in federal_declarations[:200]:
        number = esc(declaration.get("number") or declaration.get("id"))
        title = esc(declaration.get("title") or declaration.get("eventName") or "Untitled declaration")
        output.append(
            "<tr>"
            f"<td>{esc(declaration.get('date') or declaration.get('begin'))}</td>"
            f"<td>{number}</td>"
            f"<td>{esc(declaration.get('type'))}</td>"
            f"<td>{title}</td>"
            f"<td>{esc(declaration.get('incidentType'))}</td>"
            f"<td>{esc(declaration.get('begin'))} to {esc(declaration.get('end'))}</td>"
            "</tr>"
        )
    return "\n".join(output)


def noaa_event_rows(storm_rows: list[dict]) -> str:
    if not storm_rows:
        return (
            '<tr><td colspan="6" class="empty">No matched NOAA/NWS Storm Events '
            "are loaded for this state yet.</td></tr>"
        )
    output = []
    for row in storm_rows[:300]:
        output.append(
            "<tr>"
            f"<td>{esc(row.get('BEGIN_DATE_TIME'))}</td>"
            f"<td>{esc(row.get('CZ_NAME'))}</td>"
            f"<td>{esc(row.get('area_type'))}</td>"
            f"<td>{esc(row.get('EVENT_TYPE'))}</td>"
            f"<td>{esc(row.get('DEATHS_DIRECT'))} / {esc(row.get('INJURIES_DIRECT'))}</td>"
            f"<td>{esc(row.get('DAMAGE_PROPERTY'))}</td>"
            "</tr>"
        )
    return "\n".join(output)


def crosswalk_rows(crosswalk: list[dict]) -> str:
    if not crosswalk:
        return (
            '<tr><td colspan="4" class="empty">No state actions are loaded to cross-'
            "reference yet.</td></tr>"
        )
    output = []
    for row in crosswalk:
        action = row["action"]
        title = esc(action["title"] or "Untitled action")
        areas = ", ".join(row["noaa_areas"][:8]) if row["noaa_areas"] else "None matched"
        if row["federal_status"] == "matched":
            federal = row["federal_declaration"]
            federal_cell = esc(federal.get("number") or federal.get("id"))
        else:
            federal_cell = '<span class="empty">No corresponding federal declaration found</span>'
        output.append(
            "<tr>"
            f"<td>{esc(action['date_signed'])} &middot; {title}</td>"
            f"<td>{row['noaa_match_count']}</td>"
            f"<td>{esc(areas)}</td>"
            f"<td>{federal_cell}</td>"
            "</tr>"
        )
    return "\n".join(output)


def shared_css(prefix: str = "") -> str:
    return f"""
    :root {{ --navy:#17365d; --blue:#2f75b5; --pale:#edf4fa;
      --ink:#17212b; --muted:#5b6773; --line:#d8e1e8; --green:#39734d; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); font:16px/1.55 -apple-system,BlinkMacSystemFont,
      "Segoe UI",sans-serif; background:#f6f8fa; }}
    header {{ background:var(--navy); color:white; padding:1rem 1.25rem; }}
    header a {{ color:white; text-decoration:none; font-weight:700; }}
    main {{ max-width:1120px; margin:0 auto; padding:2rem 1.25rem 4rem; }}
    h1 {{ line-height:1.15; margin:.25rem 0 .75rem; }}
    h2 {{ margin-top:2rem; }}
    .eyebrow {{ color:var(--blue); font-weight:800; letter-spacing:.05em;
      text-transform:uppercase; font-size:.8rem; }}
    .lede,.note {{ color:var(--muted); max-width:820px; }}
    .notice {{ background:#fff4cc; border-left:5px solid #c49300; padding:1rem;
      margin:1.25rem 0; }}
    .metrics {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
      gap:1rem; margin:1.5rem 0; }}
    .metric,.state-card {{ background:white; border:1px solid var(--line);
      border-radius:10px; padding:1rem; }}
    .metric strong {{ display:block; font-size:1.8rem; color:var(--navy); }}
    .states {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(235px,1fr));
      gap:.8rem; }}
    .state-card a {{ color:var(--navy); font-weight:800; text-decoration:none; }}
    .status {{ display:inline-block; margin-top:.5rem; padding:.15rem .5rem;
      border-radius:99px; background:var(--pale); color:var(--navy); font-size:.78rem; }}
    table {{ width:100%; border-collapse:collapse; background:white; font-size:.9rem; }}
    th,td {{ padding:.65rem; border-bottom:1px solid var(--line); text-align:left;
      vertical-align:top; }}
    th {{ background:var(--blue); color:white; }}
    td a {{ color:#175c9c; }} .empty {{ color:var(--muted); font-style:italic; }}
    .actions {{ overflow-x:auto; }}
    .layer {{ margin-top:2.5rem; padding-top:.5rem; border-top:3px solid var(--line); }}
    .layer h2 {{ margin-top:.5rem; }}
    footer {{ margin-top:3rem; padding-top:1rem; border-top:1px solid var(--line);
      color:var(--muted); font-size:.85rem; }}
    """


def render_state_page(
    state: dict,
    actions: list[dict],
    federal_declarations: list[dict],
    storm_rows: list[dict],
    crosswalk: list[dict],
    metrics: dict,
    coverage: str,
) -> str:
    name = esc(state["name"])
    source = state.get("official_source_url", "")
    source_link = (
        f'<a href="{esc(source)}">Official state source</a>'
        if source
        else "Official source to be identified"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} State Emergency Actions | DisasterData Plus</title>
<meta name="description" content="Federal declarations, state emergency actions, and matched weather-event evidence for {name}.">
<style>{shared_css()}</style></head>
<body><header><a href="../../">DisasterData.IO</a> / <a href="../">Plus</a> / {name}</header>
<main><div class="eyebrow">DisasterData Plus</div>
<h1>{name}: Emergency Action Overview</h1>
<p class="lede">Federal FEMA declarations, state-issued emergency actions, and NOAA/NWS weather evidence, presented separately and cross-referenced where a connection can be shown.</p>
<div class="notice"><strong>Coverage:</strong> {esc(coverage)}. Absence from this page must not be interpreted as absence of a state emergency.</div>
<section class="metrics">
  <div class="metric"><strong>{metrics['federal_declaration_count']:,}</strong>federal FEMA declarations</div>
  <div class="metric"><strong>{metrics['action_count']:,}</strong>state-action records loaded</div>
  <div class="metric"><strong>{metrics['storm_match_rows']:,}</strong>matched NOAA event rows</div>
</section>
<p><a href="../../states/{esc(state['slug'])}.html">Federal declaration overview</a> &middot; {source_link}</p>

<div class="layer">
<h2>Federal FEMA declarations</h2>
<p class="note">DR, EM, and FM declarations for {name} from the site's national FEMA dataset.</p>
<div class="actions"><table><thead><tr><th>Date</th><th>Number</th><th>Type</th><th>Title</th><th>Incident type</th><th>Incident period</th></tr></thead>
<tbody>{federal_declaration_rows(federal_declarations)}</tbody></table></div>
</div>

<div class="layer">
<h2>{name} state actions</h2>
<div class="actions"><table><thead><tr><th>Date</th><th>Number</th><th>Action</th><th>Type</th><th>Governor</th></tr></thead>
<tbody>{action_rows(actions)}</tbody></table></div>
</div>

<div class="layer">
<h2>NOAA/NWS weather evidence</h2>
<p class="note">Storm Events matched within the configured date window of a state action's signing date. This is temporal and geographic evidence of nearby observed weather, not proof of causation or operational impact.</p>
<div class="actions"><table><thead><tr><th>Date</th><th>Area</th><th>Area type</th><th>Hazard</th><th>Deaths / injuries</th><th>Property damage</th></tr></thead>
<tbody>{noaa_event_rows(storm_rows)}</tbody></table></div>
</div>

<div class="layer">
<h2>Combined event crosswalk</h2>
<p class="note">Each state action, its matched NOAA evidence, and the closest federal declaration within {FEDERAL_MATCH_WINDOW_DAYS} days of its incident window, if one exists. A federal match is an automated date-proximity candidate, not a confirmed legal link.</p>
<div class="actions"><table><thead><tr><th>State action</th><th>NOAA matches</th><th>Matched areas</th><th>Federal declaration</th></tr></thead>
<tbody>{crosswalk_rows(crosswalk)}</tbody></table></div>
</div>

<h2>Methodology and coverage</h2>
<p class="note">Federal declarations are sourced from OpenFEMA via this site's national build. State actions are limited by the coverage statement above. NOAA proximity matches identify potentially related observed events within a configured window of each state action's signing date; they do not independently prove operational impacts or legal causation. The federal crosswalk match uses a wider {FEDERAL_MATCH_WINDOW_DAYS} day window than the NOAA match, since a federal declaration is often filed weeks after the state action that preceded it.</p>
<footer>Generated {date.today().isoformat()} &middot; DisasterData.IO &middot; State and federal records remain subject to source verification.</footer>
</main></body></html>"""


def render_landing(summaries: list[dict], all_states: list[dict]) -> str:
    by_abbreviation = {item["abbreviation"]: item for item in summaries}
    cards = []
    for state in all_states:
        summary = by_abbreviation.get(state["abbreviation"])
        count = summary["metrics"]["action_count"] if summary else 0
        coverage = summary["coverage"] if summary else "Not rebuilt in this run"
        cards.append(
            '<article class="state-card">'
            f'<a href="{esc(state["slug"])}/">{esc(state["name"])}</a>'
            f'<div>{count:,} loaded state-action records</div>'
            f'<span class="status">{esc(coverage)}</span>'
            "</article>"
        )
    loaded = sum(1 for item in summaries if item["metrics"]["action_count"] > 0)
    implemented = sum(1 for state in all_states if state["adapter_status"] == "implemented")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>State Emergency Evidence | DisasterData Plus</title>
<meta name="description" content="State emergency actions and observed hazard evidence across the United States.">
<style>{shared_css()}</style></head>
<body><header><a href="../">DisasterData.IO</a> / Plus</header>
<main><div class="eyebrow">DisasterData Plus</div><h1>State emergency evidence</h1>
<p class="lede">State declarations, executive actions, proclamations, and observed weather evidence supplementing the federal disaster record.</p>
<div class="notice">Coverage varies by state. A generated page is not evidence that its state-action archive is complete.</div>
<section class="metrics">
  <div class="metric"><strong>50</strong>state pages</div>
  <div class="metric"><strong>{implemented}</strong>implemented source adapters</div>
  <div class="metric"><strong>{loaded}</strong>states with loaded action data in this run</div>
</section>
<h2>Browse by state</h2><section class="states">{''.join(cards)}</section>
<footer>Generated {date.today().isoformat()} &middot; DisasterData.IO</footer>
</main></body></html>"""


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def process_state(
    state: dict,
    repo_root: Path,
    collect: bool,
    join_storms: bool,
    dry_run: bool,
) -> dict:
    state_dir = repo_root / "plus" / state["slug"]
    adapter_name = state.get("adapter_file") or (
        state["name"].lower().replace(" ", "_").replace("-", "_") + ".py"
    )
    adapter_path = state_dir / adapter_name
    collection_note = ""
    collection_error = ""

    if collect:
        if adapter_path.exists():
            try:
                adapter = import_adapter(adapter_path)
                _, collection_note = adapter.collect(
                    workdir=state_dir, scripts_dir=state_dir
                )
            except Exception as exc:
                collection_error = f"Collection failed: {exc}"
                print(f"WARNING {state['abbreviation']}: {collection_error}", file=sys.stderr)
        else:
            collection_error = "No state-source adapter is installed"

    actions, action_path = load_state_actions(state, state_dir)
    storm_note = ""
    if join_storms:
        if action_path:
            storm_join_path = ensure_declaration_id_column(action_path, state["abbreviation"])
            storm_note = run_storm_pipeline(state, state_dir, storm_join_path)
        else:
            storm_note = "Storm join skipped: no state-action CSV is available"

    federal_declarations = load_federal_declarations(repo_root, state["abbreviation"])
    storm_rows, _ = load_storm_match_rows(state_dir)
    severity_rows, _ = load_severity_rows(state_dir)
    storm_rows_by_declaration = group_by_declaration(storm_rows)
    crosswalk = build_crosswalk(actions, federal_declarations, storm_rows_by_declaration)

    metrics = state_metrics(state, actions, federal_declarations, storm_rows, severity_rows)
    coverage = coverage_label(state, actions, collection_note)
    if collection_error:
        coverage += "; " + collection_error

    summary = {
        "abbreviation": state["abbreviation"],
        "name": state["name"],
        "slug": state["slug"],
        "adapter_status": state["adapter_status"],
        "coverage": coverage,
        "action_file": action_path.name if action_path else "",
        "metrics": metrics,
        "storm_pipeline_note": storm_note,
        "generated_on": date.today().isoformat(),
    }
    if not dry_run:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "index.html").write_text(
            render_state_page(
                state, actions, federal_declarations, storm_rows, crosswalk, metrics, coverage
            ),
            encoding="utf-8",
        )
        write_json(state_dir / "state-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DisasterData Plus state pages")
    parser.add_argument("--states", default="all", help="all or comma-separated names/abbreviations")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root; normally detected automatically",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--collect",
        action="store_true",
        help="run installed state source adapters before building pages",
    )
    parser.add_argument(
        "--join-storms",
        action="store_true",
        help="run an installed eo_storm_join.py after reading state actions",
    )
    parser.add_argument("--dry-run", action="store_true", help="validate and report without writing")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return an error when a selected state has neither an adapter nor cached actions",
    )
    args = parser.parse_args()

    all_states = load_manifest(args.manifest)
    selected = select_states(all_states, args.states)
    repo_root = args.repo_root.resolve()
    print(f"Repository root: {repo_root}")
    print(f"Selected states: {', '.join(state['abbreviation'] for state in selected)}")

    summaries = []
    incomplete = []
    for state in selected:
        summary = process_state(
            state, repo_root, args.collect, args.join_storms, args.dry_run
        )
        summaries.append(summary)
        if summary["metrics"]["action_count"] == 0 and state["adapter_status"] != "implemented":
            incomplete.append(state["abbreviation"])
        print(
            f"{state['abbreviation']}: {summary['metrics']['action_count']} actions, "
            f"{summary['metrics']['federal_declaration_count']} federal declarations; "
            f"{summary['coverage']}"
        )

    if not args.dry_run:
        plus_dir = repo_root / "plus"
        plus_dir.mkdir(parents=True, exist_ok=True)
        summary_path = plus_dir / "coverage.json"
        existing = []
        if summary_path.exists():
            try:
                existing = json.loads(summary_path.read_text(encoding="utf-8")).get("states", [])
            except (json.JSONDecodeError, OSError):
                existing = []
        merged = {item["abbreviation"]: item for item in existing}
        merged.update({item["abbreviation"]: item for item in summaries})
        ordered = [merged[state["abbreviation"]] for state in all_states if state["abbreviation"] in merged]
        write_json(
            summary_path,
            {"generated_on": date.today().isoformat(), "states": ordered},
        )
        (plus_dir / "index.html").write_text(
            render_landing(ordered, all_states), encoding="utf-8"
        )

    if incomplete:
        print(
            "Coverage pending for: " + ", ".join(incomplete)
            + ". Pages were generated with explicit incomplete-coverage notices."
        )
    return 1 if args.strict and incomplete else 0


if __name__ == "__main__":
    raise SystemExit(main())
