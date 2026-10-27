# Product Requirements (Proposed v0.1)

## Purpose

JobsFinder.io is a **personal job-discovery system**, not a SaaS product. Its first priority is reducing the delay between a suitable employer job becoming publicly visible and the owner learning about it. The project should remain economical and independently maintainable despite heavy AI-assisted development.

## Target users and search scope

- One owner with configurable private search profiles, initially **US early-career software engineering** and **international early-career software engineering**.
- Employer types: startups, regional firms, universities, government, nonprofits, finance, healthcare, retail, manufacturing, utilities, etc.; not just technology companies.
- Broad job families: software/backend/full-stack/application development and other programming-intensive roles, including suitable applied AI engineering.
- Include roles with uncertain publication dates separately; preserve seven-day backfill across both daily reports.
- Support differing authorization/graduation rules per geography without assuming eligibility or visa sponsorship.

## Functional requirements

1. Register an employer and one or more **validated public job listing sources**.
2. Poll eligible sources on configured schedules; record complete/incomplete successes and failures.
3. Detect new, updated, removed, and reappearing postings using stable IDs and audit records.
4. Keep original source evidence, original date where verified, first-seen time, last-seen time, and last-changed time distinct.
5. Normalize job descriptions/links/locations and deduplicate without erasing distinct requisitions.
6. Classify new or materially changed software jobs using conservative rules then an AI reviewer, with evidence and uncertainty.
7. Create fast notifications for promising jobs and separate US/international twice-daily summaries.
8. Discover additional employers and sources, validate them, and add them to the registry.
9. Track dispositions and previously reported jobs to avoid repeats; permit manual overrides.
10. Generate short tailored letters for approved report candidates at a later milestone; never send them or applications.

## Nonfunctional requirements

- **Freshness:** target detection within one healthy poll interval for already-monitored publicly visible postings. This is not a guarantee of original publication time or universal job-market coverage.
- **Data integrity:** idempotent writes, safe crash recovery, clear baseline semantics, no false 'closed' state from errors.
- **Auditability:** trace each classification and alert back to an employer URL and stored observations.
- **Reliability:** per-source backoff, retry, network timeout, and visibility into unsuccessful checks.
- **Cost:** track LLM tokens/API/web expenses; prefer no AI call for unchanged records; impose budgets.
- **Safety:** no unauthorized crawling or bypasses; no automatic job applications or recruiter communication.
- **Privacy:** public repository contains generic policy templates only; private profile, keys, and application history stay outside Git.

## Success metrics

- Number of healthy monitored employers, not merely registry entries.
- Source poll coverage, completion rate, failure rate, and staleness.
- New unique postings detected per day and percentage screened.
- First-seen delay compared with *credible* employer publication timestamps (where available), with sample count and uncertainty.
- Screening false-negative rate on manually reviewed samples; ambiguity/review counts.
- Notification delivery success and deduplication.
- Total monthly cost by component.

## Out of scope for the MVP

- Applying automatically or contacting recruiters.
- A public consumer website, user accounts, payment processing or resume-hosting product.
- Unrestricted web crawling, bypassing anti-bot restrictions, or scraping private portals.
- Sophisticated autonomous multi-agent coordination, vector databases, and separate microservices without evidence they are needed.
- Guaranteed discovery of every employer or every job on publication day.

## Open product decisions

- Which US/international criteria to encode first, and how to store the owner's private profile.
- Earliest usable notification channel (Telegram versus email).
- How many initial employers to register and how to diversify by sector/country.
- Whether to automatically generate letters for every possible match or only shortlisted jobs.
