# Gemini live verification — 2026-10-27

Outcome: **not ready for unattended production screening**. The configured key
could read `gemini-3.8-flash` model metadata, but generation suffered persistent
503/504 failures followed by 429 quota/rate errors. No key or prompt was logged.

## Scope and actual results

Only eight existing postings were selected; their normal routing produced 16
US/international policy evaluations. No other posting was screened.

| ID | Stored role | Human assessment from source | Live outcome |
| --- | --- | --- | --- |
| 34 | Tailscale — Software Engineer, AI Enablement | Explicit 5+ professional years exceeds entry-level target | Correct grounded preliminary rejection; deeper review failed |
| 40 | Tailscale — Software Engineer, Networking (Features) | Programming-heavy; specialist Go/networking requirements need review | API failures; retained for review |
| 56 | Metabase — CI Engineer | Professional CI ownership required, no fixed years; stretch/review | API failures; retained for review |
| 67 | Metabase — Senior SRE/DevOps Engineer | Explicit five years of production infrastructure required | Correct grounded preliminary rejection; deeper review failed |
| 68 | Metabase — Software Engineer (Backend) | Potential match/stretch; Clojure willingness accepted, preferred Java/JDBC skills, no minimum years | Raw recommendation omitted quotes and was blocked; later API failures |
| 69 | Metabase — Software Engineer (Frontend) | Potential match/stretch; React/JS and complex projects, optional skills distinguished | API/quota failures; retained for review |
| 77 | Linear — Product Engineer | Required 2–5 years; stretch/review for internship/project profile | Quota errors; retained for review |
| 82 | Linear — Senior/Staff Product Engineer, Applied AI | Explicit 5+ years exceeds entry-level target | Quota errors; retained for review |

All 16 final policy results remain `needs_review`; **zero deeper reviews
completed**. There is no defensible accuracy percentage or broad claim that
Gemini's eligibility decisions are validated. The two grounded senior-role
prechecks correctly cited mandatory experience, not sponsorship/start-date
silence. Their visa/start classes stayed B. The backend recommendation was a
grounding/schema failure, not an accepted recommendation.

The 104 stored descriptions did not supply an explicit no-sponsorship case, a
2027 graduate start window, an immediate fixed start, or a clearly advertised
0–2-year/new-grad SWE opening. Those coverage gaps were not filled with fabricated
live jobs. No-sponsorship, E-Verify, unknown sponsorship and May/flexible-start
edge cases were exercised with explicitly synthetic automated regressions.

## Usage and budget

- 40 budgeted generation attempts: three returned JSON, 35 returned HTTP errors
  (11 HTTP 504, eight HTTP 503, 16 HTTP 429), and two failed locally in the initial
  verification helper because its filename shadowed a standard-library module.
  That helper was renamed; these are retained as client failures, not live AI
  successes. There was also one successful read-only model-metadata request.
- Returned token metadata: 6,139 prompt tokens, 747 output tokens, 6,886 total.
- At current paid Standard list rates, the **three returned responses** are
  approximately **$0.0074055**. This is not an account bill or a total-cost
  guarantee: no usage metadata was returned for failures, and free-tier/account
  billing status was not inspected. See [Google pricing](https://ai.google.dev/gemini-api/docs/pricing).
- The persisted daily reservation counter reached 40 and prevented further
  requests. The final replay made zero API calls and wrote zero new result rows.
- No successful final result exists to establish live cache hits. Failed results
  deliberately remain retryable, not cached approvals. Automated cache tests pass.
- The ignored global `GEMINI_MAX_CALLS=0` setting was preserved. Only this explicit
  verification invocation used a nonzero cap; recurring operation remains off.

## Confirmed fixes

1. Add `screen_jobs(posting_ids=[...])` and CLI `screen --posting-id ID` (repeatable)
   to prevent an accidental whole-registry live run. Empty selections send nothing.
2. The 45-second deadline was too short for returned generations taking 65–72
   seconds. Use a bounded 90-second timeout, 4,096-token cap and low thinking for
   Gemini 3.x. Some 90-second requests still failed; this does not solve provider
   availability. No successful response exhausted the revised token cap.
3. Require at least one exact evidence quote in the model schema and prompt,
   including recommendations with unknown sponsorship. Independent validation
   remains mandatory; the ungrounded recommendation was never accepted.
4. A source containing a May date followed by an explicit flexible graduate-start
   exception could be hard-rejected against a June availability setting. Check
   start exceptions across the full source and retain review. May-month windows
   without fixed dates also stay reviewable. Private availability was not changed.
5. Preserve returned token metadata when output is truncated or fails validation.
6. Do not write a preliminary result if the request budget prevented any attempt.
   The live replay exposed 30 unnecessary history rows before this fix; the
   subsequent replay added none. Audit history was retained, not deleted.

Prompt/cache version is `eligibility-v4-start-flexibility`. No schema migration,
ATS collection, discovery, source/posting identity or scheduling change was made.
All 104 postings remain active; only the selected eight have screening history.
SQLite quick check is `ok`, and notification deliveries remain zero.

Private event/response details and summary are under the external data directory:
`verification/gemini-live/`. They contain no API key, request headers or prompts.
No alerts, scheduled jobs, deployment, commits or pushes were triggered.

## Retest requirement

Validation after fixes: **254 automated tests passed**; Ruff lint/format and
whitespace checks passed. Tests use mocked APIs and do not add live usage.

Resolve account quota/rate and provider availability, then rerun the same bounded
batch and obtain complete grounded final results and actual cache hits. Add real
graduate/no-sponsorship examples when available before claiming those cases were
live-verified. Review the classification evidence, not merely schema validity.

Learning checkpoint: trace the selected-ID SQL filter in `screen_jobs()` to
`_request()`'s reservation, timeout and response validation, then inspect the
`ScreeningResult` final row. A valid JSON response, a grounded preliminary finding
and a completed cached eligibility review are separate acceptance steps.
