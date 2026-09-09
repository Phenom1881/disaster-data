# Florida adapter review notes

## Coverage

- Runnable structured coverage: 2020-present from the Florida Governor's Executive Orders page.
- Deeper official archive: the Florida Department of State/State Library year indexes cover 1971-present at `https://edocs.dlis.state.fl.us/fldocs/governor/orders/`.
- Gap: many pre-2020 year pages provide only order numbers linked to scanned PDFs, without descriptive metadata. A safe weather backfill requires bulk PDF extraction plus OCR/manual review, so those years are explicitly not claimed by this adapter.

## Manual/PDF review

- `FL-EO-2024-156` and `FL-EO-2023-171` required PDF review because their archive titles say only Invest 97L/93L. Their own PDFs identify a tropical wave forecast to become a tropical depression and a system predicted to intensify into a tropical depression, respectively. Citable tropical overrides are included.
- `FL-EO-2022-253` is explicitly titled Subtropical Storm Nicole on the official archive and has a citable tropical override because the shared classifier does not use “subtropical” as a keyword.

## Items left unclassified

The following declarations/actions have no supported NCEI weather category and are intentionally not overridden: `FL-EO-2024-49` (Haiti crisis), `FL-EO-2023-208` (Israel war), `FL-EO-2023-03` (migration), `FL-EO-2021-148` (Surfside collapse), `FL-EO-2021-105` (Colonial Pipeline), `FL-EO-2021-82` (Eastport Terminal), and the COVID-19 actions `FL-EO-2021-102`, `FL-EO-2020-246`, `FL-EO-2020-223`, `FL-EO-2020-150`, `FL-EO-2020-149`, `FL-EO-2020-124`, `FL-EO-2020-97`, `FL-EO-2020-94`, `FL-EO-2020-90`, `FL-EO-2020-89`, `FL-EO-2020-88`, `FL-EO-2020-87`, `FL-EO-2020-86`, `FL-EO-2020-85`, `FL-EO-2020-83`, `FL-EO-2020-82`, `FL-EO-2020-80`, `FL-EO-2020-72`, `FL-EO-2020-71`, `FL-EO-2020-70`, `FL-EO-2020-69`, `FL-EO-2020-68`, and `FL-EO-2020-52`. Terminations `FL-EO-2020-209` and `FL-EO-2020-195` are excluded from the join.

## Companion declaration audit

No evacuation, curfew, or price-gouging-only order appears in the 2020-present archive title layer without its corresponding storm declaration. The archive includes the original declarations for Isaias, Sally, Eta, Elsa, Ian (originally Tropical Depression Nine), Nicole, Idalia (Invest 93L), the 2024 South Florida flooding, Debby (Invest 97L), Helene, and Milton. Extensions and amendments remain in the action and relationship files but are excluded from `declarations_for_join.csv`.
