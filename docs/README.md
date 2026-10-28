# JobsFinder.io documentation

Development is complete. Azure hosting and permanent schedules remain to be
configured and verified. Start with the root [README](../README.md) for setup
and [deployment](deployment.md) for production operation and recovery.

Monitoring supports Greenhouse, Lever (global/EU) and Ashby. `run-due` handles
discovery, polling, SMTP alerts and seven-day reports without AI. Optional
`screen-due` uses Gemini Flash-Lite in separate morning/evening sessions. Approved
configuration enables screening with a 20-call daily application cap, including
two reserved retry calls; no permanent host schedule is installed.

## Maintenance and operation

| Document | Purpose |
| --- | --- |
| [deployment.md](deployment.md) | Azure readiness, configuration, schedules, storage, backups and recovery |
| [architecture.md](architecture.md) | Current modules, data flow and responsibility boundaries |
| [roadmap.md](roadmap.md) | Completed scope, remaining deployment steps and optional future work |
| [gemini-batch-screening.md](gemini-batch-screening.md) | Queue, batching, limits, cache and screening sessions |
| [Discovery configuration](../src/jobsfinder_io/discovery/README.md) | Private inputs, trusted directories and optional search |
| [operations-security.md](operations-security.md) | Operational and security design context |
| [testing.md](testing.md) | Regression expectations and quality checks |
| [adr/](adr/) | Accepted architecture and subsequent amendments |

## Acceptance evidence

- [Final non-AI verification](non-ai-final-verification.md): real polling/discovery,
  SMTP acceptance, persistence and recovery. SMTP acceptance is not inbox proof.
- [Final screening accuracy evaluation](flash-lite-final-accuracy.md): 30 jobs,
  37 policy outcomes, source-proof rejection guards and remaining uncertainty.
- [Final activation pilot](activation-pilot.md): ten jobs, 15 validated outcomes,
  cache reuse and approved capped configuration. Azure remains unverified.
- [QA review](qa-review.md) and [security review](security-review.md): review findings
  and safeguards. Earlier verification and reliability records are historical;
  their disabled flags and intermediate counts do not describe current defaults.

## Design history

[Product requirements](product-requirements.md), [initial data model](data-model.md),
[source monitoring](source-monitoring.md), [screening policy](ai-screening.md) and
[Phase 2 Greenhouse design](phase-2-greenhouse-design.md) retain design rationale.
Where they describe initial phases or proposals, current code and accepted ADR
amendments take precedence. ADR 0008 extends the original four-table schema;
ADRs 0009–0011 record the provider, batch workflow and final activation decisions.

Keep operational facts in deployment/configuration documentation. Record major
architecture changes in ADRs and preserve provenance without new progress logs.
