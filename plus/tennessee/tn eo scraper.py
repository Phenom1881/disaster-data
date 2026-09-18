"""Collect Tennessee executive orders from the official catalog's preservation mirror."""
from __future__ import annotations

import argparse, csv, re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import requests
from bs4 import BeautifulSoup

OFFICIAL_ARCHIVE = "https://sos.tn.gov/products/division-publications/executive-orders"
MIRROR_ROOT = "https://digitalcommons.memphis.edu"
COLLECTIONS = {
    "Bill Lee": "govpubs-tn-governor-bill-lee-eo",
    "Bill Haslam": "govpubs-tn-governor-bill-haslam-eo",
    "Phil Bredesen": "govpubs-tn-governor-phil-bredesen-eo",
    "Don Sundquist": "govpubs-tn-governor-don-sundquist-eo",
}
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
ACTION_FIELDS = ("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS = ("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS = ("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE = re.compile(r"\b(drought|wildfires?|forest fires?|brush fires?|flood(?:ing)?|rainfall|heavy rain|hurricanes?|tropical storms?|tropical depressions?|blizzard|winter|snow|ice|sleet|cold|freeze|freezing|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|hail|lightning|high winds?|damaging winds?)\b", re.I)
# "end(s|ed|ing)" added alongside "terminat*": Tennessee's own archive has
# at least one real order ("An Order Ending The State Of Emergency...",
# Haslam EO 21) whose title uses "ending" rather than "terminating," which
# this regex missed before, letting a termination slip through classify()
# as a false original declaration.
MODIFIER_RE = re.compile(r"\b(rescind(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion)|end(?:s|ed|ing)?|extend(?:s|ed|ing)?|extension|renew(?:s|ed|ing)?|amend(?:s|ed|ing)?|amendment)\b", re.I)
NUMBER_RE = re.compile(r"\bNo\.?\s*(\d+)\b", re.I)
# Every entry below was verified against the actual signed order text (the
# "IN WITNESS WHEREOF ... this __ day of ___, ____" signature clause), not
# guessed from a title or from the archive's own upload/publication date,
# which can lag the order's real effective date by days or weeks. Two
# entries (Lee 105, Lee 110) were already present, verified against a
# tn.gov press release; the rest were added by reading each order's PDF at
# its DigitalCommons/University of Memphis mirror link directly.
#
# This dict is the ONLY place this scraper attaches a real signed date or a
# corroborating source to an order (see parse_detail()) - a pair absent
# from here gets ("", "") for both, and classify() also requires either
# this dict OR an exact "declaring/declaration of a state of emergency"
# title phrase to call an order a "declaration" at all. That is why, before
# this pass, only 2 of Tennessee's 279 collected executive orders across
# four governors ever reached the join file, despite dozens of genuine
# hurricane, tornado, flood, wildfire, and drought declarations sitting in
# the same archive under different phrasing.
#
# Bill Lee's tenure is fully reviewed as of this pass: every title in the
# full collected archive containing a HAZARD_RE keyword was checked, and
# every one that is a genuine original incident (not an amendment,
# extension, renewal, or termination of an earlier order) is listed below.
#
# Two borderline cases were found and are deliberately NOT resolved here,
# left for a human call rather than guessed:
#   - Lee 107 narrates a continuation of the disaster declared by Lee 105
#     ("later amended by Executive Order No. 106"), but does not amend or
#     extend either by number, and MODIFIER_RE does not match "continued."
#     It is listed below as its own entry because that is what its title
#     and classify() logic actually support, but whether it should count
#     as a second original incident or be treated as a continuation of 105
#     is a real methodology decision this scraper does not make on its own.
#   - Haslam's Executive Orders 66 and 67 both concern Hurricane Irma
#     relief and may be a related pair rather than two independent
#     incidents; Haslam's era has not yet had its dates individually
#     verified against document text the way Lee's has (see the module
#     docstring / handoff notes for the remaining Haslam and Bredesen
#     candidates identified by title but not yet confirmed here).
OFFICIAL_DECLARATIONS = {
    ("Bill Lee", "105"): ("2024-09-27", "https://www.tn.gov/tema/news/2024/9/27/flash-report--3---hurricane-helene.html"),
    ("Bill Lee", "110"): ("2026-01-22", "https://www.tn.gov/governor/news/2026/1/22/gov--lee-issues-state-of-emergency-ahead-of-major-winter-storm.html"),
    # Waverly / Humphreys County flood, Aug 21 2021 event; FEMA-4609-DR cited in the order's own text.
    ("Bill Lee", "85"): ("2021-08-25", "https://digitalcommons.memphis.edu/govpubs-tn-governor-bill-lee-eo/85"),
    # December 10-11 2021 Middle Tennessee tornado outbreak (at least 4 deaths, per the order's own text).
    ("Bill Lee", "94"): ("2021-12-13", "https://digitalcommons.memphis.edu/govpubs-tn-governor-bill-lee-eo/94"),
    # Sevier County wildfires beginning March 30 2022 (2 fires, 3,400+ acres, 221 structures, per the order's own text).
    ("Bill Lee", "96"): ("2022-04-20", "https://digitalcommons.memphis.edu/govpubs-tn-governor-bill-lee-eo/96"),
    # Hurricane Ian relief/logistics order (Tennessee providing transit relief, not a direct TN landfall).
    ("Bill Lee", "99"): ("2022-09-29", "https://digitalcommons.memphis.edu/govpubs-tn-governor-bill-lee-eo/99"),
    # Continuation of the Sept 27 2024 severe weather/flooding event declared by EO 105 - see note above.
    ("Bill Lee", "107"): ("2024-11-06", "https://digitalcommons.memphis.edu/govpubs-tn-governor-bill-lee-eo/107"),
}

# Real candidates identified in Bill Haslam's and Phil Bredesen's collected
# archives by the same title-keyword review used for Lee above, but NOT yet
# individually verified against each order's signed document text the way
# every Lee-era entry above was. Every title below genuinely names a real
# hazard (a specific hurricane, a drought, severe storms and tornadoes, or
# winter weather), confirmed by reading the full, untruncated title text,
# not a keyword match against an unrelated administrative order (see the
# NFIP exclusions noted below). None of these are in OFFICIAL_DECLARATIONS
# yet, so none of them affect page output until each is confirmed and
# added the same way the Lee entries were.
#
# Confirmed NOT to add here, and why:
#   - Haslam 74 and 51 ("Transferring Responsibilities Associated With The
#     National Flood Insurance Program...") matched the hazard keyword
#     regex only because "Flood" appears inside a standing program's name,
#     not because either order responds to an actual flood. Both are
#     ordinary administrative program-transfer orders, not declarations.
#   - Haslam 62, Bredesen 55, Bredesen 31, Bredesen 32 are amendments or
#     renewals of an earlier order (Haslam 61, Bredesen 53, Bredesen 27/28
#     respectively) and are correctly excluded as modifiers, matching the
#     page's own stated design.
#   - Haslam 21 ("An Order Ending The State Of Emergency...") is a
#     termination that MODIFIER_RE's word list does not catch, since
#     "ending" is not among rescind/terminate/extend/renew/amend. It should
#     be excluded as a termination, not added as an original - and
#     MODIFIER_RE itself should gain an "end(s|ed|ing)" alternative so this
#     class of title does not need a one-off carve-out here or in any other
#     state's copy of this pattern.
#
# Still needing individual document-text verification before being added:
#   Bill Haslam: 72 (Hurricane Florence), 67 & 66 (Hurricane Irma - possibly
#     a related pair, see note above), 64 & 59 & 42 (drought), 61 (wildfires
#     and severe weather), 58 (Hurricane Matthew), 57 (Louisiana flooding
#     evacuee relief - a TN order responding to another state's disaster,
#     same pattern as Lee 99), 44 (extreme winter weather), 17 & 14 & 09 & 08
#     (drought conditions in the Southeast US - possibly a renewed series
#     under new numbers rather than four independent declarations; needs
#     document review to tell them apart), 05 & 04 (storms and flooding).
#   Phil Bredesen: 66 & 65 (storms and flooding), 58 & 57 (Hurricane
#     Gustav evacuee relief), 53 (severe storms and tornadoes), 28 & 27
#     (Hurricane Katrina).
_HASLAM_BREDESEN_CANDIDATES_PENDING_VERIFICATION = (
    ("Bill Haslam", "72"), ("Bill Haslam", "67"), ("Bill Haslam", "66"),
    ("Bill Haslam", "64"), ("Bill Haslam", "61"), ("Bill Haslam", "59"),
    ("Bill Haslam", "58"), ("Bill Haslam", "57"), ("Bill Haslam", "44"),
    ("Bill Haslam", "42"), ("Bill Haslam", "17"), ("Bill Haslam", "14"),
    ("Bill Haslam", "09"), ("Bill Haslam", "08"), ("Bill Haslam", "05"),
    ("Bill Haslam", "04"),
    ("Phil Bredesen", "66"), ("Phil Bredesen", "65"), ("Phil Bredesen", "58"),
    ("Phil Bredesen", "57"), ("Phil Bredesen", "53"), ("Phil Bredesen", "28"),
    ("Phil Bredesen", "27"),
)

@dataclass
class Action:
    number: str; title: str; date: str; governor: str; detail_url: str; pdf_url: str; corroboration_url: str
    @property
    def stable_id(self): return f"TN-{re.sub(r'[^A-Z0-9]+','',self.governor.upper())}-EO-{self.number}"

def get(url):
    r=requests.get(url,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); return r

def parse_detail(url, governor):
    s=BeautifulSoup(get(url).text,"html.parser")
    def meta(name):
        node=s.select_one(f'meta[name="{name}"]'); return node.get("content","").strip() if node else ""
    title=meta("bepress_citation_title"); m=NUMBER_RE.search(title)
    if not m: return None
    raw=meta("bepress_citation_date"); year=int((raw or "0")[:4] or 0)
    if year and year<2000: return None
    signed,source=OFFICIAL_DECLARATIONS.get((governor,m.group(1)),("",""))
    return Action(m.group(1),re.sub(r"\s+"," ",title),signed,governor,url,meta("bepress_citation_pdf_url"),source)

def collection_links(governor, slug):
    url=f"{MIRROR_ROOT}/{slug}/"; s=BeautifulSoup(get(url).text,"html.parser")
    links={a.get("href") for a in s.select(".article-listing a[href]")}
    if governor=="Bill Lee": links.update(f"{url}{n}" for n in range(1,16))
    return [(u,governor) for u in links if u]

def collect():
    targets=[]
    for gov,slug in COLLECTIONS.items(): targets.extend(collection_links(gov,slug))
    with ThreadPoolExecutor(max_workers=12) as pool:
        rows=list(pool.map(lambda x: parse_detail(*x),targets))
    unique={a.stable_id:a for a in rows if a}
    return sorted(unique.values(),key=lambda a:(a.date,int(a.number)),reverse=True)

def classify(a):
    m=MODIFIER_RE.search(a.title)
    if m:
        w=m.group(0).lower(); return "termination" if w.startswith(("rescind","terminat")) else "extension" if w.startswith(("extend","extension","renew")) else "amendment"
    if (a.governor,a.number) in OFFICIAL_DECLARATIONS or re.search(r"\b(declaring|declaration of) (?:a )?state of emergency\b",a.title,re.I): return "declaration"
    return "administrative"

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows([{k:(v.replace("\r","") if isinstance(v,str) else v) for k,v in row.items()} for row in rows])

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; rel=[]; joins=[]
    for a in actions:
        kind=classify(a); weather=bool(HAZARD_RE.search(a.title))
        row={"declaration_id":a.stable_id,"state":"TN","governor":a.governor,"eo_number":a.number,"action_kind":"emergency_declaration" if kind!="administrative" else "executive_order","action_type":kind,"event_description":a.title,"date_signed":a.date,"end_date":"","weather_related":str(kind!="administrative" and weather).lower(),"source_scope":"tennessee_sos_catalog_via_state_university_preservation_mirror","document_format":"pdf","detail_url":a.pdf_url or a.detail_url,"archive_record_url":a.corroboration_url or a.detail_url}; rows.append(row)
        if kind in {"termination","extension","amendment"}:
            relation={"termination":"terminates","extension":"extends","amendment":"amends"}[kind]
            for n in re.findall(r"Executive Order (?:No\.? )?(\d+)",a.title,re.I):
                if n!=a.number: rel.append({"source_order_id":a.stable_id,"target_order_id":f"TN-{re.sub(r'[^A-Z0-9]+','',a.governor.upper())}-EO-{n}","relationship_type":relation,"relationship_text":n,"relationship_source":"archive_title","confidence":"high"})
        if kind=="declaration" and weather and a.date: joins.append({f:row[f] for f in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,rel); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--actions-out",required=True); p.add_argument("--relationships-out",required=True); p.add_argument("--join-out",required=True); a=p.parse_args(); write_outputs(collect(),a.actions_out,a.relationships_out,a.join_out)
if __name__=="__main__": main()
