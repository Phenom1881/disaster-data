# Alaska (AK) — coverage and review

Governor administrative orders plus Governor/DHSEM disaster-release proxies; no complete 2000-present signed proclamation archive verified.

Source: [https://gov.alaska.gov/administrative-orders/](https://gov.alaska.gov/administrative-orders/). Administrative-order archive directly fetchable. Disaster data relies on explicitly disclosed official Governor/DHSEM release proxies because a complete signed state proclamation archive was not verified.

Verified included declaration dates: **2019-08-23 through 2026-08-18**. This span is not a claim of uninterrupted or complete coverage. Audit records with populated dates span 2001-07-03–2026-09-09. Collection completed September 10, 2026.

553 audit records; 6 included weather declarations; 0 dated out-of-state exclusions retained in the join CSV with `exclude` overrides; 145 unresolved records withheld; 6 relationship entries, including 6 unresolved or absent targets.

## Specific gaps

- DHSEM Operations documents page supplies local declaration templates, not a complete signed state archive.
- Governor and DHSEM releases are proxies; only explicit same-day or explicitly stated issuance dates enter joins.
- Coverage before the earliest verified declaration is a gap, not evidence that Alaska had no disasters.

## Companion and mutual-aid checks

DHSEM publishes the October 2025 West Coast storm declaration announcement, but its publication date alone is not a confirmed signing date; it remains in review. A January Southeast winter release has a 2025 dateline and a 2026 title, describes an earlier January 6 declaration and a later expansion, and is withheld. Denali fires were declared yesterday in the June 26, 2025 release, establishing June 25. The September 5 flood release expressly states August 29 issuance. Chevak Public Safety Building fire is structural, not wildfire. Later expansions/assistance announcements are not silently substituted for missing signed originals.

The complete relationship results are in [ak_order_relationships.csv](ak_order_relationships.csv). `explicit_order_citation` means the source cites that numbered order; it is not a claim that the cited order is necessarily the original declaration. An unresolved target means this collection could not establish the primary declaration, not that the state never issued one. Administrative amendments can also appear in this raw relationship ledger.

No dated out-of-state disaster declaration was identified for sidecar exclusion in this collected source set. This is bounded by the stated archive gaps.

## Every exclusion, unconfirmed date, and manual-review item

[excluded_and_review_records.csv](excluded_and_review_records.csv) lists every excluded, companion, unresolved, and out-of-state record with its actual citation and reason. The full audit CSV also retains source text and fetch errors. Empty signing dates remain empty in this audit; those rows cannot enter the join CSV. No unclassified declaration is silently passed to the classifier.

1 source PDFs have hash-matched OCR transcriptions included. OCR improves reproducibility but is not proof that every handwritten date is legible; unresolved dates remain withheld. A hash mismatch on a future download prevents reuse of the transcription.

## Every hazard override

- **AK-PROC-A6D583FF9DAEC3EC: `fire`** — August 18, 2026 official release expressly says declaration issued today for Mukluk wildland fire. [Source](https://ready.alaska.gov/Documents/PIO/PressReleases/2026.08.19_Press%20Release%20-%20Governor%20Dunleavy%20Activates%20Disaster%20Assistance%20Programs%20for%20Mukluk%20Fire%20081826.pdf).
- **AK-PROC-357EC442FE5AD093: `flood`** — Explicit issuance date in official DHSEM release; late August flooding. [Source](https://ready.alaska.gov/Documents/PIO/PressReleases/2025.09.05_Press%20Release%20-2025%20Late%20August%20Storm%20Disaster%20Declaration%20and%20Recovery%20Assistance.pdf).
- **AK-PROC-A6A9E065F2B06307: `fire`** — Official release dates declaration to preceding day; Denali Borough wildland fires. [Source](https://ready.alaska.gov/Documents/PIO/PressReleases/2025.06.26_PRESS%20RELEASE%20-%20Governor%20Dunleavy%20Declares%202025%20Denali%20Borough%20Fires%20a%20Disaster%2062625.pdf).
