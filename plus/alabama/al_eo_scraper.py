"""Collect Alabama executive orders and state-of-emergency proclamations."""
from __future__ import annotations
import argparse,csv,html,re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ARCHIVE_URL="https://governor.alabama.gov/newsroom/category/state-of-emergency/"
EO_ARCHIVE_URL="https://governor.alabama.gov/newsroom/category/executive-orders/"
API_URL="https://governor.alabama.gov/wp-json/wp/v2/posts"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT=60
ACTION_FIELDS=("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS=("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS=("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE=re.compile(r"\b(drought|fires?|wildfires?|forest fires?|brush fires?|flood(?:ing)?|rainfall|heavy rain|hurricanes?|(?:sub)?tropical storms?|tropical depressions?|blizzard|winter|snow|ice|sleet|cold|freeze|freezing|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|hail|lightning|high winds?|damaging winds?)\b",re.I)
MODIFIER_RE=re.compile(r"\b(termination|rescind(?:s|ed|ing)?|supplemental|extend(?:s|ed|ing)?|extension|renew(?:s|ed|ing)?|amend(?:s|ed|ing)?|amendment)\b",re.I)
OFFICIAL_DESCRIPTION_ENRICHMENTS={
    "State of Emergency: St. Clair County": "smoldering underground landfill fire in St. Clair County",
}

@dataclass
class Action:
    stable_id:str; number:str; title:str; date:str; post_url:str; document_url:str; scope:str

def clean(value): return re.sub(r"\s+"," ",html.unescape(BeautifulSoup(value or "","html.parser").get_text(" ",strip=True))).strip()

def parse_post(post,scope):
    title=clean(post["title"]["rendered"]); content=BeautifulSoup(post["content"]["rendered"],"html.parser"); links=[urljoin(post["link"],a["href"]) for a in content.select('a[href$=".pdf"]')]
    anchor=next((clean(a.get_text(" ",strip=True)) for a in content.select('a[href$=".pdf"]') if clean(a.get_text(" ",strip=True)).lower()!="download"),"")
    desc=title if re.search(r"state of emergency|Executive Order",title,re.I) else anchor or title
    if re.fullmatch(r"Executive Order (?:No\. )?\d+",title,re.I) and anchor: desc=f"{title} — {anchor}"
    if title in OFFICIAL_DESCRIPTION_ENRICHMENTS: desc=f"{title} — {OFFICIAL_DESCRIPTION_ENRICHMENTS[title]}"
    m=re.search(r"Executive Order(?: No\.)?\s*(\d+)",title+" "+anchor,re.I); number=m.group(1) if m else ""
    date=post["date"][:10]
    embedded=re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b",title)
    if embedded: date=datetime.strptime(embedded.group(0),"%B %d, %Y").strftime("%Y-%m-%d")
    slug=re.sub(r"[^a-z0-9]+","-",title.lower()).strip("-")[:56]
    sid=f"AL-EO-{number}" if number else f"AL-SOE-{date}-{slug}"
    return Action(sid,number,desc,date,post["link"],links[0] if links else post["link"],scope)

def collect():
    out=[]
    for category,scope in ((19,"state_of_emergency"),(11,"executive_orders")):
        r=requests.get(API_URL,params={"categories":category,"per_page":100,"orderby":"date","order":"desc"},headers=HEADERS,timeout=TIMEOUT); r.raise_for_status()
        out.extend(parse_post(x,scope) for x in r.json())
    return sorted({a.stable_id:a for a in out}.values(),key=lambda a:(a.date,a.stable_id),reverse=True)

def classify(a):
    m=MODIFIER_RE.search(a.title)
    if m:
        w=m.group(0).lower(); return "termination" if w.startswith(("termination","rescind")) else "extension" if w.startswith(("extend","extension","renew")) else "amendment"
    if a.scope=="state_of_emergency" and re.search(r"\bstate of emergency\b",a.title,re.I): return "declaration"
    return "administrative"

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as h: w=csv.DictWriter(h,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(rows)

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; rel=[]; joins=[]
    for a in actions:
        kind=classify(a); weather=bool(HAZARD_RE.search(a.title)); row={"declaration_id":a.stable_id,"state":"AL","governor":"Kay Ivey","eo_number":a.number,"action_kind":"emergency_declaration" if kind!="administrative" else "executive_order","action_type":kind,"event_description":a.title,"date_signed":a.date,"end_date":"","weather_related":str(kind!="administrative" and weather).lower(),"source_scope":"alabama_governor_2017_present","document_format":"pdf","detail_url":a.document_url,"archive_record_url":a.post_url}; rows.append(row)
        if kind in {"termination","extension","amendment"}:
            relation={"termination":"terminates","extension":"extends","amendment":"amends"}[kind]
            for n in re.findall(r"Executive Order(?: No\.)?\s*(\d+)",a.title,re.I):
                if n!=a.number: rel.append({"source_order_id":a.stable_id,"target_order_id":"AL-EO-"+n,"relationship_type":relation,"relationship_text":n,"relationship_source":"official_archive_title","confidence":"high"})
        if kind=="declaration" and weather: joins.append({f:row[f] for f in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,rel); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--actions-out",required=True); p.add_argument("--relationships-out",required=True); p.add_argument("--join-out",required=True); a=p.parse_args(); write_outputs(collect(),a.actions_out,a.relationships_out,a.join_out)
if __name__=="__main__": main()
