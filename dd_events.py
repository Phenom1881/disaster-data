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
