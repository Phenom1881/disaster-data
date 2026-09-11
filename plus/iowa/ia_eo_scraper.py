"""Iowa HSEMD's complete current and 2024-2025 proclamation tables."""
from pathlib import Path
import re
from urllib.parse import urljoin
from _adapter_support import *
ARCHIVE='https://homelandsecurity.iowa.gov/disasters/governors-disaster-proclamations'
OLD='https://homelandsecurity.iowa.gov/archive-governors-disaster-proclamations'
def parse_archive(content,url=ARCHIVE):
    out=[]
    for row in soup(content).select('table tr'):
        cells=row.find_all('td')
        if len(cells)<3:continue
        number=clean(cells[1].text);m=re.fullmatch(r'(20\d{2})-\d+',number)
        if not m:continue
        for el in cells[2].select('.link__details'):el.decompose()
        a=cells[2].find('a',href=True);rawdate=clean(cells[0].text)
        d=exact_date(rawdate+'/'+m[1]) if rawdate.count('/')==1 else exact_date(rawdate)
        r=make_record('IA',clean(cells[2].text),urljoin(url,a['href']) if a else url,number=number,signed=d,governor='Kim Reynolds',listing=url,kind='proclamation',evidence='HSEMD proclamation Date column '+rawdate+'; year from Proc# '+number)
        r['declaration_id']='IA-PROC-'+number
        out.append(r)
    return out

def collect():
    out=parse_archive(html(ARCHIVE),ARCHIVE)+parse_archive(html(OLD),OLD)
    enrich(out)
    return out
if __name__=='__main__':run(collect,Path(__file__).parent)
