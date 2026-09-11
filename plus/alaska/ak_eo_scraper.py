"""Alaska Governor's administrative-order archive and disaster-release proxy."""
from pathlib import Path
import re
from urllib.parse import urljoin,quote
from _adapter_support import *
ARCHIVE='https://gov.alaska.gov/administrative-orders/'
NEWS='https://gov.alaska.gov/'
def parse_archive(content,url):
    out=[]
    for article in soup(content).select('article'):
        a=article.select_one('h2 a, h3 a, h1 a');time=article.select_one('.published, time')
        if not a:continue
        title=clean(a.text);m=re.search(r'Administrative Order No\.\s*(\d+)',title)
        kind='administrative_order' if m else 'news_release'
        r=make_record('AK',title,urljoin(url,a['href']),number=('AO-'+m[1]) if m else '',listing=url,kind=kind,evidence='Publication date only: '+(clean(time.text) if time else 'unknown'))
        if m and 'amended' in title.lower():r['declaration_id']+='-AMENDED'
        out.append(r)
    return out

def collect():
    out=parse_archive(html(ARCHIVE),ARCHIVE)+collect_dhsem()
    for term in ['disaster','emergency']:
        u=NEWS+'?s='+quote(term);seen=set()
        while u:
            if u in seen:raise RuntimeError('Alaska pagination loop')
            seen.add(u);content=html(u);out.extend(parse_archive(content,u))
            s=soup(content);a=next((a for a in s.select('a[href]') if 'Older Entries' in a.text or 'Next Page' in a.text),None)
            u=urljoin(u,a['href']) if a else None
    out=list({r['declaration_id']:r for r in out}.values());enrich(out)
    for r in out:
        text=r['full_text']
        if r['record_type']=='news_release':
            # Use a dateline only when the issuance sentence explicitly confirms action.
            head=text[:2200]
            m=re.search(DATE_RE,head,re.I)
            if m and re.search(r'\btoday[, ]*(?:issued|signed|declared)\b|\b(?:issued|signed|declared)\b[^.]{0,90}\btoday\b',head,re.I):
                r['date_signed']=exact_date(m[0]);r['date_evidence']='Release dateline plus explicit issuance: '+m[0]
        for name in ['Mike Dunleavy','Michael J. Dunleavy','Bill Walker','Sean Parnell','Sarah Palin','Frank Murkowski','Tony Knowles']:
            if name.lower() in text.lower():r['governor']=name;break
    return out

DHSEM='https://ready.alaska.gov/PublicInformation/PressReleases'
def parse_dhsem(content,url=DHSEM):
    out=[]
    for a in soup(content).select('a[href]'):
        if '.pdf' not in a['href'].lower():continue
        title=clean(a.text)
        if not re.search(r'20\d{2}',title):continue
        # All release links retained for audit; only explicit declarations may join.
        title=re.sub(r'^20\d{2}[._-]\d{2}[._-]\d{2}[_ -]*','',title)
        out.append(make_record('AK',title,urljoin(url,a['href']),listing=url,kind='news_release'))
    return out

def collect_dhsem():return parse_dhsem(html(DHSEM))

if __name__=='__main__':run(collect,Path(__file__).parent)
