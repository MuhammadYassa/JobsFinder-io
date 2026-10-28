# Independent integration review

Final lead acceptance after review fixes: **225 tests passed**, Ruff lint/format
passed (63 files). All reported medium/high issues below were corrected, including
negated sponsorship/citizenship restrictions, unrelated dates, mixed-region
routing and stale-profile notifications. Conservative evidence guards preserve
uncertainty rather than guarantee semantic AI accuracy. Low-severity daily
discovery failure retry remains a documented tradeoff.

The lead built the final Docker image and ran real non-root containers against
ignored synthetic storage: repeated migrations/schema parity, persisted registry
across containers/image rebuild, health and two credential-free scheduled ticks.
The second tick skipped its completed report slot. Historical reviewer-only
Docker access limitations and intermediate test counts below describe the review
checkpoint, not final acceptance status. No live API credentials were used.

Reviewed 2026-10-27. All execution used temporary migrated databases and mocked
HTTP, synthetic employers and a synthetic private profile. No live jobs, real AI
assessment, Telegram delivery or production deployment are represented here.

## Verified acceptance dry run

`tests/test_end_to_end.py` calls the real discovery, ATS adapters, reconciliation,
screening, reporting and notification services under the process lock:

1. Import two official synthetic career pages; discover and validate one
   Greenhouse and one Lever board. Repeating discovery creates no duplicate.
2. Establish a baseline containing one existing posting. The next complete pass
   discovers two new posting identities; another pass creates none.
3. Evaluate all three stored jobs using structured mocked OpenAI responses.
   Eight requests complete preliminary/deeper policy assessments; unchanged jobs
   use cached results with zero additional requests.
4. Produce two US recommendations, one international recommendation, three
   factual cover-letter files, and two local fast alerts. Baseline jobs appear
   in reports with their baseline label and do not trigger fast alerts.
5. Repeat reports and alerts: zero repeated recommendations/alerts.
6. Fail one ATS request: all three jobs remain active. Two later complete missing
   snapshots close one posting; its reappearance preserves identity and history,
   increments revision and produces one fresh report recommendation and alert.
7. Final state: two employers, two sources, three active postings, one failed
   poll, and seven durable delivery receipts. These are synthetic stored counts.

## Findings handed to lead

- **Medium, corrected:** `screening.screen_jobs` supplied locations to the model
  but omitted them from the text against which quotes were validated. The lead
  added locations to evidence text, preventing false invalidation of location
  quotes.
- **Medium, corrected:** Compose omitted the optional Brave search credential.
  `BRAVE_SEARCH_API_KEY` now passes through Compose and appears as an empty
  placeholder in `.env.example`.
- **High, mitigation added:** An unrelated but real quote could support visa or
  start class D and trigger automatic rejection. The lead added independent
  restriction/date corroboration. Further edge cases were reported: positive
  phrases such as "No sponsorship restrictions apply" must not become exclusion
  evidence; an application deadline must not become a mandatory start date.
- **Medium, corrected:** Notifications initially lacked the report service's
  private-profile fingerprint filter. `notify_jobs(profile_path=...)` now applies
  that filter, and CLI/scheduled execution passes the configured profile path.
- **Medium, reported:** Reporting initially included US-only jobs without an
  international result in the international review queue. This can inflate that
  queue. Per-policy applicability should determine each report's stored count.
- **Low, operational tradeoff:** Daily discovery receipts initially marked the
  day complete even when individual checks returned failure counts. CLI exit
  status exposes those failures, but failed pages wait until the next daily pass
  unless receipt behavior is changed.

The lead owns implementation corrections and final regression results. This file
records the review rather than claiming every semantic AI error is preventable.

## Safety and deployment review

- Database transactions and identities preserve idempotent reconciliation;
  absence is inferred only from complete successful snapshots. Existing tests
  cover populated-schema upgrades, safe replay, incomplete/failing polls and
  process-lock recovery.
- Cross-source notification/report suppression requires exact canonical official
  URLs under the same employer. Distinct uncertain matches remain separate
  records; there is no speculative global fuzzy merge.
- AI input is explicitly untrusted; responses receive schema/type checks, exact
  evidence checks, private-profile/version/content cache keys and durable daily
  request reservations. Missing credentials preserve monitoring/review queues.
- Telegram ambiguous POST outcomes are preserved rather than automatically
  replayed. Explicit server rejection can retry; the local alert remains usable.
- DST scheduling uses `ZoneInfo("America/New_York")`; tests cover spring and fall
  changes. CLI holds an OS advisory lock rather than a DB transaction over HTTP.
- Docker uses a non-root process and persistent host data directory; build
  context excludes private files. CI remains separate from production scheduling
  and includes schema parity/container smoke checks. Docker daemon access was
  denied in this review environment, so actual image/runtime checks remain for
  the lead/CI; logical file review is not an executed Docker test.
- Discovery from imported confirmed employer pages is automatic. Unknown search
  domains are audited candidates pending explicit trust, preventing an aggregator
  snippet from becoming proof of official association. This limits autonomous
  expansion and is documented in the discovery module README.

## Executed checks

- `uv run pytest -q`: **209 passed** in 25.92 seconds at this review checkpoint.
- `uv run pytest tests/test_end_to_end.py -q`: **1 passed**.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: **61 files already formatted**.
- `git diff --check`: no whitespace errors (Git emitted line-ending notices).

The first full run overlapped a reporting edit and found the old Telegram
unauthorized-replay expectation; after the reporting agent updated that test,
the second full run passed. The lead should rerun checks after subsequent fixes.

Learning checkpoint: trace the end-to-end test's state transitions, then compare
`Posting` identities/revisions, final `ScreeningResult` rows and `Delivery`
receipts. A new first-seen timestamp, a provider publication date and a new report
receipt represent three different facts.
