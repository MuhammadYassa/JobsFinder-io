# Development status

The owner authorized the complete remaining personal workflow on 2026-10-27.
[ADR 0008](adr/0008-integrated-personal-workflow.md) records the integrated scope;
[build progress](build-plan.md) records validation and handoff details.

- [x] Registry, SQLite/SQLAlchemy/Alembic and manual Greenhouse monitoring.
- [x] Docker packaging and offline GitHub Actions CI.
- [x] Lever global/EU and Ashby public adapters, normalized locations/provenance.
- [x] Safe baseline/new/updated/missing/closed/reappeared reconciliation.
- [x] Employer candidate imports, official career-page validation and optional search.
- [x] Private-profile US/international structured screening, evidence and cache.
- [x] Local fast alerts, optional Telegram and persistent delivery history.
- [x] Separate seven-day reports, ranking, review queues and factual letter drafts.
- [x] Cron-compatible ticks, source backoff, DST-aware report slots, run recovery.
- [x] Populated-schema migration, overlap lock, mocked end-to-end regression tests.
- [x] Deployment/configuration, backup and operational instructions.
- [ ] Owner supplies private profile, source candidates and optional credentials.
- [ ] Owner chooses always-on host and activates a production schedule.
- [ ] Live provider/account smoke tests and model-quality evaluation after setup.

Known bounds: candidate-based discovery and confirmed-domain search activation
do not provide internet-wide coverage. Cross-source duplicate suppression needs
matching official URLs and employer identity; uncertain matches remain separate.
Uncertain Telegram acknowledgement is never automatically replayed. Request caps
are not dollar budgets. No dashboard, application submission or employer contact
is implemented or required.

Optional future work: curated model quality evaluation, broader discovery
providers, employer-alias reconciliation, manual screening overrides, additional
ATS adapters and operational metrics. These are separate slices.
