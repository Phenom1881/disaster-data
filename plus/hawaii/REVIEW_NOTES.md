# Hawaii (HI) — coverage and review

Current Governor emergency proclamations plus partial 2014-2022 State Procurement mirror; verified joining coverage is narrower.

Source: [https://governor.hawaii.gov/category/newsroom/emergency-proclamations/](https://governor.hawaii.gov/category/newsroom/emergency-proclamations/). Direct official archive fetched and parsed. The State Procurement Office supplies an additional, partial historical official mirror.

Verified included declaration dates: **2023-07-18 through 2026-08-22**. This span is not a claim of uninterrupted or complete coverage. Audit records with populated dates span 2022-11-28–2026-08-22. Collection completed September 10, 2026.

225 audit records; 8 included weather declarations; 0 dated out-of-state exclusions retained in the join CSV with `exclude` overrides; 15 unresolved records withheld; 101 relationship entries, including 101 unresolved or absent targets.

## Specific gaps

- 2000-2013 is not supplied by these sources; the procurement mirror is partial and some historical PDF links fail.
- Posted dates are not substituted for unreadable signing dates. Scanned or malformed signature dates remain listed for review.

## Companion and mutual-aid checks

The archive labels the August 8, 2023 link Hurricane Dora, but the linked legal instrument is a wildfire proclamation signed by Acting Governor Sylvia Luke; its fire override uses the PDF as authority. Supplemental numbered proclamations remain companions; where the original is absent or undated, the ledger records an unresolved target. Mauna Loa and other seismic/volcanic disasters are retained for audit but excluded from this weather-classifier dataset. Red-flag Fire titles need fire overrides; Tropical Cyclones needs tropical.

The complete relationship results are in [hi_order_relationships.csv](hi_order_relationships.csv). `explicit_order_citation` means the source cites that numbered order; it is not a claim that the cited order is necessarily the original declaration. An unresolved target means this collection could not establish the primary declaration, not that the state never issued one. Administrative amendments can also appear in this raw relationship ledger.

No dated out-of-state disaster declaration was identified for sidecar exclusion in this collected source set. This is bounded by the stated archive gaps.

## Every exclusion, unconfirmed date, and manual-review item

[excluded_and_review_records.csv](excluded_and_review_records.csv) lists every excluded, companion, unresolved, and out-of-state record with its actual citation and reason. The full audit CSV also retains source text and fetch errors. Empty signing dates remain empty in this audit; those rows cannot enter the join CSV. No unclassified declaration is silently passed to the classifier.

19 source PDFs have hash-matched OCR transcriptions included. OCR improves reproducibility but is not proof that every handwritten date is legible; unresolved dates remain withheld. A hash mismatch on a future download prevents reuse of the transcription.

## Every hazard override

- **HI-PROC-8A2442F4F464D477: `tropical`** — Legal proclamation explicitly concerns August 2026 tropical cyclones; supplied classifier recognizes tropical storm/hurricane but not this exact wording. [Source](https://governor.hawaii.gov/wp-content/uploads/2026/08/2608087-ATG_Proclamation-Relating-to-August-2026-Tropical-Cyclones.pdf).
- **HI-PROC-90E4F2C2D09DF827: `fire`** — Legal proclamation identifies red-flag fire conditions; bare Fire requires override. [Source](https://governor.hawaii.gov/wp-content/uploads/2024/12/2412036_Proclamation-Relating-to-December-2024-Red-Flag-Fire-Conditions.pdf).
- **HI-PROC-C7BB430F897FB068: `fire`** — Legal proclamation identifies red-flag fire conditions; bare Fire requires override. [Source](https://governor.hawaii.gov/wp-content/uploads/2024/11/Proclamation-Relating-to-November-2024-Red-Flag-Fire-Conditions_encrypted_.pdf).
- **HI-PROC-0716FAFE28103EE1: `fire`** — Linked legal PDF is expressly a wildfire proclamation, despite Hurricane Dora archive heading; classify the legal subject. [Source](https://governor.hawaii.gov/wp-content/uploads/2023/08/2307199-1.pdf).
