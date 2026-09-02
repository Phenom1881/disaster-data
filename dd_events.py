#!/usr/bin/env python3
"""
dd_events.py - one place for how DisasterData.IO decides event identity.

Imported by both gen_decl_index.py (which stamps eventId on every declaration
in the Compare index) and gen_map_events.py (which builds the Disaster page and
Map indexes). Keeping the storm rule and the event-id format here means the
Compare page, the Disaster page, and the Map overlay all group the same
declarations into the same events, and there is only one rule to maintain.

FEMA titles the same storm differently in every state it hits ("Hurricane
Helene", "Tropical Storm Helene", "Post-Tropical Cyclone Helene", "Remnants of
Hurricane Helene"...) and issues a separate declaration number per state.
storm_name() pulls the name out of the title so those pieces share one key.
Everything that is not a named tropical system keeps its own declaration id, so
unnamed events stay one to one.
"""
import re

# Tropical prefixes ordered longest-first so the captured name is the storm,
# not a fragment. The name is the word immediately after the prefix.
_STORM_RE = re.compile(
    r"\b(?:"
    r"remnants of post-tropical cyclone|remnants of post-tropical storm|"
    r"remnants of tropical storm|remnants of tropical depression|"
    r"remnants of hurricane|remnants of typhoon|"
    r"post-tropical cyclone|post-tropical storm|post tropical cyclone|post tropical storm|"
    r"tropical storm|tropical depression|tropical cyclone|super typhoon|"
    r"hurricane|typhoon"
    r")\s+([a-z][a-z'\-]+)",
    re.IGNORECASE,
)
_STORM_STOP = {"and", "of", "the", "from", "with", "system", "near", "in", "a"}


def storm_name(title):
    """Return the lowercased tropical-storm name in a FEMA declaration title
    (e.g. 'Hurricane Helene' -> 'helene'), or None if it isn't a named system."""
    t = " ".join(str(title or "").split())
    for m in _STORM_RE.finditer(t):
        nm = m.group(1).lower()
        if nm not in _STORM_STOP:
            return nm
    return None


def storm_event_id(name, year):
    """The event id for a named storm: 'storm-<name>-<year>'. The year keeps
    two same-named storms in different years apart (2024 Helene vs 2000 Helene)."""
    return "storm-%s-%s" % (name, year)


# COVID-19 is the whole of FEMA's "Biological" incident type in the OpenFEMA
# dataset, so every COVID emergency and major disaster declaration (one per
# state, plus the nationwide emergencies) groups into a single event across all
# years, not one per state or per year.
COVID_EVENT_ID = "covid-19"
COVID_EVENT_NAME = "COVID-19 Pandemic"


def is_covid(incident_type):
    """True for COVID-19 declarations. FEMA classes them as 'Biological', and
    nothing else in the dataset uses that incident type, so this collapses all
    of COVID (2020 onward, every state, emergency and major-disaster alike)
    into one event."""
    return (incident_type or "").strip().lower() == "biological"


# ----------------------------------------------------------------------
# Unnamed-event clustering ("Path B")
#
# Named storms and COVID need no geography or timing at all, the title (or
# incident type) already says what they are. Everything else, a multi-state
# tornado outbreak, a regional flood, has no such label, so the only signal
# available is that the pieces happened close together in time and in
# neighboring places. That is a weaker, inferred kind of match, so it is kept
# separate from the two rules above and bounded carefully so it cannot chain
# unrelated declarations together.
# ----------------------------------------------------------------------
import datetime

# Contiguous-state and DC adjacency. Alaska, Hawaii, and the territories
# (GU, MP, PR, VI, AS) have no entries, so they are only ever grouped by the
# named-storm or COVID rules above, never by adjacency.
STATE_ADJACENCY = {
    "AL": {"FL", "GA", "MS", "TN"},
    "AZ": {"CA", "CO", "NM", "NV", "UT"},
    "AR": {"LA", "MS", "MO", "OK", "TN", "TX"},
    "CA": {"AZ", "NV", "OR"},
    "CO": {"AZ", "KS", "NE", "NM", "OK", "UT", "WY"},
    "CT": {"MA", "NY", "RI"},
    "DE": {"MD", "NJ", "PA"},
    "FL": {"AL", "GA"},
    "GA": {"AL", "FL", "NC", "SC", "TN"},
    "ID": {"MT", "NV", "OR", "UT", "WA", "WY"},
    "IL": {"IN", "IA", "KY", "MO", "WI"},
    "IN": {"IL", "KY", "MI", "OH"},
    "IA": {"IL", "MN", "MO", "NE", "SD", "WI"},
    "KS": {"CO", "MO", "NE", "OK"},
    "KY": {"IL", "IN", "MO", "OH", "TN", "VA", "WV"},
    "LA": {"AR", "MS", "TX"},
    "ME": {"NH"},
    "MD": {"DE", "PA", "VA", "WV", "DC"},
    "MA": {"CT", "NH", "NY", "RI", "VT"},
    "MI": {"IN", "OH", "WI"},
    "MN": {"IA", "ND", "SD", "WI"},
    "MS": {"AL", "AR", "LA", "TN"},
    "MO": {"AR", "IL", "IA", "KS", "KY", "NE", "OK", "TN"},
    "MT": {"ID", "ND", "SD", "WY"},
    "NE": {"CO", "IA", "KS", "MO", "SD", "WY"},
    "NV": {"AZ", "CA", "ID", "OR", "UT"},
    "NH": {"ME", "MA", "VT"},
    "NJ": {"DE", "NY", "PA"},
    "NM": {"AZ", "CO", "OK", "TX", "UT"},
    "NY": {"CT", "MA", "NJ", "PA", "VT"},
    "NC": {"GA", "SC", "TN", "VA"},
    "ND": {"MN", "MT", "SD"},
    "OH": {"IN", "KY", "MI", "PA", "WV"},
    "OK": {"AR", "CO", "KS", "MO", "NM", "TX"},
    "OR": {"CA", "ID", "NV", "WA"},
    "PA": {"DE", "MD", "NJ", "NY", "OH", "WV"},
    "RI": {"CT", "MA"},
    "SC": {"GA", "NC"},
    "SD": {"IA", "MN", "MT", "NE", "ND", "WY"},
    "TN": {"AL", "AR", "GA", "KY", "MS", "MO", "NC", "VA"},
    "TX": {"AR", "LA", "NM", "OK"},
    "UT": {"AZ", "CO", "ID", "NV", "NM", "WY"},
    "VT": {"MA", "NH", "NY"},
    "VA": {"KY", "MD", "NC", "TN", "WV", "DC"},
    "WA": {"ID", "OR"},
    "WV": {"KY", "MD", "OH", "PA", "VA"},
    "WI": {"IL", "IA", "MI", "MN"},
    "WY": {"CO", "ID", "MT", "NE", "SD", "UT"},
    "DC": {"MD", "VA"},
}

DEFAULT_GAP_DAYS = 4        # windows within this many days count as related
DEFAULT_SPAN_CAP_DAYS = 14  # a merged event's total date range may not exceed this


def related_states(states_a, states_b):
    """True if any state in A is the same as, or borders, any state in B."""
    if states_a & states_b:
        return True
    return any(b in STATE_ADJACENCY.get(a, ()) for a in states_a for b in states_b)


def _window_gap_days(begin_a, end_a, begin_b, end_b):
    """0 if the two date windows overlap; otherwise the number of days between
    the closer edges."""
    if end_a < begin_b:
        return (begin_b - end_a).days
    if end_b < begin_a:
        return (begin_a - end_b).days
    return 0


def unnamed_cluster_label(incident_types, begin_date):
    """Display name for a newly formed unnamed cluster (two or more unnamed
    declarations merged with no storm to name them), e.g.
    'Severe Storm (April 2011)'. Falls back to a generic label if the merged
    declarations do not share one incident type."""
    types = {t for t in incident_types if t}
    label = sorted(types)[0] if len(types) == 1 else "Severe Weather"
    return "%s (%s)" % (label, begin_date.strftime("%B %Y"))


def merge_unnamed(groups, gap_days=DEFAULT_GAP_DAYS, span_cap_days=DEFAULT_SPAN_CAP_DAYS):
    """
    Fold unnamed event groups into nearby named storms, or into each other,
    when time and geography say they are plausibly the same real-world event.

    groups: a list of dicts, one per event group already formed by the
    storm-name and COVID rules above, each with:
      key             the group's current event key (string)
      kind            "storm" | "covid" | "unnamed"
      states          set of USPS state codes the group's declarations touch
      begin, end      python date objects spanning the group's declarations
      incident_types  set of incident type strings across its declarations

    Returns a dict of old key -> new canonical key, for every group whose key
    changed. A group not present in the returned dict is unchanged.

    Two rules, both bounded by span_cap_days on the merged group's total date
    range (earliest begin to latest end), which is what stops a chain of
    adjacent, same-type declarations from growing across an entire season:
      ATTACH   an "unnamed" group may join an active "storm" group (never
               "covid") if their states are the same or adjacent and their
               windows are within gap_days of each other. Incident type is
               not checked; a storm's aftermath is often filed under a
               different type than the storm itself.
      CLUSTER  two "unnamed" groups may join each other under the same time
               and geography test, but only if they also share an incident
               type. With no name and no storm to anchor to, matching type is
               the one extra signal available, and it is what keeps two
               same-week floods in different states, or two similar storms
               weeks apart, from merging on geography alone.
    Two "storm" groups, "covid" with anything, or "storm" with "covid", never
    merge: a name is authoritative once one exists.

    Groups are swept in begin-date order so each new group is only compared
    against groups already open; an open group is dropped once it has fallen
    more than gap_days behind the sweep, since nothing later can ever reach it.
    """
    prepared = []
    for g in groups:
        h = dict(g)
        h["states"] = set(h["states"])
        h["incident_types"] = set(h["incident_types"])
        prepared.append(h)

    order = sorted(range(len(prepared)),
                   key=lambda i: (0 if prepared[i]["kind"] in ("storm", "covid") else 1,
                                  prepared[i]["begin"]))
    active = []   # open clusters: dict with key,kind,states,begin,end,incident_types
    remap = {}    # original key -> canonical key, for every key that moved

    def compatible(g, c):
        if g["kind"] == "covid" or c["kind"] == "covid":
            return False
        if g["kind"] == "storm" and c["kind"] == "storm":
            return False
        if g["kind"] == "unnamed" and c["kind"] == "unnamed":
            if not (g["incident_types"] & c["incident_types"]):
                return False
        if _window_gap_days(g["begin"], g["end"], c["begin"], c["end"]) > gap_days:
            return False
        if not related_states(g["states"], c["states"]):
            return False
        span = (max(g["end"], c["end"]) - min(g["begin"], c["begin"])).days
        return span <= span_cap_days

    for i in order:
        g = prepared[i]
        active = [c for c in active
                  if (g["begin"] - c["end"]).days <= gap_days]
        target = None
        for c in active:
            if compatible(g, c):
                target = c
                break
        if target is None:
            g["orig_keys"] = {g["key"]}
            active.append(g)
            continue
        target["states"] |= g["states"]
        target["incident_types"] |= g["incident_types"]
        target["begin"] = min(target["begin"], g["begin"])
        target["end"] = max(target["end"], g["end"])
        target["orig_keys"] |= {g["key"]}
        remap[g["key"]] = target["key"]

    return remap

