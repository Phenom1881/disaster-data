"""Collect Mississippi executive orders and emergency declarations from the Governor's site."""
from __future__ import annotations
import argparse,csv,html,re
from dataclasses import dataclass
import requests
from bs4 import BeautifulSoup

ARCHIVE_URL="https://governorreeves.ms.gov/"
API_ROOT="https://governorreeves.ms.gov/wp-json/wp/v2"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT=60
ACTION_FIELDS=("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS=("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS=("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE=re.compile(r"\b(drought|wildfires?|burn ban|forest fires?|brush fires?|flood(?:ing)?|rainfall|heavy rain|hurricanes?|tropical storms?|tropical depressions?|gulf storms?|blizzard|winter|snow|ice|sleet|cold|freeze|freezing|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|hail|lightning|high winds?|damaging winds?)\b",re.I)
MODIFIER_RE=re.compile(r"\b(end(?:s|ed|ing)?|termination|rescind(?:s|ed|ing)?|supplemental|extend(?:s|ed|ing)?|extension|renew(?:s|ed|ing)?|amend(?:s|ed|ing)?|amendment)\b",re.I)

@dataclass
class Action:
    stable_id:str; number:str; title:str; date:str; detail_url:str; archive_url:str; source_kind:str

def clean(value): return re.sub(r"\s+"," ",html.unescape(BeautifulSoup(value or "","html.parser").get_text(" ",strip=True))).strip()

def pages(endpoint,fields):
    out=[]
    for page in range(1,20):
        r=requests.get(f"{API_ROOT}/{endpoint}",params={"per_page":100,"page":page,"_fields":fields},headers=HEADERS,timeout=TIMEOUT)
        if r.status_code==400: break
        r.raise_for_status(); out.extend(r.json())
        if page>=int(r.headers.get("X-WP-TotalPages","1")): break
    return out

def parse_media(x):
    title=clean(x["title"]["rendered"]); url=x["source_url"]; m=re.search(r"Executive Order(?: No\.)?\s*[-–—]?\s*(\d+)",title+" "+url,re.I); number=m.group(1) if m else ""
    if not number and "State of Emergency Declaration" not in title: return None
    date=x["date"][:10]; sid=f"MS-EO-{number}" if number else f"MS-ACTION-{date}-state-of-emergency-declaration"
    return Action(sid,number,title,date,url,f"{API_ROOT}/media/{x['id']}","media")

def parse_post(x):
    title=clean(x["title"]["rendered"])
    if not re.search(r"Governor (?:Tate )?Reeves (?:Issues|Declares|Extends|Ends) (?:a |Mississippi.s )?State of Emergency",title,re.I): return None
    if re.search(r"federal|President",title,re.I): return None
    date=x["date"][:10]; m=re.search(r"Executive Order(?: No\.)?\s*(\d+)",clean(x.get("content",{}).get("rendered","")),re.I); number=m.group(1) if m else ""
    slug=re.sub(r"[^a-z0-9]+","-",title.lower()).strip("-")[:58]; sid=f"MS-EO-{number}" if number else f"MS-ACTION-{date}-{slug}"
    return Action(sid,number,title,date,x["link"],f"{API_ROOT}/posts/{x['id']}","newsroom")

def collect():
    media=[parse_media(x) for x in pages("media","id,date,source_url,title") if x.get("source_url","").lower().endswith(".pdf")]
    posts=[parse_post(x) for x in pages("posts","id,date,link,title,content")]
    unique={a.stable_id:a for a in media+posts if a}
    return sorted(unique.values(),key=lambda a:(a.date,a.stable_id),reverse=True)

def classify(a):
    m=MODIFIER_RE.search(a.title)
    if m:
        w=m.group(0).lower(); return "termination" if w.startswith(("end","termination","rescind")) else "extension" if w.startswith(("extend","extension","renew")) else "amendment"
    if re.search(r"\b(state of emergency declaration|declares? state of emergency|issues? state of emergency)\b",a.title,re.I): return "declaration"
    return "administrative"

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as h: w=csv.DictWriter(h,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(rows)

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; rel=[]; joins=[]
    for a in actions:
        kind=classify(a); weather=bool(HAZARD_RE.search(a.title)); row={"declaration_id":a.stable_id,"state":"MS","governor":"Tate Reeves","eo_number":a.number,"action_kind":"emergency_declaration" if kind!="administrative" else "executive_order","action_type":kind,"event_description":a.title,"date_signed":a.date,"end_date":"","weather_related":str(kind!="administrative" and weather).lower(),"source_scope":"mississippi_governor_2020_present","document_format":"pdf" if a.detail_url.lower().endswith(".pdf") else "html","detail_url":a.detail_url,"archive_record_url":a.archive_url}; rows.append(row)
        if kind in {"termination","extension","amendment"}:
            relation={"termination":"terminates","extension":"extends","amendment":"amends"}[kind]
            for n in re.findall(r"Executive Order(?: No\.)?\s*(\d+)",a.title,re.I):
                if n!=a.number: rel.append({"source_order_id":a.stable_id,"target_order_id":"MS-EO-"+n,"relationship_type":relation,"relationship_text":n,"relationship_source":"official_archive_title","confidence":"high"})
        if kind=="declaration" and weather: joins.append({f:row[f] for f in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,rel); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--actions-out",required=True); p.add_argument("--relationships-out",required=True); p.add_argument("--join-out",required=True); a=p.parse_args(); write_outputs(collect(),a.actions_out,a.relationships_out,a.join_out)
if __name__=="__main__": main()
