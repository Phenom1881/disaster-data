"""Hawaii Governor emergency proclamations and State Procurement historical archive."""
from pathlib import Path
import re
from urllib.parse import urljoin
from _adapter_support import *
ARCHIVE='https://governor.hawaii.gov/category/newsroom/emergency-proclamations/'
OLD='https://spo.hawaii.gov/emergency-proclamations-archived/'
def parse_archive(content,url=ARCHIVE):
    out=[];s=soup(content)
    for h in s.select('h3'):
        a=h.find('a',href=True)
        if not a or 'proclamation' not in a.text.lower():continue
        # Posted dates are audit evidence only; PDF signature supplies date_signed.
        meta=h.find_next_sibling('p',class_='meta-info')
        out.append(make_record('HI',clean(a.text),urljoin(url,a['href']),governor='Josh Green',listing=url,kind='proclamation',evidence=clean(meta.text) if meta else ''))
    return out

def parse_old(content,url=OLD):
    s=soup(content);out=[]
    for a in s.select('a[href]'):
        if '.pdf' not in a['href'].lower():continue
        h=a.find_previous(['h2','h3','h4'])
        title=(clean(a.text)+' - '+clean(h.text)) if h else clean(a.text)
        if not re.search('proclamation|emergency',title,re.I):continue
        # Current administration collected above; this mirror adds Ige-era records.
        if not re.search(r'/(?:201[4-9]|202[0-2])/',a['href']):continue
        out.append(make_record('HI',title,urljoin(url,a['href']),governor='David Ige',listing=url,kind='proclamation'))
    return out

def collect():
    out=[];u=ARCHIVE;seen=set()
    while u:
        if u in seen:raise RuntimeError('Hawaii pagination loop')
        seen.add(u);content=html(u);batch=parse_archive(content,u)
        if not batch:raise RuntimeError('Hawaii proclamation page unexpectedly empty: '+u)
        out.extend(batch)
        a=next((a for a in soup(content).select('a[href]') if 'Next »' in a.text),None)
        u=urljoin(u,a['href']) if a else None
    out.extend(parse_old(html(OLD)))
    enrich(out,lambda r:bool(WEATHER.search(r['event_description']) or not NONWEATHER.search(r['event_description'])))
    return out
if __name__=='__main__':run(collect,Path(__file__).parent)
