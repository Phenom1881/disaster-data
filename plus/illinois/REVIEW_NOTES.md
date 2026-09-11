# Illinois (IL) — coverage and review

2000-present numbered EO archive; separate disaster-proclamation listings yield weather records from 2023; earlier proclamation backfill remains pending.

Source: [https://www.illinois.gov/government/disaster-proclamations.html](https://www.illinois.gov/government/disaster-proclamations.html). Direct official archive fetched and parsed.

Verified included declaration dates: **2023-04-01 through 2026-08-18**. This span is not a claim of uninterrupted or complete coverage. Audit records with populated dates span 2003-06-11–2026-08-18. Collection completed September 10, 2026.

377 audit records; 7 included weather declarations; 0 dated out-of-state exclusions retained in the join CSV with `exclude` overrides; 7 unresolved records withheld; 16 relationship entries, including 8 unresolved or absent targets.

## Specific gaps

- Numbered executive orders are not a complete archive of gubernatorial disaster proclamations.
- The separate current disaster-proclamation page does not supply 2000-2022 weather declarations.

## Companion and mutual-aid checks

The July 24, 2023 proclamation repeats the June/July storm covered on July 11 and is recorded as a follow-up. Older numbered operational orders do not repair the missing historical proclamation archive. The audit includes school/transport/utility actions whose general declaration is not resolved.

The complete relationship results are in [il_order_relationships.csv](il_order_relationships.csv). `explicit_order_citation` means the source cites that numbered order; it is not a claim that the cited order is necessarily the original declaration. An unresolved target means this collection could not establish the primary declaration, not that the state never issued one. Administrative amendments can also appear in this raw relationship ledger.

No dated out-of-state disaster declaration was identified for sidecar exclusion in this collected source set. This is bounded by the stated archive gaps.

## Every exclusion, unconfirmed date, and manual-review item

[excluded_and_review_records.csv](excluded_and_review_records.csv) lists every excluded, companion, unresolved, and out-of-state record with its actual citation and reason. The full audit CSV also retains source text and fetch errors. Empty signing dates remain empty in this audit; those rows cannot enter the join CSV. No unclassified declaration is silently passed to the classifier.

7 source PDFs have hash-matched OCR transcriptions included. OCR improves reproducibility but is not proof that every handwritten date is legible; unresolved dates remain withheld. A hash mismatch on a future download prevents reuse of the transcription.

## Every hazard override

None needed for the delivered declarations.
