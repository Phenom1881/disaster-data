"""Collect Arkansas executive orders from the Governor's official public API."""
from __future__ import annotations
import argparse, csv, html as html_module, re
from dataclasses import dataclass
from datetime import datetime
import requests
from bs4 import BeautifulSoup

API_URL="https://governor.arkansas.gov/wp-json/wp/v2/executive_orders"
ARCHIVE_URL="https://governor.arkansas.gov/executive-orders/"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT=90
ACTION_FIELDS=("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS=("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS=("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
NUMBER_RE=re.compile(r"\b(?:E\.?\s*O\.?|EO|DR)\s*(\d{2})\s*[-–]\s*(\d{1,2})\b",re.I)
REFERENCE_RE=re.compile(r"\b((?:E\.?\s*O\.?|EO|DR)\s*\d{2}\s*[-–]\s*\d{1,2})\b",re.I)
HAZARD_RE=re.compile(r"\b(severe storms?|severe thunderstorms?|tornado(?:es)?|flood(?:s|ing)?|wildfires?|forest fires?|drought|winter storms?|winter weather|snow|ice|freezing|freeze|extreme heat|hurricanes?|tropical storms?|high winds?|strong winds?|straight-line winds?|heavy rain|flash flooding|hail|lightning)\b",re.I)
MODIFIER_RE=re.compile(r"\b(amend(?:s|ed|ing|ment)?|renew(?:s|ed|ing|al)?|extend(?:s|ed|ing|sion)?|rescind(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion)|repeal)\b",re.I)
OPERATIONAL_RE=re.compile(r"\b(evacuation|curfew|price gouging|leave with pay|paid leave|oversize|overweight|hours of service|weigh station|suspend(?:s|ed|ing)? .{0,80}(?:transport|housing unit|procurement|tax))\b",re.I)
HAZARD_OVERRIDES={}

@dataclass(frozen=True)
class Action:
    number:str; title:str; date:str; url:str; text:str
    @property
    def stable_id(self): return "AR-"+re.sub(r"[^A-Z0-9]+","-",self.number.upper()).strip("-")

def get_json(params):
    response=requests.get(API_URL,params=params,headers=HEADERS,timeout=TIMEOUT); response.raise_for_status(); return response

def clean(value): return re.sub(r"\s+"," ",BeautifulSoup(html_module.unescape(value or ""),"html.parser").get_text(" ",strip=True)).strip()

def normalize_number(raw):
    match=NUMBER_RE.search(raw)
    if not match: return ""
    prefix="DR" if re.match(r"\s*DR",match.group(0),re.I) else "EO"
    return f"{prefix} {match.group(1)}-{int(match.group(2)):02d}"

def parse_post(post):
    title=clean(post["title"]["rendered"]); text=clean(post["content"]["rendered"])
    # A number found only in the body is normally a referenced companion order,
    # not this post's number. Preserve the post id rather than misidentifying it.
    number=normalize_number(title[:24])
    if not number: number=f"POST-{post['id']}"
    signed=""
    match=re.search(r"(?:this|on this)\s+(\d{1,2})(?:st|nd|rd|th)?\s+day of\s+([A-Za-z]+),?(?: in the year of our Lord)?\s+(20\d{2})",text,re.I)
    if match:
        try: signed=datetime.strptime(" ".join(match.groups()),"%d %B %Y").date().isoformat()
        except ValueError: pass
    if not signed: signed=post["date"][:10]
    return Action(number,title,signed,post["link"],text)

def collect():
    out=[]; page=1
    while True:
        response=get_json({"per_page":100,"page":page,"orderby":"date","order":"desc"})
        out.extend(parse_post(post) for post in response.json())
        if page >= int(response.headers.get("X-WP-TotalPages","1")): break
        page += 1
    return sorted({item.stable_id:item for item in out}.values(),key=lambda item:(item.date,item.number),reverse=True)

def classify(action):
    modifier=MODIFIER_RE.search(action.title)
    if modifier:
        word=modifier.group(0).lower()
        if word.startswith("amend") and re.search(r"\bas amended\b",action.title,re.I) and not re.search(r"\b(?:amend(?:s|ing)?\s+(?:Executive Order|E\.?O\.?|EO|DR)|to amend\s+(?:E\.?O\.?|EO|DR))\b",action.title,re.I):
            modifier=None
        if modifier is None:
            pass
        elif word.startswith(("rescind","terminat","repeal")): return "termination"
        elif word.startswith(("renew","extend")): return "extension"
        else: return "amendment"
    if OPERATIONAL_RE.search(action.title): return "administrative"
    if re.search(r"\b(do hereby declare|declare(?:s|d|ing)? (?:that )?a state of emergency|emergency declaration)\b",action.text+" "+action.title,re.I): return "declaration"
    return "administrative"

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,lineterminator="\n"); writer.writeheader(); writer.writerows(rows)

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; relationships=[]; joins=[]
    for action in actions:
        kind=classify(action); evidence=action.title+" "+action.text; weather=kind=="declaration" and bool(HAZARD_RE.search(evidence))
        row={"declaration_id":action.stable_id,"state":"AR","governor":"Sarah Huckabee Sanders","eo_number":action.number,"action_kind":"emergency_declaration" if kind!="administrative" else "executive_order","action_type":kind,"event_description":action.title,"date_signed":action.date,"end_date":"","weather_related":str(weather).lower(),"source_scope":"arkansas_governor_2023_present","document_format":"html","detail_url":action.url,"archive_record_url":action.url}; rows.append(row)
        if kind in {"termination","extension","amendment"}:
            relation={"termination":"terminates","extension":"extends","amendment":"amends"}[kind]
            seen_targets=set()
            for raw in REFERENCE_RE.findall(evidence):
                target=normalize_number(raw)
                if target and target!=action.number and target not in seen_targets:
                    seen_targets.add(target); relationships.append({"source_order_id":action.stable_id,"target_order_id":"AR-"+re.sub(r"[^A-Z0-9]+","-",target).strip("-"),"relationship_type":relation,"relationship_text":raw,"relationship_source":action.url,"confidence":"high"})
        if weather and action.date: joins.append({field:row[field] for field in JOIN_FIELDS})
    relationships=list({(r["source_order_id"],r["target_order_id"],r["relationship_type"]):r for r in relationships}.values())
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,relationships); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--actions-out",required=True); parser.add_argument("--relationships-out",required=True); parser.add_argument("--join-out",required=True)
    args=parser.parse_args(); write_outputs(collect(),args.actions_out,args.relationships_out,args.join_out)
if __name__=="__main__": main()
