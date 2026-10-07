# Plus health report

Checked 2026-10-07 02:25 UTC after the refresh. **32 green, 18 yellow, 0 red.**

## Yellow: working with gaps (18)

| State | Declarations | Why |
|---|---:|---|
| Alaska (AK) | 9 | Only 9 declarations against 95 federal ones (uneven coverage), so the source is likely missing most of the record. |
| Arizona (AZ) | 59 | The source left out 53 of 59 saved records; they are shown from earlier runs. |
| Delaware (DE) | 2 | Only 2 declarations against 26 federal ones (since 2025), so the source is likely missing most of the record. |
| Illinois (IL) | 7 | Only 7 declarations against 68 federal ones (since 2000), so the source is likely missing most of the record. |
| Indiana (IN) | 21 | The source left out 5 of 21 saved records; they are shown from earlier runs. 3 of 21 declarations have no signing date. |
| Kansas (KS) | 53 | Collection failed or produced no declarations on 1 of the 3 runs before this one. |
| Maine (ME) | 4 | Only 4 declarations against 71 federal ones (since 2011), so the source is likely missing most of the record. |
| Massachusetts (MA) | 8 | Only 8 declarations against 59 federal ones (since 1970), so the source is likely missing most of the record. |
| Mississippi (MS) | 52 | The source left out 16 of 52 saved records; they are shown from earlier runs. |
| Nevada (NV) | 9 | Only 9 declarations against 116 federal ones (since 2023), so the source is likely missing most of the record. |
| New Hampshire (NH) | 12 | Collecting from the state source produced no declarations on this run and on the retry, 12 runs in a row. The page is showing records saved from earlier runs. No successful collection is on record, and collection has failed since at least 2026-09-27. This turns red at four weeks. |
| Ohio (OH) | 7 | Collecting from the state source produced no declarations on this run and on the retry, 12 runs in a row. The page is showing records saved from earlier runs. No successful collection is on record, and collection has failed since at least 2026-09-27. This turns red at four weeks. Only 7 declarations against 61 federal ones (uneven coverage), so the source is likely missing most of the record. |
| Oklahoma (OK) | 55 | The source left out 48 of 55 saved records; they are shown from earlier runs. |
| Oregon (OR) | 252 | Collecting from the state source failed on this run and on the retry (Oregon adapter: scrape failed (requests.exceptions.HTTPError: 503 Server Error: Service Unavailable for url: https://www.oregon.gov/gov/_...). The page is showing records saved from earlier runs; the last successful collection was 2026-10-06 (0 days ago). This turns red at four weeks. 82 of 252 declarations have no signing date. |
| Rhode Island (RI) | 8 | Only 8 declarations against 31 federal ones (since 2015), so the source is likely missing most of the record. |
| Vermont (VT) | 6 | The source left out 4 of 6 saved records; they are shown from earlier runs. Only 6 declarations against 62 federal ones (since 2017), so the source is likely missing most of the record. |
| Wisconsin (WI) | 18 | Collection failed or produced no declarations on 1 of the 3 runs before this one. |
| Wyoming (WY) | 4 | Only 4 declarations against 45 federal ones (since 2019), so the source is likely missing most of the record. |

## Green (32)

AL, AR, CA, CO, CT, FL, GA, HI, ID, IA, KY, LA, MD, MI, MN, MO, MT, NE, NJ, NM, NY, NC, ND, PA, SC, SD, TN, TX, UT, VA, WA, WV

## Where the time went

Collecting from state sources took 53.5 min in all, and matching storms took 1.7 min. The 10 slowest states:

| State | Collecting | Matching storms |
|---|---:|---:|
| MS | 8.0 min | 1 s |
| NJ | 7.2 min | 11 s |
| NC | 7.3 min | 1 s |
| MA | 4.7 min | 2 s |
| TX | 4.0 min | 1 s |
| CT | 3.7 min | 0 s |
| NY | 2.0 min | 0 s |
| SC | 1.8 min | 5 s |
| VT | 1.7 min | 0 s |
| PA | 1.4 min | 0 s |

## Every state

| State | Grade | Source this run | Failed runs in a row | Declarations | Federal | Dated | Titled | Linked | Storm matched | Notes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| AL | green | returned everything | 0 | 30 | 102 | 30 | 30 | 30 | 29 |  |
| AK | yellow | returned everything | 0 | 9 | 95 | 9 | 9 | 9 | 4 |  |
| AZ | yellow | returned part | 0 | 59 | 120 | 59 | 59 | 59 | 50 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| AR | green | returned everything | 0 | 10 | 89 | 10 | 10 | 10 | 8 |  |
| CA | green | returned everything | 0 | 47 | 397 | 47 | 47 | 47 | 43 |  |
| CO | green | returned everything | 0 | 120 | 112 | 120 | 120 | 120 | 94 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| CT | green | returned everything | 0 | 14 | 43 | 14 | 14 | 14 | 14 |  |
| DE | yellow | returned everything | 0 | 2 | 26 | 2 | 2 | 2 | 2 |  |
| FL | green | returned everything | 0 | 25 | 188 | 25 | 25 | 25 | 22 |  |
| GA | green | returned everything | 0 | 32 | 81 | 32 | 32 | 32 | 31 |  |
| HI | green | returned everything | 0 | 11 | 75 | 11 | 11 | 11 | 8 |  |
| ID | green | returned everything | 0 | 208 | 61 | 208 | 208 | 208 | 14 | 206 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| IL | yellow | returned everything | 0 | 7 | 68 | 7 | 7 | 7 | 5 |  |
| IN | yellow | returned part | 0 | 21 | 56 | 18 | 21 | 21 | 12 |  |
| IA | green | returned everything | 0 | 54 | 79 | 54 | 54 | 54 | 46 |  |
| KS | yellow | returned part | 0 | 53 | 96 | 53 | 53 | 53 | 45 | The source left out 1 saved record(s); shown from earlier runs. 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| KY | green | returned part | 0 | 13 | 99 | 13 | 13 | 13 | 11 | The source left out 1 saved record(s); shown from earlier runs. |
| LA | green | returned everything | 0 | 26 | 111 | 26 | 26 | 26 | 21 |  |
| ME | yellow | returned everything | 0 | 4 | 71 | 4 | 4 | 4 | 4 |  |
| MD | green | returned everything | 0 | 11 | 38 | 11 | 11 | 11 | 11 |  |
| MA | yellow | returned everything | 0 | 8 | 59 | 8 | 8 | 8 | 7 |  |
| MI | green | returned everything | 0 | 23 | 46 | 23 | 23 | 23 | 17 |  |
| MN | green | returned everything | 0 | 15 | 81 | 15 | 15 | 15 | 14 |  |
| MS | yellow | returned part | 0 | 52 | 99 | 52 | 52 | 52 | 48 |  |
| MO | green | returned everything | 0 | 83 | 88 | 83 | 83 | 83 | 62 | 5 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| MT | green | returned part | 0 | 19 | 113 | 19 | 19 | 19 | 14 | The source left out 1 saved record(s); shown from earlier runs. 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NE | green | returned part | 0 | 60 | 88 | 60 | 60 | 60 | 16 | The source left out 2 saved record(s); shown from earlier runs. 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NV | yellow | returned everything | 0 | 9 | 116 | 9 | 9 | 9 | 6 |  |
| NH | yellow | no declarations | 12 | 12 | 63 | 12 | 12 | 12 | 9 |  |
| NJ | green | returned everything | 0 | 151 | 59 | 151 | 151 | 151 | 95 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NM | green | returned everything | 0 | 45 | 126 | 45 | 45 | 45 | 23 |  |
| NY | green | returned everything | 0 | 25 | 118 | 25 | 25 | 25 | 22 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NC | green | returned everything | 0 | 34 | 85 | 34 | 34 | 34 | 32 |  |
| ND | green | returned everything | 0 | 34 | 76 | 34 | 34 | 34 | 18 | 7 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| OH | yellow | no declarations | 12 | 7 | 61 | 7 | 7 | 7 | 3 |  |
| OK | yellow | returned part | 0 | 55 | 259 | 55 | 55 | 55 | 53 | 6 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| OR | yellow | failed | 1 | 252 | 174 | 170 | 252 | 252 | 76 | 64 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| PA | green | returned everything | 0 | 10 | 64 | 10 | 10 | 10 | 10 |  |
| RI | yellow | returned everything | 0 | 8 | 31 | 8 | 8 | 8 | 8 |  |
| SC | green | returned everything | 0 | 50 | 51 | 50 | 50 | 50 | 37 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| SD | green | returned everything | 0 | 25 | 98 | 25 | 25 | 25 | 16 | 4 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| TN | green | returned everything | 0 | 14 | 97 | 14 | 14 | 14 | 9 |  |
| TX | green | returned part | 0 | 59 | 392 | 59 | 59 | 59 | 57 | The source left out 1 saved record(s); shown from earlier runs. 14 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| UT | green | returned everything | 0 | 33 | 61 | 33 | 33 | 33 | 20 | 11 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| VT | yellow | returned part | 0 | 6 | 62 | 6 | 6 | 6 | 5 |  |
| VA | green | returned everything | 0 | 75 | 77 | 75 | 75 | 74 | 65 | 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| WA | green | returned everything | 0 | 39 | 223 | 39 | 39 | 39 | 24 |  |
| WV | green | returned part | 0 | 18 | 85 | 18 | 18 | 18 | 12 | The source left out 1 saved record(s); shown from earlier runs. |
| WI | yellow | returned everything | 0 | 18 | 56 | 18 | 18 | 18 | 15 |  |
| WY | yellow | returned everything | 0 | 4 | 45 | 4 | 4 | 4 | 4 |  |

<details><summary>How grades are set</summary>

How grades are set

Red, needs attention now:
- collecting from the state source failed or produced no declarations, on this run and on the retry, and the last successful collection was 4 weeks ago or more (or no records are saved to show)
- no declarations on the page
- fewer than half the declarations have a signing date, so the rest cannot be matched to storms
- declarations fell by more than a fifth since the last run
- the page was not rebuilt on this run

Yellow, working with gaps:
- collecting failed or produced no declarations on this run and on the retry, but the page shows records saved from a successful collection less than 4 weeks ago
- collection failed or produced no declarations on another of the last 4 runs
- the source left out more than a tenth of the saved records, which are shown from earlier runs
- fewer than 10 declarations, which usually means the source only covers recent years
- more than a tenth of the declarations have no signing date, title or working link
- fewer than a quarter of the dated declarations matched any storm record
- declarations fell since the last run

Green: none of the above.

</details>
