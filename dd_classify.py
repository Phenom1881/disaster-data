"""
dd_classify.py  -- shared jurisdiction classifier for Disaster Data.

One source of truth for "what kind of place is this, and do we build a page for it."
Used by gen_jurisdiction_pages.py (to decide which localities get pages) and by
gen_state_pages.py (to decide which declarations are NOT attributed to any locality,
so they can be listed on the statewide page).

classify(state_ab, raw_name) -> dict:
    kind   : "county" | "city" | "tribal"  (page-worthy)  OR
             "statewide" | "minor"          (no page)
    keep   : bool  (True for county/city/tribal)
    display: cleaned display name (e.g. "Tazewell County", "Orleans Parish",
             "Pamunkey Indian Reservation", "Alexandria (city)")
    noun   : the locality-type word ("County","Parish","Borough","Municipio",...)
    base   : name with the type token stripped (used to build slugs)
"""
import re

# county-equivalents: token in the (...) -> display noun. All map to kind "county".
COUNTY_NOUN = {
    "County": "County",
    "Parish": "Parish",
    "Borough": "Borough",
    "Census Area": "Census Area",
    "Municipality": "Municipality",
    "City and Borough": "City and Borough",
    "County-equivalent": "County",
    "Municipio": "Municipio",
    "Island": "Island",
    "District": "District",
}

# explicit tribal type tokens
TRIBAL_TOKENS = {
    "Indian Reservation", "Reservation", "ANV/ANVSA", "OTSA", "TDSA",
    "TJSA", "SAIR", "Joint Area", "Native Regional Corporation",
}

# untyped tribal names (no parenthetical type) -- keyword detector
TRIBAL_RE = re.compile(
    r"reservation|tribe|tribes|pueblo|\bnation\b|\bband\b|rancheria|colony|"
    r"\bindian\b|sioux|mohawk|potawatomi|shoshon|paiute|chippewa|cherokee|"
    r"choctaw|creek|wampanoag|\bute\b|navajo|hopi|yakama|tulalip|catawba|"
    r"menominee|coushatta|chitimacha|kickapoo|winnebago|\bomaha\b|ponca|osage|"
    r"kiowa|comanche|apache|caddo|wichita|seminole|passamaquoddy|penobscot|"
    r"maliseet|micmac|quechan|mohegan|narragansett|schaghticoke|aquinnah|"
    r"chickahominy|mattaponi|pamunkey|nansemond|monacan|rappahannock|"
    r"\bTDSA\b|\bOTSA\b|\bANVSA\b|\bTJSA\b|\bSAIR\b",
    re.I,
)

# things we never build a page for (unorganized / sub-county survey / education areas)
DROP_RE = re.compile(
    r"Regional Educational Attendance Area|School District|\(Township of\)|"
    r"\(Plantation of\)|\bGore\b|\bGrant\b|Surplus|\bTract\b|\bStrip\b|"
    r"Unorganized Territory|\(Village of\)|\(Town of\)",
    re.I,
)

# states whose untyped, non-tribal names are genuine independent cities
CITY_STATES = {"VA", "MD", "MO", "NV"}

# qualifiers that are NOT type tokens (multi-state markers, metro-area notes)
_QUAL = re.compile(r"^\s*(also|in|&)\b", re.I)
# strip those qualifiers from display
_STRIP_QUAL = re.compile(r"\s*\((?:also|in|&)\b[^)]*\)", re.I)


def _type_token(raw):
    """First parenthetical that is a real type token (skip name/metro qualifiers)."""
    for m in re.findall(r"\(([^)]*)\)", raw):
        if _QUAL.match(m):
            continue
        return m.strip()
    return None


def _strip_all_parens(s):
    return re.sub(r"\s*\([^)]*\)", "", s).strip()


def classify(state_ab, raw):
    raw = raw.strip()
    name = _STRIP_QUAL.sub("", raw).strip()   # display-clean (qualifiers removed)

    if re.match(r"^statewide$", name, re.I):
        return {"kind": "statewide", "keep": False, "display": name, "noun": "", "base": name}

    tok = _type_token(raw)

    # county-equivalents
    if tok in COUNTY_NOUN:
        base = _strip_all_parens(name)
        noun = COUNTY_NOUN[tok]
        disp = base if base.endswith(noun) else (base + " " + noun)
        return {"kind": "county", "keep": True, "display": disp, "noun": noun, "base": base}

    # Alaska untyped census areas / city-and-borough written without parens
    m = re.search(r"\b(Census Area|City and Borough)\b", name)
    if m and tok not in TRIBAL_TOKENS:
        noun = m.group(1)
        base = name[: m.start()].strip()
        return {"kind": "county", "keep": True, "display": name, "noun": noun, "base": base or name}

    # tribal (typed or untyped)
    if tok in TRIBAL_TOKENS or TRIBAL_RE.search(name):
        base = re.sub(r"\s*\((?:TDSA|OTSA|ANV/ANVSA|TJSA|SAIR)\)", "", name, flags=re.I).strip()
        base = re.sub(r"\s+(?:TDSA|OTSA|ANVSA|TJSA|SAIR)$", "", base, flags=re.I).strip()
        if base.isupper():
            base = base.title()
        return {"kind": "tribal", "keep": True, "display": base, "noun": "", "base": base}

    # explicit drop list (townships, gores, grants, REAAs, surplus, ...)
    if DROP_RE.search(raw):
        return {"kind": "minor", "keep": False, "display": name, "noun": "", "base": name}

    # untyped, non-tribal in an independent-city state -> independent city
    if "(" not in raw and state_ab in CITY_STATES:
        return {"kind": "city", "keep": True, "display": name + " (city)", "noun": "city", "base": name}

    # everything else: not page-worthy (minor / unorganized / territorial parcel)
    return {"kind": "minor", "keep": False, "display": name, "noun": "", "base": name}
