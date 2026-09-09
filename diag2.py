import csv, requests, io
import pdfplumber

with open("plus/indiana/in_emergency_actions_all.csv", newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

targets = ["22-15", "23-2", "23-3", "23-5", "23-6", "24-4", "24-7", "24-8", "26-03", "26-08", "12-01", "25-61"]

for eo in targets:
    row = next((r for r in rows if r.get("eo_number") == eo), None)
    if not row:
        print(f"{eo}: NOT FOUND in actions file")
        continue
    url = row["source_url"]
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        print(f"{eo}: {url} -> {len(text)} chars extracted")
    except Exception as e:
        print(f"{eo}: ERROR - {e}")
