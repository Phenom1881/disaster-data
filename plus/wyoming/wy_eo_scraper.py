"""Wyoming Governor's public CMS archive, including every listed EO."""
from pathlib import Path
import re,json
from urllib.parse import urljoin
from _adapter_support import *
ARCHIVE='https://governor.wyo.gov/state-government/executive-orders'
API='https://governor.wyo.gov/api/cms/graphql'
QUERY='query($path:String!){page(where:{path_ends_with:$path},orderBy:{publishedUtc:DESC}){displayText render parentRoute path}}'
def parse_archive(content,url=ARCHIVE):
    out=[]
    for a in soup(content).select('a[href]'):
        p=a.find_parent(['p','li']);m=re.search(r'^(20\d{2})[-–](\d+)\b',clean(p.text if p else a.text))
        if not m:continue
        p=a.find_parent(['p','li']);title=clean(p.text if p else a.text)
        title=re.sub(r'^20\d{2}[-–]\d+\s*','',title)
        r=make_record('WY',title,urljoin(url,a['href']),number=m[1]+'-'+m[2].zfill(2),governor='Mark Gordon',listing=url)
        if 'reissued version' in title:r['declaration_id']+='-REISSUED'
        out.append(r)
    return out

def collect():
    data=json.loads(fetch(API,payload={'query':QUERY,'variables':{'path':'executive-orders'}})[0])
    if data.get('errors'):raise RuntimeError(str(data['errors']))
    out=[]
    for page in data['data']['page']:out.extend(parse_archive(page['render']))
    enrich(out)
    return out
if __name__=='__main__':run(collect,Path(__file__).parent)
