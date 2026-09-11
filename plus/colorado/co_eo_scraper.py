"""Colorado State Publications Library: D-series orders, 2000 onward."""
from pathlib import Path
import re
from urllib.parse import urljoin
from _adapter_support import *
ARCHIVE='https://spl.cde.state.co.us/artemis/goserials/'
GOVERNORS={'go4013internet':'Bill Owens','go4113internet':'Bill Ritter','go4213internet':'John Hickenlooper','go4312internet':'Jared Polis'}
def parse_archive(content,url,governor):
    out=[]
    for a in soup(content).select('a[href]'):
        m=re.search(r'go\d{4}(20\d{2})(\d{3})internet\.pdf',a['href'],re.I)
        if not m:
            old=re.search(r'go4013d(\d{3})(\d{2})internet\.pdf',a['href'],re.I)
            if not old or int(old[2])>26:continue
            year='20'+old[2];num=old[1]
        else:year,num=m[1],m[2]
        title=re.sub(r'^\s*\d+\s*\(PDF\)\s*','',clean(a.text),flags=re.I)
        # Older layouts put the description beside the link in the table cell.
        if not title or title==clean(a.text) and len(title)<12:
            cell=a.find_parent(['td','li']);title=re.sub(r'^\s*\d+\s*(?:\(PDF\))?\s*','',clean(cell.text if cell else a.text),flags=re.I)
        r=make_record('CO',title,urljoin(url,a['href']),number=f'D-{year}-{num}',governor=governor,listing=url)
        out.append(r)
    return out

def collect():
    s=soup(html(ARCHIVE));out=[]
    for key,g in GOVERNORS.items():
        a=next((a for a in s.select('a[href]') if key in a['href']),None)
        if not a:raise RuntimeError('Colorado library series missing: '+key)
        u=urljoin(ARCHIVE,a['href']).rstrip('/')+'/'
        out.extend(parse_archive(html(u),u,g))
    enrich(out,lambda r:bool(len(r['event_description'])<15 or WEATHER.search(r['event_description']) or re.search('emergency|disaster|National Guard',r['event_description'],re.I)))
    for r in out:
        text=r['full_text']
        m=re.search(r'D\s*(?:20\d{2}[- ]*\d{3}|\d{3}[- ]+\d{2})\s+(.{8,1000}?)(?=Pursuant|WHEREAS|Under|I, |By virtue)',text,re.I)
        if m:r['event_description']=clean(m[1])
        elif not r['event_description']:
            m=re.search(r'E\s*X\s*E\s*C\s*U\s*T\s*I\s*V\s*E\s+O\s*R\s*D\s*E\s*R\s+(.{8,1000}?)(?=Pursuant|WHEREAS|Under|I, |By virtue)',text,re.I)
            if m:r['event_description']=clean(m[1])
    return out
if __name__=='__main__':run(collect,Path(__file__).parent)
