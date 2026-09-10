"""Scrape the official Wisconsin Governor executive-order archive."""
from __future__ import annotations
import argparse, csv, html as html_lib, json, re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

STATE="WI"; GOVERNOR="Tony Evers"
ARCHIVE_URL="https://evers.wi.gov/pages/newsroom/executive-orders.aspx"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlus-Adapter/1.0)"}
HAZARDS={"drought":r"\bdrought\b","fire":r"\bwildfires?\b","flood":r"\bflood(?:ing)?\b","tropical":r"\bhurricanes?\b|\btropical storm\b","winter":r"\bwinter\b|\bsnow\b|\bice\b|\bwind chill\b","severe_storm":r"\bsevere weather\b|\btornado(?:es)?\b|\bthunderstorms?\b","wind":r"\bdamaging winds?\b|\bhigh winds?\b"}
# EO 5's archive label omits the hazard, but its own official PDF heading says
# "in Response to Severe Winter Weather." This is description enrichment, not inference.
TITLE_ENRICH={"5":"Executive Order 5, Declaring a State of Emergency in Response to Severe Winter Weather"}

@dataclass
class Action:
    eo_number:str; title:str; date_signed:str; url:str; action_type:str="other"; hazard:str=""

def parse_archive(page: str) -> list[Action]:
    marker=page.find("var WPQ1ListData")
    if marker < 0: raise ValueError("embedded Wisconsin order table not found")
    start=page.find("[",marker); rows,_=json.JSONDecoder().raw_decode(page[start:])
    out=[]
    for row in rows:
        title=html_lib.unescape(BeautifulSoup(row.get("Title2", ""),"html.parser").get_text(" ",strip=True))
        m=re.search(r"(?:Executive Order\s*#?|Executive Order\s+)(\d+)",title,re.I)
        if not m or "Emergency Order" in title and "Executive Order" not in title: continue
        eo=m.group(1); title=TITLE_ENRICH.get(eo,title)
        try: date=datetime.strptime(row.get("Date", ""),"%m/%d/%Y").date().isoformat()
        except ValueError: date=""
        url=urljoin(ARCHIVE_URL,row.get("AccessibleURL") or row.get("URL") or "")
        low=title.lower(); hazard=next((c for c,p in HAZARDS.items() if re.search(p,title,re.I)),"")
        if re.search(r"\bamend(?:s|ed|ing)?\b|\bextend(?:s|ed|ing)?\b|\brescind",low): typ="amendment"
        elif re.search(r"declaring (?:a )?state of emergency|declaration of a state of emergency|proclamation declaring a state of emergency",low) and hazard: typ="declaration"
        elif "energy emergency" in low or "closing state" in low or "emergency management assistance compact" in low or "price gouging" in low: typ="operational"
        else: typ="other"
        # EO 7 repeats the EO 5 declaration but is primarily a state-office closure.
        if eo == "7": typ="operational"
        out.append(Action(eo,title,date,url,typ,hazard))
    return sorted(out,key=lambda x:(x.date_signed,int(x.eo_number)))

def scrape(session=None):
    session=session or requests.Session(); r=session.get(ARCHIVE_URL,headers=HEADERS,timeout=45); r.raise_for_status(); return parse_archive(r.text)

def write_outputs(rows, actions_out, relationships_out, join_out):
    for p in (actions_out,relationships_out,join_out): p.parent.mkdir(parents=True,exist_ok=True)
    with actions_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n"); w.writerow(["declaration_id","eo_number","title","date_signed","action_type","hazard_category","archive_record_url"])
        for x in rows:w.writerow([f"WI-EO-{x.eo_number}",x.eo_number,x.title,x.date_signed,x.action_type,x.hazard,x.url])
    with relationships_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n"); w.writerow(["source_declaration_id","relationship_type","target_declaration_id"]); w.writerow(["WI-EO-7","operational_companion","WI-EO-5"])
    with join_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n"); w.writerow(["declaration_id","governor","eo_number","event_description","date_signed","archive_record_url"])
        for x in rows:
            if x.action_type=="declaration":w.writerow([f"WI-EO-{x.eo_number}",GOVERNOR,x.eo_number,x.title,x.date_signed,x.url])

def main():
    p=argparse.ArgumentParser();p.add_argument("--actions-out",required=True);p.add_argument("--relationships-out",required=True);p.add_argument("--join-out",required=True);a=p.parse_args()
    try: rows=scrape()
    except (requests.RequestException,ValueError) as exc: raise SystemExit(f"Wisconsin archive scrape failed: {exc}")
    write_outputs(rows,Path(a.actions_out),Path(a.relationships_out),Path(a.join_out));print(f"Wisconsin: {len(rows)} executive orders processed")
if __name__=="__main__":main()
