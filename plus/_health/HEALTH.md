# Plus health report

Checked 2026-10-08 17:14 UTC after the refresh. **48 green, 2 yellow, 0 red.**

## Yellow: working with gaps (2)

| State | Declarations | Why |
|---|---:|---|
| Oklahoma (OK) | 55 | The source left out 48 of 55 saved records; they are shown from earlier runs. |
| Wisconsin (WI) | 18 | Collecting from the state source failed on this run and on the retry (Wisconsin adapter: scrape failed). The page is showing records saved from earlier runs; the last successful collection was 2026-10-08 (0 days ago). This turns red at four weeks. |

## Green (48)

AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA, HI, ID, IL, IN, IA, KS, KY, LA, ME, MD, MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ, NM, NY, NC, ND, OH, OR, PA, RI, SC, SD, TN, TX, UT, VT, VA, WA, WV, WY

## Where the time went

Collecting from state sources took 49.8 min in all, and matching storms took 1.5 min. The 10 slowest states:

| State | Collecting | Matching storms |
|---|---:|---:|
| NH | 9.7 min | 1 s |
| NJ | 4.9 min | 8 s |
| NC | 4.6 min | 1 s |
| TX | 4.0 min | 1 s |
| CT | 3.4 min | 1 s |
| MA | 3.3 min | 1 s |
| CA | 1.9 min | 1 s |
| WA | 1.7 min | 1 s |
| LA | 1.6 min | 1 s |
| MI | 1.5 min | 1 s |

## Every state

| State | Grade | Source this run | Failed runs in a row | Declarations | Federal | Dated | Titled | Linked | Storm matched | Notes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| AL | green | returned everything | 0 | 31 | 102 | 31 | 31 | 31 | 29 |  |
| AK | green | returned everything | 0 | 23 | 95 | 23 | 23 | 23 | 17 |  |
| AZ | green | returned everything | 0 | 59 | 120 | 59 | 59 | 59 | 54 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| AR | green | returned everything | 0 | 33 | 89 | 33 | 33 | 33 | 29 |  |
| CA | green | returned everything | 0 | 47 | 397 | 47 | 47 | 47 | 43 |  |
| CO | green | returned everything | 0 | 120 | 112 | 120 | 120 | 120 | 94 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| CT | green | returned everything | 0 | 20 | 43 | 20 | 20 | 20 | 19 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| DE | green | returned everything | 0 | 15 | 26 | 15 | 15 | 15 | 15 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| FL | green | returned everything | 0 | 26 | 188 | 26 | 26 | 26 | 22 |  |
| GA | green | returned everything | 0 | 32 | 81 | 32 | 32 | 32 | 31 |  |
| HI | green | returned everything | 0 | 37 | 75 | 37 | 37 | 37 | 31 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| ID | green | returned everything | 0 | 208 | 61 | 208 | 208 | 208 | 14 | 206 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| IL | green | returned everything | 0 | 15 | 68 | 15 | 15 | 15 | 13 |  |
| IN | green | returned everything | 0 | 35 | 56 | 34 | 35 | 35 | 27 |  |
| IA | green | returned everything | 0 | 54 | 79 | 54 | 54 | 54 | 46 |  |
| KS | green | returned part | 0 | 53 | 96 | 53 | 53 | 53 | 45 | The source left out 1 saved record(s); shown from earlier runs. 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| KY | green | returned part | 0 | 13 | 99 | 13 | 13 | 13 | 11 | The source left out 1 saved record(s); shown from earlier runs. |
| LA | green | returned everything | 0 | 26 | 111 | 26 | 26 | 26 | 21 |  |
| ME | green | returned everything | 0 | 24 | 71 | 24 | 24 | 24 | 23 |  |
| MD | green | returned everything | 0 | 23 | 38 | 23 | 23 | 23 | 23 |  |
| MA | green | returned everything | 0 | 16 | 59 | 16 | 16 | 16 | 15 |  |
| MI | green | returned everything | 0 | 23 | 46 | 23 | 23 | 23 | 23 |  |
| MN | green | returned everything | 0 | 15 | 81 | 15 | 15 | 15 | 14 |  |
| MS | green | returned everything | 0 | 43 | 99 | 43 | 43 | 43 | 42 |  |
| MO | green | returned everything | 0 | 83 | 88 | 83 | 83 | 83 | 62 | 5 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| MT | green | returned part | 0 | 19 | 113 | 19 | 19 | 19 | 14 | The source left out 1 saved record(s); shown from earlier runs. 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NE | green | returned everything | 0 | 33 | 88 | 33 | 33 | 33 | 14 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NV | green | returned everything | 0 | 13 | 116 | 13 | 13 | 13 | 9 |  |
| NH | green | returned everything | 0 | 14 | 63 | 14 | 14 | 14 | 11 | Failed on the first try this run and recovered on the retry. |
| NJ | green | returned everything | 0 | 145 | 59 | 145 | 145 | 145 | 103 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NM | green | returned everything | 0 | 45 | 126 | 45 | 45 | 45 | 25 |  |
| NY | green | returned everything | 0 | 25 | 118 | 25 | 25 | 25 | 22 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NC | green | returned everything | 0 | 34 | 85 | 34 | 34 | 34 | 32 |  |
| ND | green | returned everything | 0 | 34 | 76 | 34 | 34 | 34 | 18 | 7 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| OH | green | maintained by hand | 0 | 18 | 61 | 18 | 18 | 18 | 15 | Maintained by hand: no automatic source works for this state, so declarations are added from official announcements and news coverage. This run's automatic source attempt: Ohio adapter: could not fetch Ohio GovDelivery bulletin feed: 406 Client Error: Not Acceptable for url: https://content.govdelivery.com/a.... |
| OK | yellow | returned part | 0 | 55 | 259 | 55 | 55 | 55 | 53 | 6 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| OR | green | returned everything | 0 | 252 | 174 | 237 | 252 | 252 | 106 | 78 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| PA | green | returned everything | 0 | 17 | 64 | 17 | 17 | 17 | 17 |  |
| RI | green | returned everything | 0 | 13 | 31 | 13 | 13 | 13 | 13 |  |
| SC | green | returned everything | 0 | 50 | 51 | 50 | 50 | 50 | 37 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| SD | green | returned everything | 0 | 25 | 98 | 25 | 25 | 25 | 16 | 4 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| TN | green | returned everything | 0 | 24 | 97 | 24 | 24 | 24 | 18 | 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| TX | green | returned part | 0 | 59 | 392 | 59 | 59 | 59 | 57 | The source left out 1 saved record(s); shown from earlier runs. 14 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| UT | green | returned everything | 0 | 33 | 61 | 33 | 33 | 33 | 20 | 11 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| VT | green | returned everything | 0 | 11 | 62 | 11 | 11 | 11 | 11 |  |
| VA | green | returned everything | 0 | 75 | 77 | 75 | 75 | 75 | 65 | 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| WA | green | returned everything | 0 | 39 | 223 | 39 | 39 | 39 | 26 |  |
| WV | green | returned everything | 0 | 18 | 85 | 18 | 18 | 18 | 12 |  |
| WI | yellow | failed | 1 | 18 | 56 | 18 | 18 | 18 | 15 |  |
| WY | green | returned everything | 0 | 13 | 45 | 13 | 13 | 13 | 12 |  |

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

A state marked as maintained by hand (its automatic source does not work, so
its records are added by hand from official announcements and news coverage)
is not graded on collection; the other checks still apply.

</details>
