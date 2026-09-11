# Idaho (ID) — coverage and review

2000-present OARC EO metadata plus IDWR drought orders; non-drought proclamations have incomplete coverage.

Source: [https://adminrules.idaho.gov/executive-orders/](https://adminrules.idaho.gov/executive-orders/). Direct official archive fetched and parsed.

Verified included declaration dates: **2000-06-28 through 2026-07-28**. This span is not a claim of uninterrupted or complete coverage. Audit records with populated dates span 2000-06-28–2026-07-28. Collection completed September 10, 2026.

412 audit records; 208 included weather declarations; 0 dated out-of-state exclusions retained in the join CSV with `exclude` overrides; 6 unresolved records withheld; 21 relationship entries, including 13 unresolved or absent targets.

## Specific gaps

- Numbered EOs do not comprehensively contain disaster proclamations. Governor-approved IDWR drought orders provide the historical disaster records.
- IDWR Date Declared is used for historical orders; detected conflicts with a readable Governor approval clause are withheld.
- Other disaster proclamations are limited to individually verified Governor/IOEM releases.

## Companion and mutual-aid checks

Numbered disaster-account transfers are funding mechanisms, not substitutes for missing proclamations. The 2010 IOEM flood release explicitly confirms Acting Governor Bob Geddes signed that day. The July 29, 2026 fire release says the Governor signed Tuesday, confirming July 28. California wildfire EMAC assistance is identified but no signed Idaho declaration/date was confirmed; it is not joined. Governor-approved IDWR drought orders are distinct county/state legal actions, not invented EOs.

The complete relationship results are in [id_order_relationships.csv](id_order_relationships.csv). `explicit_order_citation` means the source cites that numbered order; it is not a claim that the cited order is necessarily the original declaration. An unresolved target means this collection could not establish the primary declaration, not that the state never issued one. Administrative amendments can also appear in this raw relationship ledger.

No dated out-of-state disaster declaration was identified for sidecar exclusion in this collected source set. This is bounded by the stated archive gaps.

## Every exclusion, unconfirmed date, and manual-review item

[excluded_and_review_records.csv](excluded_and_review_records.csv) lists every excluded, companion, unresolved, and out-of-state record with its actual citation and reason. The full audit CSV also retains source text and fetch errors. Empty signing dates remain empty in this audit; those rows cannot enter the join CSV. No unclassified declaration is silently passed to the classifier.

## Every hazard override

- **ID-PROC-7D424679AB1F18C1: `fire`** — Official release explicitly dates signing to Tuesday preceding Wednesday July 29, 2026; Big Grass/Turner fires. [Source](https://gov.idaho.gov/pressrelease/gov-little-declares-fire-disaster-emergency-in-parts-of-idaho-deploys-idaho-national-guard-to-big-grass-fire-in-owyhee-county/).
