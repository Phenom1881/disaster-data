# Plus health report

Checked 2026-10-26 23:44 UTC after the refresh. **49 green, 1 yellow, 0 red.**

## Yellow: working with gaps (1)

| State | Declarations | Why |
|---|---:|---|
| Kansas (KS) | 51 | Collecting from the state source failed on this run and on the retry (Kansas adapter: scrape failed (Kansas: could not read https://www.kansastag.gov/388/Kansas-Disaster-Declarations: 403 Client Error: Forbi...), 2 runs in a row. The page is showing records saved from earlier runs; the last successful collection was 2026-10-24 (2 days ago). This turns red at four weeks. |

## Green (49)

AL, AK, AZ, AR, CA, CO, CT, DE, FL, GA, HI, ID, IL, IN, IA, KY, LA, ME, MD, MA, MI, MN, MS, MO, MT, NE, NV, NH, NJ, NM, NY, NC, ND, OH, OK, OR, PA, RI, SC, SD, TN, TX, UT, VT, VA, WA, WV, WI, WY

## Where the time went

Collecting from state sources took 51.3 min in all, and matching storms took 1.9 min. The 10 slowest states:

| State | Collecting | Matching storms |
|---|---:|---:|
| TX | 9.2 min | 1 s |
| NJ | 9.1 min | 11 s |
| NC | 7.5 min | 1 s |
| CT | 4.5 min | 0 s |
| WA | 1.8 min | 1 s |
| LA | 1.7 min | 1 s |
| VT | 1.6 min | 1 s |
| SC | 1.4 min | 4 s |
| PA | 1.4 min | 1 s |
| MI | 1.4 min | 1 s |

## FEMA declarations with no state declaration

382 of the 1,016 FEMA weather major disasters and emergencies in the years each state's page covers have no state declaration on that page within 21 days. A state's list is most likely incomplete where this is high.

The 10 states with the most:

| State | Since | No state declaration | FEMA declarations |
|---|---:|---:|---:|
| NE | 1970 | 60 | 64 |
| NH | 1990 | 39 | 52 |
| TN | 2000 | 34 | 53 |
| MA | 1970 | 30 | 45 |
| AK | 2004 | 24 | 36 |
| IL | 2000 | 22 | 28 |
| KS | 2009 | 20 | 35 |
| CT | 1971 | 20 | 37 |
| VT | 2011 | 19 | 29 |
| ID | 2000 | 15 | 18 |

## Every state

| State | Grade | Source this run | Failed runs in a row | Declarations | Federal | Dated | Titled | Linked | Storm matched | Notes |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| AL | green | returned everything | 0 | 31 | 103 | 31 | 31 | 31 | 29 |  |
| AK | green | returned everything | 0 | 23 | 95 | 23 | 23 | 23 | 17 |  |
| AZ | green | returned everything | 0 | 59 | 120 | 59 | 59 | 59 | 54 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| AR | green | returned everything | 0 | 36 | 89 | 36 | 36 | 36 | 32 |  |
| CA | green | returned everything | 0 | 47 | 398 | 47 | 47 | 47 | 43 |  |
| CO | green | returned everything | 0 | 112 | 112 | 112 | 112 | 112 | 94 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| CT | green | returned everything | 0 | 20 | 43 | 20 | 20 | 20 | 19 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| DE | green | returned everything | 0 | 15 | 26 | 15 | 15 | 15 | 15 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| FL | green | returned everything | 0 | 26 | 189 | 26 | 26 | 26 | 22 |  |
| GA | green | returned everything | 0 | 45 | 82 | 45 | 45 | 45 | 43 |  |
| HI | green | returned everything | 0 | 37 | 77 | 37 | 37 | 37 | 31 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| ID | green | returned everything | 0 | 208 | 61 | 208 | 208 | 208 | 14 | 206 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| IL | green | returned everything | 0 | 15 | 68 | 15 | 15 | 15 | 13 |  |
| IN | green | returned everything | 0 | 35 | 56 | 34 | 35 | 35 | 27 |  |
| IA | green | returned everything | 0 | 54 | 79 | 54 | 54 | 54 | 49 |  |
| KS | yellow | failed | 2 | 51 | 96 | 51 | 51 | 51 | 45 | 2 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| KY | green | returned everything | 0 | 16 | 99 | 16 | 16 | 16 | 14 |  |
| LA | green | returned everything | 0 | 45 | 111 | 45 | 45 | 45 | 40 |  |
| ME | green | returned everything | 0 | 24 | 71 | 24 | 24 | 24 | 23 |  |
| MD | green | returned everything | 0 | 31 | 38 | 31 | 31 | 31 | 28 |  |
| MA | green | returned everything | 0 | 16 | 59 | 16 | 16 | 16 | 15 |  |
| MI | green | returned everything | 0 | 23 | 46 | 23 | 23 | 23 | 23 |  |
| MN | green | returned everything | 0 | 15 | 81 | 15 | 15 | 15 | 15 |  |
| MS | green | returned everything | 0 | 43 | 99 | 43 | 43 | 43 | 42 |  |
| MO | green | returned everything | 0 | 68 | 88 | 68 | 68 | 68 | 63 | 5 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| MT | green | returned everything | 0 | 16 | 113 | 16 | 16 | 16 | 14 | 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NE | green | returned everything | 0 | 19 | 88 | 19 | 19 | 19 | 14 |  |
| NV | green | returned everything | 0 | 13 | 116 | 13 | 13 | 13 | 9 |  |
| NH | green | returned everything | 0 | 14 | 64 | 14 | 14 | 14 | 11 |  |
| NJ | green | returned everything | 0 | 83 | 59 | 83 | 83 | 83 | 70 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NM | green | returned everything | 0 | 45 | 127 | 45 | 45 | 45 | 34 |  |
| NY | green | returned everything | 0 | 24 | 118 | 24 | 24 | 24 | 22 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| NC | green | returned everything | 0 | 56 | 85 | 56 | 56 | 56 | 53 |  |
| ND | green | returned everything | 0 | 34 | 76 | 34 | 34 | 34 | 18 | 7 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| OH | green | maintained by hand | 0 | 18 | 61 | 18 | 18 | 18 | 16 | Maintained by hand: no automatic source works for this state, so declarations are added from official announcements and news coverage. This run's automatic source attempt: Ohio adapter: could not fetch Ohio GovDelivery bulletin feed: 406 Client Error: Not Acceptable for url: https://content.govdelivery.com/a.... |
| OK | green | returned everything | 0 | 55 | 260 | 55 | 55 | 55 | 53 | 6 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| OR | green | returned everything | 0 | 253 | 174 | 238 | 253 | 253 | 110 | 78 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| PA | green | returned everything | 0 | 17 | 64 | 17 | 17 | 17 | 17 |  |
| RI | green | returned everything | 0 | 13 | 31 | 13 | 13 | 13 | 13 |  |
| SC | green | returned everything | 0 | 67 | 51 | 67 | 67 | 67 | 53 | 1 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| SD | green | returned everything | 0 | 22 | 98 | 22 | 22 | 22 | 18 | 4 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| TN | green | returned everything | 0 | 30 | 97 | 30 | 30 | 30 | 20 | 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| TX | green | returned everything | 0 | 58 | 392 | 58 | 58 | 58 | 58 | 14 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| UT | green | returned everything | 0 | 32 | 62 | 32 | 32 | 32 | 21 | 11 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| VT | green | returned everything | 0 | 11 | 62 | 11 | 11 | 11 | 11 |  |
| VA | green | returned everything | 0 | 82 | 77 | 82 | 82 | 82 | 65 | 3 drought declaration(s) are not counted in the storm match rate; NOAA's storm database logs drought only in some months. |
| WA | green | returned everything | 0 | 43 | 223 | 43 | 43 | 43 | 39 |  |
| WV | green | returned everything | 0 | 18 | 86 | 18 | 18 | 18 | 15 |  |
| WI | green | returned everything | 0 | 18 | 57 | 18 | 18 | 18 | 16 |  |
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
