# Flash-Lite controlled live verification

This records the initial five-job test. See the subsequent
[larger accuracy evaluation](flash-lite-accuracy-evaluation.md) for current status.

**Ready for a larger, separately approved accuracy test; not unattended AI.**
The primary model is `gemini-3.5-flash-lite`. Scheduled screening remains false
and the saved call allowance stays zero. No deployment, schedules, notifications,
commits or pushes occurred.

## Changes and compatibility

The installed Google GenAI SDK and model accepted JSON MIME/schema output and
low thinking. Queue/cache identities, evidence checks, batch/token bounds,
provider backoff and Pacific reset are retained. Model changes use separate
cache identities; previous screening history remains intact.

Code, Compose, `.env.example` and authorized private non-secret settings now use
the owner-supplied **15 RPM / 250000 input TPM / 500 RPD**. The former hardcoded
20/day validation ceiling was fixed. Two requests remain reserved for retries.
The separate `GEMINI_MAX_CALLS` allowance stayed zero except for the explicit
one-request command. Quota-boundary tests passed; the account dashboard was not
accessed or its quotas exhausted live.

Pre-live labels exposed a graduation check gap: an explicit 2026-only cutoff
could be softened to unknown for a documented 2027 graduate. The validator now
checks explicit graduation facts without inferring graduation from availability.
Flexible May starts and windows including the candidate's year remain reviewable.
Ten manually labeled synthetic cases cover sponsorship, seniority, preferences,
graduate eligibility and flexible starts. Their mocked success is not a live
accuracy score. See [ADR 0011](adr/0011-flash-lite-screening.md).

## The one live batch

Labels, source snapshots and expected outcomes were frozen privately before the
call. The CLI used five selected IDs, `--max-calls 1 --no-retries`, and estimate
mode to avoid a separate token-count request. A transport guard blocked any
second request or unselected jobs.

| ID | Real role | Relevant-policy result |
| ---: | --- | --- |
| 130 | Notion early-career AI SWE | Recommend; unknown sponsorship. Immediate hiring without a fixed date did not exclude it. |
| 183 | Notion new grad, December 2026 | Reject; explicit graduation/start window conflicts with the profile. |
| 244 | Render product SWE, all levels | Review; six-year requirement. Unsupported visa class C was downgraded to B. |
| 308 | GoCardless London SRE II | Review; infrastructure gaps and unknown sponsorship. |
| 321 | Wealthsimple staff production developer | Reject; eight-year experience requirement, without inventing a visa prohibition. |

The existing conservative router requested both policies for every job: **five
jobs produced ten results**. Every ID appeared once; all requested policies and
exact source quotes/URLs were present. Non-null experience excerpts also matched
the source. All ten stored results were manually inspected.

Broad dispositions and start classes matched the predefined acceptable labels.
Two visa labels did not: Render was expected to retain C, but the model quoted
experience rather than its immigration restriction. Validation safely changed
both results to B/review. This is missing evidence coverage, not unrestricted
eligibility. SRE required/preferred experience fields were null despite relevant
requirements. No suitable/uncertain job was falsely rejected in this sample.

## Actual usage and validation

- Generation requests: **1**; retry/token-count requests: **0**.
- Input: **10110 tokens**; output: **2799**; total: **12909**.
- SDK request/response time: **7.228 seconds**.
- API failures: **0**; valid JSON; **5 jobs / 10 results stored**; no omissions.
- A repeat with allowance zero reused **10 cached results** with **0 requests**.
- **440 tests passed**, including the full mocked regression suite; Ruff passed.

One diagnostic launch stopped locally because instrumentation replaced the SDK
class before a lazy type annotation loaded. It made zero network requests and
used zero quota. Importing the module first fixed the helper; its audit remains
separate. No additional generation was used to chase a passing result.

## Remaining accuracy work

Prioritize immigration quote coverage, required/preferred field completeness,
country routing and more graduate-window examples. Redundant out-of-region
reviews currently waste output and can confuse reasons. Explicit flexible May
dates and absolute sponsorship bans were synthetic regressions, not live cases.
Five jobs cannot establish general accuracy. Larger testing needs separate
approval; scheduled screening remains disabled.

Private labels, raw non-thinking JSON, results and review are in the external
data directory under `verification/flash-lite-*.json`; do not publish them.

Learning checkpoint: `screen_jobs` selects the model, `BatchConfig` interprets
quotas, `reserve_request` charges attempts, and `validate_batch` checks individual
evidence. `ScreeningResult.payload["batch_request_key"]` links each result to one
shared usage receipt. Valid JSON alone does not establish correct eligibility.

Official references: [model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
[thinking](https://ai.google.dev/gemini-api/docs/thinking),
[structured JSON](https://ai.google.dev/gemini-api/docs/structured-output).
