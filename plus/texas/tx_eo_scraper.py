"""Collect Texas disaster proclamations from the official Governor news archive.

The Governor's site publishes every proclamation as a news post. This reads the
monthly news archive pages (gov.texas.gov/news/archive/YYYY/MM) from January
2015 through the current month, keeps the posts whose titles mention a
proclamation or disaster declaration, and reads each post for its date and
text.

The archive is large (well over a hundred monthly pages). One page that errors
must not sink the whole state, and an empty result must never be written as if
Texas had no proclamations, so:
  - each request is retried on a timeout or a 429/5xx answer, with a pause;
  - a monthly page that still fails is skipped and counted, not fatal;
  - if no monthly page could be read, or pages were read but none held a
    proclamation post, or no post could be parsed, the scraper stops with an
    error that says which, and build-plus.py keeps the saved records;
  - a summary line with every count is printed so the run log shows what
    happened even when it worked.
"""
from __future__ import annotations
import argparse, csv, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

ARCHIVE_URL="https://gov.texas.gov/news/category/proclamation"
MONTH_URL="https://gov.texas.gov/news/archive/{year}/{month:02d}"
FIRST_YEAR=2015
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT=45
# Fewer parallel requests than before (12). Sep 25's run got a 500 from the
# archive, and the site answers a steady, small crawl more reliably.
LISTING_WORKERS=4; DETAIL_WORKERS=4
RETRY_STATUS={429,500,502,503,504}; RETRY_WAITS=(5,20)
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
    """GET with retries on a timeout, a dropped connection, or a 429/5xx."""
    last=None
    for wait in (0,)+RETRY_WAITS:
        if wait: time.sleep(wait)
        try:
            response=requests.get(url,headers=HEADERS,timeout=TIMEOUT)
        except (requests.Timeout,requests.ConnectionError) as exc:
            last=exc; continue
        if response.status_code in RETRY_STATUS:
            last=requests.HTTPError(f"{response.status_code} Server Error for url: {url}",response=response); continue
        response.raise_for_status(); return response
    raise last

def month_urls(today=None):
    """Every monthly archive page from January 2015 through the current month.
    Months that have not happened yet are not requested."""
    today=today or date.today()
    return [MONTH_URL.format(year=y,month=m) for y in range(FIRST_YEAR,today.year+1) for m in range(1,13) if (y,m)<=(today.year,today.month)]

def parse_detail(url,title):
    soup=BeautifulSoup(get(url).text,"html.parser"); main=soup.select_one("main") or soup
    text=re.sub(r"\s+"," ",main.get_text(" ",strip=True))
    if not re.search(r"\|\s*Proclamation\b",text): return None
    match=re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})\b",text)
    date_text=""
    if match:
        months={name:i for i,name in enumerate("January February March April May June July August September October November December".split(),1)}
        date_text=f"{match.group(3)}-{months[match.group(1)]:02d}-{int(match.group(2)):02d}"
    slug=urlparse(url).path.rstrip("/").rsplit("/",1)[-1]
    number=f"PROCLAMATION-{date_text or 'UNDATED'}-{slug}"
    governor="Dan Patrick" if re.search(r"Acting Governor Dan Patrick",title,re.I) else "Greg Abbott"
    return Action(number,title,date_text,url,text,governor)

def parse_listing(html):
    soup=BeautifulSoup(html,"html.parser"); out=[]
    for anchor in soup.select("h3 a[href*='/news/post/']"):
        title=re.sub(r"\s+"," ",anchor.get_text(" ",strip=True))
        if RELEVANT_RE.search(title): out.append((urljoin(ARCHIVE_URL,anchor["href"]),title))
    next_link=soup.select_one("a.pagination-next[href]")
    return out,(urljoin(ARCHIVE_URL,next_link["href"]) if next_link else "")

def count_posts(html):
    """How many news posts a listing page links to, proclamations or not.
    Zero on every page means the layout changed (or the answer was not the
    archive at all), which is a different problem from a month with no
    proclamations in it."""
    return len(BeautifulSoup(html,"html.parser").select("a[href*='/news/post/']"))

def page_title(html):
    soup=BeautifulSoup(html,"html.parser")
    return re.sub(r"\s+"," ",soup.title.get_text(" ",strip=True)) if soup.title else "(no title)"

def _fetch_listing(url):
    try: return url,get(url).text,None
    except requests.RequestException as exc: return url,None,exc

def collect(stats=None):
    stats={} if stats is None else stats
    urls=month_urls()
    # Read last month's page first. If the site is down or refusing this
    # runner, that answers it in about a minute instead of retrying every
    # page and running into the workflow's time limit.
    probe=urls[-2] if len(urls)>1 else urls[-1]
    probe_result=_fetch_listing(probe)
    if probe_result[2] is not None:
        raise RuntimeError(f"the Governor's news archive did not answer ({probe_result[2]})")
    with ThreadPoolExecutor(max_workers=LISTING_WORKERS) as pool:
        results=list(pool.map(_fetch_listing,[u for u in urls if u!=probe]))
    results.insert(len(urls)-2 if len(urls)>1 else 0,probe_result)
    read=[(url,page) for url,page,exc in results if page is not None]
    failed=[(url,exc) for url,page,exc in results if exc is not None]
    stats.update(months=len(urls),months_read=len(read),months_failed=len(failed))
    for url,exc in failed[:5]:
        print(f"  WARNING: Texas archive page not read: {exc}",file=sys.stderr)
    if len(failed)>5:
        print(f"  WARNING: {len(failed)-5} more Texas archive pages not read",file=sys.stderr)
    if not read:
        raise RuntimeError(f"none of the {len(urls)} monthly archive pages could be read; first error: {failed[0][1]}")
    targets=[]
    for url,page in read: targets.extend(parse_listing(page)[0])
    unique=dict(targets)
    stats.update(posts=sum(count_posts(page) for _,page in read),proclamation_posts=len(unique))
    if not unique:
        latest_url,latest=read[-1]
        raise RuntimeError(f"read {len(read)} monthly archive pages but found no proclamation posts in them "
                           f"({stats['posts']} news post links in all); the archive layout may have changed. "
                           f"Latest page {latest_url} is titled {page_title(latest)!r}")
    detail_errors=[]
    def safe_parse(pair):
        try:
            return parse_detail(*pair)
        except requests.RequestException as exc:
            detail_errors.append(exc); return None
    with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
        parsed=list(pool.map(safe_parse,unique.items()))
    actions=[item for item in parsed if item]
    stats.update(details_failed=len(detail_errors),not_proclamation=len(parsed)-len(actions)-len(detail_errors))
    for exc in detail_errors[:3]:
        print(f"  WARNING: Texas proclamation post not read: {exc}",file=sys.stderr)
    if not actions:
        raise RuntimeError(f"found {len(unique)} proclamation posts but could not parse any of them "
                           f"({len(detail_errors)} could not be read, {stats['not_proclamation']} were not marked as a proclamation)")
    return sorted({item.stable_id:item for item in actions if not item.date or item.date>="2015-01-20"}.values(),key=lambda item:(item.date,item.number),reverse=True)

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
    return len(rows),len(joins)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--actions-out",required=True); parser.add_argument("--relationships-out",required=True); parser.add_argument("--join-out",required=True)
    args=parser.parse_args(); stats={}
    try:
        actions=collect(stats)
    except (requests.RequestException,RuntimeError) as exc:
        raise SystemExit(f"Texas archive scrape failed: {exc}")
    n_actions,n_joins=write_outputs(actions,args.actions_out,args.relationships_out,args.join_out)
    print(f"Texas: read {stats['months_read']} of {stats['months']} monthly archive pages ({stats['months_failed']} not read), "
          f"{stats['proclamation_posts']} proclamation posts, {n_actions} parsed ({stats['details_failed']} not read), "
          f"{n_joins} weather declarations.")
if __name__=="__main__": main()
