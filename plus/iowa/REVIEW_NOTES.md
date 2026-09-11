# Iowa (IA) — coverage and review

2024-present HSEMD proclamation tables; 2000-2023 not collected.

Source: [https://homelandsecurity.iowa.gov/disasters/governors-disaster-proclamations](https://homelandsecurity.iowa.gov/disasters/governors-disaster-proclamations). Direct official archive fetched and parsed. The linked legacy archive failed TLS validation; certificate checking was not disabled.

Verified included declaration dates: **2024-04-17 through 2026-07-24**. This span is not a claim of uninterrupted or complete coverage. Audit records with populated dates span 2024-01-08–2026-07-24. Collection completed September 10, 2026.

99 audit records; 54 included weather declarations; 0 dated out-of-state exclusions retained in the join CSV with `exclude` overrides; 1 unresolved records withheld; 25 relationship entries, including 25 unresolved or absent targets.

## Specific gaps

- The linked 2008-2023 legacy archive fails TLS certificate validation in this environment.
- 2000-2007 is not exposed by the collected tables; scanned signatures require OCR.

## Companion and mutual-aid checks

County-specific proclamations that independently declare emergencies are retained when the legal text does not amend an earlier order. Explicit extensions are companions. Several separate proclamations can therefore relate to one multi-county storm. The dataset grain is legal declaration, not unique meteorological event.

The complete relationship results are in [ia_order_relationships.csv](ia_order_relationships.csv). `explicit_order_citation` means the source cites that numbered order; it is not a claim that the cited order is necessarily the original declaration. An unresolved target means this collection could not establish the primary declaration, not that the state never issued one. Administrative amendments can also appear in this raw relationship ledger.

No dated out-of-state disaster declaration was identified for sidecar exclusion in this collected source set. This is bounded by the stated archive gaps.

## Every exclusion, unconfirmed date, and manual-review item

[excluded_and_review_records.csv](excluded_and_review_records.csv) lists every excluded, companion, unresolved, and out-of-state record with its actual citation and reason. The full audit CSV also retains source text and fetch errors. Empty signing dates remain empty in this audit; those rows cannot enter the join CSV. No unclassified declaration is silently passed to the classifier.

80 source PDFs have hash-matched OCR transcriptions included. OCR improves reproducibility but is not proof that every handwritten date is legible; unresolved dates remain withheld. A hash mismatch on a future download prevents reuse of the transcription.

## Every hazard override

None needed for the delivered declarations.
