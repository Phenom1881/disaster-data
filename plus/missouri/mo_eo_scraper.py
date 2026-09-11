"""Missouri Secretary of State's 2000-present executive-order archive."""
from pathlib import Path
import re
from urllib.parse import urljoin
from _adapter_support import *
ARCHIVE='https://www.sos.mo.gov/library/reference/orders/default'
def parse_archive(content,url,year):
    out=[];seen=set()
    for p in soup(content).select('p,li'):
        text=clean(p.get_text(" ",strip=True));m=re.match(r'Executive Order\s+(\d{2}-\d+)\b',text,re.I)
        if not m or m[1] in seen:continue
        a=p.find('a',href=True)
        if not a:continue
        # Do not mistake a referenced order link inside a description for a new entry.
        if not re.search(r'Executive Order\s+'+re.escape(m[1]),clean(a.text),re.I):continue
        seen.add(m[1]);description=text[m.end():].strip()
        dates=re.findall(r'\(([A-Za-z]+)\.?\s+(\d{1,2})\)',description)
        signed=''
        if dates:
            mon,day=dates[-1];signed=exact_date(f'{mon} {day} {year}')
        g=re.search(r'G\s*ov\.\s+([A-Za-z]+(?:\s+[A-Za-z.]+){1,2})\s+(?:orders|declares|directs|establishes|amends|extends|implements|renews|rescinds|appoints|activates|names|creates|designates)',description)
        out.append(make_record('MO',description,urljoin(url,a['href']),number=m[1],signed=signed,governor=g[1] if g else '',listing=url,evidence='SOS year-index signing date: '+(f'{dates[-1]} {year}' if dates else 'unconfirmed')))
    return out

def collect():
    out=[];index=soup(html(ARCHIVE));years=[]
    for a in index.select('a[href]'):
        if re.fullmatch(r'20\d{2}',clean(a.text)) and int(a.text)<=date.today().year:years.append((int(a.text),urljoin(ARCHIVE,a['href'])))
    if not years:raise RuntimeError('No Missouri year-index links')
    for year,u in sorted(set(years)):out.extend(parse_archive(html(u),u,year))
    enrich(out,lambda r:bool(WEATHER.search(r['event_description']) or re.search(r'emergency|disaster|mutual|National Guard',r['event_description'],re.I)))
    return out
if __name__=='__main__':run(collect,Path(__file__).parent)
