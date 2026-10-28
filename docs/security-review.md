# Independent security and data-safety review

Final lead status: all findings listed below have regression fixes. Screening
uses eligibility-v2 cache version; unsupported exclusion/support claims downgrade
to review, mixed locations retain both policies, and uncertain notifications
produce a nonzero CLI exit. Final acceptance: 225 offline tests and Ruff pass.

Scope: screening, operational scheduling, CLI, process lock, and migrations.
Review performed against local code and synthetic inputs; no live API calls.

## Findings sent for correction

- Screening exclusion evidence: a negated citizenship requirement could still
  validate as class D. An unrelated historic ISO date plus the word "start"
  could validate an incompatible start date. Preserve review state unless the
  quoted requirement explicitly supports the classification.
- Mixed-region routing: a US location plus a non-priority foreign location
  (for example New York and Paris) could skip international screening. Unknown
  secondary locations must retain both policies.
- Non-B immigration findings need relevant supporting evidence, not merely any
  quote appearing in the posting.
- CLI notification summaries should expose uncertain acknowledgements as an
  unsuccessful operation while retaining the no-replay receipt.

These findings were delivered to the lead and screening owner. The final test
log and handoff establish which corrections have landed.

## Verified safeguards

- Private profiles are loaded locally, restricted to assessment fields, size
  bounded, and excluded from tracked source/build inputs. HTTP exceptions are
  sanitized; operational logs contain counts and exception types.
- OpenAI requests have no tools, treat descriptions as untrusted data, disable
  response storage, bound inputs/outputs, and reserve calls transactionally in a
  persistent daily budget before requests. Exact evidence quotes and source
  links are independently checked. Failures remain reviewable.
- Cache identities include posting content, profile, policy, prompt and model;
  unavailable calls do not become successful cached rejections.
- CLI workflows hold an OS advisory lock released after process termination.
  Poll recovery marks abandoned runs failed without closing their postings.
  API requests run outside database transactions.
- The populated original four-table migration has an automated preservation
  test, foreign-key checks, and conservative baseline defaults. Upgrade
  instructions require stopping writers and backing up first.
- Operational errors remain separate from successful source scans. Tests cover
  backoff, isolated failures, persisted scheduling, interrupted work and DST.

Validation: 17 operations, process-lock and workflow-persistence tests passed.
The production deployment must use one local persistent database/lock directory;
SQLite network filesystems and independent uncoordinated library callers are
outside this locking guarantee. The AI budget is a request cap, not a dollar cap.
