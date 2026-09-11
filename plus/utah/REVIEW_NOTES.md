# Utah (UT) — coverage and review

2000-present Office of Administrative Rules executive-document indexes and legal texts.

Source: [https://rules.utah.gov/publications/executive-documents/](https://rules.utah.gov/publications/executive-documents/). Direct official archive fetched and parsed.

Verified included declaration dates: **2000-06-28 through 2026-07-22**. This span is not a claim of uninterrupted or complete coverage. Audit records with populated dates span 2000-01-18–2026-08-18. Collection completed September 10, 2026.

557 audit records; 32 included weather declarations; 1 dated out-of-state exclusions retained in the join CSV with `exclude` overrides; 16 unresolved records withheld; 19 relationship entries, including 16 unresolved or absent targets.

## Specific gaps

- Repeated statewide fire-danger management orders are excluded rather than counted as separate fires.
- An explicitly dated current-index snapshot is a fallback only if live index discovery fails; it cannot discover newer records.

## Companion and mutual-aid checks

The 2005 Katrina evacuee declaration concerns an out-of-state hurricane and is sidecar-excluded. Repeated 2000-2003 statewide fire-danger orders are retained in the audit but excluded as recurring mobilization mechanisms, rather than treated as individual fires. Crop-loss order 2026-01 explicitly documents freezing temperatures and needs a winter override.

The complete relationship results are in [ut_order_relationships.csv](ut_order_relationships.csv). `explicit_order_citation` means the source cites that numbered order; it is not a claim that the cited order is necessarily the original declaration. An unresolved target means this collection could not establish the primary declaration, not that the state never issued one. Administrative amendments can also appear in this raw relationship ledger.

## Every exclusion, unconfirmed date, and manual-review item

[excluded_and_review_records.csv](excluded_and_review_records.csv) lists every excluded, companion, unresolved, and out-of-state record with its actual citation and reason. The full audit CSV also retains source text and fetch errors. Empty signing dates remain empty in this audit; those rows cannot enter the join CSV. No unclassified declaration is silently passed to the classifier.

37 source PDFs have hash-matched OCR transcriptions included. OCR improves reproducibility but is not proof that every handwritten date is legible; unresolved dates remain withheld. A hash mismatch on a future download prevents reuse of the transcription.

## Every hazard override

- **UT-EO-2026-04: `fire`** — Official order identifies fire emergency/active fire danger; bare Fire/Fires requires explicit override. [Source](https://rules.utah.gov/wp-content/uploads/Utah-Executive-Order-No.-2026-04.pdf).
- **UT-EO-2026-01: `winter`** — Order expressly documents freezing temperatures below 26F and crop losses on April 3, 4, 17 and 18. [Source](https://rules.utah.gov/wp-content/uploads/Utah-Executive-Order-No.-2026-01.pdf).
- **UT-EO-2025-08: `fire`** — Official order identifies fire emergency/active fire danger; bare Fire/Fires requires explicit override. [Source](https://rules.utah.gov/wp-content/uploads/Utah-Executive-Order-No.-2025-08.pdf).
- **UT-PROC-CE6DE5EA6C138884: `fire`** — Official order identifies fire emergency/active fire danger; bare Fire/Fires requires explicit override. [Source](https://rules.utah.gov/wp-content/uploads/ExecDoc129116.pdf).
- **UT-EO-2005-0017: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://rules.utah.gov/wp-content/uploads/ExecDoc103951.pdf).
