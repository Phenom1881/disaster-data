#!/usr/bin/env python3
"""
test_event_clustering.py

Regression fixture for DisasterData.IO event clustering.

It tests the OUTPUT partition (which declarations resolve into the same event),
not the implementation, so the grouping rule can change and only the expected
partitions need updating, never the test structure. It runs the REAL
generators, so it catches a break in dd_events, gen_decl_index, or
gen_map_events, and it pins the property the recent unification bought:

  * gen_map_events groups the declarations into the expected event partition
    (this is what the Disaster page and the Map show), AND
  * gen_decl_index stamps an eventId that induces the SAME partition (this is
    what Compare groups on), so all three views agree by construction.

Tiers:
  regression  current, intended behavior. Must pass.
  guard       things that must never merge, now or after future work. Must pass.
  target      behavior not built yet (unnamed same-incident clustering, e.g.
              the 2011 tornado Super Outbreak). Expected to fail today; when one
              starts passing it prints PROMOTE, meaning move it to regression.

Exit 0 only when every regression and guard case passes and every case agrees
between the two generators. A target case failing is expected and does not fail
the run. Stdlib only, no pytest, so it runs in a bare GitHub Actions step.

Run:  python test_event_clustering.py
Point at specific files with env vars GEN_DECL_INDEX / GEN_MAP_EVENTS if they
are not sitting next to this test.
"""

import importlib.util
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------
# Load the real generators (space-named in the repo, underscored on upload)
# ----------------------------------------------------------------------

def locate(env_var, names):
    override = os.environ.get(env_var)
    if override and os.path.exists(override):
        return override
    for name in names:
        candidate = os.path.join(HERE, name)
        if os.path.exists(candidate):
            return candidate
    raise SystemExit(
        "Could not find any of %s next to the test. Set %s to its path."
        % (names, env_var)
    )


def load(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN_DECL = locate("GEN_DECL_INDEX", ["gen decl index.py", "gen_decl_index.py"])
GEN_MAP = locate("GEN_MAP_EVENTS", ["gen map events.py", "gen_map_events.py"])
gdi = load(GEN_DECL, "gen_decl_index_under_test")
gme = load(GEN_MAP, "gen_map_events_under_test")


# ----------------------------------------------------------------------
# Synthetic declaration builder
# ----------------------------------------------------------------------

STATE_FIPS = {
    "AL": "01", "CA": "06", "FL": "12", "GA": "13", "KY": "21", "LA": "22",
    "MS": "28", "MO": "29", "NJ": "34", "NY": "36", "NC": "37", "OR": "41",
    "SC": "45", "TN": "47", "TX": "48", "VA": "51", "WA": "53", "GU": "66",
    "MP": "69",
}


def D(state, number, dtype, title, incident, counties=("001", "003"),
      year=2024, begin=None, end=None):
    """One declaration spec. Expands to one OpenFEMA-shaped row per county."""
    return {
        "state": state, "number": number, "dtype": dtype, "title": title,
        "incident": incident, "counties": list(counties), "year": year,
        "begin": begin, "end": end,
    }


def rows_for(spec):
    sf = STATE_FIPS[spec["state"]]
    y = spec["year"]
    begin = (spec["begin"] or "%d-06-10" % y) + "T00:00:00.000Z"
    end = (spec["end"] or "%d-06-20" % y) + "T00:00:00.000Z"
    declared = "%d-06-15T00:00:00.000Z" % y
    out = []
    for c in spec["counties"]:
        out.append({
            "state": spec["state"], "disasterNumber": spec["number"],
            "declarationType": spec["dtype"], "declarationTitle": spec["title"],
            "incidentType": spec["incident"], "declarationDate": declared,
            "incidentBeginDate": begin, "incidentEndDate": end,
            "fyDeclared": y, "fipsStateCode": sf, "fipsCountyCode": c,
            "designatedArea": "Area %s (County)" % c, "paProgramDeclared": 1,
        })
    return out


def decl_id(spec):
    return "%s-%d" % (spec["dtype"], spec["number"])


# ----------------------------------------------------------------------
# Partition helpers  (a partition is a set of frozensets of declaration ids)
# ----------------------------------------------------------------------

def canon(groups):
    return frozenset(frozenset(g) for g in groups if g)


def partition_from_decl_index(indexes):
    """What Compare groups on: cluster declaration ids by their eventId."""
    by_event = {}
    for data in indexes.values():
        for d in data["declarations"]:
            by_event.setdefault(d["eventId"], set()).add(d["id"])
    return canon(by_event.values())


def partition_from_events(events, num_to_id):
    """What the Disaster page and Map show: cluster ids by the event they
    landed in. Disaster numbers are unique per declaration here, so each
    number maps to exactly one id and one event."""
    groups = []
    for ev in events.values():
        ids = {num_to_id[n] for n in ev["dns"] if n in num_to_id}
        groups.append(ids)
    return canon(groups)


def show(partition):
    parts = sorted(["{" + ", ".join(sorted(g)) + "}" for g in partition])
    return "  ".join(parts)


# ----------------------------------------------------------------------
# Golden cases
# ----------------------------------------------------------------------

CASES = [
    # ---- regression: current, intended behavior ----
    dict(name="helene_multistate", tier="regression",
         note="one storm titled differently per state merges",
         decls=[D("NC", 4830, "DR", "Hurricane Helene", "Hurricane"),
                D("FL", 4828, "DR", "Tropical Storm Helene", "Tropical Storm"),
                D("VA", 4831, "DR", "Post-Tropical Cyclone Helene", "Hurricane")],
         expect=[["DR-4830", "DR-4828", "DR-4831"]]),

    dict(name="helene_two_years", tier="regression",
         note="same name, different years, stay apart",
         decls=[D("NC", 4830, "DR", "Hurricane Helene", "Hurricane", year=2024),
                D("FL", 1345, "DR", "Hurricane Helene", "Hurricane", year=2000)],
         expect=[["DR-4830"], ["DR-1345"]]),

    dict(name="covid_all_biological", tier="regression",
         note="every COVID emergency and disaster, all states and years, into one",
         decls=[D("TX", 3458, "EM", "COVID-19 Pandemic", "Biological", year=2020),
                D("TX", 4485, "DR", "Coronavirus Disease 2019 (COVID-19) Pandemic", "Biological", year=2020),
                D("CA", 4482, "DR", "COVID-19 Pandemic", "Biological", year=2020),
                D("FL", 4486, "DR", "COVID-19 Pandemic", "Biological", year=2021)],
         expect=[["EM-3458", "DR-4485", "DR-4482", "DR-4486"]]),

    dict(name="no_cross_contamination", tier="regression",
         note="storm, COVID, and a winter storm keep to themselves",
         decls=[D("NC", 4830, "DR", "Hurricane Helene", "Hurricane"),
                D("TX", 4485, "DR", "COVID-19 Pandemic", "Biological", year=2020),
                D("VA", 4863, "DR", "Winter Storm Jett", "Severe Winter Storm", year=2025)],
         expect=[["DR-4830"], ["DR-4485"], ["DR-4863"]]),

    dict(name="ida_post_tropical_and_remnants", tier="regression",
         note="hurricane, remnants, and post-tropical forms merge",
         decls=[D("LA", 4611, "DR", "Hurricane Ida", "Hurricane", year=2021),
                D("NJ", 4614, "DR", "Remnants of Hurricane Ida", "Severe Storm", year=2021),
                D("NY", 4615, "DR", "Post-Tropical Cyclone Ida", "Severe Storm", year=2021)],
         expect=[["DR-4611", "DR-4614", "DR-4615"]]),

    dict(name="storm_name_mid_title", tier="regression",
         note="name found anywhere in the title, not only at the start",
         decls=[D("LA", 4611, "DR", "Hurricane Ida", "Hurricane", year=2021),
                D("MS", 4620, "DR", "Severe Storms and Flooding from Hurricane Ida", "Severe Storm", year=2021)],
         expect=[["DR-4611", "DR-4620"]]),

    dict(name="typhoon_and_super_typhoon", tier="regression",
         note="Pacific systems merge across territories",
         decls=[D("GU", 4692, "DR", "Typhoon Mawar", "Typhoon", year=2023),
                D("MP", 4693, "DR", "Super Typhoon Mawar", "Typhoon", year=2023)],
         expect=[["DR-4692", "DR-4693"]]),

    dict(name="unnamed_singletons_separate", tier="regression",
         note="unnamed events each stand alone, one to one",
         decls=[D("VA", 4863, "DR", "Winter Storm Jett", "Severe Winter Storm", year=2025),
                D("MO", 4700, "DR", "Severe Storms and Flooding", "Flood", year=2023)],
         expect=[["DR-4863"], ["DR-4700"]]),

    # ---- guard: must never merge, now or after future work ----
    dict(name="different_storms_same_year", tier="guard",
         note="two named storms in one season stay separate",
         decls=[D("NC", 4830, "DR", "Hurricane Helene", "Hurricane", year=2024),
                D("FL", 4834, "DR", "Hurricane Milton", "Hurricane", year=2024)],
         expect=[["DR-4830"], ["DR-4834"]]),

    dict(name="independent_floods_distant_states", tier="guard",
         note="same incident type, same week, far apart, must not chain together",
         decls=[D("WA", 4701, "DR", "Flooding", "Flood", year=2023, begin="2023-01-05", end="2023-01-12"),
                D("KY", 4702, "DR", "Flooding", "Flood", year=2023, begin="2023-01-06", end="2023-01-11")],
         expect=[["DR-4701"], ["DR-4702"]]),

    dict(name="back_to_back_severe_storm_systems", tier="guard",
         note="two distinct systems weeks apart stay separate",
         decls=[D("MO", 4710, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2024, begin="2024-03-01", end="2024-03-05"),
                D("GA", 4711, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2024, begin="2024-05-01", end="2024-05-05")],
         expect=[["DR-4710"], ["DR-4711"]]),

    dict(name="adjacent_same_type_weeks_apart", tier="guard",
         note="Path B: adjacent states, same incident type, but too many days apart to link",
         decls=[D("AL", 5001, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2020, begin="2020-04-01", end="2020-04-03"),
                D("GA", 5002, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2020, begin="2020-04-20", end="2020-04-22")],
         expect=[["DR-5001"], ["DR-5002"]]),

    dict(name="storm_orphan_too_late", tier="guard",
         note="Path B: adjacent to a named storm, but weeks after it ended, must not attach",
         decls=[D("NC", 4830, "DR", "Hurricane Helene", "Hurricane", year=2024, begin="2024-09-25", end="2024-09-28"),
                D("SC", 4899, "DR", "Severe Storms and Flooding", "Severe Storm", year=2024, begin="2024-10-20", end="2024-10-22")],
         expect=[["DR-4830"], ["DR-4899"]]),

    dict(name="span_cap_breaks_a_long_chain", tier="guard",
         note="Path B: a 5-state adjacent chain, 4 days apart each hop, must not become one 26-day blob",
         decls=[D("AL", 6001, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2019, begin="2019-05-01", end="2019-05-03"),
                D("GA", 6002, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2019, begin="2019-05-07", end="2019-05-09"),
                D("SC", 6003, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2019, begin="2019-05-13", end="2019-05-15"),
                D("NC", 6004, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2019, begin="2019-05-19", end="2019-05-21"),
                D("VA", 6005, "DR", "Severe Storms and Tornadoes", "Severe Storm", year=2019, begin="2019-05-25", end="2019-05-27")],
         expect=[["DR-6001", "DR-6002", "DR-6003"], ["DR-6004", "DR-6005"]]),

    # ---- regression: Path B (unnamed same-incident / storm-attach clustering) ----
    dict(name="tornado_super_outbreak_2011", tier="regression",
         note="one multi-state outbreak in a tight window merges (Path B)",
         decls=[D("AL", 1971, "DR", "Severe Storms, Tornadoes, Straight-line Winds, and Flooding", "Severe Storm", year=2011, begin="2011-04-25", end="2011-04-28"),
                D("GA", 1973, "DR", "Severe Storms, Tornadoes, and Straight-line Winds", "Severe Storm", year=2011, begin="2011-04-27", end="2011-04-28"),
                D("TN", 1974, "DR", "Severe Storms, Tornadoes, Straight-line Winds, and Flooding", "Severe Storm", year=2011, begin="2011-04-25", end="2011-04-28"),
                D("MS", 1972, "DR", "Severe Storms, Tornadoes, Straight-line Winds, and Flooding", "Severe Storm", year=2011, begin="2011-04-25", end="2011-04-28")],
         expect=[["DR-1971", "DR-1973", "DR-1974", "DR-1972"]]),

    dict(name="generic_titled_storm_sibling", tier="regression",
         note="a storm's own declaration titled generically joins it (Path B)",
         decls=[D("NC", 4830, "DR", "Hurricane Helene", "Hurricane", year=2024, begin="2024-09-25", end="2024-09-28"),
                D("SC", 4832, "DR", "Severe Storms and Flooding", "Severe Storm", year=2024, begin="2024-09-26", end="2024-09-28")],
         expect=[["DR-4830", "DR-4832"]]),

    # ---- target: nothing currently unbuilt; kept as a slot for future rules ----
]



# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------

def run_case(case):
    records, num_to_id = [], {}
    for spec in case["decls"]:
        records.extend(rows_for(spec))
        num_to_id[spec["number"]] = decl_id(spec)

    indexes = gdi.build_indexes(records, {"DR", "EM", "FM"})
    tmp = tempfile.mkdtemp()
    out_dir = os.path.join(tmp, "decl-index")
    os.makedirs(out_dir)
    gdi.write_indexes(indexes, out_dir)
    events, _, _ = gme.build_events(out_dir)

    p_decl = partition_from_decl_index(indexes)
    p_map = partition_from_events(events, num_to_id)
    expected = canon([g for g in case["expect"]])

    return {
        "agree": p_decl == p_map,
        "correct": p_map == expected,
        "p_map": p_map,
        "p_decl": p_decl,
        "expected": expected,
    }


def main():
    print("DisasterData.IO event clustering fixture")
    print("  gen_decl_index: %s" % os.path.basename(GEN_DECL))
    print("  gen_map_events: %s" % os.path.basename(GEN_MAP))
    print("  dd_events rule: storm merge + COVID grouping + unnamed one to one")
    print()

    tallies = {"regression": [0, 0], "guard": [0, 0], "target": [0, 0]}
    agree_ok = agree_total = 0
    hard_failures = []
    promotions = []

    for tier in ("regression", "guard", "target"):
        header = {"regression": "REGRESSION  (must pass)",
                  "guard": "GUARD  (must never over-merge)",
                  "target": "TARGET  (Path B, expected to fail until built)"}[tier]
        print(header)
        for case in [c for c in CASES if c["tier"] == tier]:
            r = run_case(case)
            agree_total += 1
            agree_ok += 1 if r["agree"] else 0

            if tier == "target":
                if r["correct"] and r["agree"]:
                    label = "PROMOTE"
                    promotions.append(case["name"])
                    tallies[tier][0] += 1
                else:
                    label = "xfail  "
                tallies[tier][1] += 1
            else:
                passed = r["correct"] and r["agree"]
                label = "PASS   " if passed else "FAIL   "
                tallies[tier][0] += 1 if passed else 0
                tallies[tier][1] += 1
                if not passed:
                    hard_failures.append((case, r))

            print("  %s %-34s %s" % (label, case["name"], case["note"]))
        print()

    # Detail on anything that broke
    for case, r in hard_failures:
        print("---- %s ----" % case["name"])
        if not r["agree"]:
            print("  AGREEMENT BROKEN: Compare and Map/Disaster grouped differently")
            print("    Compare (eventId): %s" % show(r["p_decl"]))
            print("    Map/Disaster     : %s" % show(r["p_map"]))
        if not r["correct"]:
            print("  WRONG PARTITION")
            print("    expected: %s" % show(r["expected"]))
            print("    got     : %s" % show(r["p_map"]))
        print()

    if promotions:
        print("PROMOTE: these target cases now pass, move them to the regression tier:")
        for name in promotions:
            print("  %s" % name)
        print()

    reg = tallies["regression"]
    grd = tallies["guard"]
    tgt = tallies["target"]
    print("Summary")
    print("  regression : %d/%d" % (reg[0], reg[1]))
    print("  guard      : %d/%d" % (grd[0], grd[1]))
    print("  agreement  : %d/%d  (Compare eventId == Map/Disaster key)" % (agree_ok, agree_total))
    print("  target     : %d/%d now passing (rest expected-fail)" % (tgt[0], tgt[1]))
    print()

    ok = not hard_failures and agree_ok == agree_total
    print("RESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
