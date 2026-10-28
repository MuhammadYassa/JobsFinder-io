# Completed Flash-Lite accuracy verification

Screening remains disabled: saved `GEMINI_BATCH_ENABLED=false`, `GEMINI_MAX_CALLS=0`.
The system is suitable for a capped pilot with human review, **not independent
eligibility decisions or unattended disposal of uncertain jobs**. No schedules,
notifications, deployment, paid-service activation, commits or pushes occurred.

## Reference and method

All 30 labeled jobs now have all 37 requested policy outcomes. The corrected
reference was frozen before these additional predictions; only the two previously
documented source-based corrections (12 and 181) were applied. No other labels were
changed to agree with Gemini. Original labels, adjudications and histories remain.
Reference SHA256:
`669b1cd57641f71dc2332f9d75be195e97ea9a0203a84946fcc7ca25b3ffdc03`.

Four batches of at most six covered the remaining 22 jobs. One international
outcome was omitted; its valid US outcome saved independently and missing work
remained pending. A separately reviewed, single-request manual follow-up completed
only that missing policy. This operator action was explicitly counted; it did not
enable automatic retry or change provider backoff/configuration. All calls used
SDK attempts 1. There were no token-count calls or live quota-boundary tests.

Final scoring combines the latest applicable raw answers for all 30 jobs (including
the previously completed 8 jobs) and independently replays them through the final
local validation. Earlier generations retain their original prompt/request
provenance; offline revalidation is not represented as new model output.

## HTTP400 diagnosis

The final two requests form a controlled comparison. They used the same model,
SDK, profile, job, requested policy, instructions and generation options. A digest
assertion verified that **the only body difference was restoring outer
`responseJsonSchema.maxItems=10`**. The simplified request succeeded; the otherwise
identical old-schema request returned HTTP400.

This reproduces and isolates the failing schema setting used by both earlier
ten-job failures. Google still returned only a generic invalid-argument response;
the exact internal compiler/state limit is not disclosed. Schema complexity is
consistent with [Google's documented limitations](https://ai.google.dev/gemini-api/docs/structured-output#limitations),
but is an explanation, not a recovered server trace. Keep the simplified schema;
counts, IDs, policy coverage, exact quotes, URLs and rejection proofs are enforced
locally. New error diagnostics retain only fixed enums, never secret-bearing
provider messages, fields or response bodies.

## Accuracy

| Measure | Raw Gemini | Final validation |
| --- | ---: | ---: |
| False rejections, unique jobs | 7 / 21 retainable jobs | 0 / 21 |
| False rejections, policy outcomes | 9 / 27 retainable outcomes | 0 / 27 |
| False acceptances, unique jobs | 0 / 9 unsuitable jobs | 0 / 9 |
| False acceptances, policy outcomes | 0 / 10 unsuitable outcomes | 0 / 10 |
| Disposition within frozen acceptable set | 26 / 37 (70.3%) | 33 / 37 (89.2%) |
| Needs Review outcomes | 12 | 27 |
| All required outcomes present | 37 / 37 | 37 / 37 |

False acceptance means recommending/stretching an explicitly unsuitable job;
Needs Review is a referral, not eligibility approval. Two raw recommendations
for uncertain internships/mobile fit became review. Final outcomes: 27 review,
6 reject, 3 stretch, 1 recommend. Four unsuitable jobs conservatively remain review
because the supplied evidence did not independently establish a hard exclusion;
these explain the remaining disposition disagreement. All six final rejections
have explicit source-grounded proof. Unknown sponsorship never becomes approval.

The raw false rejections concerned analytics 1, networking 37, integration 194,
applied AI 215, security 217 and both policies for conditional-sponsorship roles 247
and 254. Required/preferred, three-year ranges and skill-depth assumptions remain
model weaknesses. Some experience summaries still need human interpretation.

This is a small, single-reviewer development evaluation; guards were improved
using these cases. Zero final false rejections here is **not** an estimate of zero
future errors. Synthetic OPT, permits and flexible graduate-date cases are offline
regressions, not additional live accuracy observations.

## Changes and recovery

- Every hard rejection passes `require_rejection_proof`. A title, unrelated
  exact quote, preferred years, three-year range or vague skill gap is insufficient.
  Required professional experience above the policy's 0–3 review range needs an
  exact matching required clause. Immigration/start exclusions retain specialized
  corroboration; unsupported findings become review. All proof excerpts persist.
- Conditional sponsorship exceptions are checked beyond selectively quoted text.
  US authorization wording alone is not an OPT ban. Seniority/analyst ambiguity
  cannot cause unsupported automatic rejection.
- Non-timing quotes cannot establish a compatible/urgent start. A private
  first-full-time goal makes internship/student status reviewable. Countries
  cannot be invented from a broad region or a US international-policy evaluation.
- Optional web qualifications cannot prove Android requirements. Actual source
  headings, imperative experience requirements and technical clauses are retained;
  salary/cultural statements stay invalid experience. Local completion is tagged.
- Fixed a queue recovery bug: context changes now persist the reset attempt
  counter before owned-client initialization. A zero-call launch exposed it;
  no API budget was consumed. Global provider usage is never reset by this fix.

Final validation version: `hard-exclusion-proof-v8`; batch prompt:
`eligibility-v4-start-flexibility:batch-v3-hard-evidence`. All 37 valid outcomes
were cached; a repeat with SDK construction forbidden made 0 calls, left 0 pending
and marked all 30 queue records complete. Invalid/incomplete outcomes do not satisfy
the cache; automated regressions and the live omission verify this behavior.

## Usage and checks

- **6 additional generation requests:** 5 successful screening/follow-up requests
  and 1 deliberate old-schema diagnostic returning 400. No unexpected quota failures.
- Returned usage: 59659 input + 7851 output = 67510 tokens. The diagnostic returned no
  token receipt; its billing cannot be inferred. No dollar cost is asserted.
- Successful request latencies: 4.598, 5.657, 5.604, 3.661, 3.073 seconds; diagnostic 1.187 s.
- **491 tests passed**, Ruff check/format passed; final Docker build and offline
  non-root/schema/CLI checks passed.

Private audit files live outside OneDrive under `data/verification` in the
application data directory: `accuracy-finish-reference.json`,
`accuracy-finish-live.json`, `accuracy-finish-acceptance.json`. Earlier scoring
artifacts remain historical; no private profile or audit data entered Git/image.

Learning checkpoint: `validate_batch` checks identities and evidence;
`validate_result` corroborates eligibility; `require_rejection_proof` gates
exclusion; `validate_context` preserves geography/search-goal uncertainty.
`rejection_evidence` and `experience_origins` distinguish source proof from model
claims. Monitoring remains independent of all these AI checks.
