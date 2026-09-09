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
MODIFIER_RE = re.compile(r"\b(rescind(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion)|extend(?:s|ed|ing)?|extension|renew(?:s|ed|ing)?|amend(?:s|ed|ing)?|amendment)\b", re.I)
NUMBER_RE = re.compile(r"\bNo\.?\s*(\d+)\b", re.I)
OFFICIAL_DECLARATIONS = {
    ("Bill Lee", "105"): ("2024-09-27", "https://www.tn.gov/tema/news/2024/9/27/flash-report--3---hurricane-helene.html"),
    ("Bill Lee", "110"): ("2026-01-22", "https://www.tn.gov/governor/news/2026/1/22/gov--lee-issues-state-of-emergency-ahead-of-major-winter-storm.html"),
}

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
