"""Collect Nevada executive and emergency orders from the Governor website."""
from __future__ import annotations
import argparse, csv, re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

EO_ROOT="https://www.gov.nv.gov/executive-actions/executive-orders/"
EMERGENCY_ROOT="https://www.gov.nv.gov/executive-actions/emergency-orders/"
LEGACY_PROCLAMATIONS_ROOT="https://www.gov.nv.gov/Newsroom/Proclamations/"
PROCLAMATIONS_ROOT="https://www.gov.nv.gov/proclamations/"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT=90
ACTION_FIELDS=("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS=("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS=("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE=re.compile(r"\b(wildfires?|forest fires?|fires?|flood(?:s|ing)?|flash flood(?:s|ing)?|severe (?:storms?|weather)|winter storms?|winter weather|snow|ice|freez(?:e|ing)|drought|extreme heat|tornado(?:es)?|hail|heavy rain(?:fall)?|high winds?|atmospheric river|hurricanes?|tropical storms?)\b",re.I)
MODIFIER_RE=re.compile(r"\b(amend(?:s|ed|ing|ment)?|renew(?:s|ed|ing|al)?|extend(?:s|ed|ing|sion)?|rescind(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion)|revok(?:e|es|ed|ing))\b",re.I)
OPERATIONAL_RE=re.compile(r"\b(evacuation|curfew|price gouging|leave with pay|hours of service|transportation waiver|suspension of regulations?)\b",re.I)
HAZARD_OVERRIDES={
    # The migrated page does not expose the proclamation body as searchable
    # HTML. The signed proclamation, cited in hazard_overrides.csv, attributes
    # the delivery emergency to storms and extreme winter conditions.
    "PROCLAMATION-2023-01-06-PROCLAMATION-DECLARING-A-LIQUID-PETROLEUM-GAS-DELIVERY-EMERGENCY":"winter",
}

@dataclass(frozen=True)
class Action:
    number:str; title:str; date:str; url:str; text:str; collection:str="executive_order"
    @property
    def stable_id(self): return "NV-"+self.number

def get(url):
    response=requests.get(url,headers=HEADERS,timeout=TIMEOUT); response.raise_for_status(); return response

def parse_listing(html,base_url,collection):
    soup=BeautifulSoup(html,"html.parser"); out=[]; seen=set()
    for anchor in soup.select("a[href]"):
        href=urljoin(base_url,anchor["href"]); path=urlparse(href).path.rstrip("/")
        base_path=urlparse(base_url).path.rstrip("/")
        if href in seen or path==base_path or not path.startswith(base_path+"/"): continue
        text=re.sub(r"\s+"," ",anchor.get_text(" ",strip=True))
        if collection=="executive_order":
            path_match=re.search(r"/eo-(20\d{2}-\d{3})(?:-|/|$)",path,re.I)
            text_match=re.search(r"\bEO\s+(20\d{2}-\d{3})\b",text,re.I)
            if not path_match and not text_match: continue
            # Two 2024 index labels mistakenly say 2026; the official detail URL
            # and order itself are authoritative, so prefer the URL identifier.
            number=(path_match or text_match).group(1)
            title=re.sub(r"^EO\s+20\d{2}-\d{3}\s*-?\s*","",text,flags=re.I)
        else:
            if not re.search(r"(?:declaration|emergency)",text,re.I): continue
            slug=path.rsplit("/",1)[-1]; number="EMERGENCY-"+slug.upper()
            title=text
        seen.add(href); out.append((number,title,href,collection))
    return out

def extract_date(text,year=""):
    # Proclamation pages often display an event-style date range near the top
    # (and migrated pages sometimes display the wrong range). Prefer the date
    # in the Governor's signature clause, including years written in words.
    signed_any=re.search(
        r"\bthis\s+(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\b.{0,140}?\b(20\d{2}|two thousand twenty[- ](?:three|four|five|six))\b",
        text,re.I,
    )
    if signed_any:
        raw_year=signed_any.group(3).lower()
        word_years={"two thousand twenty-three":"2023","two thousand twenty three":"2023","two thousand twenty-four":"2024","two thousand twenty four":"2024","two thousand twenty-five":"2025","two thousand twenty five":"2025","two thousand twenty-six":"2026","two thousand twenty six":"2026"}
        signed_year=word_years.get(raw_year,raw_year)
        return datetime.strptime(f"{signed_any.group(2)} {signed_any.group(1)} {signed_year}","%B %d %Y").strftime("%Y-%m-%d")
    if year:
        signed=list(re.finditer(r"\bthis\s+(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+(January|February|March|April|May|June|July|August|September|October|November|December)\b",text,re.I))
        if signed:
            match=signed[-1]
            return datetime.strptime(f"{match.group(2)} {match.group(1)} {year}","%B %d %Y").strftime("%Y-%m-%d")
    pattern=r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b"
    matches=list(re.finditer(pattern,text))
    match=next((item for item in matches if not year or item.group(3)==year),None)
    return datetime.strptime(match.group(0),"%B %d, %Y").strftime("%Y-%m-%d") if match else ""

def parse_detail(number,title,url,collection):
    soup=BeautifulSoup(get(url).text,"html.parser"); main=soup.select_one("main") or soup
    text=re.sub(r"\s+"," ",main.get_text(" ",strip=True)); year=number[:4] if number[:4].isdigit() else ""; return Action(number,title,extract_date(text,year),url,text,collection)

def collect_proclamations():
    """Collect true emergency proclamations, excluding commemorative records.

    Nevada migrated the former Newsroom/Proclamations archive to
    /proclamations/. The new index is paginated and contains hundreds of
    honorary proclamations, so candidates must be opened and verified from
    their full text. One legacy March 10, 2023 record shares a migrated URL
    with the later May 29 flood declaration; retain it from the index row and
    cite the Governor's contemporaneous release rather than pretending the
    collided detail URL still identifies the older document.
    """
    root=PROCLAMATIONS_ROOT
    try:
        get(LEGACY_PROCLAMATIONS_ROOT)
        root=LEGACY_PROCLAMATIONS_ROOT
    except requests.RequestException:
        pass
    pairs=[]; page=1; seen_pages=set()
    while True:
        url=root if page==1 else f"{root}?pg={page}"
        response=get(url)
        if response.url in seen_pages: break
        seen_pages.add(response.url)
        soup=BeautifulSoup(response.text,"html.parser")
        for anchor in soup.select("a.title-subsection[href]"):
            title=re.sub(r"\s+"," ",anchor.get_text(" ",strip=True))
            if not re.search(r"\b(?:declaration|declaring).{0,80}\b(?:emergency|disaster)|\b(?:emergency|disaster).{0,80}\bdeclaration\b",title,re.I): continue
            if re.search(r"\b(?:amend|extend|ending|termination|terminated|rescission|rescinded)\w*\b",title,re.I): continue
            pairs.append((title,urljoin(root,anchor["href"])))
        next_link=next((a for a in soup.select("a[href]") if a.get_text(" ",strip=True)=="Next Page" and a.get("aria-disabled")!="true"),None)
        if not next_link: break
        page += 1

    actions=[]
    for listing_title,detail_url in dict.fromkeys(pairs):
        try:
            soup=BeautifulSoup(get(detail_url).text,"html.parser"); main=soup.select_one("main") or soup
            text=re.sub(r"\s+"," ",main.get_text(" ",strip=True)); heading=soup.find("h1")
            title=re.sub(r"\s+"," ",heading.get_text(" ",strip=True)) if heading else listing_title
            date=extract_date(text)
            if not date or not re.search(r"\b(?:declare|declaring|declaration).{0,160}\b(?:state of emergency|disaster)|\bstate of emergency\b",text,re.I): continue
            slug=urlparse(detail_url).path.rstrip("/").rsplit("/",1)[-1].upper()
            actions.append(Action(f"PROCLAMATION-{date}-{slug}",title,date,detail_url,text,"proclamation"))
        except requests.RequestException:
            continue

    # The migrated index still exposes this row, but its reused detail URL now
    # resolves to the May 29 flood declaration. The dated official release is
    # the surviving unambiguous record for the March 10 declaration.
    march10_url="https://www.gov.nv.gov/press-releases/governor-lombardo-declares-state-of-emergency-due-to-severe-weather-in-northern-nevada/"
    try:
        soup=BeautifulSoup(get(march10_url).text,"html.parser")
        text=re.sub(r"\s+"," ",(soup.select_one("main") or soup).get_text(" ",strip=True))
        actions.append(Action("PROCLAMATION-2023-03-10-DECLARATION-OF-EMERGENCY","DECLARATION OF EMERGENCY", "2023-03-10",march10_url,text,"proclamation"))
    except requests.RequestException:
        pass
    return actions

def collect():
    pairs=[]
    for year in range(2023,datetime.now().year+1):
        url=f"{EO_ROOT}{year}-executive-orders/"
        try: pairs.extend(parse_listing(get(url).text,url,"executive_order"))
        except requests.RequestException: pass
    emergency_index=get(EMERGENCY_ROOT).text
    soup=BeautifulSoup(emergency_index,"html.parser")
    year_urls={urljoin(EMERGENCY_ROOT,a["href"]) for a in soup.select("a[href]") if re.search(r"20\d{2}-emergency-orders",a["href"],re.I)}
    for url in year_urls: pairs.extend(parse_listing(get(url).text,url,"emergency_order"))
    unique={row[0]:row for row in pairs}
    actions=[parse_detail(*row) for row in unique.values()]
    actions.extend(collect_proclamations())
    # The proclamation archive mirrors some emergency-order records. Prefer
    # the executive-actions copy when date and title identify the same order.
    deduped={}
    for action in actions:
        key=(action.date,re.sub(r"\W+"," ",action.title.lower()).strip())
        if key not in deduped or deduped[key].collection=="proclamation": deduped[key]=action
    return sorted(deduped.values(),key=lambda item:(item.date,item.number),reverse=True)

def classify(action):
    modifier=MODIFIER_RE.search(action.title)
    if modifier:
        word=modifier.group(0).lower()
        if word.startswith(("rescind","terminat","revok")): return "termination"
        if word.startswith(("renew","extend")): return "extension"
        return "amendment"
    if OPERATIONAL_RE.search(action.title): return "administrative"
    evidence=action.title+" "+action.text
    if action.collection in {"emergency_order","proclamation"} and re.search(r"\b(?:declaration of emergency|state of emergency)\b",evidence,re.I): return "declaration"
    if re.search(r"\b(?:hereby|do)\s+(?:declare|proclaim)\b.{0,120}\b(?:state of emergency|disaster)\b",evidence,re.I): return "declaration"
    return "administrative"

def relationships(actions):
    known={item.number for item in actions}; rows=[]
    for action in actions:
        kind=classify(action)
        if kind not in {"amendment","extension","termination"}: continue
        for target in sorted(set(re.findall(r"\b20\d{2}-\d{3}\b",action.title+" "+action.text))-{action.number}):
            if target in known: rows.append({"source_order_id":action.stable_id,"target_order_id":"NV-"+target,"relationship_type":kind,"relationship_text":action.title,"relationship_source":action.url,"confidence":"high"})
    return rows

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,lineterminator="\n"); writer.writeheader(); writer.writerows(rows)

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; joins=[]
    for action in actions:
        kind=classify(action); evidence=action.title+" "+action.text; weather=kind=="declaration" and (bool(HAZARD_RE.search(evidence)) or action.number in HAZARD_OVERRIDES)
        row={"declaration_id":action.stable_id,"state":"NV","governor":"Joe Lombardo","eo_number":action.number,"action_kind":action.collection,"action_type":kind,"event_description":action.title,"date_signed":action.date,"end_date":"","weather_related":str(weather).lower(),"source_scope":"nevada_governor_executive_actions_2023_present","document_format":"html","detail_url":action.url,"archive_record_url":action.url}; rows.append(row)
        if weather and kind=="declaration" and action.date: joins.append({field:row[field] for field in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,relationships(actions)); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--actions-out",required=True); parser.add_argument("--relationships-out",required=True); parser.add_argument("--join-out",required=True)
    args=parser.parse_args(); write_outputs(collect(),args.actions_out,args.relationships_out,args.join_out)
if __name__=="__main__": main()
