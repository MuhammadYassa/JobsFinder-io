# ADR 0011 — Flash-Lite primary screening model

- Status: Accepted by the owner's explicit model/quota/live-test request
- Supersedes: ADR0010's default model and 20-request quota ceiling

Use `gemini-3.5-flash-lite` with the official Google GenAI SDK, JSON MIME/schema
and low thinking. The model supports these settings; the controlled live batch
confirmed access and valid structured output. Keep queue identities, evidence
validation, successful-result caching, retry/backoff, Pacific-day reset and
independent monitoring unchanged. Model changes naturally invalidate model-keyed
cache entries; old screening history remains.

Configure the owner-supplied project limits:15RPM,250000 input TPM,500RPD. The
previous hard ceiling20/day was a local validation bug for this new tier. The
application ceiling is now500, with two normal retry reservations retained.
`GEMINI_MAX_CALLS` remains a separate invocation/day allowance. The one diagnostic
overrides it to1; saved allowance stays0 and scheduled activation staysfalse.
These quotas describe this model/project; selecting another model requires its
actual quota settings, not assumptions of500/day support.

Graduation validation now recognizes an explicit earlier-year graduation cutoff
against private graduation facts. Availability alone never establishes graduation.
Flexible starts and alternatives including the candidate's graduation year remain
reviewable. No nationality/profile facts are hardcoded in public fixtures.

Exactly one live generation returned five jobs/ten policy evaluations. No further
live expansion was performed. Missing immigration evidence still becomes review;
larger accuracy testing is warranted before production activation.

## Final-evaluation corrections

The owner authorized the larger controlled accuracy evaluation. Batch prompt
`eligibility-v4-start-flexibility:batch-v2-evidence` narrows explicit US-only and
international-only geography; mixed/global/unknown locations retain both policies.
Older results remain historical but cannot satisfy the new evidence-version cache.
Repeated unchanged results within the new version still reuse their cache.

Required/preferred skill and experience excerpts now include exact source clauses
even without numeric years. Bounded qualification hints retain section semantics;
local completion is tagged `exact_source_fallback`, separately from model output.
Hints are not proof that every qualification is a mandatory exclusion. Truncated
extraction and ambiguous requirements require human review.

Negative, unrelated or merely general immigration evidence cannot establish
employer support. Conditional visa-transfer exceptions remain reviewable rather
than becoming an absolute ban. Explicit winter internship dates can corroborate
an incompatible start when their year is stated in the source title.

The provider response schema no longer multiplies its nested array constraints
by a dynamic outer `maxItems`. Application validation still enforces job count,
exact IDs, duplicate IDs, policy coverage and evidence. Google documents that
[complex nested schemas can fail with HTTP400](https://ai.google.dev/gemini-api/docs/structured-output#limitations).
Live confirmation and accuracy results are recorded separately; mocked tests
alone do not establish either compatibility or accuracy.

The larger evaluation spent3generation attempts:2generic HTTP400 failures and
1successful10-job/13-policy request after simplifying the outer array constraint.
This supports the schema correction without proving the generic failures' exact
cause. Raw false rejections and invalid qualification fields prevented acceptance.

Successful-result caching additionally requires the current `validation_version`.
An offline replay can append corrected records with original generation prompt,
request key and prior-result ID, without claiming a new model response. Invalid
replays append deferred review receipts and remain queued. Old history is kept.
See the [accuracy report](../flash-lite-accuracy-evaluation.md); AI stays disabled.

## Completed controlled evaluation

The owner authorized up to6additional requests to finish the frozen reference.
Five screening calls completed all30jobs/37policy outcomes; the sixth isolated
the old outer `maxItems=10` constraint as a reproducible HTTP400 trigger with an
otherwise identical request. The simplified schema stays. Server-internal reasons
remain undisclosed; fixed diagnostic enums preserve useful errors without secrets.

`batch-v3-hard-evidence` and `hard-exclusion-proof-v8` require explicit matching
proof for every hard rejection; ambiguous skill/role gaps remain reviewable.
Source geography, timing and private full-time goals are checked independently.
Queue context transitions now persist attempt resets before client recursion;
global quota counters are unchanged. Original model outputs/provenance remain.
See the [final evaluation](../flash-lite-final-accuracy.md): raw7-job/9-policy
false rejections became0in local validation. This supports a capped human-reviewed
pilot, not autonomous eligibility decisions. Saved AI activation remains off.

References: [model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite),
[thinking levels](https://ai.google.dev/gemini-api/docs/thinking),
[structured output](https://ai.google.dev/gemini-api/docs/structured-output).
