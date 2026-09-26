"""Scrape the official Wisconsin Governor executive-order archive.

Primary source: the Governor's executive-order archive,
https://evers.wi.gov/pages/newsroom/executive-orders.aspx, a SharePoint page
that embeds every order (number, title, date, PDF) as JSON.

evers.wi.gov does not answer GitHub's servers at all (every request from the
weekly job timed out connecting, Sep 2026), so the archive could not be
refreshed. When it cannot be reached, the scraper falls back to the
Governor's press releases, published through GovDelivery:
https://content.govdelivery.com/accounts/WIGOV/bulletins.rss
Each state of emergency the Governor declares is announced there ("Gov. Evers
Declares State of Emergency in Response to Severe Storms throughout Eastern
Wisconsin"). Only a release that names the executive order it announces
becomes a record, WI-EO-<number>, the same id the archive gives that order,
so the archive and the releases can never produce two records for one
declaration. A release that names no order, or orders that amend or extend
another, is listed in the run log for review and not written. Saved archive
records are never replaced by a release: a saved row is written back as it was.
"""
from __future__ import annotations
import argparse, csv, html as html_lib, json, re, sys, time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from xml.etree import ElementTree as ET
import requests
from bs4 import BeautifulSoup

STATE="WI"; GOVERNOR="Tony Evers"
ARCHIVE_URL="https://evers.wi.gov/pages/newsroom/executive-orders.aspx"
RELEASE_FEED="https://content.govdelivery.com/accounts/WIGOV/bulletins.rss"
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlus-Adapter/1.0)"}
FEED_HEADERS={**HEADERS,"Accept":"application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"}
# The archive either answers or the connection times out; waiting 45 s twice
# only delayed the fallback. One short try is enough to tell.
ARCHIVE_TIMEOUT=20
HAZARDS={"drought":r"\bdrought\b","fire":r"\bwildfires?\b","flood":r"\bflood(?:ing)?\b","tropical":r"\bhurricanes?\b|\btropical storm\b","winter":r"\bwinter\b|\bsnow\b|\bice\b|\bwind chill\b","severe_storm":r"\bsevere weather\b|\btornado(?:es)?\b|\bthunderstorms?\b|\bsevere storms?\b","wind":r"\bdamaging winds?\b|\bhigh winds?\b"}
# EO 5's archive label omits the hazard, but its own official PDF heading says
# "in Response to Severe Winter Weather." This is description enrichment, not inference.
TITLE_ENRICH={"5":"Executive Order 5, Declaring a State of Emergency in Response to Severe Winter Weather"}
ACTION_FIELDS=["declaration_id","eo_number","title","date_signed","action_type","hazard_category","archive_record_url"]
JOIN_FIELDS=["declaration_id","governor","eo_number","event_description","date_signed","archive_record_url"]

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
        try: date_text=datetime.strptime(row.get("Date", ""),"%m/%d/%Y").date().isoformat()
        except ValueError: date_text=""
        url=urljoin(ARCHIVE_URL,row.get("AccessibleURL") or row.get("URL") or "")
        low=title.lower(); hazard=next((c for c,p in HAZARDS.items() if re.search(p,title,re.I)),"")
        if re.search(r"\bamend(?:s|ed|ing)?\b|\bextend(?:s|ed|ing)?\b|\brescind",low): typ="amendment"
        elif re.search(r"declaring (?:a )?state of emergency|declaration of a state of emergency|proclamation declaring a state of emergency",low) and hazard: typ="declaration"
        elif "energy emergency" in low or "closing state" in low or "emergency management assistance compact" in low or "price gouging" in low: typ="operational"
        else: typ="other"
        # EO 7 repeats the EO 5 declaration but is primarily a state-office closure.
        if eo == "7": typ="operational"
        out.append(Action(eo,title,date_text,url,typ,hazard))
    return sorted(out,key=lambda x:(x.date_signed,int(x.eo_number)))

def scrape(session=None):
    session=session or requests.Session(); r=session.get(ARCHIVE_URL,headers=HEADERS,timeout=ARCHIVE_TIMEOUT); r.raise_for_status(); return parse_archive(r.text)

# ---------------------------------------------------------------- press releases
_FOLLOW_UP=r"(?:extend\w*|extension|renew\w*|amend\w*|expand\w*|updat\w*|remain\w*|likely|possible|consider\w*|lift\w*|end(?:s|ed|ing)?|rescind\w*|terminat\w*)"
# "Gov. Evers Declares State of Emergency ...", "Gov. Evers Declares Emergency
# as State Prepares for Winter Storm", "Gov. Evers Signs Executive Order
# Declaring State of Emergency ...": the verb right after the Governor's name,
# no follow-up word between it and the emergency.
RELEASE_SOE_RE=re.compile(
    r"\bGov(?:ernor|\.)?\s+(?:Tony\s+)?Evers\s+(?:declares?|declared|signs?|signed|issues?|issued)\b"
    r"(?:(?!\b"+_FOLLOW_UP+r"\b)[^.;:]){0,60}?\b(?:state of emergency|emergency)\b",re.I)
# Emergencies that are not about the weather, and releases about bills,
# grants or aid that mention an emergency.
RELEASE_OFF_TOPIC_RE=re.compile(r"\b(?:economic disruption|price gouging|energy emergency|shutdown|foodshare|public health|health emergency|opioid\w*|fentanyl|half-staff|flag|bills?|grants?|funding|responders)\b",re.I)
RELEASE_WEATHER_RE=re.compile(r"\b(?:weather|storms?|flood\w*|tornad\w*|winter|snow\w*|ice|blizzard|winds?|rain\w*|wildfires?|fires?|drought)\b",re.I)
# The order the release announces: "signed Executive Order #315 declaring".
SIGNED_EO_RE=re.compile(r"\bsign\w*\s+(?:an?\s+)?Executive Order\s*(?:No\.?\s*)?#?\s*(\d{1,4})\b|\bExecutive Order\s*(?:No\.?\s*)?#?\s*(\d{1,4})\s*,?\s*(?:declaring|which declares|to declare)\b",re.I)
EO_NUMBER_RE=re.compile(r"\bExecutive Order\s*(?:No\.?\s*)?#?\s*(\d{1,4})\b",re.I)
AMENDING_RE=re.compile(r"\b(?:amend\w*|extend\w*|expand\w*|renew\w*)\s+(?:the\s+)?(?:state of emergency|Executive Order)\b",re.I)
try:
    from zoneinfo import ZoneInfo
    _WI_TZ=ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover - no tz database; Central standard time is close enough
    _WI_TZ=timezone(timedelta(hours=-6))

@dataclass
class Release:
    title:str; url:str; date_signed:str; eo_number:str=""; hazard:str=""

def release_date(pub_date):
    """The release's date in Wisconsin; the feed stamps items in GMT or with an offset."""
    try: stamp=parsedate_to_datetime(pub_date)
    except (TypeError,ValueError,IndexError): return ""
    if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(_WI_TZ).date().isoformat()

def is_weather_emergency_release(title):
    title=re.sub(r"^\s*press release:\s*","",title,flags=re.I)
    return bool(RELEASE_SOE_RE.search(title) and not RELEASE_OFF_TOPIC_RE.search(title) and RELEASE_WEATHER_RE.search(title))

def announced_order(text):
    """The number of the order a release announces, or '' when it cannot be
    told: 'signed Executive Order #315' or 'Executive Order #315 declaring',
    else the only order number the release mentions."""
    m=SIGNED_EO_RE.search(text)
    if m: return m.group(1) or m.group(2)
    numbers={n for n in EO_NUMBER_RE.findall(text)}
    return numbers.pop() if len(numbers)==1 else ""

def feed_releases(xml_bytes,review=None):
    """Weather state-of-emergency releases in the GovDelivery feed that name
    the order they announce, oldest first, one per order. Releases that name
    no order, or orders amending or extending another, go to review (a list
    of titles) instead: a record without the archive's id could never be
    reconciled with it later."""
    review=[] if review is None else review
    root=ET.fromstring(xml_bytes)
    out,seen=[],set()
    for item in root.iter("item"):
        title=" ".join((item.findtext("title") or "").split())
        if not is_weather_emergency_release(title): continue
        day=release_date(item.findtext("pubDate") or "")
        if not day: continue
        text=title+" "+BeautifulSoup(item.findtext("description") or "","html.parser").get_text(" ",strip=True)
        clean_title=re.sub(r"^\s*press release:\s*","",title,flags=re.I)
        if "state of emergency" not in text.lower() or AMENDING_RE.search(text):
            review.append(f"{day} {clean_title}"); continue
        number=announced_order(text)
        if not number:
            review.append(f"{day} {clean_title} (no order number)"); continue
        if number in seen: continue
        seen.add(number)
        hazard=next((c for c,p in HAZARDS.items() if re.search(p,clean_title,re.I)),"") or "severe_storm"
        out.append(Release(clean_title,(item.findtext("link") or "").strip(),day,number,hazard))
    return sorted(out,key=lambda x:x.date_signed)

def read_saved(path):
    try:
        with open(path,newline="",encoding="utf-8") as f: return list(csv.DictReader(f))
    except (OSError,csv.Error): return []

def release_rows(releases,saved_join):
    """Join rows for the releases: a saved record for the same order is
    written back unchanged; a new one gets WI-EO-<number>."""
    by_id={r.get("declaration_id",""):r for r in saved_join}
    rows=[]
    for r in releases:
        hit=by_id.get(f"WI-EO-{r.eo_number}")
        if hit: rows.append({k:hit.get(k,"") for k in JOIN_FIELDS}); continue
        rows.append({"declaration_id":f"WI-EO-{r.eo_number}","governor":GOVERNOR,"eo_number":r.eo_number,"event_description":r.title,"date_signed":r.date_signed,"archive_record_url":r.url})
    return rows

def scrape_releases(session=None,review=None):
    session=session or requests.Session()
    last=None
    for wait in (0,10):
        if wait: time.sleep(wait)
        try:
            r=session.get(RELEASE_FEED,headers=FEED_HEADERS,timeout=45); r.raise_for_status()
            return feed_releases(r.content,review)
        except (requests.RequestException,ET.ParseError) as exc: last=exc
    raise last

def write_release_outputs(releases,actions_out,relationships_out,join_out):
    """Fallback outputs: the saved files, plus the releases' records."""
    saved_join=read_saved(join_out); saved_actions=read_saved(actions_out)
    rows=release_rows(releases,saved_join)
    known={r.get("declaration_id") for r in saved_join}
    join=saved_join+[r for r in rows if r["declaration_id"] not in known]
    have={r.get("declaration_id") for r in saved_actions}
    actions=saved_actions+[{"declaration_id":r["declaration_id"],"eo_number":r["eo_number"],"title":r["event_description"],"date_signed":r["date_signed"],"action_type":"declaration","hazard_category":next((x.hazard for x in releases if x.date_signed==r["date_signed"]),""),"archive_record_url":r["archive_record_url"]} for r in rows if r["declaration_id"] not in have]
    for p,fields,data in ((join_out,JOIN_FIELDS,join),(actions_out,ACTION_FIELDS,actions)):
        p.parent.mkdir(parents=True,exist_ok=True)
        with p.open("w",newline="\n",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n",extrasaction="ignore"); w.writeheader(); w.writerows(data)
    if not relationships_out.exists():
        with relationships_out.open("w",newline="\n",encoding="utf-8") as f:
            w=csv.writer(f,lineterminator="\n"); w.writerow(["source_declaration_id","relationship_type","target_declaration_id"]); w.writerow(["WI-EO-7","operational_companion","WI-EO-5"])
    return len(join)-len(saved_join)

def write_outputs(rows, actions_out, relationships_out, join_out):
    for p in (actions_out,relationships_out,join_out): p.parent.mkdir(parents=True,exist_ok=True)
    with actions_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n"); w.writerow(ACTION_FIELDS)
        for x in rows:w.writerow([f"WI-EO-{x.eo_number}",x.eo_number,x.title,x.date_signed,x.action_type,x.hazard,x.url])
    with relationships_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n"); w.writerow(["source_declaration_id","relationship_type","target_declaration_id"]); w.writerow(["WI-EO-7","operational_companion","WI-EO-5"])
    with join_out.open("w",newline="\n",encoding="utf-8") as f:
        w=csv.writer(f,lineterminator="\n"); w.writerow(JOIN_FIELDS)
        for x in rows:
            if x.action_type=="declaration":w.writerow([f"WI-EO-{x.eo_number}",GOVERNOR,x.eo_number,x.title,x.date_signed,x.url])

def main():
    p=argparse.ArgumentParser();p.add_argument("--actions-out",required=True);p.add_argument("--relationships-out",required=True);p.add_argument("--join-out",required=True);a=p.parse_args()
    try:
        rows=scrape()
    except (requests.RequestException,ValueError) as archive_exc:
        print(f"Wisconsin archive not reachable ({archive_exc}); reading the Governor's press releases instead",file=sys.stderr)
        review=[]
        try:
            releases=scrape_releases(review=review)
        except (requests.RequestException,ET.ParseError) as exc:
            raise SystemExit(f"Wisconsin archive scrape failed: {archive_exc}; press releases not read either: {exc}")
        for line in review:
            print(f"  REVIEW: Wisconsin release not recorded automatically: {line}",file=sys.stderr)
        added=write_release_outputs(releases,Path(a.actions_out),Path(a.relationships_out),Path(a.join_out))
        print(f"Wisconsin: archive not reachable; {len(releases)} weather emergency press releases read, {added} new declarations added (read from the Governor's press releases)")
        return
    write_outputs(rows,Path(a.actions_out),Path(a.relationships_out),Path(a.join_out));print(f"Wisconsin: {len(rows)} executive orders processed")
if __name__=="__main__":main()
