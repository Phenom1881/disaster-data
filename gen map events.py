#!/usr/bin/env python3
"""
gen_map_events.py - build the national event indexes (map-events.js + events.json).

Reads data/decl-index/{ST}.json (+ manifest.json) and groups declarations
NATIONALLY into events, then writes both the Map overlay index and the Disaster
page index from one pass.

GROUPING: named tropical systems (hurricanes, tropical storms, typhoons, their
post-tropical / remnant forms) are merged by STORM NAME + YEAR, because FEMA
titles the same storm differently in every state it hits ("Hurricane Helene",
"Tropical Storm Helene", "Post-Tropical Cyclone Helene", "Remnants of Hurricane
Helene"...) and issues a separate declaration number per state. So all of
Helene 2024 collapses into one event spanning every state, county, and
declaration number it touched. Everything else falls back to the declaration's
eventId (else its id) - the SAME key Compare uses - so unnamed events are left
as they are. Two different storms that share a name in different years stay
separate (the year is part of the key).

The storm rule now lives in the shared dd_events module (imported below), the
same rule gen_decl_index stamps onto every declaration as eventId, so the
Compare page, the Disaster page, and the Map overlay all group storms
identically. There is one rule to maintain.

Outputs:
  map-events.js  window.MAP_EVENTS = [{id, n, y, t, it, sw, f:[...]}, ...]
                 events WITH a county footprint only (statewide-only dropped).
  events.json    [{id, n, y, t, it, sw, states:[...], dns:[...], f:[...]}, ...]
                 all events (statewide-only kept, empty f).

  id  event key   n  display name   y  year   t  DR/EM/FM (DR>EM>FM if mixed)
  it  incident type   sw 1 if any piece statewide
  states sorted USPS abbrevs   dns sorted disaster numbers   f sorted 5-digit FIPS

Run after the decl-index is built:
    python gen_map_events.py --in data/decl-index --out map-events.js
Optional: --types DR   --since 2000   --events-out events.json
"""
import argparse
import glob
import json
import os
import re
import sys

# The storm-identity rule is shared with gen_decl_index via dd_events so the
# Compare index, Disaster page, and Map overlay never drift apart. The path
# insert lets "import dd_events" resolve when this script is run from any
# directory or loaded by the test fixture. See dd_events.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dd_events import storm_name, storm_event_id


def num_from_id(did):
    digits = "".join(ch for ch in str(did or "") if ch.isdigit())
    return int(digits) if digits else 0


def type_from_id(did):
    s = str(did or "").upper()
    for t in ("DR", "EM", "FM"):
        if s.startswith(t):
            return t
    return ""


def st_from_path(path):
    return os.path.splitext(os.path.basename(path))[0].upper()


def load_state_files(in_dir):
    manifest_path = os.path.join(in_dir, "manifest.json")
    files = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as fh:
                m = json.load(fh)
            for s in m.get("states", []):
                f = s.get("file")
                if f:
                    p = os.path.join(in_dir, f)
                    files.append(((s.get("state") or st_from_path(p)).upper(), p))
        except Exception as e:
            sys.stderr.write("  manifest unreadable (%s); globbing instead\n" % e)
    if not files:
        files = [(st_from_path(p), p)
                 for p in sorted(glob.glob(os.path.join(in_dir, "*.json")))
                 if os.path.basename(p) != "manifest.json"]
    return files


def build_events(in_dir, types=None, since=0):
    events = {}
    n_decls = 0
    n_merged = 0
    for st, path in load_state_files(in_dir):
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

            title = d.get("title") or d.get("eventName") or ""
            sname = storm_name(title)
            if sname:
                key = storm_event_id(sname, year)     # merge the storm across states
            else:
                key = d.get("eventId") or d.get("id")
            if not key:
                continue

            fips = [f for f in (d.get("fips") or []) if f]
            dn = d.get("number") or num_from_id(d.get("id"))
            tl = title.lower()

            ev = events.get(key)
            if ev is None:
                ev = {
                    "id": key,
                    "name": d.get("eventName") or d.get("title") or d.get("id") or key,
                    "storm": sname,
                    "year": year,
                    "type": dtype,
                    "it": d.get("incidentType") or "Other",
                    "sw": bool(d.get("statewide")),
                    "number": dn or 0,
                    "types": set(),
                    "has_hurr": False, "has_typhoon": False, "has_ts": False,
                    "states": set(), "dns": set(), "fips": set(),
                }
                events[key] = ev
            else:
                n_merged += 1

            ev["fips"].update(fips)
            if st:
                ev["states"].add(st)
            if dn:
                ev["dns"].add(dn)
            if dtype:
                ev["types"].add(dtype)
            if "hurricane" in tl:
                ev["has_hurr"] = True
            if "typhoon" in tl:
                ev["has_typhoon"] = True
            if "tropical storm" in tl or "tropical depression" in tl:
                ev["has_ts"] = True
            if d.get("statewide"):
                ev["sw"] = True
            ev["number"] = max(ev["number"], dn or 0)
            ev["year"] = max(ev["year"], year)
    return events, n_decls, n_merged


def finalize(ev):
    """Compute the display id/name/type/incident for an event after grouping."""
    if ev.get("storm"):
        nm = ev["storm"].title()
        if ev["has_hurr"]:
            disp, it = "Hurricane " + nm, "Hurricane"
        elif ev["has_typhoon"]:
            disp, it = "Typhoon " + nm, "Typhoon"
        elif ev["has_ts"]:
            disp, it = "Tropical Storm " + nm, "Tropical Storm"
        else:
            disp, it = nm, (ev["it"] or "Tropical")
        eid = ev["id"]  # already "storm-<name>-<year>"
    else:
        disp, it, eid = ev["name"], ev["it"], ev["id"]
    tset = ev["types"]
    t = "DR" if "DR" in tset else ("EM" if "EM" in tset else ("FM" if "FM" in tset else ev["type"]))
    return eid, disp, t, it


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", default="data/decl-index")
    ap.add_argument("--out", dest="out", default="map-events.js")
    ap.add_argument("--events-out", dest="events_out", default="events.json")
    ap.add_argument("--types", default="")
    ap.add_argument("--since", type=int, default=0)
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    types = set(t.strip().upper() for t in args.types.split(",") if t.strip()) or None
    events, n_decls, n_merged = build_events(args.in_dir, types=types, since=args.since)

    ordered = sorted(events.values(), key=lambda e: (e["year"], e["number"]), reverse=True)

    map_rows, evt_rows, dropped = [], [], 0
    for ev in ordered:
        eid, disp, t, it = finalize(ev)
        f = sorted(ev["fips"])
        evt_rows.append({
            "id": eid, "n": disp, "y": ev["year"], "t": t, "it": it,
            "sw": 1 if ev["sw"] else 0,
            "states": sorted(ev["states"]), "dns": sorted(ev["dns"]), "f": f,
        })
        if f:
            map_rows.append({"id": eid, "n": disp, "y": ev["year"], "t": t,
                             "it": it, "sw": 1 if ev["sw"] else 0, "f": f})
        else:
            dropped += 1

    def dump(obj):
        return json.dumps(obj, indent=2) if args.pretty else json.dumps(obj, separators=(",", ":"))

    out_text = "window.MAP_EVENTS=%s;\n" % dump(map_rows)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out_text)
    epayload = dump(evt_rows) + "\n"
    with open(args.events_out, "w", encoding="utf-8") as fh:
        fh.write(epayload)

    print("map-events.js written: %s" % args.out)
    print("  declarations read : %d" % n_decls)
    print("  merged into events : %d fewer rows via grouping" % n_merged)
    print("  events (with fips): %d   (dropped %d statewide-only)" % (len(map_rows), dropped))
    print("  file size         : %.1f KB" % (len(out_text.encode("utf-8")) / 1024.0))
    print("events.json written: %s   (%d events, %.1f KB)"
          % (args.events_out, len(evt_rows), len(epayload.encode("utf-8")) / 1024.0))
    for r in sorted(evt_rows, key=lambda r: len(r["f"]), reverse=True)[:6]:
        print("    %-22s %-26s %2d states %4d counties  %s"
              % (r["id"], (r["n"] or "")[:26], len(r["states"]), len(r["f"]), r["y"]))


if __name__ == "__main__":
    main()
