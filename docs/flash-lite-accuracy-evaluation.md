# Flash-Lite accuracy evaluation

Historical first-stage report. See the [completed evaluation](flash-lite-final-accuracy.md)
for the final30-job results, reproduced schema failure and current pilot recommendation.

**Do not activate unattended screening yet.** The evaluation freezes source-only labels
before predictions and excludes the five development jobs from the earlier test.

## Scope and safeguards

Thirty real stored descriptions: 4 potentially suitable, 19 uncertain, 7 unsuitable.
They cover US/international backend, frontend, data, applied AI, security, mobile,
support, management and internships. Unknown sponsorship and three-year ranges
are deliberately retained. The sample is concentrated in the existing registry,
with one source-only reviewer; it is not a statistical estimate for all employers.
Explicit OPT, absolute citizenship/work-permit restrictions and flexible May/June
windows absent from the live sample use clearly synthetic offline regressions.

Labels, exact supporting excerpts, full descriptions, source URLs/content hashes,
profile fingerprint and three balanced ten-job groups are private, outside
OneDrive. Frozen-label SHA256:
`a37c4e9dfde39864f2c4526381367eddcc31d72c6d53be0ea4a5f7c1b65173bc`.

The generation budget is 3 new attempts, no automatic retries or token-count API
requests. Process-only input cap 60000 permits these long ten-job batches; the
saved cap, profile, quota limits and disabled flags are unchanged. Existing daily
usage counts toward the CLI allowance; a separate transport guard enforces the
new-request cap. One read-only model-metadata request diagnoses access separately.

## Corrections before prediction

- Explicit US/foreign geography selects its policy; global/mixed/unknown retains both.
- Exact required/preferred clauses, including nonnumeric skills, have bounded
  source hints and transparent field origins. Local completion is not counted as
  successful model extraction. Ambiguous/truncated extraction requires review.
- Negative or unrelated immigration quotes cannot establish sponsorship support;
  conditional transfer exceptions remain reviewable. Unknown permits never prove a ban.
- Explicit year plus fixed winter-internship dates can establish incompatible timing.
- New evidence-version cache identities preserve old history but require fresh
  evaluation; unchanged new-version jobs reuse successful results.

## Live findings

The first two ten-job attempts returned HTTP 400, no predictions and no token
usage receipts. The second provider message was only “Request contains an invalid
argument.” The metadata request succeeded for the configured key/model, reporting
input limit 1048576 and output limit 65536; this does not prove generation access.

A dynamic outer-array `maxItems` combined with nested evaluation arrays was
removed as a suspected cause. Exact counts/IDs remain strictly validated locally.
Google documents [nested-schema complexity as an HTTP400 cause](https://ai.google.dev/gemini-api/docs/structured-output#limitations),
but this generic error alone does not confirm it. With that constraint removed,
the third/final budgeted attempt succeeded for 10 jobs / 13 policy results. Every ID,
requested policy, quote and URL matched; countries followed source locations and
global jobs retained unknown international countries. No retries were made.

| Actual usage | Result |
| --- | --- |
| Generation attempts | 3: 2 HTTP 400, 1 success |
| Read-only model metadata | 1 success; no generation |
| Token-count calls / automatic retries | 0 / 0 |
| Successful-request input / output | 24086 / 3802 tokens |
| Total returned token usage | 27888; failed requests returned no usage receipts |
| Request latencies | 1.712 s, 3.738 s, 11.634 s |
| Initial live completeness | 10/30 jobs; 13/37 expected policy results |

No dollar cost is asserted. Failed-request billing/token usage cannot be inferred
from missing receipts. The initial two failures left 20 jobs pending, rather than
silently recording rejections. The strict request budget was not increased.

## Accuracy and offline corrections

The frozen labels initially produced 6 apparent raw false rejections. Full-source
adjudication found 2 manual-label errors: 181 has explicit Jan 25–Apr 16 internship
dates, and 12 describes configuration/network support without development work.
Their original labels and source snapshots are retained; a separate adjudication
records these corrections. They are not silently relabeled to agree with Gemini.

After adjudication, raw predictions had **4 false-rejection policy outcomes across
3 jobs**, among 9 retain/review policy cases: analytics 1, applied AI 215 and both
policies for developer-tooling 254. There were 0 false acceptances among 4 unsuitable
policy cases; 5/13 raw outcomes were uncertain/review. At job level, 3/6 retainable
jobs were falsely rejected. Small sample sizes and policy duplication matter.

The live validator corrected 2 of those 4 outcomes. Additional offline fixes:

- A visa C unresolved restriction cannot justify rejection solely for immigration.
- Seniority inferred from role complexity without explicit level/year evidence
  remains reviewable. Ambiguous programming/data scope is not automatically unrelated.
- Salary/general cultural-AI paragraphs are invalid experience, even as exact quotes.
- Missing real heading variants now extract exact nonnumeric qualifications.

All 13 captured raw outcomes were replayed offline under
`qualification-and-eligibility-v3`, with 0 API calls. **11 valid outcomes: 8 review,
3 reject, 0 remaining false rejections/acceptances in this replay.** Outcomes 178 and 181
remain pending because their experience fields contained salary/general culture
text. Their invalid predictions are not counted as successful evaluations.
Three required-experience omissions were corrected using tagged exact-source
fallbacks; this is local completion, not improved model extraction accuracy.

Revalidation appended provenance-linked records, preserving raw responses and
earlier result history. Cache identity now includes validator version. A zero-call
probe reused all 11 current valid outcomes; 8 jobs complete, 22 pending. Pending consists
of 20 HTTP-failed jobs plus 2 invalid outputs. Current valid completeness is 11/37 policy
outcomes. Invalid/deferred receipts cannot satisfy the successful-result cache.

Remaining mistakes include describing Clojure as mandatory despite an explicit
learning alternative, inferred seniority and inconsistent experience summaries.
The guards reduce harm but do not establish semantic accuracy. The new guards
were tested with captured responses and mocks, not another live generation.

Before activation, separately approve another bounded test: evaluate the 20 unseen
failed-batch jobs as holdout data, and the 2 invalid cases as regression cases.
Include truly positive graduate/flexible-start cases and synthetic OPT/permit
edges. Preserve human review; do not present zero replay errors as 100% accuracy.

## Validation and traceability

468 mocked tests passed, including omissions/duplicates, invalid evidence,
pending failures, cached results, quotas and the new accuracy regressions. Ruff
passed. The updated Docker image built/loaded; an offline container confirmed
UID 1000, the new schema/version and absence of `.env` and private profiles.

Private receipts: `verification/accuracy-holdout-labels.json`,
`accuracy-holdout-live.json`, `accuracy-access.json`, `accuracy-holdout-score.json`.
Offline adjudications, corrected results and cache verification are in
`accuracy-offline-final.json`; earlier offline receipts remain intact.
No notifications, schedule activation, deployment, commits or pushes occurred.

Learning checkpoint: follow `pipelines_for` → `qualification_evidence` →
`validate_batch` → `validate_result`. Compare raw output with stored payloads and
`experience_origins`; matching quotes alone do not establish a correct decision.
