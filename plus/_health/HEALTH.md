# Plus health report

Checked 2026-11-20 14:58 UTC after the refresh. **44 green, 6 yellow, 0 red.**

## Yellow: working with gaps (6)

| State | Declarations | Why |
|---|---:|---|
| Colorado (CO) | 116 | The source left out 22 of 116 saved records; they are shown from earlier runs. |
| Florida (FL) | 63 | Collection failed or produced no declarations on 1 of the 3 runs before this one. |
| Kansas (KS) | 81 | The source left out 12 of 81 saved records; they are shown from earlier runs. |
| Missouri (MO) | 69 | Collection failed or produced no declarations on 1 of the 3 runs before this one. |
| Montana (MT) | 50 | 6 of 50 declarations have no signing date. |
| South Dakota (SD) | 86 | Collecting from the state source failed on this run and on the retry (South Dakota adapter: scrape failed (South Dakota: 0 orders parsed from the registry page: 67107 bytes, title 'South Dakota Secretary of ...). The page is showing records saved from earlier runs; the last successful collection was 2026-11-18 (2 days ago). This turns red at four weeks. |

## Green (44)

AL, AK, AZ, AR, CA, CT, DE, GA, HI, ID, IL, IN, IA, KY, LA, ME, MD, MA, MI, MN, MS, NE, NV, NH, NJ, NM, NY, NC, ND, OH, OK, OR, PA, RI, SC, TN, TX, UT, VT, VA, WA, WV, WI, WY

## Where the time went

Collecting from state sources took 55.3 min in all, and matching storms took 2.1 min. The 10 slowest states:

| State | Collecting | Matching storms |
|---|---:|---:|
| TX | 11.6 min | 2 s |
| NJ | 9.1 min | 8 s |
| NC | 6.6 min | 1 s |
| CT | 4.4 min | 3 s |
| SC | 1.9 min | 2 s |
| LA | 1.7 min | 1 s |
| MI | 1.5 min | 1 s |
| ID | 1.4 min | 1 s |
| MA | 1.3 min | 6 s |
| WA | 1.4 min | 1 s |

## FEMA declarations with no state declaration

284 of the 1,755 FEMA weather major disasters and emergencies in the years each state's page covers have no state declaration on that page within 21 days. A state's list is most likely incomplete where this is high.

The 10 states with the most:

| State | Since | No state declaration | FEMA declarations |
|---|---:|---:|---:|
| NH | 1990 | 31 | 52 |
| TN | 2000 | 26 | 53 |
| VT | 2000 | 19 | 42 |
| NE | 2000 | 19 | 45 |
| ME | 2000 | 18 | 40 |
| CT | 1971 | 15 | 37 |
| ND | 2000 | 14 | 41 |
| NY | 2000 | 13 | 57 |
| AR | 2000 | 11 | 46 |
| KS | 2000 | 11 | 53 |

## Every state

| State | Grade | Source this run | Failed runs in a row | Declarations | Federal | Dated | Titled | Linked | Storm matched | Notes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| AL | green | returned everything | 0 | 68 | 103 | 68 | 68 | 68 | 65 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| AK | green | returned everything | 0 | 47 | 95 | 47 | 47 | 47 | 33 |  |
| AZ | green | returned everything | 0 | 62 | 120 | 62 | 62 | 62 | 55 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| AR | green | returned everything | 0 | 58 | 89 | 58 | 58 | 58 | 54 |  |
| CA | green | returned everything | 0 | 177 | 398 | 177 | 177 | 177 | 162 | 6 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| CO | yellow | returned part | 0 | 116 | 112 | 116 | 116 | 116 | 98 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| CT | green | returned everything | 0 | 25 | 43 | 25 | 25 | 25 | 22 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| DE | green | returned everything | 0 | 17 | 26 | 17 | 17 | 17 | 17 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| FL | yellow | returned everything | 0 | 63 | 190 | 63 | 63 | 63 | 55 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| GA | green | returned everything | 0 | 55 | 82 | 55 | 55 | 55 | 52 |  |
| HI | green | returned everything | 0 | 39 | 77 | 39 | 39 | 39 | 35 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| ID | green | returned everything | 0 | 216 | 61 | 216 | 216 | 216 | 20 | 206 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| IL | green | returned everything | 0 | 27 | 68 | 27 | 27 | 27 | 26 |  |
| IN | green | returned everything | 0 | 42 | 56 | 41 | 42 | 42 | 35 |  |
| IA | green | returned everything | 0 | 125 | 79 | 125 | 125 | 125 | 115 |  |
| KS | yellow | returned part | 0 | 81 | 96 | 81 | 81 | 81 | 76 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| KY | green | returned everything | 0 | 69 | 99 | 69 | 69 | 69 | 61 | 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| LA | green | returned everything | 0 | 62 | 111 | 62 | 62 | 62 | 56 |  |
| ME | green | returned everything | 0 | 36 | 71 | 36 | 36 | 36 | 35 |  |
| MD | green | returned everything | 0 | 47 | 38 | 47 | 47 | 47 | 43 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| MA | green | returned everything | 0 | 29 | 59 | 29 | 29 | 29 | 24 |  |
| MI | green | returned everything | 0 | 28 | 46 | 28 | 28 | 28 | 28 |  |
| MN | green | returned everything | 0 | 50 | 81 | 50 | 50 | 50 | 46 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| MS | green | returned everything | 0 | 64 | 99 | 64 | 64 | 64 | 63 |  |
| MO | yellow | returned everything | 0 | 69 | 88 | 69 | 69 | 69 | 64 | 5 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| MT | yellow | returned everything | 0 | 50 | 113 | 44 | 50 | 50 | 40 | 4 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NE | green | returned everything | 0 | 49 | 88 | 49 | 49 | 49 | 42 |  |
| NV | green | returned everything | 0 | 15 | 116 | 15 | 15 | 15 | 12 |  |
| NH | green | returned everything | 0 | 17 | 64 | 17 | 17 | 17 | 14 |  |
| NJ | green | returned everything | 0 | 84 | 59 | 84 | 84 | 84 | 71 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NM | green | returned everything | 0 | 58 | 128 | 58 | 58 | 58 | 45 |  |
| NY | green | returned everything | 0 | 76 | 118 | 76 | 76 | 76 | 69 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NC | green | returned everything | 0 | 83 | 85 | 83 | 83 | 83 | 80 |  |
| ND | green | returned everything | 0 | 63 | 76 | 63 | 63 | 63 | 39 | 8 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| OH | green | maintained by hand | 0 | 42 | 61 | 42 | 42 | 42 | 40 | Maintained by hand: no automatic source works for this state, so declarations are added from official announcements and news coverage. This run's automatic source attempt: Ohio adapter: could not fetch Ohio GovDelivery bulletin feed: 406 Client Error: Not Acceptable for url: https://content.govdelivery.com/a.... |
| OK | green | returned everything | 0 | 76 | 260 | 76 | 76 | 76 | 74 | 6 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| OR | green | returned everything | 0 | 292 | 174 | 283 | 292 | 292 | 134 | 94 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| PA | green | returned everything | 0 | 27 | 64 | 27 | 27 | 27 | 27 |  |
| RI | green | returned everything | 0 | 15 | 31 | 15 | 15 | 15 | 14 |  |
| SC | green | returned everything | 0 | 68 | 51 | 68 | 68 | 68 | 54 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| SD | yellow | failed | 1 | 86 | 98 | 86 | 86 | 86 | 72 | 8 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| TN | green | returned everything | 0 | 53 | 97 | 53 | 53 | 53 | 37 | 5 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| TX | green | returned everything | 0 | 99 | 392 | 99 | 99 | 99 | 99 | 18 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| UT | green | returned everything | 0 | 34 | 62 | 34 | 34 | 34 | 25 | 11 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| VT | green | returned everything | 0 | 12 | 62 | 12 | 12 | 12 | 12 |  |
| VA | green | returned everything | 0 | 85 | 77 | 85 | 85 | 85 | 65 | 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| WA | green | returned everything | 0 | 81 | 223 | 81 | 81 | 81 | 66 |  |
| WV | green | returned part | 0 | 80 | 86 | 80 | 80 | 80 | 78 | The source left out 1 saved record(s); shown from earlier runs. 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| WI | green | returned everything | 0 | 74 | 57 | 74 | 74 | 74 | 64 | 8 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| WY | green | returned everything | 0 | 14 | 45 | 14 | 14 | 14 | 13 |  |

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
- its storm classifier (eo_storm_join.py) differs from the shared copy in plus/
- fewer than a quarter of the dated declarations matched any storm record
- declarations fell since the last run

A fall is not counted against a state when records a reviewer excluded as not
weather events (hazard_overrides.csv) explain it; the report notes it instead.

Green: none of the above.

A state marked as maintained by hand (its automatic source does not work, so
its records are added by hand from official announcements and news coverage)
is not graded on collection; the other checks still apply.

</details>
