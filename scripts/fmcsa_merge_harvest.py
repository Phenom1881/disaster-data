#!/usr/bin/env python3
"""Merge a hand-run FMCSA harvest into plus/_fmcsa/entries.csv.

FMCSA refuses GitHub's servers, so the weekly refresh can never read its
archive pages; it keeps the saved entries instead (scripts/plus_fmcsa.py).
New entries come from a harvest run outside GitHub, saved as one TSV per
archive page:

    <harvest dir>/fy17.tsv, 2018.tsv ... 2026.tsv
        STATE <tab> LINK TEXT <tab> LINK URL <tab> EFFECTIVE (MM/DD/YYYY or NONE)

and, optionally, the hazard sentence read from each declaration's own page:

    <harvest dir>/hazard.tsv
        LINK URL <tab> SENTENCE (or NONE)

Rows are cleaned the same way parse_archive_page() would clean them: the
state is taken from the title when the title names one, relative links are
made absolute, and links outside /emergency/ are skipped. Saved entries are
never removed, and a saved hazard sentence is kept unless the harvest has a
new one.

    python scripts/fmcsa_merge_harvest.py <harvest dir>
"""
import importlib.util
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("plus_fmcsa", HERE / "plus_fmcsa.py")
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)

PAGE_BASE = "https://www.fmcsa.dot.gov/emergency/archive-emergency-declarations-"


def page_for(stem: str) -> tuple[int, str]:
    if stem == "fy17":
        return 2017, PAGE_BASE + "fy17"
    return int(stem), PAGE_BASE + stem


def harvested(folder: Path) -> tuple[dict, list]:
    entries, skipped = {}, []
    for path in sorted(folder.glob("*.tsv")):
        if path.stem == "hazard":
            continue
        year, page = page_for(path.stem)
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) != 4:
                continue
            state_label, title, url, effective = (p.strip() for p in parts)
            title = pf._clean(title)
            url = url.strip("<>").strip()
            if not url or url == "NONE":
                skipped.append((path.name, title, "no link"))
                continue
            path_part = urlparse(urljoin("https://www.fmcsa.dot.gov/", url)).path
            if "/emergency/" not in path_part:
                skipped.append((path.name, title, "not an /emergency/ page"))
                continue
            url = "https://www.fmcsa.dot.gov" + path_part
            named = pf.STATE_RE.match(title)
            label = named.group(1) if named else state_label
            state = next((s for s in pf.STATES if s.lower() == label.lower()), None)
            if not state:
                skipped.append((path.name, title, "no state: " + state_label))
                continue
            eff = pf.parse_effective("Effective: " + effective, year) if effective != "NONE" else ""
            entries[url] = {"entry_id": pf.entry_id(url), "state": state, "title": title,
                            "effective": eff, "url": url, "hazard_text": "", "archive_page": page}
    return entries, skipped


def hazard_sentences(folder: Path) -> dict:
    path = folder / "hazard.tsv"
    found = {}
    if not path.exists():
        return found
    for line in path.read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        url, sentence = (p.strip() for p in line.split("\t", 1))
        sentence = pf._clean(sentence)
        # Same test hazard_sentence() applies to a page it reads itself.
        if sentence != "NONE" and pf.hazard_types(sentence) and not pf.NOT_WEATHER_RE.search(sentence):
            found["https://www.fmcsa.dot.gov" + urlparse(url).path] = sentence
    return found


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    folder = Path(sys.argv[1])
    target = HERE.parent / "plus" / "_fmcsa" / "entries.csv"
    saved = pf.load_entries(target)
    new, skipped = harvested(folder)
    sentences = hazard_sentences(folder)
    merged = dict(saved)
    added = 0
    for url, entry in new.items():
        old = merged.get(url)
        if old:
            entry["hazard_text"] = old.get("hazard_text", "")
            entry["effective"] = entry["effective"] or old.get("effective", "")
        else:
            added += 1
        merged[url] = entry
    for url, sentence in sentences.items():
        if url in merged:
            merged[url]["hazard_text"] = sentence
    rows = sorted(merged.values(), key=lambda e: (e["state"], e["effective"], e["url"]))
    pf.write_csv(target, pf.ENTRY_FIELDS, rows)
    print(f"{len(new)} harvested, {added} new, {len(rows)} saved in all, "
          f"{sum(1 for r in rows if r['hazard_text'])} with a hazard sentence")
    for name, title, why in skipped:
        print(f"  skipped ({why}) {name}: {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
