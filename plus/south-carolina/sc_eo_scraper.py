"""Collect South Carolina executive orders from official Governor and State Library archives."""
from __future__ import annotations
import argparse,csv,re
from dataclasses import dataclass
from urllib.parse import unquote
import requests
from bs4 import BeautifulSoup

GOVERNOR_URL="https://www.governor.sc.gov/executive-branch/executive-orders"
LIBRARY_COLLECTION="https://dc.statelibrary.sc.gov/collections/ec2abe0f-f0b1-43ec-8a18-412583e3e1ed"
API_URL="https://dc.statelibrary.sc.gov/server/api/discover/search/objects"
SCOPE="ec2abe0f-f0b1-43ec-8a18-412583e3e1ed"; TIMEOUT=90
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
ACTION_FIELDS=("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS=("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS=("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
HAZARD_RE=re.compile(r"\b(drought|wildfires?|forest fires?|brush fires?|fire weather|flood(?:s|ing)?|rainfall|heavy rain|mudslide|landslide|hurricanes?|tropical storms?|tropical depressions?|tropical weather|cyclone|blizzard|winter storms?|winter weather|snow(?:fall|storm)?|ice|icing|sleet|cold|freeze|freezing|nor['’]?easter|severe storms?|severe weather|thunderstorms?|tornado(?:es)?|hail|lightning|wind storms?|high winds?|damaging winds?|wind gusts?)\b",re.I)
MODIFIER_RE=re.compile(r"\b(rescind(?:s|ed|ing)?|terminate[sd]?|extend(?:s|ed|ing)?|extension|renew(?:s|ed|ing)?|renewal|amend(?:s|ed|ing)?|cancel(?:s|ed|ing)?)\b",re.I)
NUMBER_RE=re.compile(r"\b(?:19|20)\d{2}-\d{1,2}\b")
OPERATIONAL_RE=re.compile(r"\b(legal holidays?|leave with pay|transportation regulations|motor vehicle regulations|suspending (?:the )?federal rules|evacuation|closing state offices|office closings?|curfew)\b",re.I)

@dataclass
class Action:
    number:str; description:str; date:str; governor:str; url:str; source:str; subjects:str=""; uuid:str=""
    @property
    def stable_id(self): return "SC-EO-"+self.number if self.number else f"SC-ACTION-{self.date}-{self.uuid[:8]}"

def metadata(item,key): return "; ".join(v.get("value","") for v in item.get("metadata",{}).get(key,[]))

def current_descriptions():
    r=requests.get(GOVERNOR_URL,headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); s=BeautifulSoup(r.text,"html.parser"); out={}
    for a in s.select('a[href$=".pdf"]'):
        m=NUMBER_RE.search(a.get_text(" ",strip=True))
        if not m or "Official" not in a.get_text(" ",strip=True): continue
        desc=""; node=a
        for _ in range(16):
            node=node.next_element
            if node is None or getattr(node,"name",None)=="br": break
            if isinstance(node,str) and " - " in node: desc=node.split(" - ",1)[1].strip(); break
        if not desc: desc=re.sub(r"\s+"," ",unquote(a.get("href","")).rsplit("/",1)[-1].rsplit(".pdf",1)[0]).split(" - ",1)[-1]
        dm=re.search(r"/(20\d{2}-\d{2}-\d{2})[^/]*\.pdf",unquote(a.get("href","")))
        out[m.group(0)]=(desc,dm.group(1) if dm else "",a["href"])
    return out

def collect():
    cur=current_descriptions(); out=[]
    for page in range(100):
        r=requests.get(API_URL,params={"scope":SCOPE,"size":100,"page":page,"sort":"dc.date.issued,ASC"},headers=HEADERS,timeout=TIMEOUT); r.raise_for_status(); data=r.json()["_embedded"]["searchResult"]; objs=data.get("_embedded",{}).get("objects",[])
        for obj in objs:
            it=obj["_embedded"]["indexableObject"]; title=metadata(it,"dc.title"); m=NUMBER_RE.search(title); date=metadata(it,"dc.date.issued")[:10]; gov=metadata(it,"dc.contributor.author"); desc=metadata(it,"dc.description"); subj=metadata(it,"dc.subject"); uri=metadata(it,"dc.identifier.uri")
            number=m.group(0) if m else ""
            if number in cur: desc,date2,url=cur[number]; date=date2 or date
            else: url=uri
            out.append(Action(number,desc or title,date,gov,url,uri or LIBRARY_COLLECTION,subj,it.get("uuid","")))
        if page+1>=data["page"]["totalPages"]: break
    return sorted({a.stable_id:a for a in out}.values(),key=lambda a:(a.date,a.number),reverse=True)

def classify(a):
    text=a.description+" "+a.subjects; m=MODIFIER_RE.search(text)
    if m:
        w=m.group(0).lower(); return "termination" if w.startswith(("rescind","terminate","cancel")) else "extension" if w.startswith(("extend","extension","renew")) else "amendment"
    if re.search(r"\bstate of emergency\b.{0,80}\b(over|ended|terminated)\b",text,re.I): return "termination"
    if OPERATIONAL_RE.search(a.description): return "administrative"
    if re.search(r"\b(declar(?:es|ing|ation)(?: that)?(?: a)? state of emergency|state of emergency exists)\b",a.description,re.I): return "declaration"
    return "administrative"

def write_csv(path,fields,rows):
    with open(path,"w",newline="",encoding="utf-8") as h: w=csv.DictWriter(h,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows([{k:(v.replace("\r","") if isinstance(v,str) else v) for k,v in row.items()} for row in rows])

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; rel=[]; joins=[]
    for a in actions:
        kind=classify(a); evidence=a.description+" "+a.subjects; weather=bool(HAZARD_RE.search(evidence) or (kind=="declaration" and re.search(r"\bTropical Disturbance\b",evidence,re.I))); desc=a.description
        if weather and not HAZARD_RE.search(desc):
            hazard="; ".join(x for x in a.subjects.split("; ") if HAZARD_RE.search(x)); desc=f"{desc} — {hazard}" if hazard else desc
        gov=a.governor
        if not gov: gov=("Henry McMaster" if a.date>="2017-01-24" else "Nikki Haley" if a.date>="2011-01-12" else "Mark Sanford" if a.date>="2003-01-15" else "Jim Hodges" if a.date>="1999-01-13" else "David Beasley" if a.date>="1995-01-11" else "Carroll A. Campbell Jr." if a.date>="1987-01-14" else "Richard Riley" if a.date>="1979-01-10" else "James B. Edwards" if a.date>="1975-01-15" else "John C. West" if a.date>="1971-01-19" else "Robert E. McNair")
        elif "," in gov:
            last,first=[x.strip() for x in gov.split(",",1)]; gov=f"{first} {last}"
        row={"declaration_id":a.stable_id,"state":"SC","governor":gov,"eo_number":a.number,"action_kind":"emergency_declaration" if kind!="administrative" else "executive_order","action_type":kind,"event_description":desc,"date_signed":a.date,"end_date":"","weather_related":str(weather and kind!="administrative").lower(),"source_scope":"south_carolina_state_library_1966_present","document_format":"pdf","detail_url":a.url,"archive_record_url":a.source}; rows.append(row)
        for n in NUMBER_RE.findall(evidence):
            if n!=a.number and kind in {"termination","extension","amendment"}: rel.append({"source_order_id":a.stable_id,"target_order_id":"SC-EO-"+n,"relationship_type":{"termination":"terminates","extension":"extends","amendment":"amends"}[kind],"relationship_text":n,"relationship_source":"official_archive_metadata","confidence":"high"})
        if kind=="declaration" and weather and a.date: joins.append({f:row[f] for f in JOIN_FIELDS})
    write_csv(actions_out,ACTION_FIELDS,rows); write_csv(relationships_out,REL_FIELDS,rel); write_csv(join_out,JOIN_FIELDS,joins)

def main():
    p=argparse.ArgumentParser(); p.add_argument("--actions-out",required=True); p.add_argument("--relationships-out",required=True); p.add_argument("--join-out",required=True); a=p.parse_args(); write_outputs(collect(),a.actions_out,a.relationships_out,a.join_out)
if __name__=="__main__": main()
