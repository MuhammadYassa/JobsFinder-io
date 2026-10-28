# Gemini batch screening

Monitoring, email and reports keep working independently. AI is still disabled:
`GEMINI_BATCH_ENABLED=false`, `GEMINI_MAX_CALLS=0`. No paid/live requests were
made to validate this implementation.

Validation: **372 tests passed**, Ruff clean, Docker build/Compose and offline
container migrations/CLI checks passed. The real disabled command queued 252
candidates without changing the existing 75 screening rows or request usage.

`run-due` records active software/uncertain postings in a durable queue, including
initial baselines without claiming new publication. Manual `screen` also refreshes
that queue. Changed content gets new work; closed/superseded jobs stop consuming
requests. Success is cached per job, policy, profile and model. Queue errors and
budget counts appear in `health`.

Each request contains a JSON array of job records inside an envelope with the
private profile. Output is an array keyed by stable database job IDs, containing
separate US/international evaluations where needed. Unknown sponsorship,
preferred requirements and flexible graduate starts retain the existing cautious
rules. Evidence must come from that particular job and match its source URL.
Missing/duplicate IDs, unsupported quotes, refusals and truncation never mean
successful screening. Successful items save independently; others remain queued.

## Size and request estimates

The default is **10 jobs per generation request**. It shrinks for long descriptions
or output limits. Tests exercise both 10 and 25 jobs; 25 needs a larger output
budget, for example `GEMINI_BATCH_OUTPUT_TOKENS=65536`, and sufficient input space.
Those tests establish serialization/storage, not live accuracy at either size.

| New jobs | Default 10-job batches | Configured 25-job batches, if they fit |
| ---: | ---: | ---: |
| 25 | 3 | 1 |
| 100 | 10 | 4 |
| 250 | 25 | 10 |

These are generation-request estimates, assuming successful complete responses,
no long-job splits, no cached jobs and no token-count calls. Extra count/retry
requests consume the same local allowance. The normal 18-request daily allocation
means 250 uncached jobs at default size require at least two Pacific days.
No promise of exactly two daily requests or a dollar cost is made.

Configuration is in `.env.example`. Main controls: `GEMINI_BATCH_SIZE` (1–25),
input/output token budgets, `GEMINI_BATCH_MODEL`, `GEMINI_RPM`, `GEMINI_TPM`,
`GEMINI_DAILY_LIMIT` (maximum 20), and `GEMINI_RETRY_RESERVE` (default 2).
Set RPM/TPM from the project's actual AI Studio limits before activation; defaults
are application limits, not claims about the account's quota. `GEMINI_MAX_CALLS`
limits both one invocation and the Pacific day's total. UTC counters are retained
only for historical usage. All keys in one Google project share its quota.

Token counting defaults to `near_limit`: use the official `count_tokens` call
when the conservative input estimate reaches 80% of the configured input cap.
`always` and `estimate` are also supported. Count requests include instruction,
schema and job text as supported Developer API text input, plus a 512-token
framing margin. Successful counts are cached. Unexpectedly oversized counts
reduce the batch on a later pass; single oversized jobs stay pending for review.
Count requests are conservatively charged to the local daily/RPM/TPM budget even
if Google meters that endpoint differently. Estimates are not tokenizer guarantees.

429/503/504 and transport failures retain work and provider backoff. A failed
batch stops that invocation; later ticks retry after the persisted delay. There
is no immediate SDK/application retry storm. Default maximum is two generation
attempts per job per Pacific day. Partial/invalid responses wait 15 minutes;
truncated responses also reduce the next batch size. Token usage is counted once
per request in the summary and request receipt, not once per job.

## Later controlled live test — only after owner approval

1. Check model access and actual quota/reset in AI Studio. Keep scheduled
   screening disabled. Confirm `GEMINI_MAX_CALLS=0` outside this one invocation.
2. Choose 3–5 stored IDs spanning strong fit, senior, unknown sponsorship and
   explicit restrictions; inspect their actual descriptions. Review your private
   profile, particularly flexible May/June 2027 availability.
3. First make a zero-call queue check, passing the real absolute DB/profile paths:

```sh
uv run jobsfinder-io --db /absolute/jobsfinder.db screen --profile /private/profile.json --posting-id 1 --posting-id 2 --posting-id 3 --batch-size 5 --max-calls 0
```

4. After approval, repeat that selected-ID command with `--max-calls 1 --no-retries`.
   For this small diagnostic use `GEMINI_TOKEN_COUNT_MODE=estimate` so the single
   request is generation; no automatic retry is made. Do not select all jobs.
5. Compare every ID/policy/evidence quote against the source and profile. Inspect
   ScreeningResult and `health`; verify invalid/omitted jobs remain queued. Repeat
   unchanged selected IDs to confirm zero generation calls for successful items.
   Review token metadata on `gemini-batch-request:*` receipts. A complete response
   demonstrates service access, not general eligibility accuracy.
6. Only then consider a 10-job comparison. Expand to 25 only after measuring
   accuracy, latency and output size. Larger prompts risk mixed evidence,
   incomplete arrays, truncation and slower responses; schema alone cannot
   guarantee correct reasoning. Existing service/quota problems can still occur.

See [deployment](deployment.md) for later optional session cron configuration.
No applications, recruiter messages or notifications are triggered by `screen`.

Learning checkpoint: follow `screen_jobs` → `screen_batch` → `pack_batches` →
`reserve_request` → `validate_batch`. A queue receipt says work is pending;
an independent ScreeningResult says a specific job/policy passed validation.
The batch request receipt holds the token usage shared by all its results.
