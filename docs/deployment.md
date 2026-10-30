# Operating JobsFinder.io

Use one always-on computer or Linux Docker host. Production SQLite must remain
on persistent local storage outside OneDrive or other sync folders. GitHub
Actions tests and publishes successful main releases to GHCR. No schedule
or remote deployment has been activated here.

**Azure production:** follow [pull-based CI/CD setup](azure-cicd.md). It uses
separate updater/worker timers, tested images instead of on-VM builds, and
consistent backups before migrations. Manual Compose/build/cron examples below
remain for local operation; do not combine them with production systemd timers.

## Azure deployment readiness

The existing Docker/Compose workflow fits a single always-on Azure Linux VM.
Deployment automation is provided; no Azure resources, registry settings or
schedules have been activated. The host has not been verified; complete these
steps before calling the deployment operational:

1. Use persistent managed-disk storage for `/var/lib/jobsfinder`. Never put SQLite
   on the VM's temporary/resource disk or a shared network filesystem. Microsoft
   documents [managed-disk persistence and temporary-disk loss](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/faq).
   Keep one scheduler host per database; configure disk ownership as below.
2. Stop local writers and transfer a consistent SQLite backup plus protected
   private configuration. Preserve the complete database, including employer
   registry, postings/history, screening cache/queue, quotas and delivery receipts.
   Retain original backups. Do not replace it with a new empty database. Do not
   run local and Azure workers independently against divergent production copies.
3. Configure the host `.env` with Linux paths and UID/GID. Keep credentials and
   profiles outside the image and Git. Allow HTTPS to configured public providers
   and authenticated SMTP to the configured mail host. Azure documents
   [authenticated SMTP on port 587](https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-network/troubleshoot-outbound-smtp-connectivity);
   host firewall and provider acceptance still need verification.
4. Pull the approved GHCR image on Azure; build locally only for development.
   With both schedules stopped, run the
   migration, health and local report commands below. Review pending/uncertain
   outbox state before enabling delivery. Send a test email only when authorized
   and confirm inbox receipt. Check model access and actual quota before enabling
   paid screening; repository defaults are application limits, not account proof.
5. Install the two tick schedules only when ready, configure log rotation and
   protected backups, and verify restore into a separate directory. Confirm
   persistent storage is mounted before workers run after a host restart.

The repository is prepared for this deployment path; persistent disk, networking,
credentials, image execution and scheduler behavior require target-host checks.

## Configure a Linux host

1. Install Docker Engine and Compose; put the checkout at `/opt/jobsfinder`.
2. Create `/var/lib/jobsfinder` **and** its `private` and `reports` directories,
   all owned by the runtime UID/GID. The parent must be writable because SQLite
   journals and process locks live there. Protect directories/files with modes
   700/600. On Linux, an administrator can use `install -d -m 700 -o UID -g GID`
   for each directory, replacing UID/GID with the actual runtime account IDs.
3. For a new host, copy `.env.example` to ignored `.env`; preserve existing configuration. Set
   `JOBSFINDER_DATA_DIR=/var/lib/jobsfinder`, `LOCAL_UID`/`LOCAL_GID` to that account,
   `JOBSFINDER_CANDIDATES=/app/data/private/candidates.json`, and
   `JOBSFINDER_REPORT_DIR=/app/data/reports`.
   Protect the populated `.env` with `chmod 600 .env`.
4. The [final pilot passed](activation-pilot.md): AI defaults to enabled, with
   `GEMINI_MAX_CALLS=20`, `GEMINI_DAILY_LIMIT=20`, retry reserve 2 and batch size 10.
   Put the private profile at `/var/lib/jobsfinder/private/profile.json` and set
   `JOBSFINDER_PROFILE=/app/data/private/profile.json`. To operate without AI,
   explicitly set `GEMINI_BATCH_ENABLED=false` and `GEMINI_MAX_CALLS=0`.
   Monitoring/reports remain independent and need no AI profile or key.

```sh
cd /opt/jobsfinder
docker compose config --quiet
docker compose build
docker compose run --rm -T jobsfinder alembic upgrade head
docker compose run --rm -T jobsfinder jobsfinder-io health
docker compose run --rm -T jobsfinder jobsfinder-io report --local-only
```

On this Windows machine the verified database stays at
`%LOCALAPPDATA%/JobsFinder.io/data/jobsfinder.db`. Preserve the existing ignored
`.env` mount. Local uv does not load `.env`; pass the database explicitly:

```powershell
uv run jobsfinder-io --db "$env:LOCALAPPDATA/JobsFinder.io/data/jobsfinder.db" health
```

## Personal email

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_FROM`, `SMTP_TO` and, when
authentication is required, `SMTP_USERNAME`/`SMTP_PASSWORD`. Exactly one plain
personal recipient is allowed. Default: STARTTLS on port 587. For implicit TLS
use `SMTP_SECURITY=ssl` and port 465. Certificate verification is required.
Keep credentials in protected `.env` or host environment, never argv or source.

For Gmail use `smtp.gmail.com` and an eligible account's
[app password with 2-Step Verification](https://support.google.com/accounts/answer/185833),
not the normal account password. If app passwords are unavailable, use another
compatible SMTP provider. OAuth SMTP is not implemented.

```sh
docker compose run --rm -T jobsfinder jobsfinder-io test-email
```

This sends only one test to your configured address, without draining queued
job mail. Missing settings return a nonzero test exit. Monitoring without SMTP
still writes local artifacts and retains a durable outbox. Before configuring
SMTP later, inspect any accumulated queue: eligible pending mail will send.

New report/alert groups consolidate older **never-attempted** messages of the
same kind, retaining all still-relevant unreported jobs in the seven-day window.
Old message history and local files remain. Attempted, accepted or uncertain
messages are not replaced or automatically replayed by consolidation.

Temporary failures before acceptance retry after five/ten minutes, at most three
attempts. Authentication/recipient failures require correction and manual review.
A lost DATA acknowledgement or interrupted sending becomes `uncertain` and
never replays automatically. Inspect your inbox and `health.email_review` before
manual recovery. SMTP acceptance is not proof of final inbox delivery. There is
no automatic recovery command for ambiguous/exhausted messages; retain the local
artifact and investigate before changing receipts.

## Discovery and reports

Keep operator-confirmed official career pages in the private candidates file.
See [discovery configuration](../src/jobsfinder_io/discovery/README.md) for imports,
trusted directories, budgets and optional Brave search. Unknown search/directory
domains remain audit candidates until confirmed; they are never autoapproved.
Supported ATS endpoints are validated before registration. Newly registered
sources begin hourly monitoring; their first poll establishes a baseline.

Without search credentials, imports and trusted directories provide useful but
finite coverage. Replenish inputs to keep finding employers. Durable rotation
advances across restarts but cannot find employers outside those inputs.
Optional Brave requires explicit configuration plus `BRAVE_SEARCH_API_KEY`;
leave it absent unless provider usage is approved. Its rotating plan covers US
states, industries, roles, and priority/additional countries. It guarantees no
coverage. JavaScript-only pages and unsupported ATS boards can fail safely.

Non-AI reports combine US, international and uncertain-country sections and
separate initial baselines. They include seven-day discoveries/material changes,
source dates, first-seen dates, official application links, and quoted technology
and experience evidence. Eligibility, sponsorship and start dates remain
unverified. Conservative relevance retains uncertain technical and senior roles
for manual review. No AI rankings or cover letters are generated. Persistent
revision receipts suppress unchanged entries. Local reports do not consume
future email recommendations. Empty reports still include actual check counts.

## Activate when ready

After verifying mail and candidate inputs, install this host cron entry:

```cron
*/5 * * * * cd /opt/jobsfinder && /usr/bin/docker compose run --rm -T jobsfinder jobsfinder-io run-due >> /var/lib/jobsfinder/scheduler.log 2>&1
```

Use the Docker path from `command -v docker`, an account with Docker/log access,
and log rotation. Every tick checks hourly source intervals/failure backoff,
runs discovery from 06:00 America/New_York, queues grouped new-job alerts, creates
one report at 10:00 and 20:00 New York, and processes eligible outbox messages.
Initial baselines do not trigger fast alerts. AI is never invoked.

New York daylight saving time is handled in the application; cron can use host
time. Late ticks catch the latest same-day report slot, rather than every missed
historical slot. Seven-day reports recover missed jobs. Durable success receipts
prevent repeated tasks; interrupted work resumes after restart. Failed polls
never close jobs; closure requires two complete successful absences. One OS lock
serializes all CLI workflows. Use one scheduler host per database.

On Windows, prepare Task Scheduler only when ready: repeat every five minutes
indefinitely, run `docker.exe compose run --rm -T jobsfinder jobsfinder-io run-due`
with the checkout as working directory, and choose "Do not start a new instance".
Keep the computer awake and Docker Desktop running. The application lock is
additional protection. No Windows task was installed during verification.

## Backup and acceptance

The bind mount survives container removal/upgrades; it is not a backup. Stop
cron, wait for active commands, back up SQLite plus private files, rebuild,
migrate, inspect health, then resume. Never migrate during active workflows.
For live backups use SQLite's backup API instead of copying an active database.
Protect backups and test restoring into a separate data directory.

See [final non-AI verification](non-ai-final-verification.md) for historical checks.
SMTP credentials and an always-on host are required for unattended email operation.
The [final pilot](activation-pilot.md) approved enabled, capped screening
configuration; its separate host schedule remains a deployment step.

The [final non-AI verification](non-ai-final-verification.md) includes one Gmail
test accepted over authenticated STARTTLS, real discovery growth, report-content
checks, container recovery and remaining coverage limitations. SMTP acceptance
does not independently confirm inbox delivery. Repeat deployment smoke checks
on the chosen cloud host: its persistent-disk permissions, SMTP egress and uptime
have not been verified here. Never use GitHub Actions as the production host.

For non-AI production, do not install the optional screening cron entry. Runtime
overrides can enforce AI-off without rewriting a separately maintained `.env`:

```sh
docker compose run --rm -T -e GEMINI_API_KEY= -e GEMINI_MAX_CALLS=0 -e GEMINI_BATCH_ENABLED=false jobsfinder jobsfinder-io run-due
```

Discovery settings remain operator-owned. Configure reviewed daily inputs for
continued registry growth; a finite import cannot provide internet-wide coverage.

## Approved batch screening, enabled in configuration

The multi-job implementation is described in [batch screening](gemini-batch-screening.md).
The [final pilot](activation-pilot.md) passed and the owner approved enabled
defaults: enabled, 20 calls/day, 2 reserved, 10 jobs/batch, 8 batches/session.
`run-due` maintains the screening queue without calling Gemini;
polling, email and reports do not wait for Gemini.

When deploying the always-on host, a second five-minute cron entry can run
`screen-due`. No permanent schedule has been installed during this task:

```cron
*/5 * * * * cd /opt/jobsfinder && /usr/bin/docker compose run --rm -T jobsfinder jobsfinder-io screen-due >> /var/lib/jobsfinder/screening.log 2>&1
```

It only starts requests during 09:30–10:00 and 19:30–20:00 New York, with DST
handling, and stops starting new requests at report time. An in-flight request
may finish later. Reports remain independently available with uncertain
eligibility labels. The separate screening lock prevents two screeners from
overlapping without holding the monitoring lock during API waits. Stop **both**
jobs before migrations/backups/upgrades, and configure quota limits from AI Studio.
The enabled configuration is prepared; installing both permanent tick commands
and provisioning persistent hosting remain deployment steps. Build the final
image locally for manual use; on Azure pull the approved GHCR image through the
production updater before starting either timer.
