"""Collect Louisiana executive orders from the official State Register indexes."""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import time
import zipfile
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

CURRENT_URL = "https://www.doa.la.gov/doa/osr/executive-orders/"
ARCHIVE_URL = "https://www.doa.la.gov/doa/osr/archives/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DisasterDataPlusBot/1.0)"}
TIMEOUT = 90
ACTION_FIELDS = ("declaration_id","state","governor","eo_number","action_kind","action_type","event_description","date_signed","end_date","weather_related","source_scope","document_format","detail_url","archive_record_url")
REL_FIELDS = ("source_order_id","target_order_id","relationship_type","relationship_text","relationship_source","confidence")
JOIN_FIELDS = ("declaration_id","governor","eo_number","event_description","date_signed","archive_record_url")
NUMBER_RE = re.compile(r"\b(JML|JBE)\s*(\d{2,4})\s*[-–]\s*(\d{1,3})\b", re.I)
HAZARD_RE = re.compile(r"\b(hurricanes?|tropical storms?|tropical depressions?|severe storms?|tornado(?:es)?|flood(?:s|ing)?|heavy rain|winter weather|winter storms?|snow|ice|freeze|freezing|drought|wildfires?|extreme heat|heat-related|subsidence)\b", re.I)
MODIFIER_RE = re.compile(r"\b(renewal|renew(?:s|ed|ing)?|extend(?:s|ed|ing)?|extension|amend(?:s|ed|ing|ment)?|rescind(?:s|ed|ing)?|terminat(?:e|es|ed|ing|ion))\b", re.I)
OPERATIONAL_RE = re.compile(r"\b(evacuation|curfew|price gouging|leave with pay|suspension of|suspend\w*.{0,50}licens\w*|licensed bed capacity|elections?--rescheduled|waiver|office closings?)\b", re.I)
DATE_RE = re.compile(r"(?:on\s+)?(?:this\s+)?(\d{1,2})\s*(?:st|nd|rd|th)?\s+day\s+of\s+([A-Za-z]+)\s*,?\s*(2\s*0\s*\d\s*\d)", re.I)
HAZARD_OVERRIDES = {}  # Intentionally empty: titles/document text supply all hazard evidence.
TESSERACT = shutil.which("tesseract")   # installed by the Plus workflow's OCR step
# Why a declaration's document gave no date on this run, printed to the log.
# Before 2026-09-28 every failure here was swallowed, and ten parallel
# requests left weather declarations such as JML 24-89 undated every run.
DATE_PROBLEMS: Counter = Counter()

@dataclass(frozen=True)
class Action:
    number: str
    description: str
    url: str
    date: str = ""
    text: str = ""

    @property
    def stable_id(self):
        return "LA-EO-" + re.sub(r"[^A-Z0-9]+", "-", self.number.upper()).strip("-")

    @property
    def governor(self):
        return "Jeff Landry" if self.number.upper().startswith("JML") else "John Bel Edwards"

def get(url):
    for attempt in (1, 2):
        try:
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            return response
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(3)

def _docx_text(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))

def _ocr_text(blob, dpi=300):
    """Text of a scanned PDF's first and last two pages, read with the
    tesseract program. "" when tesseract is not installed."""
    if not TESSERACT:
        return ""
    try:
        import pypdfium2 as pdfium
        from PIL import ImageFilter
        document = pdfium.PdfDocument(blob)
        try:
            count = len(document)
            images = []
            for index in sorted({0, 1, count - 2, count - 1} & set(range(count))):
                page = document[index]
                try:
                    images.append(page.render(scale=dpi / 72, grayscale=True).to_pil().copy())
                finally:
                    page.close()
        finally:
            document.close()
    except Exception:
        return ""
    parts = []
    for image in images:
        buffer = io.BytesIO()
        image.convert("L").filter(ImageFilter.MedianFilter(3)).save(buffer, "PNG")
        try:
            result = subprocess.run([TESSERACT, "stdin", "stdout", "--psm", "3"], input=buffer.getvalue(),
                                    capture_output=True, timeout=120, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0:
            parts.append(result.stdout.decode("utf-8", "replace"))
    return " ".join(parts)

def _pdf_text(blob):
    try:
        import pdfplumber
    except ImportError:
        return ""
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        text = " ".join((page.extract_text() or "") for page in pdf.pages)
    if text.strip():
        return text
    DATE_PROBLEMS["scanned PDF, read with OCR" if TESSERACT else "scanned PDF, OCR not installed"] += 1
    return _ocr_text(blob)

def document_text(url):
    response = get(url)
    kind = response.headers.get("Content-Type", "").lower()
    if url.lower().endswith(".docx") or "wordprocessingml" in kind:
        return _docx_text(response.content)
    if url.lower().endswith(".pdf") or "pdf" in kind:
        return _pdf_text(response.content)
    return BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)

def extract_date(text):
    matches = DATE_RE.findall(text)
    if not matches:
        return ""
    day, month, year = matches[-1]; year = re.sub(r"\s+", "", year)
    try:
        return datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date().isoformat()
    except ValueError:
        return ""

def parse_index(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for anchor in soup.select("a[href]"):
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        match = NUMBER_RE.search(title)
        if not match:
            continue
        yy = match.group(2)[-2:]
        year = 2000 + int(yy)
        if year < 2000:
            continue
        number = f"{match.group(1).upper()} {yy}-{int(match.group(3)):02d}"
        description = title[match.end():].lstrip(" -–—") or title
        url = urljoin(base_url, anchor["href"])
        out[number] = Action(number, description, url)
    return list(out.values())

def classify(action):
    modifier = MODIFIER_RE.search(action.description)
    if modifier:
        word = modifier.group(0).lower()
        if word.startswith(("rescind", "terminat")):
            return "termination"
        if word.startswith(("renew", "extend")):
            return "extension"
        return "amendment"
    if OPERATIONAL_RE.search(action.description):
        return "administrative"
    if re.search(r"\b(state of (?:emergency|disaster)|disaster declaration|declaration of public health emergency)\b", action.description, re.I):
        prior_forward = re.search(r"\b(?:declared|declaration\s+of)\s+(?:a\s+)?state\s+of\s+(?:emergency|disaster).{0,240}\b(?:JML|JBE|Executive\s+Order(?:\s+Number|\s+No\.)?)\s*\d{2,4}\s*[-–]\s*\d+", action.text, re.I | re.S)
        prior_reverse = re.search(r"\bstate\s+of\s+(?:emergency|disaster)\s+was\s+declared\s+through\s+Executive\s+Order\s+(?:Number|No\.)?\s*(?:JML|JBE)\s*\d{2,4}\s*[-–]\s*\d+", action.text, re.I | re.S)
        if prior_forward or prior_reverse:
            return "extension"
        return "declaration"
    return "administrative"

def load_saved_dates(path):
    """Dates already found, by order number, so a document is read only
    until its date is known."""
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            return {row["eo_number"]: row["date_signed"] for row in csv.DictReader(handle)
                    if row.get("eo_number") and row.get("date_signed")}
    except (OSError, csv.Error, KeyError):
        return {}

def collect(saved_dates=None):
    saved_dates = saved_dates or {}
    indexed = {}
    for url in (ARCHIVE_URL, CURRENT_URL):
        for action in parse_index(get(url).text, url):
            indexed[action.number] = action
    def enrich(action):
        likely_relevant = re.search(r"\b(emergency|disaster|hurricane|storm|tornado|flood|weather|drought|fire|heat|subsidence)\b", action.description, re.I)
        is_document = re.search(r"\.(?:pdf|docx)(?:$|\?)", action.url, re.I)
        if not (likely_relevant and is_document):
            return Action(action.number, action.description, action.url, "", "")
        try:
            text = document_text(action.url)
        except (requests.RequestException, OSError, ValueError, zipfile.BadZipFile) as exc:
            # Keep the index record if an official document is temporarily unavailable.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            DATE_PROBLEMS[f"document not downloaded ({type(exc).__name__}{' ' + str(status) if status else ''})"] += 1
            text = ""
        date = extract_date(text)
        if not date and saved_dates.get(action.number):
            date = saved_dates[action.number]
            DATE_PROBLEMS["date kept from an earlier run"] += 1
        elif not date and text:
            DATE_PROBLEMS["read, but no signing date found"] += 1
        return Action(action.number, action.description, action.url, date, text)
    # Four at a time: ten parallel requests to the State Register left
    # documents undated run after run.
    with ThreadPoolExecutor(max_workers=4) as pool:
        enriched=list(pool.map(enrich,indexed.values()))
    return sorted(enriched, key=lambda item: (item.date, item.number), reverse=True)

def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)

def write_outputs(actions, actions_out, relationships_out, join_out):
    rows, relationships, joins = [], [], []
    for action in actions:
        kind = classify(action)
        evidence = f"{action.description} {action.text}"
        weather = kind == "declaration" and bool(HAZARD_RE.search(evidence))
        row = {"declaration_id":action.stable_id,"state":"LA","governor":action.governor,"eo_number":action.number,"action_kind":"emergency_declaration" if kind != "administrative" else "executive_order","action_type":kind,"event_description":action.description,"date_signed":action.date,"end_date":"","weather_related":str(weather).lower(),"source_scope":"louisiana_state_register_2016_present","document_format":action.url.rsplit(".",1)[-1].lower(),"detail_url":action.url,"archive_record_url":ARCHIVE_URL if action.number.upper().startswith("JBE") or action.number[4:6] in {"24","25"} else CURRENT_URL}
        rows.append(row)
        if kind in {"termination","extension","amendment"}:
            relation = {"termination":"terminates","extension":"extends","amendment":"amends"}[kind]
            for match in NUMBER_RE.finditer(evidence):
                target = f"{match.group(1).upper()} {match.group(2)[-2:]}-{int(match.group(3)):02d}"
                if target != action.number:
                    relationships.append({"source_order_id":action.stable_id,"target_order_id":"LA-EO-"+re.sub(r"[^A-Z0-9]+","-",target).strip("-"),"relationship_type":relation,"relationship_text":match.group(0),"relationship_source":action.url,"confidence":"high"})
        if weather and action.date:
            joins.append({field: row[field] for field in JOIN_FIELDS})
    relationships = list({(r["source_order_id"],r["target_order_id"],r["relationship_type"]):r for r in relationships}.values())
    write_csv(actions_out, ACTION_FIELDS, rows)
    write_csv(relationships_out, REL_FIELDS, relationships)
    write_csv(join_out, JOIN_FIELDS, joins)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actions-out", required=True); parser.add_argument("--relationships-out", required=True); parser.add_argument("--join-out", required=True)
    args = parser.parse_args()
    write_outputs(collect(load_saved_dates(args.actions_out)), args.actions_out, args.relationships_out, args.join_out)
    if DATE_PROBLEMS:
        print("Louisiana documents: " + "; ".join(f"{n} {why}" for why, n in DATE_PROBLEMS.most_common()))

if __name__ == "__main__":
    main()
