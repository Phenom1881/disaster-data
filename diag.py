import sys
sys.path.insert(0, "plus/indiana")
from in_eo_scraper import DATE_RE
import requests
import csv

with open("plus/indiana/in_emergency_actions_all.csv", newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

target = next(r for r in rows if r.get("eo_number") == "24-6")
print("Testing EO:", target["eo_number"], "-", target["title"])
pdf_url = target["source_url"]
print("PDF URL:", pdf_url)

session = requests.Session()
resp = session.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
print("HTTP status:", resp.status_code)
print("Content-Type:", resp.headers.get("Content-Type"))
print("Content length:", len(resp.content))

import pdfplumber, io
with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
    text = "\n".join((page.extract_text() or "") for page in pdf.pages)

print("Extracted text length:", len(text))
print("Last 500 chars of extracted text:")
print(repr(text[-500:]))
print()
print("DATE_RE matches found:", DATE_RE.findall(text))
