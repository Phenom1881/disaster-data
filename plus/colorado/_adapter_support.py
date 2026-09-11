"""Shared, fail-closed scraping utilities. No dependency on the storm joiner."""
import argparse,csv,hashlib,io,json,os,re,time
from datetime import date,datetime
from pathlib import Path
from urllib.parse import urljoin,urldefrag
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

JOIN_FIELDS=['declaration_id','governor','eo_number','event_description','date_signed','archive_record_url']
ACTION_FIELDS=JOIN_FIELDS+['listing_url','document_url','date_evidence','record_type','decision','reason','full_text','fetch_error']
REL_FIELDS=['source_order_id','target_order_id','relationship_type','relationship_text','source_url','target_status']
OVERRIDE_FIELDS=['declaration_id','hazard_category_override','review_note','source_url']
CACHE=Path(os.environ.get('DDPLUS_CACHE', '.ddplus-cache'))

def clean(s):return ' '.join(str(s or '').split())
def soup(s):return BeautifulSoup(s,'html.parser')
def fetch(url, payload=None, headers=None):
    url=urldefrag(url)[0]; key=hashlib.sha256((url+json.dumps(payload,sort_keys=True)).encode()).hexdigest()
    CACHE.mkdir(parents=True,exist_ok=True); body=CACHE/(key+'.bin'); meta=CACHE/(key+'.json')
    if body.exists() and meta.exists() and (time.time()-meta.stat().st_mtime<3600 or os.environ.get('DDPLUS_OFFLINE')=='1'):return body.read_bytes(),json.loads(meta.read_text())
    if os.environ.get('DDPLUS_OFFLINE')=='1':raise RuntimeError('Offline cache missing: '+url)
    error=None
    for attempt in range(3):
        try:
            h={'User-Agent':'DisasterDataPlus/1.0 (public archive research)'};h.update(headers or {})
            r=requests.get(url,headers=h,timeout=45) if payload is None else requests.post(url,json=payload,headers=h,timeout=45)
            r.raise_for_status()
            if any(x in r.text[:6000] for x in ['Request Rejected','Sorry, you have been blocked','Just a moment...']):raise RuntimeError('Archive request rejected despite HTTP 200: '+url)
            m={'url':url,'final_url':r.url,'status':r.status_code,'content_type':r.headers.get('Content-Type',''),'retrieved_at':datetime.now().astimezone().isoformat(),'sha256':hashlib.sha256(r.content).hexdigest()}
            body.write_bytes(r.content);meta.write_text(json.dumps(m,indent=2));return r.content,m
        except (requests.RequestException,RuntimeError) as e:
            error=e
            if isinstance(e,requests.HTTPError) and e.response.status_code in (400,401,403,404):break
            time.sleep(.4*(attempt+1))
    raise RuntimeError(str(error))

def html(url):return fetch(url)[0].decode('utf-8',errors='replace')
def pdf_text(url):
    data,m=fetch(url)
    if not data.startswith(b'%PDF'):raise ValueError('Not a PDF: '+url)
    return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(data)).pages)

def valid_date(s):
    try:
        d=date.fromisoformat(s)
        return '2000-01-01'<=s<=date.today().isoformat()
    except (ValueError,TypeError):return False

def exact_date(s):
    s=re.sub(r'(\d)\s*(st|nd|rd|th)\b',r'\1',clean(s),flags=re.I).replace(',','')
    for f in ['%Y-%m-%d','%m/%d/%Y','%m-%d-%Y','%B %d %Y','%b %d %Y','%d %B %Y']:
        try:return datetime.strptime(s,f).date().isoformat()
        except ValueError:pass
    return ''
MONTH=r'(?:January|February|March|April|May|June|July|August|September|October|November|December)'
DATE_RE=rf'{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+20\d{{2}}'

def signed_date(text):
    """Require a signature/issuance clause; never take an event or expiry date."""
    t=re.sub(r'-\s+', '-', clean(text))
    patterns=[rf'(?:this|on)\s+(\d{{1,2}})\s*(?:st|nd|rd|th)?\s+(?:day\s+)?of\s+({MONTH})[ ,]+(20\d{{2}})',rf'\b(?:Signed|Dated|Done|Issued|Date signed|Date Issued)(?:\s+on)?\s*[:,-]?\s*({DATE_RE})']
    for pat in patterns:
        matches=list(re.finditer(pat,t,re.I))
        if matches:
            m=matches[-1]; d=exact_date(f'{m[2]} {m[1]} {m[3]}') if len(m.groups())==3 else exact_date(m[1])
            if d:return d,m.group()
    # Colorado signature block: GIVEN ... at ... this <word ordinal> day of ...
    words={'first':1,'second':2,'third':3,'fourth':4,'fifth':5,'sixth':6,'seventh':7,'eighth':8,'ninth':9,'tenth':10,'eleventh':11,'twelfth':12,'thirteenth':13,'fourteenth':14,'fifteenth':15,'sixteenth':16,'seventeenth':17,'eighteenth':18,'nineteenth':19,'twentieth':20,'twenty first':21,'twenty second':22,'twenty third':23,'twenty fourth':24,'twenty fifth':25,'twenty sixth':26,'twenty seventh':27,'twenty eighth':28,'twenty ninth':29,'thirtieth':30,'thirty first':31}
    m=re.search(rf'(?:this|on)\s+([a-z -]+?)\s+day\s+of\s+({MONTH})[ ,]+(20\d{{2}})',t,re.I)
    if m and m[1].lower().replace('-',' ') in words:
        return exact_date(f'{m[2]} {words[m[1].lower().replace("-"," ")]} {m[3]}'),m.group()
    return '',''

WEATHER=re.compile(r'\b(?:drought|flood\w*|wildfires?|forest fires?|brush fires?|fires?|winter|snow\w*|ice storm|blizzard|tornado\w*|hurricane\w*|tropical|storms?|severe weather|wind\w*|heavy rain\w*|extreme cold|freez\w*|crop loss)\b',re.I)
NONWEATHER=re.compile(r'COVID|coronavirus|pandemic|avian|influenza|homeless|affordable housing|vaccination|opioid|monkeypox|mpox|invasive|axis deer|cyber|hazardous material|earthquake|volcan|tsunami|water system fire|structur(?:e|al) fire|building collapse|bridge repair|civil unrest',re.I)
MODIFIER=re.compile(r'^(?:(?:executive order|proclamation)\s+[\w-]+\s*[:.-]?\s*)?(?:amend\w*|extend\w*|rescind\w*|renew\w*|supplement\w*|terminat\w*|continu\w*|restat\w*)\b|\b(?:supplementary|supplemental|extension|amendment)\b',re.I)
OPERATIONAL=re.compile(r'hours.of.service|motor.carrier|propane|liquid petroleum|fuel(?:s)? proclamation|school clos|administrative leave|travel (?:ban|advisory)|waiv(?:e|er|ing)|suspend\w*.*(?:regulat|hours)|harvest|weight limit',re.I)
ORDINAL=re.compile(r'^(?:(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|twenty|thirtieth|thirty|fortieth|forty)[ -]*)+',re.I)

def make_record(state,title,url,number='',signed='',governor='',listing='',kind='order',evidence=''):
    url=urldefrag(url)[0]
    identifier=f'{state}-EO-{number}' if number else f'{state}-PROC-'+hashlib.sha256(url.encode()).hexdigest()[:16].upper()
    return dict(declaration_id=identifier,governor=governor,eo_number=number,event_description=clean(title),date_signed=signed,archive_record_url=url,listing_url=listing or url,document_url=url,date_evidence=evidence,record_type=kind,decision='',reason='',full_text='',fetch_error='')

def enrich_record(r):
    try:
        u=r['document_url']
        if 'drive.google.com/file/d/' in u:
            docid=u.split('/file/d/')[1].split('/')[0]
            u='https://drive.google.com/uc?export=download&id='+docid
        data,meta=fetch(u)
        if data.startswith(b'%PDF'):
            text='\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(data)).pages)
            transcriptions=Path(__file__).parent/'ocr_transcriptions.json'
            if len(clean(text))<80 and transcriptions.exists():
                item=json.loads(transcriptions.read_text()).get(meta['sha256'])
                if item:text=item['text'];r['date_evidence']+='; hash-matched OCR transcription'
        else:
            s=soup(data);main=s.select_one('article .entry-content, .field--name-body, .node__content, #main-content') or s.find('main') or s
            text=main.get_text(' ',strip=True)
            # Drupal media landing pages expose a real download anchor.
            if re.search(r'/media/\d+/?$',u):
                a=next((a for a in s.select('a[href]') if '/download' in a['href'] or '.pdf' in a['href']),None)
                if a:
                    r['document_url']=urljoin(u,a['href']);pdfdata,pdfmeta=fetch(r['document_url']);text='\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(pdfdata)).pages)
                    tp=Path(__file__).parent/'ocr_transcriptions.json'
                    if len(clean(text))<80 and tp.exists():
                        item=json.loads(tp.read_text()).get(pdfmeta['sha256'])
                        if item:text=item['text'];r['date_evidence']+='; hash-matched OCR transcription'
        r['full_text']=clean(text)
        m=re.search(r'\bI,\s+([A-Za-z .]+?),\s*(?:Governor|as Governor)',r['full_text'],re.I)
        if m:r['governor']=clean(m[1]).title()
        if len(r['full_text'])<80:r['fetch_error']='No usable embedded text; OCR/manual review required'
        d,e=signed_date(text)
        if d and r['record_type'] not in ('news_release','drought_order'):
            if r['date_signed'] and d!=r['date_signed']:r['date_evidence']+='; signature differs from listing: '+r['date_signed']
            r['date_signed']=d;r['date_evidence']+='; PDF/legal signature: '+e
        return r
    except Exception as e:r['fetch_error']=str(e);return r

def enrich(records,predicate=lambda r:True):
    targets=[r for r in records if predicate(r)]
    with ThreadPoolExecutor(max_workers=6) as ex:list(ex.map(enrich_record,targets))
    return records

def write_csv(path,fields,rows):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n',extrasaction='ignore');w.writeheader();w.writerows({k:re.sub(r'[\x00-\x08\x0b-\x1f]', ' ', str(v)) for k,v in row.items()} for row in rows)

def decide(r):
    title=r['event_description']; text=r['full_text']; combined=title+' '+text
    if re.search(r'COVID|coronavirus|pandemic',text[:2500],re.I):return 'exclude','Source identifies COVID/public-health emergency'
    if re.search(r'Wildland Fire Management|Transfer of Funds.*Wildfire Emergency|Support Early Wildfire Response',title,re.I):return 'exclude','Recurring fire-management or funding mechanism without a distinct disaster event'
    if NONWEATHER.search(title):return 'exclude','Non-weather disaster, public health, administrative, or outside NOAA storm-event scope'
    if re.search(r'commission|task force|all.hazard|national flood insurance|asylum seekers|Ebola|workers.{0,3}right|housing tax|criminal justice|energy alliance|transportation of hemp|appointments|appropriation bills|budget|preparedness|prescribed or controlled fire|medical services week',title,re.I):return 'exclude','Administrative, public-health, preparedness, or ceremonial action'
    if re.search(r'\b(?:amend(?:s|ing)?|extend(?:s|ing)?|rescind(?:s|ing)?|renew(?:s|ing)?)\b',title,re.I) or MODIFIER.search(title) or (r['record_type']=='proclamation' and ORDINAL.match(title)):
        return 'companion','Amendment, extension, continuation, or supplementary action; not a separate event'
    if re.search(r'operating time|oversiz|overweight|exemption|transportation',title,re.I) or OPERATIONAL.search(title):return 'companion','Narrow operational relief; general declaration must be checked separately'
    if not WEATHER.search(title):return 'review' if re.search(r'emergency|disaster',title,re.I) else 'exclude','No event-specific weather declaration confirmed from title'
    if re.search(r'creat\w*|establish\w*|commission|task force|preparedness|all.hazard|national flood insurance|prevention|mitigation|conservation|resilien|firearm|fire fighter|firefighter',title,re.I):return 'exclude','Standing administrative/preparedness mechanism rather than identifiable disaster declaration'
    if not re.search(r'declar|proclam|emergency|disaster',title,re.I) and r['record_type']!='proclamation':return 'review','Weather reference does not establish a disaster declaration'
    if not valid_date(r['date_signed']):return 'review','Signing date unconfirmed or outside 2000-present'
    return 'include','Dated event-specific weather/disaster declaration'

def finalize(records,base):
    """Reviewed corrections are keyed to real records and never create records."""
    review_path=Path(base)/'review_decisions.json'
    reviews=json.loads(review_path.read_text()) if review_path.exists() else {}
    unique={}
    for r in records:
        if r['date_signed'] and r['date_signed']<'2000-01-01':continue
        key=r['declaration_id']
        if key not in unique or len(r['full_text'])>len(unique[key]['full_text']):unique[key]=r
    records=list(unique.values());rels=[];overrides=[]
    for r in records:
        r['decision'],r['reason']=decide(r)
        review=reviews.get(r['declaration_id'],{})
        for field in ['date_signed','date_evidence','governor','event_description','decision','reason']:
            if field in review:r[field]=review[field]
        if r['decision']=='include' and re.search(r'\bfires?\b',r['event_description'],re.I) and not re.search(r'wildfire|forest fire|brush fire',r['event_description'],re.I) and not review.get('hazard_category_override'):
            r['decision']='review';r['reason']='Bare Fire/Fires title requires a source-supported hazard override before joining.'
        if r['decision'] in ['include','override_exclude'] and not valid_date(r['date_signed']):r['decision']='review';r['reason']='Signing date unconfirmed or outside 2000-present'
        if review.get('hazard_category_override') and r['decision'] in ('include','override_exclude'):
            overrides.append(dict(declaration_id=r['declaration_id'],hazard_category_override=review['hazard_category_override'],review_note=review['reason'],source_url=review.get('source_url',r['archive_record_url'])))
        for rel in review.get('relationships',[]):
            rels.append(dict(source_order_id=r['declaration_id'],target_order_id=rel.get('target',''),relationship_type=rel.get('type','companion'),relationship_text=rel.get('evidence',r['reason']),source_url=review.get('source_url',r['archive_record_url']),target_status='present' if rel.get('target') in unique else 'not_found_in_collected_archive'))
        if r['decision']=='companion' and not review.get('relationships'):
            # Explicit citations are relationships, not inferred parent declarations.
            refs=[]
            for other in records:
                n=other['eo_number']
                if n and other['declaration_id']!=r['declaration_id'] and re.search(r'(?<![\w-])'+re.escape(n).replace(r'\-',r'[- ]+')+r'(?![\w-])',r['full_text'] or r['event_description']):refs.append(other)
            for other in refs:
                rels.append(dict(source_order_id=r['declaration_id'],target_order_id=other['declaration_id'],relationship_type='explicit_order_citation',relationship_text='Companion source explicitly cites this order number; citation does not by itself establish the primary declaration.',source_url=r['archive_record_url'],target_status='present'))
            if refs:continue
            rels.append(dict(source_order_id=r['declaration_id'],target_order_id='',relationship_type='companion_unresolved',relationship_text=r['reason'],source_url=r['archive_record_url'],target_status='unresolved_no_fabricated_target'))
    return sorted(records,key=lambda r:(r['date_signed'],r['declaration_id'])),rels,overrides

def run(collector,base):
    p=argparse.ArgumentParser();p.add_argument('--actions-out',required=True);p.add_argument('--relationships-out',required=True);p.add_argument('--join-out',required=True)
    a=p.parse_args();records,rels,overrides=finalize(collector(),base)
    joins=[r for r in records if r['decision'] in ('include','override_exclude')]
    if not records:raise RuntimeError('Archive parser produced no audit records; refusing empty success')
    write_csv(a.actions_out,ACTION_FIELDS,records);write_csv(a.relationships_out,REL_FIELDS,rels);write_csv(a.join_out,JOIN_FIELDS,joins)
    if overrides:write_csv(Path(a.join_out).parent/'hazard_overrides.csv',OVERRIDE_FIELDS,overrides)
    elif (Path(a.join_out).parent/'hazard_overrides.csv').exists():(Path(a.join_out).parent/'hazard_overrides.csv').unlink()
    print(json.dumps({'actions':len(records),'declarations':len(joins),'relationships':len(rels),'overrides':len(overrides),'review':sum(r['decision']=='review' for r in records)}))
