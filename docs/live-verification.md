# Live ATS verification — 2026-10-27

Executed against real public endpoints through the existing Docker CLI. No AI,
paid search, notification, production scheduler or deployment was activated.
No application code changes or dependency changes were required.

| Employer | Provider / board token | Baseline rows | Repeat observed / new |
| --- | --- | ---: | ---: |
| [Tailscale](https://job-boards.greenhouse.io/tailscale) | Greenhouse / tailscale | 53 | 53 / 0 |
| [Metabase](https://jobs.lever.co/metabase) | Lever / metabase | 19 | 19 / 0 |
| [Linear](https://linear.app/careers) | Ashby / Linear | 32 | 32 / 0 |

Endpoints:

- `https://boards-api.greenhouse.io/v1/boards/tailscale/jobs?content=true`
- `https://api.lever.co/v0/postings/metabase?mode=json`
- `https://api.ashbyhq.com/posting-api/job-board/Linear`

Employer associations were checked against official careers pages, branded
boards, Metabase's official embedded `accountName: "metabase"` configuration,
and Linear's official career page's Ashby job/application URLs.

## Results

- 104 stored jobs; all initially `baseline`, not newly published.
- Six complete successful poll records, HTTP 200; zero failed/partial/running
  polls, enrichment errors, source failures or stale sources.
- Repeated polls: unchanged 53/19/32, zero new/updated/missing/closed/reappeared.
  Database row IDs, external IDs, first-seen times and revisions were preserved;
  last-verification times advanced. No duplicate identities or extra rows.
- All 104 jobs have IDs, descriptions, locations and HTTPS application links.
  Fresh API responses matched stored descriptions, locations, canonical and
  application URLs, and source update times for every row.
- Greenhouse: 53 original-publication and 53 update timestamps preserved;
  publication values matched the public list's `first_published` evidence too.
- Ashby: 32 last-publication timestamps preserved as source updates, with explicit
  provenance that they are not original publication evidence.
- Lever: publication/update times remain unknown. Its live response includes
  undocumented `createdAt`; the adapter does not retain or interpret that field
  as a publication timestamp. This is a known timestamp limitation, not fabricated
  publication evidence.
- `poll-due` initially selected three unpolled sources; after polling it selected
  zero and made no new poll records. `health` reported 104 active jobs, three
  validated healthy sources and no failed tasks.
- SQLite quick check: `ok`; foreign-key check: zero violations. Screening and
  delivery tables remain empty.

## Storage and next step

The operating database is `%LOCALAPPDATA%/JobsFinder.io/data/jobsfinder.db`, outside
the checkout's OneDrive tree. Ignored `.env` selects that Docker host mount;
the mounted database persisted across every disposable CLI container. The prior
empty checkout database and synthetic smoke databases were left untouched.
Local CLI use must explicitly supply this database with `--db`.

One-off scripts, command logs and aggregate snapshots are in ignored
`data/live-verification/`; downloaded job descriptions are stored in the external
database. Credentials remain empty and the configured AI request budget is zero.

The monitoring integration is ready for a controlled AI activation test after
reviewing/copying the private profile to the mounted private directory, configuring
an API key/model, and choosing a small nonzero request budget. Actual model
behavior, account access/cost and live notification delivery remain unverified.
No schedules were installed, and nothing was committed or pushed.
