"""Collect Florida executive orders from the Governor's official archive."""
from __future__ import annotations

import argparse, csv, re, sys
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ARCHIVE_URL = "https://www.flgov.com/eog/news/executive-orders"
TIMEOUT = 60
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
ACTION_FIELDS = ("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS = ("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS = ("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE = re.compile(r"\b(drought|wildfires?|forest fires?|brush fires?|fire weather|flood(?:ing)?|rainfall|heavy rain|mudslide|landslide|hurricanes?|tropical storms?|tropical depressions?|tropical weather|cyclone|blizzard|winter storms?|winter weather|snow(?:fall|storm)?|ice|icing|sleet|cold|freeze|freezing|nor['’]?easter|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|hail|lightning|wind storms?|high winds?|damaging winds?|wind gusts?)\b", re.I)
MODIFIER_RE = re.compile(r"\b(rescind(?:s|ed|ing)?|termination|terminate[sd]?|extend(?:s|ed|ing)?|extension|renew(?:s|ed|ing)?|amend(?:s|ed|ing)?|amendment)\b", re.I)
EO_RE = re.compile(r"\b(?:executive order\s*)?(\d{2,4}-\d{1,3})\b", re.I)

@dataclass
class Action:
    number: str; title: str; date: str; document_url: str
    @property
    def stable_id(self): return "FL-EO-" + self.number

def fetch(url, params=None):
    r=requests.get(url,params=params,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); return r

def parse_page(html):
    soup=BeautifulSoup(html,"html.parser"); out=[]
    for row in soup.select("table tbody tr"):
        a=row.select_one("td.views-field-field-file-upload a[href]"); t=row.select_one("time")
        if not a or not t: continue
        title=re.sub(r"\s+"," ",a.get_text(" ",strip=True)); m=re.search(r"#(\d{4}-\d{1,3})",title)
        if m: out.append(Action(m.group(1),title,t.get("datetime","")[:10] or datetime.strptime(t.get_text(strip=True),"%m/%d/%Y").strftime("%Y-%m-%d"),urljoin(ARCHIVE_URL,a["href"])))
    return out

def classify(a):
    m=MODIFIER_RE.search(a.title)
    if m:
        w=m.group(0).lower()
        return "termination" if w.startswith(("rescind","terminate")) else "extension" if w.startswith(("extend","extension","renew")) else "amendment"
    if re.search(r"\b(state of emergency|emergency management)\b",a.title,re.I): return "declaration"
    return "administrative"

def collect():
    out=[]
    for year_value in range(1,8):
        for page in range(100):
            r=fetch(ARCHIVE_URL,{"field_date_value":year_value,"page":page}); batch=parse_page(r.text)
            if not batch: break
            out.extend(batch)
            if not BeautifulSoup(r.text,"html.parser").select_one('a[rel="next"]'): break
    return sorted({a.stable_id:a for a in out}.values(),key=lambda a:(a.date,a.number),reverse=True)

def relationships(a,kind):
    if kind not in {"termination","extension","amendment"}: return []
    rel={"termination":"terminates","extension":"extends","amendment":"amends"}[kind]; rows=[]
    for n in EO_RE.findall(a.title):
        n=("20"+n) if re.fullmatch(r"\d{2}-\d+",n) else n
        target="FL-EO-"+n
        if target!=a.stable_id: rows.append({"source_order_id":a.stable_id,"target_order_id":target,"relationship_type":rel,"relationship_text":n,"relationship_source":"official_archive_title","confidence":"high"})
    return rows

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as h:
        w=csv.DictWriter(h,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows([{k:(v.replace("\r","") if isinstance(v,str) else v) for k,v in row.items()} for row in rows])

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; rel=[]; joins=[]
    for a in actions:
        kind=classify(a); weather=bool(HAZARD_RE.search(a.title) or (kind=="declaration" and re.search(r"\b(?:Invest \d+[A-Z]|Subtropical Storm)\b",a.title,re.I))); action_kind="emergency_declaration" if kind!="administrative" else "executive_order"
        row={"declaration_id":a.stable_id,"state":"FL","governor":"Ron DeSantis","eo_number":a.number,"action_kind":action_kind,"action_type":kind,"event_description":a.title,"date_signed":a.date,"end_date":"","weather_related":str(weather and kind!="administrative").lower(),"source_scope":"florida_governor_2020_present","document_format":"pdf","detail_url":a.document_url,"archive_record_url":ARCHIVE_URL}
        rows.append(row); rel.extend(relationships(a,kind))
        if kind=="declaration" and weather: joins.append({f:row[f] for f in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,rel); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--actions-out",required=True); p.add_argument("--relationships-out",required=True); p.add_argument("--join-out",required=True); a=p.parse_args()
    write_outputs(collect(),a.actions_out,a.relationships_out,a.join_out)
if __name__=="__main__": main()
