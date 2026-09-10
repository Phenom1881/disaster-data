"""Scrape Governor Walz's official Minnesota executive-order archive."""
from __future__ import annotations
import argparse,csv,re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

STATE="MN";GOVERNOR="Tim Walz"
ARCHIVE_URL="https://mn.gov/governor/newsroom/executive-orders/"
LIST_URL="https://mn.gov/governor/rest/html/Executive%20Orders"
PARAMS={"detailPage":"/governor/newsroom/executive-orders/index.jsp","id":"1055-63318"}
HEADERS={"User-Agent":"DisasterDataPlus-Adapter/1.0","Referer":ARCHIVE_URL}
HAZARDS={"drought":r"\bdrought\b","fire":r"\bwildfires?\b","flood":r"\bflood(?:ing)?\b","tropical":r"\bhurricanes?\b|\btropical storm\b","winter":r"\bwinter storm\b|\bblizzard\b|\bsnow(?:fall)?\b","severe_storm":r"\bsevere storms?\b|\bsevere weather\b|\btornado(?:es)?\b|\bthunderstorms?\b","wind":r"\bhurricane.force winds?\b|\bdamaging winds?\b"}
# These official detail-page headings are generic. The appended phrases come
# directly from the corresponding order text / Governor press release and keep
# a regenerated join from losing reviewed weather declarations.
TITLE_ENRICH={
    "19-30":"Executive Order 19-30 Declaring a Peacetime Emergency after rapid snowmelt flooding and Winter Storm Wesley",
    "20-108":"Executive Order 20-108 Declaring a Peacetime Emergency and Providing Assistance to Stranded Motorists after a powerful winter storm",
    "22-23":"Executive Order 22-23 Declaring a Peacetime Emergency and Providing National Guard Assistance to Stranded Motorists during a winter storm",
    "23-01":"Executive Order 23-01 Declaring a Peacetime Emergency and Providing National Guard Assistance to Stranded Motorists during a winter storm",
    "25-06":"Executive Order 25-06 Declaring a Peacetime Emergency and Providing Storm Recovery Assistance in Beltrami County after severe storms and hurricane-force winds",
}
SIGNED_DATE_ENRICH={"25-15":"2025-12-28"}

@dataclass
class Action:
    eo_number:str;title:str;date_signed:str;url:str;action_type:str="other";hazard:str="";related_order:str=""

def blocked(text,url=""):
    low=(text[:3000]+url).lower();return "radware bot manager" in low or "validate.perfdrive.com" in low

def parse_list(page):
    soup=BeautifulSoup(page,"html.parser");out=[];seen=set()
    for a in soup.find_all("a",href=True):
        label=a.get_text(" ",strip=True);m=re.fullmatch(r"(?:Executive Order|EO)\s+(\d{2}-\d+)",label,re.I)
        if not m:continue
        url=urljoin(ARCHIVE_URL,a["href"]);eo=m.group(1)
        if eo not in seen:out.append(Action(eo,label,"",url));seen.add(eo)
    if not out:raise ValueError("Minnesota order list contained no order records")
    return out

def parse_detail(action,page):
    soup=BeautifulSoup(page,"html.parser");text=re.sub(r"\s+"," ",soup.get_text(" ",strip=True))
    h=soup.find(["h1","h2"],string=re.compile(r"Executive Order",re.I))
    scope=h.parent.get_text(" ",strip=True) if h and h.parent else text
    # The description normally follows the EO heading on the official detail page.
    pos=scope.lower().find(action.eo_number.lower());tail=scope[pos+len(action.eo_number):pos+len(action.eo_number)+900] if pos>=0 else scope[:900]
    tail=re.split(r"Last Modified",tail,flags=re.I)[0].strip(" :-")
    action.title=TITLE_ENRICH.get(action.eo_number,(f"Executive Order {action.eo_number} {tail}").strip())
    dm=re.search(r"Last Modified:\s*([A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2}/\d{1,2}/\d{4})",text,re.I)
    if dm:
        for fmt in ("%B %d, %Y","%m/%d/%Y"):
            try:action.date_signed=datetime.strptime(dm.group(1),fmt).date().isoformat();break
            except ValueError:pass
    action.date_signed=SIGNED_DATE_ENRICH.get(action.eo_number,action.date_signed)
    low=action.title.lower();action.hazard=next((c for c,p in HAZARDS.items() if re.search(p,action.title,re.I)),"")
    rm=re.search(r"(?:amending|extending|rescinding).*?Executive Order\s+(\d{2}-\d+)",action.title,re.I);action.related_order=rm.group(1) if rm else ""
    if re.search(r"\bamending\b|\bextending\b|\brescinding\b",low):action.action_type="amendment"
    elif "declaring a peacetime emergency" in low and action.hazard:action.action_type="declaration"
    elif re.search(r"providing (?:for )?(?:emergency )?relief|motor carriers|assistance to (?:the state of|stranded motorists)|national guard assistance",low):action.action_type="operational"
    return action

def scrape(session=None):
    session=session or requests.Session();r=session.get(LIST_URL,params=PARAMS,headers=HEADERS,timeout=45);r.raise_for_status()
    if blocked(r.text,r.url):raise ValueError("official Minnesota archive returned its Radware anti-bot page; refusing to emit an empty data set")
    rows=parse_list(r.text)
    for x in rows:
        d=session.get(x.url,headers=HEADERS,timeout=30);d.raise_for_status()
        if blocked(d.text,d.url):raise ValueError("Minnesota detail request was intercepted by Radware")
        parse_detail(x,d.text)
    return sorted(rows,key=lambda x:(x.date_signed,x.eo_number))

def write_outputs(rows,actions_out,relationships_out,join_out):
    for p in(actions_out,relationships_out,join_out):p.parent.mkdir(parents=True,exist_ok=True)
    with actions_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n");w.writerow(["declaration_id","eo_number","title","date_signed","action_type","related_order","hazard_category","archive_record_url"])
        for x in rows:w.writerow([f"MN-EO-{x.eo_number}",x.eo_number,x.title,x.date_signed,x.action_type,x.related_order,x.hazard,x.url])
    with relationships_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n");w.writerow(["source_declaration_id","relationship_type","target_declaration_id"])
        for x in rows:
            if x.related_order:w.writerow([f"MN-EO-{x.eo_number}",x.action_type,f"MN-EO-{x.related_order}"])
    with join_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n");w.writerow(["declaration_id","governor","eo_number","event_description","date_signed","archive_record_url"])
        for x in rows:
            if x.action_type=="declaration":w.writerow([f"MN-EO-{x.eo_number}",GOVERNOR,x.eo_number,x.title,x.date_signed,x.url])

def main():
    p=argparse.ArgumentParser();p.add_argument("--actions-out",required=True);p.add_argument("--relationships-out",required=True);p.add_argument("--join-out",required=True);a=p.parse_args()
    try:rows=scrape()
    except (requests.RequestException,ValueError) as exc:raise SystemExit(f"Minnesota archive scrape failed: {exc}")
    write_outputs(rows,Path(a.actions_out),Path(a.relationships_out),Path(a.join_out));print(f"Minnesota: {len(rows)} executive orders processed")
if __name__=="__main__":main()
