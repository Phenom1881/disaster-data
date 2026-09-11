"""Illinois: official disaster proclamations and full numbered-EO indexes."""
from pathlib import Path
import re
from urllib.parse import urljoin
from _adapter_support import *
ARCHIVE='https://www.illinois.gov/government/disaster-proclamations.html'
EO_ARCHIVES=['https://www.illinois.gov/government/executive-orders.html','https://www.illinois.gov/government/executive-orders-archive.html']
def parse_archive(content,url=ARCHIVE):
    s=soup(content);out=[]
    for a in s.find_all('a',href=True):
        if clean(a.text)!='Read Proclamation':continue
        li=a.find_parent('li');h=li.find_previous(['h2','h3']);m=re.search(r'\b\d{1,2}-\d{1,2}-20\d{2}\b',li.get_text(' ',strip=True))
        if not h:continue
        title=clean(h.text); description=[]
        for el in h.next_siblings:
            if getattr(el,'name',None) in ('h2','h3','ul'):break
            if getattr(el,'name',None)=='p':description.append(clean(el.text))
        r=make_record('IL',title+('. '+' '.join(description) if description else ''),urljoin(url,a['href']),signed=exact_date(m[0]) if m else '',governor='JB Pritzker',listing=url,kind='proclamation',evidence='Official dated proclamation listing: '+(m[0] if m else 'undated'))
        out.append(r)
    return out

def parse_orders(content,url):
    out=[]
    for row in soup(content).select('.cmp-exe-order-feed__item'):
        a=next((a for a in row.select('a[href]') if '(HTML)' in a.text),None)
        if not a:continue
        m=re.search(r'(20\d{2})\.html',a['href']);n=re.search(r'(?:Order(?: Number)?\s+)(?:(?:\d{2}|20\d{2})-)?(\d+)',a.text,re.I)
        if not(m and n) or int(m[1])<2000:continue
        title=clean(row.find('p').text) if row.find('p') else clean(a.text)
        out.append(make_record('IL',title or clean(a.text),urljoin(url,a['href']),number=f'{m[1]}-{int(n[1]):02}',listing=url))
    return out

def collect():
    out=parse_archive(html(ARCHIVE))
    for u in EO_ARCHIVES:out.extend(parse_orders(html(u),u))
    # All orders remain in the audit; linked details establish dates and scope.
    enrich(out)
    return out
if __name__=='__main__':run(collect,Path(__file__).parent)
