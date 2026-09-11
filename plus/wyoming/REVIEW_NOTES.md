# Wyoming (WY) — coverage and review

2019-present Governor CMS executive-order archive; 2000-2018 backfill pending.

Source: [https://governor.wyo.gov/state-government/executive-orders](https://governor.wyo.gov/state-government/executive-orders). Governor page is a JavaScript shell. Its public CMS GraphQL API directly exposed archive content and official Google Drive document links; no proxy publisher used.

Verified included declaration dates: **2021-03-16 through 2025-08-24**. This span is not a claim of uninterrupted or complete coverage. Audit records with populated dates span 2019-07-22–2026-09-01. Collection completed September 10, 2026.

62 audit records; 4 included weather declarations; 0 dated out-of-state exclusions retained in the join CSV with `exclude` overrides; 5 unresolved records withheld; 19 relationship entries, including 13 unresolved or absent targets.

## Specific gaps

- Website is a JavaScript shell; its public CMS API supplies the real archive entries.
- Most linked Google Drive orders are scans; hash-matched OCR is included, and uncertain signatures remain excluded.

## Companion and mutual-aid checks

Order 2022-05 expressly replaces 2022-04, but 2022-04 is not among the collected archive entries. This is a concrete missing-primary declaration check for Yellowstone flooding, not a claim that no declaration existed. Livestock-feed waivers in 2021/2024/2026 likewise do not establish a general declaration for each event. Order 2024-13 mobilizes multiple agencies for documented 2024 wildfires and watershed impacts, so is broader than a carrier waiver. The Green River Tunnel crash order and Fort Laramie Canal collapse are excluded because their source does not establish a weather cause. The Dollar Lake Fire order signature was visually verified as August 24, 2025.

The complete relationship results are in [wy_order_relationships.csv](wy_order_relationships.csv). `explicit_order_citation` means the source cites that numbered order; it is not a claim that the cited order is necessarily the original declaration. An unresolved target means this collection could not establish the primary declaration, not that the state never issued one. Administrative amendments can also appear in this raw relationship ledger.

No dated out-of-state disaster declaration was identified for sidecar exclusion in this collected source set. This is bounded by the stated archive gaps.

## Every exclusion, unconfirmed date, and manual-review item

[excluded_and_review_records.csv](excluded_and_review_records.csv) lists every excluded, companion, unresolved, and out-of-state record with its actual citation and reason. The full audit CSV also retains source text and fetch errors. Empty signing dates remain empty in this audit; those rows cannot enter the join CSV. No unclassified declaration is silently passed to the classifier.

46 source PDFs have hash-matched OCR transcriptions included. OCR improves reproducibility but is not proof that every handwritten date is legible; unresolved dates remain withheld. A hash mismatch on a future download prevents reuse of the transcription.

## Every hazard override

- **WY-EO-2025-05: `fire`** — Legal order names lightning-caused Red Canyon and other active wildland fires; bare Fire requires override. [Source](https://drive.google.com/file/d/1Sfw3kuER7PLW922xQbppBdj_kQ1LjKrd/view).
- **WY-EO-2025-06: `fire`** — Signed order declares emergency for the Dollar Lake Fire in Sublette County; image resolves malformed OCR ordinal. [Source](https://drive.google.com/file/d/17dIMoUSoA_amplRTt5eZ1tcEpAcFwnlJ/view).
- **WY-EO-2024-13: `fire`** — Legal order mobilizes multiple state agencies for specific 2024 wildfires and subsequent watershed/road impacts; broader than a carrier waiver. [Source](https://drive.google.com/file/d/1_c1UigOQo_4SEGqJGXqvAKRcVko_W-Bv/view?usp=sharing).
- **WY-EO-2021-04: `winter`** — Legal order expressly identifies severe winter storm conditions; generic archive title needs winter override. [Source](https://drive.google.com/file/d/1Et80prkKGYKkVAmkevdBK6CZOyqrpNa-/view?usp=drive_link).
