# South Carolina adapter review notes

## Coverage

- Structured official coverage: 1966-present from the South Carolina State Library Executive Orders collection, enriched with the Governor's 2017-present descriptions.
- The collection starts on 1966-02-01. Some early records have no printed order number; they use a stable date/UUID identifier while leaving `eo_number` blank.

## Manual/PDF review and ambiguities

No OCR was required. `SC-EO-2025-33` needed a citable override because “Tropical Disturbance Invest 94L” is direct official hazard language but is not one of the shared classifier's literal tropical keywords.

The following emergency declarations are intentionally unclassified because they are non-weather: `SC-EO-2020-08` (COVID-19), `SC-EO-2006-06` (industrial mill fire), `SC-ACTION-1986-12-16-757ecd06` (boiler explosion), `SC-ACTION-1984-04-30-a6a0ed7a` (law-enforcement emergency), and `SC-ACTION-1975-10-22-29e9c849` (Florence civil emergency). Early records without an abstract remain in the action inventory and are not promoted to declarations.

## Companion declaration audit

Found original declarations for the principal narrow storm companions: Debby (`SC-EO-2024-16`/`17`), Helene (`SC-EO-2024-24`), Idalia (`SC-EO-2023-29`), Ian (`SC-EO-2022-28`), Dorian (`SC-EO-2019-26`), Irma (`SC-EO-2017-20`), and the 1999 Floyd emergency (unnumbered State Library record dated 1999-09-14). Their leave, evacuation, bank-holiday, transportation, and rescission orders are excluded from the join.

The archive contains narrow weather leave/closure actions for which no distinct statewide declaration for the same event was found: severe weather on 2026-03-17; 2025-06-03 and 2025-03-12; winter weather on 2025-02-26, 2025-02-06, and 2025-01-17; Orangeburg flooding on 2025-01-17; Potential Tropical Cyclone Eight on 2024-09-24; severe weather on 2024-02-16, 2024-01-29, and 2024-01-11; Tropical Storm Nicole on 2022-11-23; severe weather on 2022-04-11; winter weather on 2022-01-25 and 2022-01-19; severe weather on 2021-03-26; Tropical Storm Zeta on 2020-11-09; Hurricane Isaias leave on 2020-08-26 (the archive's `SC-EO-2020-49` is a transportation waiver, not a general declaration); April 2020 tornado leave; and winter/severe-weather leave on 2020-04-06 and 2020-02-19. These narrow actions remain in the action inventory and are not treated as substitute declarations.

## 2026-10-16: declarations the classifier missed

Eleven weather declarations in the saved records never reached the join file, three of them listed above as found.

- **Descriptions read as link labels.** The Governor's page labels each PDF link "Official (PDF)" or "Text Alternative (PDF)". For 2017 to 2019 orders the scraper read that label as the description, so Irma (`SC-EO-2017-20`), Florence (`SC-EO-2018-26`) and Dorian (`SC-EO-2019-26`) were classed as administrative. When the text after a link is only a label, the description now comes from the PDF's file name, such as "2017-20-Declaring-State-of-Emergency-to-Prepare-for-Hurricane-Irma.pdf".
- **Titles that are the declaration.** "State of Emergency Due to Severe Winter Weather" and "Declare State of Emergency to Address Flooding" name no verb the classifier knew. A description that begins "State of Emergency" is now a declaration, as is "Declare". This adds `SC-EO-2020-24` (severe weather, April 13, 2020), `SC-EO-2022-04` and `SC-EO-2022-06` (the January 2022 winter storms), `SC-EO-2024-33` (flooding, November 2024), `SC-EO-2025-10` and `SC-EO-2025-14` (wildfires, March 2025), and `SC-EO-2018-42` and `SC-EO-2018-48` (Florence's aftermath, then Michael). The April 2020 and January 2022 leave actions listed above therefore do have statewide declarations.
- **Declarations made again.** A South Carolina state of emergency lasts 15 days unless declared again, so a long emergency can have more than one declaration, such as `SC-EO-2018-26` and `SC-EO-2018-42` for Florence. Each is listed, as `SC-EO-2024-16` and `SC-EO-2024-17` for Debby already were.
- **Abstracts.** From April 2014 on, the saved records show only a bare title, such as "Executive order no. 2016-26", so none of Haley's later orders could be classified. The State Library's page for that order shows its summary as an Abstract: it "declares that a State of Emergency exists in South Carolina" for Hurricane Matthew. The scraper read only `dc.description`, and it now also reads `dc.description.abstract` when `dc.description` is empty. If that is where the State Library keeps these summaries, Matthew (`SC-EO-2016-26`) and Joaquin (`SC-EO-2015-21`) reach the join on the next refresh; if they stay off, the summaries are under another field.
- **Orders the State Library has not catalogued.** `SC-EO-2025-02` ("Declaring a State of Emergency to Address Winter Weather", January 2025) is on the Governor's page but not in the State Library collection, and `SC-EO-2026-01` is missing from it too. Orders on the Governor's page with a dated file name are now added from it.
- The subject added to a description that names no hazard is now set in parentheses instead of after a dash.
