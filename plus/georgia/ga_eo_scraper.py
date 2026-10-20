"""Collect Georgia executive orders from official current and preserved archives."""
from __future__ import annotations
import argparse,csv,re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

CURRENT_ROOT="https://gov.georgia.gov"
ARCHIVE_URL=CURRENT_ROOT+"/executive-action/executive-orders/executive-order-archives"
DEAL_ROOT="https://nathandeal.georgia.gov"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT=60
ACTION_FIELDS=("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS=("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS=("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE=re.compile(r"\b(drought|wildfires?|forest fires?|brush fires?|fire weather|flood(?:ing)?|rainfall|heavy rain|mudslide|landslide|hurricanes?|tropical storms?|tropical depressions?|tropical weather|cyclone|blizzard|winter storms?|winter weather|snow(?:fall|storm)?|ice|icing|sleet|cold|freeze|freezing|nor['’]?easter|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|hail|lightning|wind storms?|high winds?|damaging winds?|wind gusts?)\b",re.I)
MODIFIER_RE=re.compile(r"\b(rescind(?:s|ed|ing)?|terminate[sd]?|extend(?:s|ed|ing)?|extension|renew(?:s|ed|ing)?|renewal|amend(?:s|ed|ing)?|expand(?:s|ed|ing)?)\b",re.I)
OPERATIONAL_RE=re.compile(r"\b(suspending fuel taxes|national guard troops|commercial vehicle|transportation regulations|legal holidays?|leave with pay|closing state offices|evacuation order|curfew)\b",re.I)
NUMBER_RE=re.compile(r"\b\d{2}\.\d{2}\.\d{2}\.\d{1,2}\b")
# Declarations whose titles give only the counties ("Declaring a State of
# Emergency for 14 counties in North Georgia"), each read in the Governor's
# press release for the order (cited in hazard_overrides.csv). Expansions of
# an emergency already declared, such as 12.30.15.01 for the December 2015
# flooding, are not listed: they are not new declarations.
REVIEWED_WEATHER={
    "GA-EO-01-28-14-02":"winter storm, statewide, January 28, 2014",
    "GA-EO-02-10-14-01":"winter storm warning, 14 North Georgia counties",
    "GA-EO-02-15-15-01":"winter storm with icing, 15 North Georgia counties",
    "GA-EO-02-24-15-01":"winter storm warning, 50 North Georgia counties, from February 25, 2015",
    "GA-EO-12-24-15-01":"flooding and storm damage, Fannin, Gilmer and Pickens counties",
    "GA-EO-01-19-16-01":"winter storm warning, 15 counties",
    "GA-EO-01-21-16-02":"second winter storm of January 2016, 21 counties",
    "GA-EO-01-22-17-01":"tornadoes, January 21 and 22, 2017, seven South Central Georgia counties",
    "GA-EO-01-02-18-01":"winter storm, 28 counties, January 2018",
}

@dataclass
class Action:
    number:str; description:str; url:str; source:str
    @property
    def date(self):
        try: return datetime.strptime(".".join(self.number.split(".")[:3]),"%m.%d.%y").strftime("%Y-%m-%d")
        except ValueError: return ""
    @property
    def stable_id(self): return "GA-EO-"+self.number.replace(".","-")

def fetch(url):
    r=requests.get(url,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); return r.text

def parse_current(html,page_url):
    s=BeautifulSoup(html,"html.parser"); out=[]
    for tr in s.select("table#datatable tbody tr"):
        a=tr.select_one('a[href*="download"]'); d=tr.select_one("td.views-field-field-document-description")
        if not a or not d: continue
        number=re.sub(r"\s+","",a.get_text(" ",strip=True));
        if NUMBER_RE.fullmatch(number): out.append(Action(number,re.sub(r"\s+"," ",d.get_text(" ",strip=True)),urljoin(page_url,a["href"]),page_url))
    return out

def parse_deal(html,page_url):
    s=BeautifulSoup(html,"html.parser"); out=[]
    for a in s.select('a[href$=".pdf"]'):
        href=a.get("href",""); m=re.search(r"(\d{2}\.\d{2}\.\d{2}\.\d{1,2})\.pdf",href,re.I)
        if not m: continue
        desc=re.sub(r"\s+"," ",a.get_text(" ",strip=True)); out.append(Action(m.group(1),desc,urljoin(page_url,href),page_url))
    return out

# The Governor's yearly pages list at most 500 orders each. 2020, 2021, 2023
# and 2024 came back with exactly 500 and without their earliest weeks: 2023
# began at January 18, so the January 12, 2023 tornado declaration
# (01.12.23.02) was never read. The rest of a year is on later pages
# (?page=1, ?page=2, ...). Reading stops at the first page that adds no order
# not already seen, so a page that ignores the parameter ends it at once.
MAX_PAGES=20

def collect_year(url,get=None):
    get=get or fetch; out=[]; seen=set()
    for page in range(MAX_PAGES):
        page_url=url if page==0 else f"{url}?page={page}"
        try: html=get(page_url)
        except requests.HTTPError:
            if page==0: raise
            break
        new=[a for a in parse_current(html,page_url) if a.number not in seen]
        if not new: break
        for a in new: a.source=url
        seen.update(a.number for a in new); out.extend(new)
    return out

def collect():
    out=[]
    for y in range(2019,datetime.now().year+1):
        suffix=f"{y}" if y>=2022 else f"{y}-executive-orders"; u=f"{CURRENT_ROOT}/executive-action/executive-orders/{suffix}"; out.extend(collect_year(u))
    for y in range(2011,2019):
        u=f"{DEAL_ROOT}/{'2011-executive-orders' if y==2011 else 'executive-orders/'+str(y)}"; out.extend(parse_deal(fetch(u),u))
    return sorted({a.stable_id:a for a in out}.values(),key=lambda a:(a.date,a.number),reverse=True)

def classify(a):
    m=MODIFIER_RE.search(a.description)
    if m:
        w=m.group(0).lower(); return "termination" if w.startswith(("rescind","terminate")) else "extension" if w.startswith(("extend","extension","renew")) else "amendment"
    if OPERATIONAL_RE.search(a.description): return "administrative"
    if re.search(r"\b(declar(?:es|ing|ation)(?: a)? state of (?:emergency|preparedness))\b",a.description,re.I): return "declaration"
    return "administrative"

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as h: w=csv.DictWriter(h,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows([{k:(v.replace("\r","") if isinstance(v,str) else v) for k,v in row.items()} for row in rows])

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; rel=[]; joins=[]
    for a in actions:
        kind=classify(a); weather=bool(HAZARD_RE.search(a.description) or re.search(r"\bstorms?\b|\bweather conditions?\b",a.description,re.I) or a.stable_id in REVIEWED_WEATHER); gov="Nathan Deal" if a.date<"2019-01-14" else "Brian P. Kemp"
        row={"declaration_id":a.stable_id,"state":"GA","governor":gov,"eo_number":a.number,"action_kind":"emergency_declaration" if kind!="administrative" else "executive_order","action_type":kind,"event_description":a.description,"date_signed":a.date,"end_date":"","weather_related":str(weather and kind!="administrative").lower(),"source_scope":"georgia_governor_2011_present","document_format":"pdf","detail_url":a.url,"archive_record_url":a.source}; rows.append(row)
        refs=NUMBER_RE.findall(a.description)
        for n in refs:
            target="GA-EO-"+n.replace(".","-")
            if target!=a.stable_id and kind in {"termination","extension","amendment"}: rel.append({"source_order_id":a.stable_id,"target_order_id":target,"relationship_type":{"termination":"terminates","extension":"extends","amendment":"amends"}[kind],"relationship_text":n,"relationship_source":"official_archive_description","confidence":"high"})
        if kind=="declaration" and weather: joins.append({f:row[f] for f in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,rel); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--actions-out",required=True); p.add_argument("--relationships-out",required=True); p.add_argument("--join-out",required=True); a=p.parse_args(); write_outputs(collect(),a.actions_out,a.relationships_out,a.join_out)
if __name__=="__main__": main()
