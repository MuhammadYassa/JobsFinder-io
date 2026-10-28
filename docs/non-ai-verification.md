# Non-AI production verification

Verified 2026-10-27 New York (2026-10-28 UTC). No schedules, remote deployments,
commits, paid search or AI calls were activated. Three independent agents built
SMTP, reports and discovery, then reviewed integration and failure recovery.

## Reused and completed

Existing Greenhouse/Lever/Ashby collectors, SQLite history, source backoff,
baseline/change detection, process locking, Docker and cron commands were reused.
Completed secure SMTP grouped delivery, durable attempts/uncertainty handling,
non-AI combined reports/alerts, discovery rotation/trusted directory imports,
06:00 discovery and 10:00/20:00 New York scheduling, explicit zero-AI orchestration,
local-only verification and outbox health. No migration was needed.

Live discovery exposed a genuine gzip bug: streamed bytes were decoded, then
decoded again when rebuilding the response with the original encoding header.
The fix removes encoding/length headers from the decoded response. A compressed
fixture tests it. Three initial failed checks remain in the audit history;
reruns succeeded. Robots delays over 30 seconds now defer rather than stall a
whole tick. Report crash/conflict recovery and separate local scheduler receipts
were also tested and corrected. Report counters include the current tick's writes.

## Real records

| Employer | Provider | Stored jobs |
| --- | --- | ---: |
| Tailscale | Greenhouse | 53 |
| Metabase | Lever | 19 |
| Linear | Ashby | 32 |
| Notion | Ashby | 139 |
| Render | Ashby | 35 |
| Total | 5 validated sources | 278 |

The registry grew **3 to 4 to 5 employers**, with a one-page budget advancing
between Render and Notion. Official career-page links and real public feed
responses validated both new sources. A further discovery pass registered zero
duplicates. The source import is on persistent disk under `private/candidates.json`;
it contains no search configuration or paid calls.

Metabase polled 19 unchanged jobs. The scheduler then polled all four remaining
due sources successfully, establishing the two new baselines. Repeated Notion
and Render polls returned 139 and 35 unchanged jobs; the database remains 278
rows with zero duplicate source/posting identities. All 13 poll records are
complete successes. All postings remain labeled initial baselines, not newly
published jobs. A following scheduler tick correctly reported zero sources due.

Every posting retains an application URL. Greenhouse retains 53 publication
timestamps; Lever/Ashby publication dates remain unknown where unavailable.
Provider update timestamps remain separate. Local combined report artifacts
were generated on the external disk, including baseline labels, source excerpts,
unknown eligibility and application links. Recommendation receipts prevent
unchanged repeats; full email-body artifacts remain available without SMTP.

The database remains `%LOCALAPPDATA%/JobsFinder.io/data/jobsfinder.db`, outside
OneDrive. Gemini request budget remains 41 historical calls and screening history
remains 75 rows, unchanged by this task. The ignored configuration request cap
is explicitly zero; every live scheduler summary reports zero AI calls.

## Validation and activation limits

The non-AI regression suite passes: **236 passed, 7 deselected** after excluding
the three AI test modules. Coverage includes mocked discovery-to-registration,
baseline/new/repeated polling, grouped SMTP alerts/reports, temporary failure,
restart retry, uncertain DATA acknowledgement, duplicate suppression, missing
credentials, 06:00/10:00/20:00 New York slots and DST. AI/screening-specific test
modules and CLI cases were deliberately excluded as requested. Ruff lint/format,
Docker build, Compose validation, and offline-container migrations/schema/CLI
checks passed. The container used a disposable test database; production schema
was not changed. CI remains separate from scheduling.

SMTP host, authentication and recipient were absent, so **no live test email was
sent**. Mock SMTP success is not inbox verification. Configure the SMTP settings
in [deployment](deployment.md), run the single `test-email` diagnostic, and
confirm receipt before enabling the host's five-minute schedule.

Without search credentials, automatic growth is limited to confirmed imports
and trusted directory inputs. The two-entry verification import is finite;
replenish it for continued expansion. Unknown employers require domain review.
Broad query rotation is available but does not provide all-state/all-industry
coverage by itself. JavaScript-only pages and unsupported ATS boards remain
limitations. An always-on host and scheduler activation are still required.

Learning checkpoint: follow `operations.run_due` into `discovery.discover`,
`poll_due`, and `reporting.non_ai`; then trace `delivery.enqueue_email` and
`deliver_pending`. TaskRun holds the grouped message and attempt history;
Delivery reserves individual posting revisions so a restarted tick cannot resend
an unchanged recommendation. The local OS lock protects the whole CLI operation.
