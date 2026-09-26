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
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}; TIMEOUT=30
# Fewer parallel requests than before (12); Sep 25's run got a 500 from the
# archive. One retry per request, and a time budget for the whole crawl, so a
# slow site cannot push the 50-state job past its 90-minute limit.
LISTING_WORKERS=8; DETAIL_WORKERS=8
RETRY_STATUS={429,500,502,503,504}; RETRY_WAITS=(5,)
CRAWL_BUDGET_SECONDS=25*60
_deadline=[None]
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
    """GET with a retry on a timeout, a dropped connection, or a 429/5xx.
    Once the crawl's time budget is spent, every further request fails at
    once, and collect() decides whether enough was read."""
    last=None
    for wait in (0,)+RETRY_WAITS:
        if _deadline[0] is not None and time.monotonic()>_deadline[0]:
            raise requests.Timeout(f"crawl time budget spent before {url}")
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

_MONTH_NUM={name:i for i,name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(),1)}
DATE_RE=re.compile(r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+(\d{1,2}),\s+(20\d{2})\b",re.I)

def _iso(match):
    try:
        return date(int(match.group(3)),_MONTH_NUM[match.group(1)[:3].lower()],int(match.group(2))).isoformat()
    except ValueError:
        return ""

def first_date(text):
    """The post's date: the byline's ('September 2, 2026 | Austin, Texas |
    ...') when there is one, else the first 'September 2, 2026' or 'Sep 2,
    2026' in the text. An impossible date ('June 31') gives ''."""
    match=re.search(DATE_RE.pattern+r"\s*\|",text,re.I) or DATE_RE.search(text)
    return _iso(match) if match else ""

# The Governor's post categories. A byline names one after the dateline:
# "June 15, 2026 | Austin, Texas | Proclamation", "06/16/2026 | Press Release".
CATEGORIES=("Proclamation","Press Release","Executive Order","Media Advisory","Statement","Speech","Op-Ed","Appointment","Letter","Announcement","Video")
CATEGORY_RE=re.compile(r"\|\s*("+"|".join(re.escape(c) for c in CATEGORIES)+r")\b",re.I)
PROCLAMATION_TEXT_RE=re.compile(r"\bdo hereby\b|\bWHEREAS\b|\bby the authority vested\b",re.I)

def byline_category(text):
    """The category a post is filed under ('Proclamation', 'Press Release'),
    read from the first '| Category' in its opening text whatever the date
    format, or '' when there is none."""
    m=CATEGORY_RE.search(text[:600])
    return m.group(1) if m else ""

def is_proclamation_post(text,title):
    """A proclamation post is filed under Proclamation in its byline. A post
    filed under anything else (Press Release) is not one, even when its title
    mentions a disaster declaration. With no category at all (the byline
    changed), it counts only if its title names a proclamation and its text
    reads like one ('do hereby', 'WHEREAS'), so press releases cannot slip in."""
    category=byline_category(text)
    if category:
        return category.lower()=="proclamation"
    return bool(re.search(r"\bProclamation\b|\bdisaster declaration\b",title,re.I) and PROCLAMATION_TEXT_RE.search(text))

def parse_detail(url,title):
    soup=BeautifulSoup(get(url).text,"html.parser"); main=soup.select_one("main") or soup
    text=re.sub(r"\s+"," ",main.get_text(" ",strip=True))
    if not is_proclamation_post(text,title): return None
    date_text=first_date(text)
    # An undated page (an error page served with status 200, say) would get
    # an id of its own next to the record's real dated one. Skip it instead.
    if not date_text: return None
    slug=urlparse(url).path.rstrip("/").rsplit("/",1)[-1]
    number=f"PROCLAMATION-{date_text or 'UNDATED'}-{slug}"
    governor="Dan Patrick" if re.search(r"Acting Governor Dan Patrick",title,re.I) else "Greg Abbott"
    return Action(number,title,date_text,url,text,governor)

def parse_listing(html):
    """(post url, title) for every proclamation post a listing page links to.
    Any link to /news/post/ counts, not only one inside an <h3>, so a change
    of heading level does not empty the state. A post linked twice (image and
    title) is kept once, with the longer text as its title."""
    soup=BeautifulSoup(html,"html.parser"); found={}
    for anchor in soup.select("a[href*='/news/post/']"):
        url=urljoin(ARCHIVE_URL,anchor["href"]).split("#")[0]
        title=re.sub(r"\s+"," ",anchor.get_text(" ",strip=True))
        if len(title)>len(found.get(url,"")): found[url]=title
    out=[(url,title) for url,title in found.items() if RELEVANT_RE.search(title)]
    next_link=soup.select_one("a.pagination-next[href]")
    return out,(urljoin(ARCHIVE_URL,next_link["href"]) if next_link else "")

def count_posts(html):
    """How many news posts a listing page links to, proclamations or not.
    Zero on every page means the layout changed (or the answer was not the
    archive at all), which is a different problem from a month with no
    proclamations in it."""
    return len(BeautifulSoup(html,"html.parser").select("a[href*='/news/post/']"))

def category_targets(max_pages=60):
    """(post url, title) pairs from the Proclamation category listing,
    following its "next" links, newest first."""
    out,url,seen=[],ARCHIVE_URL,set()
    for _ in range(max_pages):
        if not url or url in seen: break
        seen.add(url)
        try: page=get(url).text
        except requests.RequestException as exc:
            print(f"  WARNING: Texas category page not read: {exc}",file=sys.stderr); break
        rows,url=parse_listing(page)
        out.extend(rows)
    return out

def outline_page(html,limit=12):
    """A short outline of a listing page for the run log: its title, link
    counts, and the first few links, to fix the parser against."""
    soup=BeautifulSoup(html,"html.parser")
    links=soup.find_all("a",href=True)
    scripts=len(soup.find_all("script"))
    text_len=len(soup.get_text(" ",strip=True))
    sample="; ".join(f"{re.sub(chr(92)+'s+',' ',a.get_text(' ',strip=True))[:50]!r} -> {a['href'][:80]}" for a in links[:limit])
    return (f"title {page_title(html)!r}, {len(html)} characters, {text_len} of text, {len(links)} links, "
            f"{html.count('/news/post/')} mentions of /news/post/, {scripts} scripts; first links: {sample}")

def page_title(html):
    soup=BeautifulSoup(html,"html.parser")
    return re.sub(r"\s+"," ",soup.title.get_text(" ",strip=True)) if soup.title else "(no title)"

def _fetch_listing(url):
    try: return url,get(url).text,None
    except requests.RequestException as exc: return url,None,exc

def collect(stats=None):
    stats={} if stats is None else stats
    _deadline[0]=time.monotonic()+CRAWL_BUDGET_SECONDS
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
        # The monthly archive gave nothing: try the Proclamation category
        # listing and its older pages before giving up.
        latest_url,latest=read[-1]
        print(f"  WARNING: no proclamation posts in {len(read)} monthly archive pages ({stats['posts']} news post "
              f"links in all); trying the category listing. Latest archive page: {outline_page(latest)}",file=sys.stderr)
        unique=dict(category_targets())
        stats["category_posts"]=len(unique)
        stats["proclamation_posts"]=len(unique)
        if not unique:
            raise RuntimeError(f"no proclamation posts in {len(read)} monthly archive pages or the category listing; "
                               f"the site layout may have changed. Latest archive page: {outline_page(latest)}")
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

def saved_by_url(*paths):
    """{post url: (declaration_id, eo_number, date_signed)} from saved files.
    A record's id carries the date it was first read with, so a post already
    saved keeps that id and date: a change in how dates are read must not
    give it a second id."""
    out={}
    for path in paths:
        try:
            with open(path,newline="",encoding="utf-8") as handle:
                for r in csv.DictReader(handle):
                    url=r.get("detail_url") or r.get("archive_record_url") or ""
                    if url and r.get("declaration_id") and url not in out:
                        out[url]=(r["declaration_id"],r.get("eo_number",""),r.get("date_signed",""))
        except (OSError,csv.Error):
            pass
    return out

def write_outputs(actions,actions_out,relationships_out,join_out):
    rows=[]; joins=[]
    saved=saved_by_url(join_out,actions_out)
    for action in actions:
        kind=classify(action); evidence=action.title+" "+action.text; weather=kind=="declaration" and bool(HAZARD_RE.search(evidence))
        sid,number,signed=saved.get(action.url,(action.stable_id,action.number,action.date))
        number=number or action.number; signed=signed or action.date
        row={"declaration_id":sid,"state":"TX","governor":action.governor,"eo_number":number,"action_kind":"emergency_declaration" if kind!="administrative" else "proclamation","action_type":kind,"event_description":action.title,"date_signed":signed,"end_date":"","weather_related":str(weather).lower(),"source_scope":"texas_governor_proclamation_archive_2015_present","document_format":"html","detail_url":action.url,"archive_record_url":action.url}; rows.append(row)
        if weather and signed: joins.append({field:row[field] for field in JOIN_FIELDS})
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
