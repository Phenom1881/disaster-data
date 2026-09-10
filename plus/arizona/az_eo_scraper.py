"""Collect Arizona executive orders from the current Governor's official archive."""
from __future__ import annotations
import argparse, csv, re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

ARCHIVE_URL = "https://azgovernor.gov/executive-orders"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT = 90
ACTION_FIELDS = ("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS = ("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS = ("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE = re.compile(r"\b(wildfires?|forest fires?|flood(?:s|ing)?|flash flood(?:s|ing)?|severe (?:storms?|weather)|winter storms?|winter weather|snow|ice|freez(?:e|ing)|drought|extreme heat|heat emergency|tornado(?:es)?|hail|heavy rain(?:fall)?|high winds?|monsoon|hurricanes?|tropical storms?)\b", re.I)
MODIFIER_RE = re.compile(r"\b(amend(?:s|ed|ing|ment)?|renew(?:s|ed|ing|al)?|extend(?:s|ed|ing|sion)?|rescind(?:s|ed|ing)?|replac(?:e|es|ed|ing)|terminat(?:e|es|ed|ing|ion)|revok(?:e|es|ed|ing))\b", re.I)
OPERATIONAL_RE = re.compile(r"\b(evacuation|curfew|price gouging|leave with pay|hours of service|transportation waiver|suspension of regulations?)\b", re.I)
HAZARD_OVERRIDES = {}

@dataclass(frozen=True)
class Action:
    number: str; title: str; date: str; url: str; text: str
    @property
    def stable_id(self): return "AZ-" + self.number

def get(url):
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT); response.raise_for_status(); return response

def normalize_number(raw, date):
    match = re.search(r"20\d{2}-\d{1,2}", raw)
    if match: return match.group(0)
    digits = re.search(r"\b(\d{1,2})\b", raw)
    return f"{date[:4]}-{int(digits.group(1)):02d}" if digits and date else raw.strip()

def parse_listing(html, base_url=ARCHIVE_URL):
    soup = BeautifulSoup(html, "html.parser"); out = []
    seen = set()
    for anchor in soup.select("a[href]"):
        href = urljoin(base_url, anchor["href"])
        if "/executive-order/" not in urlparse(href).path or href in seen: continue
        seen.add(href); block = anchor.find_parent(["article", "li", "div"]) or anchor
        blob = re.sub(r"\s+", " ", block.get_text(" ", strip=True))
        number_match = re.search(r"Executive Order:\s*(?:Executive Order\s*)?([^\s]+(?:\s+\d+)?)", blob, re.I)
        date_match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b", blob)
        if not number_match or not date_match: continue
        date = datetime.strptime(date_match.group(0), "%B %d, %Y").strftime("%Y-%m-%d")
        raw_number = number_match.group(1)
        number = normalize_number(raw_number, date)
        title = re.split(r"Executive Order:", blob, maxsplit=1, flags=re.I)[0].strip()
        out.append((number, title, date, href))
    return out

def parse_detail(number, title, date, url):
    soup = BeautifulSoup(get(url).text, "html.parser"); main = soup.select_one("main") or soup
    text = re.sub(r"\s+", " ", main.get_text(" ", strip=True))
    return Action(number, title, date, url, text)

def collect():
    records = []
    for page in range(5):
        url = ARCHIVE_URL + (f"?page={page}" if page else "")
        records.extend(parse_listing(get(url).text, url))
    unique = {row[0]: row for row in records}
    return sorted((parse_detail(*row) for row in unique.values()), key=lambda item:(item.date,item.number), reverse=True)

def classify(action):
    modifier = MODIFIER_RE.search(action.title)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind","terminat","revok")): return "termination"
        if word.startswith(("renew","extend")): return "extension"
        return "amendment"
    if OPERATIONAL_RE.search(action.title): return "administrative"
    evidence = action.title + " " + action.text
    if re.search(r"\b(?:hereby|do)\s+(?:declare|proclaim)\b.{0,120}\b(?:state of emergency|disaster)\b", evidence, re.I) or re.search(r"\bdeclar(?:ing|ation of)\b.{0,100}\b(?:state of emergency|disaster)\b", action.title, re.I): return "declaration"
    return "administrative"

def relationships(actions):
    known = {item.number for item in actions}; rows=[]
    for action in actions:
        kind=classify(action)
        if kind not in {"amendment","extension","termination"}: continue
        for target in sorted(set(re.findall(r"\b20\d{2}-\d{1,2}\b", action.title+" "+action.text))-{action.number}):
            if target in known: rows.append({"source_order_id":action.stable_id,"target_order_id":"AZ-"+target,"relationship_type":kind,"relationship_text":action.title,"relationship_source":action.url,"confidence":"high"})
    return rows

def write_csv(path, fields, rows):
    with open(path,"w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,lineterminator="\n"); writer.writeheader(); writer.writerows(rows)

def write_outputs(actions, actions_out, relationships_out, join_out):
    rows=[]; joins=[]
    for action in actions:
        kind=classify(action); evidence=action.title+" "+action.text; weather=kind=="declaration" and bool(HAZARD_RE.search(evidence))
        row={"declaration_id":action.stable_id,"state":"AZ","governor":"Katie Hobbs","eo_number":action.number,"action_kind":"executive_order","action_type":kind,"event_description":action.title,"date_signed":action.date,"end_date":"","weather_related":str(weather).lower(),"source_scope":"arizona_governor_executive_orders_2023_present","document_format":"html","detail_url":action.url,"archive_record_url":action.url}; rows.append(row)
        if weather and kind=="declaration" and action.date: joins.append({field:row[field] for field in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,relationships(actions)); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--actions-out",required=True); parser.add_argument("--relationships-out",required=True); parser.add_argument("--join-out",required=True)
    args=parser.parse_args(); write_outputs(collect(),args.actions_out,args.relationships_out,args.join_out)
if __name__=="__main__": main()
