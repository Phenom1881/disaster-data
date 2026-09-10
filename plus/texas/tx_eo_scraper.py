"""Collect Texas disaster proclamations from the official Governor news archive."""
from __future__ import annotations
import argparse, csv, re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

ARCHIVE_URL="https://gov.texas.gov/news/category/proclamation"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT=90
ACTION_FIELDS=("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS=("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS=("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE=re.compile(r"\b(severe storms?|severe weather|flood(?:s|ing)?|flash flood(?:s|ing)?|hurricanes?|tropical storms?|tropical depressions?|wildfires?|fire weather|forest fires?|drought|winter storms?|winter weather|snow|ice|freez(?:e|ing)|extreme heat|tornado(?:es)?|hail|heavy rain|wind gusts?|high winds?|straight-line winds?)\b",re.I)
MODIFIER_RE=re.compile(r"\b(amend(?:s|ed|ing|ment)?|renew(?:s|ed|ing|al)?|extend(?:s|ed|ing)?|extension|adding|add(?:s|ed)?(?:\s+an)?(?:\s+additional)?(?:\s+\d+)?\s+count(?:y|ies)|additional\s+\d+\s+counties|expand(?:s|ed|ing)?|rescind(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion))\b",re.I)
OPERATIONAL_RE=re.compile(r"\b(evacuation|curfew|price gouging|leave with pay|hours of service|vehicle regulations?|suspend(?:s|ed|ing)? (?:tax|hotel|motel)|suspension of regulations?)\b",re.I)
RELEVANT_RE=re.compile(r"\b(proclamation|state of disaster|disaster declaration)\b",re.I)
HAZARD_OVERRIDES={}

@dataclass(frozen=True)
class Action:
    number:str; title:str; date:str; url:str; text:str; governor:str="Greg Abbott"
    @property
    def stable_id(self): return "TX-"+self.number

def get(url):
    response=requests.get(url,headers=HEADERS,timeout=TIMEOUT); response.raise_for_status(); return response

def parse_detail(url,title):
    soup=BeautifulSoup(get(url).text,"html.parser"); main=soup.select_one("main") or soup
    text=re.sub(r"\s+"," ",main.get_text(" ",strip=True))
    if not re.search(r"\|\s*Proclamation\b",text): return None
    match=re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b",text)
    date=""
    if match:
        months={name:i for i,name in enumerate("January February March April May June July August September October November December".split(),1)}
        date=f"{match.group(3)}-{months[match.group(1)]:02d}-{int(match.group(2)):02d}"
    slug=urlparse(url).path.rstrip("/").rsplit("/",1)[-1]
    number=f"PROCLAMATION-{date or 'UNDATED'}-{slug}"
    governor="Dan Patrick" if re.search(r"Acting Governor Dan Patrick",title,re.I) else "Greg Abbott"
    return Action(number,title,date,url,text,governor)

def parse_listing(html):
    soup=BeautifulSoup(html,"html.parser"); out=[]
    for anchor in soup.select("h3 a[href*='/news/post/']"):
        title=re.sub(r"\s+"," ",anchor.get_text(" ",strip=True))
        if RELEVANT_RE.search(title): out.append((urljoin(ARCHIVE_URL,anchor["href"]),title))
    next_link=soup.select_one("a.pagination-next[href]")
    return out,(urljoin(ARCHIVE_URL,next_link["href"]) if next_link else "")

def collect():
    month_urls=[f"https://gov.texas.gov/news/archive/{year}/{month:02d}" for year in range(2015,2027) for month in range(1,13)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        pages=list(pool.map(lambda url: get(url).text,month_urls))
    targets=[]
    for page in pages: targets.extend(parse_listing(page)[0])
    unique=dict(targets)
    def safe_parse(pair):
        try:
            return parse_detail(*pair)
        except requests.RequestException:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        actions=list(pool.map(safe_parse,unique.items()))
    return sorted({item.stable_id:item for item in actions if item and (not item.date or item.date>="2015-01-20")}.values(),key=lambda item:(item.date,item.number),reverse=True)

def classify(action):
    if re.match(r"Dr\.\s+John Hellerstedt",action.title,re.I): return "administrative"
    modifier=MODIFIER_RE.search(action.title)
    if modifier:
        word=modifier.group(0).lower()
        if word.startswith(("rescind","terminat")): return "termination"
        if word.startswith(("renew","extend")): return "extension"
        return "amendment"
    if OPERATIONAL_RE.search(action.title): return "administrative"
    evidence=action.title+" "+action.text
    if re.search(r"\b(issues?|declares?|signed?)\b.{0,80}\b(disaster (?:declaration|proclamation)|state of disaster)\b",evidence,re.I) or re.search(r"\bdo hereby (?:certify|declare)\b.{0,120}\bdisaster\b",action.text,re.I): return "declaration"
    return "administrative"

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,lineterminator="\n"); writer.writeheader(); writer.writerows(rows)

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; joins=[]
    for action in actions:
        kind=classify(action); evidence=action.title+" "+action.text; weather=kind=="declaration" and bool(HAZARD_RE.search(evidence))
        row={"declaration_id":action.stable_id,"state":"TX","governor":action.governor,"eo_number":action.number,"action_kind":"emergency_declaration" if kind!="administrative" else "proclamation","action_type":kind,"event_description":action.title,"date_signed":action.date,"end_date":"","weather_related":str(weather).lower(),"source_scope":"texas_governor_proclamation_archive_2015_present","document_format":"html","detail_url":action.url,"archive_record_url":action.url}; rows.append(row)
        if weather and action.date: joins.append({field:row[field] for field in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,[]); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--actions-out",required=True); parser.add_argument("--relationships-out",required=True); parser.add_argument("--join-out",required=True)
    args=parser.parse_args(); write_outputs(collect(),args.actions_out,args.relationships_out,args.join_out)
if __name__=="__main__": main()
