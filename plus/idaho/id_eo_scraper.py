"""Idaho OARC public archive service and Governor's current EO index."""
from pathlib import Path
import re,json
from urllib.parse import urljoin
from _adapter_support import *
ARCHIVE='https://adminrules.idaho.gov/executive-orders/'
GOV='https://gov.idaho.gov/executive-orders/'
def parse_api(data,url=ARCHIVE):
    out=[]
    for r in data.get('data',[]):
        if int(r['year'])<2000:continue
        number=r['documentNumber'];u=urljoin(url,r['file'])
        out.append(make_record('ID',r['documentName'],u,number=number,listing=url))
    return out

def parse_archive(content,url=GOV):
    out=[]
    for a in soup(content).select('main a[href]'):
        m=re.search(r'Executive Ord-?er\s+(20\d{2}-\d+[A-Za-z]?)',a.text,re.I)
        if not m:continue
        parent=a.find_parent(['li','p']);title=clean(parent.text if parent else a.text)
        out.append(make_record('ID',title,urljoin(url,a['href']),number=m[1],governor='Brad Little',listing=url))
    return out

def collect():
    content=html(ARCHIVE);m=re.search(r'var dfmFetchDocuments\s*=\s*(\{.*?\});',content)
    if not m:raise RuntimeError('OARC public API configuration missing')
    cfg=json.loads(m[1]);data=json.loads(fetch(cfg['rest_base']+'/fetch-documents',payload={'azurePayload':{'documentType':cfg['document_type']}},headers={'X-WP-Nonce':cfg['nonce']})[0])
    out=parse_api(data)+parse_archive(html(GOV))+collect_proclamations();byid={r['declaration_id']:r for r in out}
    out=enrich(list(byid.values()))
    for r in out:
        t=r['full_text'];m=re.search(r'(?:EXECUTIVE ORDER|Executive Order)\s*(?:NO\.?|No\.?)?\s*20\d{2}[-–]\d+\s*[:.-]?\s*(.{10,500}?)\s*WHEREAS',t,re.I)
        if m:r['event_description']=clean(m[1])
        for name in ['Brad Little','C. L. Otter','Butch Otter','Jim Risch','Dirk Kempthorne']:
            if name.lower() in t.lower():r['governor']=name;break
    return out

DROUGHT='https://idwr.idaho.gov/legal-matters/drought-declarations/'
def parse_drought(content,url=DROUGHT):
    out=[];ss=soup(content)
    for row in ss.select('table tr'):
        cells=row.find_all('td')
        if len(cells)<2:continue
        a=cells[0].find('a',href=True)
        if not a:continue
        title=clean(a.text)
        if 'drought' not in title.lower():title='Order Declaring Drought Emergency - '+title
        out.append(make_record('ID',title,urljoin(url,a['href']),signed=exact_date(clean(cells[1].text)),listing=url,kind='drought_order',evidence='IDWR Date Declared column: '+clean(cells[1].text)))
    # Current statewide order is outside the historical table.
    for a in ss.select('a[href]'):
        if 'StatewideDeclaration' in a['href']:
            out.append(make_record('ID','Order Declaring Drought Emergency - Statewide',urljoin(url,a['href']),listing=url,kind='drought_order'))
    return out

def parse_news(content,url):
    out=[]
    for a in soup(content).select('h2.entry-title a[href]'):
        if '/pressrelease/' in a['href']:
            out.append(make_record('ID',clean(a.text),urljoin(url,a['href']),governor='Brad Little',listing=url,kind='news_release'))
    return out

def collect_proclamations():
    out=parse_drought(html(DROUGHT));u='https://gov.idaho.gov/?s=disaster';seen=set()
    while u:
        if u in seen:raise RuntimeError('Idaho newsroom pagination loop')
        seen.add(u);content=html(u);out.extend(parse_news(content,u));ss=soup(content)
        a=next((a for a in ss.select('a[href]') if clean(a.text)=='Next'),None)
        u=urljoin(u,a['href']) if a else None
    # Separately identified official historical release, not an invented archive range.
    out.append(make_record('ID','Spring Flooding Declaration','https://ioem.idaho.gov/spring-flooding-declaration/',governor='Bob Geddes (Acting Governor)',kind='news_release'))
    return out

if __name__=='__main__':run(collect,Path(__file__).parent)
