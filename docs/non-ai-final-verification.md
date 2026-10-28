# Non-AI pre-deployment verification — complete

Owner authorizes exactly one real SMTP test to the configured personal recipient.
All alert/report deliveries use mocks; every command forces AI off in its own
environment. Preserve `.env`, production records and existing request limits.
No paid search activation, schedules, deployment, commits or pushes.

Lead owns live calls/configuration/production DB and any application fixes.
Discovery reviewer researches public sources and mocks; workflow QA owns
`tests/test_nonai_acceptance.py`; recovery reviewer owns
`tests/test_recovery_acceptance.py`. No overlapping application edits.

- [x] Record starting registry, configuration presence and AI usage; safe backup.
- [x] Repeat real Greenhouse/Lever/Ashby polling and inspect records/idempotence.
- [x] Measure real free discovery candidates, validations, failures and growth.
- [x] Exactly one accepted SMTP test; inspect authentication/STARTTLS and receipt.
- [x] Inspect real-data local reports; mocked grouped alerts/delivery/recovery.
- [x] Controlled local-only ticks, injected scheduling/DST/overlap tests.
- [x] Docker non-root/persistent storage/migrations and test-copy restore.
- [x] Full tests, Ruff, independent QA and final readiness handoff.

## A. Actual live checks

Greenhouse/Tailscale (53), Lever/Metabase (19), and Ashby/Linear (32) each polled
twice during verification, all unchanged. Newly discovered sources were picked up
by `poll-due` automatically. Existing Notion/Render also polled successfully.

| Employer | Provider | Jobs |
| --- | --- | ---: |
| Tailscale | Greenhouse | 53 |
| Metabase | Lever | 19 |
| Linear | Ashby | 32 |
| Notion | Ashby | 139 |
| Render | Ashby | 35 |
| Zapier | Ashby | 12 |
| GoCardless | Greenhouse | 24 |
| Wealthsimple | Ashby | 41 |
| Ninja Van | Lever | 139 |
| Total | 9 validated sources | 494 |

All 27 stored poll records are complete successes. No duplicate source/job
identity groups exist. All 494 retain their initial-baseline discovery kind;
first discovery was never relabeled publication. There are 77 actual source
publication timestamps, preserved separately from discovery/updates; other
publication dates remain unknown. Application links are retained throughout.
One source job genuinely has no description. Closure/reappearance, incomplete
feeds, API failures and interrupted runs were tested on temporary mocked data;
no natural live closure/reappearance was observed in these controlled polls.

## B. Measured discovery

Employers/sources increased **5/5 → 9/9**. The free
[Django corporate-member directory](https://www.djangoproject.com/foundation/corporate-members/)
produced 57 raw candidate URLs. Five belonged to reviewed domains; 52 were held
as untrusted candidate URLs. These include publisher/social links and are not
57 confirmed employers. Homepage-to-careers navigation found Zapier's real jobs
page and validated its Ashby board without a manually supplied Zapier careers URL.
Four other directory-page checks failed safely (unsupported page, cross-host
redirect, or the response-size cap).

Seven operator-reviewed career-page imports covered the US and Germany, Ireland,
UK, UAE, Canada and Singapore. GoCardless, Wealthsimple and Ninja Van validated
and registered; Flatiron Health, N26, Tines and Careem lacked supported detectable
links in this bounded static-page pass. Their regions are attempted coverage,
not claims of successful monitoring. A separate repeat of all four successful
new sources rejected **4 duplicates**, added 0 employers, and had 0 failures.

Total: 4 newly validated/registered sources, 8 failed/unsupported checks across
the two discovery passes, and 4 duplicates in the repeat. Brave was not configured
at inspection and **0 Brave API calls** were made. Daily region/industry/country
rotation is tested with mocks, but no-key discovery stays limited to configured
directories/imports and reviewed domains. It does not independently search the
whole internet or guarantee all industries/states/countries. Unknown domains
are never autoapproved. Original daily configuration was not overwritten;
supplemental verification inputs stay in the private verification directory.

## C. Gmail email

Exactly **one message was accepted** using the existing `test-email` command,
Gmail on port 587, authenticated STARTTLS with certificate verification, and the
configured single personal recipient. Inbox receipt is not independently known.

An earlier invocation failed during authentication before MAIL/DATA. Login-only
probes verified TLS 1.3 and returned authentication error 535 with that earlier
configuration; no messages were submitted by those probes. After the user
continued, the configured command returned `sent:1`, `error:null`, exit 0.
Both the failed attempt and successful acceptance remain in the audit history;
the failed diagnostic is terminal and will not automatically resend.

All job-alert/report SMTP tests used mocks. No bulk job messages, employer
messages or recruiter messages were sent. Secrets were never printed or stored
in public files; user configuration was not rewritten.

## D. Reports and scheduling

A disposable copy of real data generated a comprehensive report with **451**
conservatively relevant/uncertain jobs and 451 checked official application links,
with US, international and uncertain/multiple-country sections. All original
baselines were clearly labeled; 12 corrected-description revisions were labeled
material changes. Publication-unknown and eligibility/sponsorship/start-date
uncertainty labels were inspected in actual report content. The next report
contained 0 unchanged local recommendations. Reports remain on persistent disk.

Real production local-only `run-due` ticks correctly found no hourly sources
prematurely due and skipped already-completed daily/report slots. After source
text corrections, one grouped 12-job local alert was created; the repeat reused
that exact artifact with `duplicate:true`. Neither tick sent email or called AI.
Exact 06:00 discovery and 10:00/20:00 New York report boundaries, DST, hourly
intervals, failure backoff, overlap and restart recovery passed injected-time
tests. No permanent schedule or system-clock change was made.

## E. Fixes and quality

**424 tests passed**, including the full existing suite with external services
mocked. Ruff lint/format and diff whitespace checks passed. Independent discovery,
workflow and recovery/security reviewers verified the changes.

Confirmed fixes:

- Follow at most three explicit trusted-domain careers links from directory
  homepages, preserving robots/HTTPS/DNS checks and actual page provenance.
- Fall back to HTML when Lever/Ashby plain-text fields are empty. Real re-polling
  recovered missing description/additional text in 12 Lever records; the next
  139-job poll was entirely unchanged. One genuinely empty source remains empty.
- Exclude future records in injected-time reports; correct explicit country and
  mixed-geography routing; prioritize exact experience/years excerpts.
- Consolidate never-attempted report/alert backlogs into a fresh group while
  retaining history. Attempted/sent/uncertain messages are never blindly replayed.
  Include lifecycle state in alert keys so a closed job cannot remain in a stale
  pending message when an earlier job set returns.
- Keep recipient-change failure history, timestamps and per-job receipts aligned.

Docker build, Compose validation, Alembic upgrade/check and CLI smoke checks
passed. Network-disabled containers ran as UID1000, enforced posting identity
constraints, retained a populated 278-job backup across container restarts, and
recovered the Linux file lock after killing its holder. Backup/restore passed
integrity and foreign-key checks. Destructive tests used copies only. Production
SQLite stays outside OneDrive. Git/build-context checks exclude private files;
the offline image check found no `.env` or private profile directory.

No Gemini requests occurred: screening results stayed at 75, historical request
usage stayed at 41, and no new batch request budget was created. AI was forced
off per process/container; the user's saved Gemini limits were not modified.

## F. Readiness and activation

The verified registry monitoring, personal SMTP delivery, local/queued reporting
and non-AI scheduler are ready to operate on an always-on host. Coverage remains
bounded, and the chosen cloud host itself has not been verified or deployed.

Next: choose a host with Docker and persistent local disk; transfer a consistent
SQLite backup and protected private configuration; set Linux host paths and
UID/GID ownership including the parent data directory; apply/check migrations;
verify that host's network/SMTP access; then explicitly approve/install the
five-minute non-AI cron entry. Maintain reviewed discovery inputs and inspect
health/backups. Keep optional Gemini scheduling disabled. See
[deployment](deployment.md). Nothing was committed, pushed or deployed.

Learning checkpoint: `run-due` polls due sources, retains baseline provenance,
then builds non-AI artifacts. `enqueue_email` reserves each posting revision;
`deliver_pending` records acceptance or safe retry/uncertainty. Outbox history
explains delivery outcomes without treating a timeout as proof of receipt.
