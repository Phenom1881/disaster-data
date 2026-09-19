FEMA Daily Ops Briefing Archive
Captures FEMA's Daily Operations Briefing PDF and keeps a permanent, browsable archive on DisasterData.IO.
Current architecture
FEMA distributes the Daily Operations Briefing through GovDelivery. The PDF URL changes from day to day, so DisasterData does not try to predict the FEMA URL directly.
The archive pipeline uses a source resolver:
1. Primary source: Data Liberation Project public RSS feed
   - The Data Liberation Project receives FEMA's Daily Operations Briefing emails and publishes the non-private briefing metadata as a public RSS feed.
   - DisasterData reads that public feed to discover the current FEMA GovDelivery PDF URL.
   - DisasterData then downloads the PDF directly from FEMA GovDelivery.
2. Optional fallback: private kill-the-newsletter feed
   - If KTN_FEED_URL is configured as a GitHub Actions secret, the fetcher can also inspect that private RSS feed.
   - The private feed URL must never be committed to the repository.
3. Last-resort fallback: Disaster Center mirror
   - The fixed Disaster Center PDF mirror is checked only if the RSS sources are unavailable or stale.
   - It is not trusted as the primary source because the mirror has previously stopped updating while continuing to serve an older PDF.
Every downloaded candidate is opened and validated. The archive date is taken from the briefing PDF itself rather than trusting the email subject, feed title, current date, or mirror metadata.
Daily workflow
The GitHub Actions workflow is:
.github/workflows/ops-briefing.yml
It runs daily at:
13:45 UTC
The workflow also supports manual runs with workflow_dispatch.
The workflow:
1. Checks out the repository.
2. Installs Python dependencies.
3. Finds and runs the briefing fetcher in scripts/.
4. Builds the static Ops Briefing pages.
5. Commits any new PDFs, history changes, and generated pages back to the repository.
The workflow has contents: write permission so the GitHub Actions bot can commit newly archived files.
Fetcher behavior
The fetcher is:
scripts/fetch ops briefing.py
The workflow locates it with:
find scripts -iname 'fetch*ops*brief*.py'
The fetcher:
- reads the public Data Liberation Project RSS feed
- optionally reads the private KTN feed if configured
- uses Disaster Center only as a fallback
- downloads candidate PDFs
- validates the date from the PDF itself
- ignores briefings already present locally
- saves new PDFs into the archive
- updates history.csv
- reports source health clearly
A current briefing that is already archived is a healthy success.
A source that is unreachable, stale, or invalid is reported visibly. If every configured source is unusable or stale, the fetcher exits non-zero so GitHub Actions does not show a misleading green run.
Output
Archived PDFs:
archive/ops-briefings/YYYY-MM-DD.pdf
Permanent local history:
archive/ops-briefings/history.csv
The local CSV is the durable DisasterData record. It should not depend on an RSS feed remaining online forever.
Current columns:
- date
- filename
- source_url
- archived_at
Public pages
The page builder is located in scripts/ and is found by the workflow with:
find scripts -iname 'build*ops*pages*.py'
It builds:
- /ops-briefings/index.html
- archive browsing pages
- briefing day pages
The public archive is available at:
https://disasterdata.io/ops-briefings/
Source health
The default freshness limit is three days.
It can be changed with:
STALE_MAX_DAYS
Expected outcomes:
New briefing found
The PDF is validated, archived, added to history.csv, pages are rebuilt, and the changes are committed.
Current briefing already archived
The run succeeds without creating a duplicate.
Primary source unavailable but fallback succeeds
The run succeeds and logs a warning showing that a fallback source was used.
Every source stale or unusable
The fetcher exits non-zero so the GitHub Action fails visibly.
This is intentional. A failed health check is preferable to a successful-looking workflow that has silently stopped collecting briefings.
Environment variables
DD_OUT
Archive root.
Default:
archive
DLP_FEED_URL
Optional override for the Data Liberation Project public RSS feed.
Normally this does not need to be configured.
KTN_FEED_URL
Optional private kill-the-newsletter RSS feed.
If used, store this only in GitHub Actions secrets.
Never place the private URL in the README, source code, workflow file, commit history, or public site.
OPS_PDF_URL
Optional override for the Disaster Center fallback PDF.
STALE_MAX_DAYS
Maximum acceptable age of the newest briefing before a source is considered stale.
Default:
3
REQUEST_TIMEOUT
HTTP request timeout in seconds.
Default:
45
Historical recovery
The Data Liberation Project also maintains a public historical CSV generated from the history of its RSS feed.
That source can be used for controlled backfill of missing DisasterData archive dates.
Backfill should remain separate from the normal daily path so the routine workflow stays fast and predictable.
Historical recovery should:
1. read the external historical record
2. identify dates missing from DisasterData's history.csv
3. download the original FEMA GovDelivery PDFs
4. validate each PDF date
5. archive only validated missing files
6. rebuild the static archive after the recovery run
Do not manufacture placeholder dates when no briefing can be verified.
Site conventions
Ops Briefing pages should follow the shared DisasterData site conventions:
- tab title format: Disaster Data | [page]
- shared navigation loaded with <script src="/nav.js"></script>
- no page-specific duplicate navigation
- paper background: #f6f1e7
- teal accent: #004c53
- ember accent: #c85c2e
- Fraunces for headings
- Public Sans for body text
- no em or en dashes in site copy
Operational notes
The archive has previously used three different collection approaches:
1. a private kill-the-newsletter feed
2. a dedicated Gmail account
3. the Disaster Center fixed PDF mirror
Each experienced a different reliability problem.
The current design therefore avoids making any private mailbox or third-party mirror the only source of truth. The external feed is used for discovery, the PDF is downloaded from FEMA GovDelivery when possible, the PDF itself is validated, and DisasterData maintains its own permanent archive.doesn't need to change, so nothing downstream (front-end pages,
citations, etc.) will need to be touched when the migration happens.
