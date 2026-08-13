# FEMA Daily Ops Briefing Archive

Captures FEMA's Daily Operations Briefing PDF every day and keeps a
permanent, browsable archive on DisasterData.IO.

## How it works

FEMA emails a link to the day's briefing PDF to subscribers of its
GovDelivery "Daily Operations Briefing" list around 8:30am ET. This
pipeline turns that email into a durable archive:

1. A kill-the-newsletter.com inbox receives the email and exposes it
   as a private RSS feed.
2. A GitHub Action runs daily, reads that feed, pulls out the PDF link
   and date, downloads any briefing not already archived, and appends
   a row to `archive/ops-briefings/history.csv`.
3. `history.csv` is the permanent record. The RSS feed itself only
   keeps the most recent ~42 entries, so it can never be the archive
   on its own.

Only the raw PDF is archived, no text or table extraction. That keeps
the daily job resilient to FEMA changing the briefing's format.

**This inbox is a stopgap.** The plan is to migrate this to a
dedicated Gmail inbox read directly over IMAP (no kill-the-newsletter
dependency at all), but that requires creating and configuring a new
Google account first. Until that's done, this KTN feed keeps the
archive running.

## Current feed

- KTN inbox: `kt4ypjpe4t689mt61chn@kill-the-newsletter.com`
- Feed URL: `https://kill-the-newsletter.com/feeds/kt4ypjpe4t689mt61chn.xml`

This feed URL must stay private, never commit it directly into the
repo. If it leaked, someone could unsubscribe it from the FEMA list or
send spam to the inbox.

## One-time setup

1. **Subscribe.** Go to the FEMA GovDelivery signup page and subscribe
   `kt4ypjpe4t689mt61chn@kill-the-newsletter.com` to the "Daily
   Operations Briefing" list:
   https://public.govdelivery.com/accounts/USDHSFEMA/subscriber/new
2. **Add the feed URL as a GitHub secret** on the disaster-data repo,
   named `KTN_FEED_URL`, set to
   `https://kill-the-newsletter.com/feeds/kt4ypjpe4t689mt61chn.xml`.
3. Push these files (`scripts/fetch_ops_briefing.py`, the workflow,
   this README) to the repo.
4. Trigger the workflow manually once from the Actions tab
   (workflow_dispatch), after the next briefing has landed in the KTN
   feed, to confirm parsing works end to end before trusting the
   unattended daily cron.

## Output

- `archive/ops-briefings/YYYY-MM-DD.pdf`: one archived PDF per day
- `archive/ops-briefings/history.csv`: columns are `date`, `filename`,
  `source_url`, `archived_at`, `feed_entry_id`

Front-end pages (30-day browse index, single-day view, subscribe
callout) read from `history.csv` and are a separate build step.

## Future: Gmail/IMAP migration

When ready to drop KTN, the swap is small: replace the feed-fetch
step with an IMAP poll against a dedicated Gmail inbox, same
extraction regex, same `history.csv` output. `history.csv` itself
doesn't need to change, so nothing downstream (front-end pages,
citations, etc.) will need to be touched when the migration happens.
