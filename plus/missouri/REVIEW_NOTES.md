# Missouri (MO) — coverage and review

2000-present Secretary of State year indexes and legal order text.

Source: [https://www.sos.mo.gov/library/reference/orders/default](https://www.sos.mo.gov/library/reference/orders/default). Direct official archive fetched and parsed.

Verified included declaration dates: **2000-03-10 through 2026-07-10**. This span is not a claim of uninterrupted or complete coverage. Audit records with populated dates span 2000-01-20–2026-08-25. Collection completed September 10, 2026.

619 audit records; 68 included weather declarations; 15 dated out-of-state exclusions retained in the join CSV with `exclude` overrides; 49 unresolved records withheld; 215 relationship entries, including 50 unresolved or absent targets.

## Specific gaps

- Operational waivers are retained separately; unresolved primary declarations are listed in the relationship ledger.
- Some source descriptions or dates need manual reconciliation; exclusions and unresolved records are individually listed.

## Companion and mutual-aid checks

The January 11, 2017 EOC activation (17-05) precedes the January 12 formal emergency (17-06). Order 22-09 explicitly continues 22-08; 12-07 extends 12-06. Interstate/evacuee orders, including Arkansas assistance (00-22), are excluded through the sidecar. Many transport waivers still have no confirmed primary declaration in the collected record set.

The complete relationship results are in [mo_order_relationships.csv](mo_order_relationships.csv). `explicit_order_citation` means the source cites that numbered order; it is not a claim that the cited order is necessarily the original declaration. An unresolved target means this collection could not establish the primary declaration, not that the state never issued one. Administrative amendments can also appear in this raw relationship ledger.

## Every exclusion, unconfirmed date, and manual-review item

[excluded_and_review_records.csv](excluded_and_review_records.csv) lists every excluded, companion, unresolved, and out-of-state record with its actual citation and reason. The full audit CSV also retains source text and fetch errors. Empty signing dates remain empty in this audit; those rows cannot enter the join CSV. No unclassified declaration is silently passed to the classifier.

## Every hazard override

- **MO-EO-00-22: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2000/eo00_022).
- **MO-EO-04-17: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2004/eo04_017).
- **MO-EO-04-19: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2004/eo04_019).
- **MO-EO-05-24: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_024).
- **MO-EO-05-25: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_025).
- **MO-EO-05-26: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_026).
- **MO-EO-05-28: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_028).
- **MO-EO-05-29: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_029).
- **MO-EO-05-32: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_032).
- **MO-EO-05-34: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_034).
- **MO-EO-05-35: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_035).
- **MO-EO-05-38: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2005/eo05_038).
- **MO-EO-08-27: `exclude`** — SOS description explicitly activates interstate assistance compact for another state; no corresponding Missouri weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2008/eo08_027).
- **MO-EO-17-22: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2017/eo22).
- **MO-EO-24-03: `exclude`** — Out-of-state disaster assistance/evacuee support explicitly identified by source; no matching in-state weather event. [Source](https://www.sos.mo.gov/library/reference/orders/2024/eo3).
