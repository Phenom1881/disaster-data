#!/usr/bin/env python3
"""
gen_map_events.py - build the national event-to-counties index for the Map overlay.

Reads the per-state declaration index that gen_decl_index.py already writes
(data/decl-index/{ST}.json, listed in manifest.json), groups declarations
NATIONALLY by event (eventId, falling back to the declaration id - the SAME
key Compare groups on), unions the FIPS each event designated across every
state it touched, and writes map-events.js:

    window.MAP_EVENTS = [ {id, n, y, t, it, sw, f:[...]}, ... ];

  id  event key (eventId, else declaration id)      n   display name
  y   year                                          t   DR / EM / FM
  it  incident type (Flood, Hurricane, ...)         sw  1 if any piece was statewide
  f   sorted list of 5-digit county FIPS it hit

map.html loads this as a <script> tag, exactly like map-data.js, to power the
overlay picker: choose several events, shade each county by how many of them
designated it. Events with no county footprint (purely statewide rows, which
the index drops) are omitted, since they cannot be drawn per county.

Run it after the decl-index is built, in the same job:
    python gen_map_events.py --in data/decl-index --out map-events.js

Optional trimming if the file gets heavy:
    --types DR         only major disasters (comma list, default all)
    --since 2000       only events in/after a year (default all)
"""
import argparse
import glob
import json
import os
import sys


def num_from_id(did):
    digits = "".join(ch for ch in str(did or "") if ch.isdigit())
    return int(digits) if digits else 0


def type_from_id(did):
    s = str(did or "").upper()
    for t in ("DR", "EM", "FM"):
        if s.startswith(t):
            return t
    return ""


def load_state_files(in_dir):
    """Return the list of {ST}.json paths, preferring the manifest."""
    manifest_path = os.path.join(in_dir, "manifest.json")
    files = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                m = json.load(fh)
            files = [os.path.join(in_dir, s["file"])
                     for s in m.get("states", []) if s.get("file")]
        except Exception as e:
            sys.stderr.write("  manifest unreadable (%s); globbing instead\n" % e)
    if not files:
        files = [p for p in sorted(glob.glob(os.path.join(in_dir, "*.json")))
                 if os.path.basename(p) != "manifest.json"]
    return files


def build_events(in_dir, types=None, since=0):
    """Group declarations across all states into national events."""
    events = {}          # key -> {id, name, year, type, it, sw, number, fips:set}
    n_decls = 0
    for path in load_state_files(in_dir):
        try:
            with open(path, encoding="utf-8") as fh:
                idx = json.load(fh)
        except Exception as e:
            sys.stderr.write("  skip %s (%s)\n" % (path, e))
            continue
        for d in idx.get("declarations", []):
            n_decls += 1
            dtype = (d.get("type") or "").upper() or type_from_id(d.get("id"))
            if types and dtype not in types:
                continue
            year = d.get("year") or 0
            if since and year < since:
                continue
            key = d.get("eventId") or d.get("id")
            if not key:
                continue
            fips = [f for f in (d.get("fips") or []) if f]
            ev = events.get(key)
            if ev is None:
                ev = {
                    "id": key,
                    "name": d.get("eventName") or d.get("title") or d.get("id") or key,
                    "year": year,
                    "type": dtype,
                    "it": d.get("incidentType") or "Other",
                    "sw": bool(d.get("statewide")),
                    "number": d.get("number") or num_from_id(d.get("id")),
                    "fips": set(),
                }
                events[key] = ev
            ev["fips"].update(fips)
            if d.get("statewide"):
                ev["sw"] = True
            ev["number"] = max(ev["number"], d.get("number") or 0)
            ev["year"] = max(ev["year"], year)
    return events, n_decls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", default="data/decl-index",
                    help="directory holding {ST}.json + manifest.json")
    ap.add_argument("--out", dest="out", default="map-events.js")
    ap.add_argument("--types", default="",
                    help="comma list of declaration types to keep (e.g. DR,EM). Default: all")
    ap.add_argument("--since", type=int, default=0,
                    help="only keep events in/after this year. Default: all")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    types = set(t.strip().upper() for t in args.types.split(",") if t.strip()) or None
    events, n_decls = build_events(args.in_dir, types=types, since=args.since)

    rows, dropped = [], 0
    for ev in events.values():
        if not ev["fips"]:
            dropped += 1
            continue
        rows.append({
            "id": ev["id"],
            "n": ev["name"],
            "y": ev["year"],
            "t": ev["type"],
            "it": ev["it"],
            "sw": 1 if ev["sw"] else 0,
            "f": sorted(ev["fips"]),
        })
    # newest first, so the picker lists recent disasters at the top
    rows.sort(key=lambda r: (r["y"], num_from_id(r["id"])), reverse=True)

    payload = (json.dumps(rows, indent=2) if args.pretty
               else json.dumps(rows, separators=(",", ":")))
    out_text = "window.MAP_EVENTS=%s;\n" % payload
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out_text)

    total_fips = sum(len(r["f"]) for r in rows)
    size = len(out_text.encode("utf-8"))
    print("map-events.js written: %s" % args.out)
    print("  declarations read : %d" % n_decls)
    print("  events (with fips): %d   (dropped %d with no county footprint)"
          % (len(rows), dropped))
    print("  total county refs : %d" % total_fips)
    print("  file size         : %.1f KB" % (size / 1024.0))
    for r in sorted(rows, key=lambda r: len(r["f"]), reverse=True)[:5]:
        print("    %-16s %-30s %4d counties  %s"
              % (r["id"], (r["n"] or "")[:30], len(r["f"]), r["y"]))


if __name__ == "__main__":
    main()
