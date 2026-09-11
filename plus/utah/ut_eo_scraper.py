"""Utah official executive-document PDFs; dated discovery snapshot when index is blocked.

The fallback is explicit and bounded: it cannot discover orders newer than its
capture date. It re-fetches every linked legal document, not a declarations CSV.
"""
from pathlib import Path
import re,json,sys
from urllib.parse import urljoin
from _adapter_support import *
ARCHIVE='https://rules.utah.gov/publications/executive-documents/'
def parse_archive(content,url=ARCHIVE):
    out=[]
    for p in soup(content).select('p, li'):
        text=clean(p.text);m=re.match(r'(\d{2}/\d{2}/20\d{2}):?\s*(.*)',text)
        if not m:
            old=re.match(r'(Executive Order|Supplemental Proclamation|Proclamation|Declaration)(.*?),?\s*issued\s+(\d{1,2}/\d{1,2}/\d{4})\s*[,;:]?\s*(.*)',text,re.I)
            a=p.find('a',href=True)
            if old and a and exact_date(old[3])>='2000-01-01':
                out.append({'date':old[3],'title':old[4].split(' [')[0].lstrip(',:; '),'order_label':old[1]+' '+old[2].strip(' ,'),'url':urljoin(url,a['href'])})
            continue
        a=p.find('a',href=True)
        if a:out.append({'date':m[1],'title':m[2].split(clean(a.text))[0].strip(' ,.:'),'order_label':clean(a.text),'url':urljoin(url,a['href'])})
    return out

def parse_records(items):
    out=[]
    for item in items:
        m=re.search(r'20\d{2}-[\w/-]+',item['order_label'])
        number=m[0].rstrip(',') if m else '';kind='proclamation' if 'Proclamation' in item['order_label'] else 'order'
        r=make_record('UT',item['title'],item['url'],number=number,signed=exact_date(item['date']),governor=item.get('governor','Spencer J. Cox'),listing=item.get('listing',ARCHIVE),kind=kind,evidence='Official executive-document index date (not publication date): '+item['date'])
        if number:r['declaration_id']='UT-'+('PROC-' if kind=='proclamation' else 'EO-')+number
        if 'Modified' in item['order_label']:r['declaration_id']+='-MODIFIED'
        out.append(r)
    return out

def collect():
    try:
        content=html(ARCHIVE);items=parse_archive(content)
        governors={'gary-r-herbert':'Gary R. Herbert','jon-m-huntsman-jr':'Jon M. Huntsman Jr.','olene-s-walker':'Olene S. Walker','michael-o-leavitt':'Michael O. Leavitt'}
        seen=set()
        for a in soup(content).select('a[href]'):
            key=next((k for k in governors if 'executive-documents-of-'+k in a['href']),None)
            if not key or key in seen:continue
            seen.add(key);u=urljoin(ARCHIVE,a['href'].strip());batch=parse_archive(html(u),u)
            for r in batch:r.update(governor=governors[key],listing=u)
            items.extend(batch)
        if not items:raise RuntimeError('No dated records in Utah live HTML')
    except RuntimeError as e:
        snapshot=json.loads((Path(__file__).parent/'archive_snapshot.json').read_text());items=snapshot['records']
        print('WARNING: Utah HTML index unavailable; re-fetching official document URLs from discovery snapshot dated '+snapshot['captured']+'. Newer discovery requires index access. '+str(e),file=sys.stderr)
    out=parse_records(items);enrich(out)
    if not any(r['full_text'] for r in out):raise RuntimeError('No Utah legal documents readable; cannot report successful live collection')
    return out
if __name__=='__main__':run(collect,Path(__file__).parent)
