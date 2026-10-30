# Development status

The owner authorized the complete remaining personal workflow on 2026-10-27.
[ADR 0008](adr/0008-integrated-personal-workflow.md) records the integrated scope;
[final pilot](activation-pilot.md) and [non-AI acceptance](non-ai-final-verification.md)
record validation and handoff details. Development is complete; deployment is pending.

- [x] Registry, SQLite/SQLAlchemy/Alembic and manual Greenhouse monitoring.
- [x] Docker packaging and offline GitHub Actions CI.
- [x] Main-only tested GHCR publishing and pull-based Azure deployment tooling;
  target-host activation remains pending ([setup](azure-cicd.md)).
- [x] Lever global/EU and Ashby public adapters, normalized locations/provenance.
- [x] Safe baseline/new/updated/missing/closed/reappeared reconciliation.
- [x] Employer candidate imports, official career-page validation and optional search.
- [x] Private-profile US/international structured screening, evidence and cache.
- [x] Local fast alerts, optional Telegram and persistent delivery history.
- [x] Separate seven-day reports, ranking, review queues and factual letter drafts.
- [x] Cron-compatible ticks, source backoff, DST-aware report slots, run recovery.
- [x] Populated-schema migration, overlap lock, mocked end-to-end regression tests.
- [x] Deployment/configuration, backup and operational instructions.
- [x] Private profile, candidate inputs and configured provider pilot verified locally.
- [x] Live monitoring, SMTP acceptance and capped Gemini accuracy/pilot evaluation.
- [ ] Transfer consistent database backup and private configuration to the Azure host.
- [ ] Owner chooses always-on host and activates a production schedule.
- [ ] Verify the Azure image, persistent disk, health, provider connectivity and email receipt before activating schedules.

Known bounds: candidate-based discovery and confirmed-domain search activation
do not provide internet-wide coverage. Cross-source duplicate suppression needs
matching official URLs and employer identity; uncertain matches remain separate.
Uncertain Telegram acknowledgement is never automatically replayed. Request caps
are not dollar budgets. No dashboard, application submission or employer contact
is implemented or required.

Optional future work: curated model quality evaluation, broader discovery
providers, employer-alias reconciliation, manual screening overrides, additional
ATS adapters and operational metrics. These are separate slices.
