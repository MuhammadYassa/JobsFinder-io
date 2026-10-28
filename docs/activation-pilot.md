# Final pilot and approved AI configuration

The owner approved activation after one final live pilot. Ten previously
unscreened real postings (53,54,66,70,75,85,87,98,211,310) produced all 15 requested
policy results in **one request**, no retries/count-token calls, 8.868 seconds.
Usage: 19722 input + 4187 output = 23909 tokens. All IDs, quotes, URLs and hard-exclusion
proofs were checked; potentially suitable jobs remained visible. Results:
11 Needs Review outcomes and 4 supported rejections. All 15 persisted outcomes were
reused with 0 additional calls. This was the only live request in this task.

Current application/Compose/example defaults and private `.env`:

```dotenv
GEMINI_BATCH_ENABLED=true
GEMINI_BATCH_MODEL=gemini-3.5-flash-lite
GEMINI_MAX_CALLS=20
GEMINI_DAILY_LIMIT=20
GEMINI_RETRY_RESERVE=2
GEMINI_BATCH_SIZE=10
GEMINI_SESSION_BATCHES=8
GEMINI_BATCH_INPUT_TOKENS=24000
GEMINI_TOKEN_COUNT_MODE=near_limit
GEMINI_RPM=15
GEMINI_TPM=250000
```

The 20-call ceiling counts generation, failures and token-count calls conservatively.
18 normal calls are available, 2 reserved for retries, resetting at Pacific midnight.
At most 8 generation batches per morning/evening session, persisted across ticks:
**up to 160 jobs/day**, often fewer for long descriptions, counts, failures or retries.
The project's 500 RPD allowance does not increase this application limit. Existing
usage is not reset. Old work drains gradually; successful current-version caches
remain reusable, and invalid/failed work stays pending.

Screening windows: 09:30–10:00 and 19:30–20:00 America/New_York. Reports: 10:00/20:00,
independent of Gemini availability. Existing DST handling remains. The pilot used
a temporary 60000 input cap to fit 10 jobs in one request; production retains 24000
and adaptive splitting. Unknown eligibility remains Needs Review, not sponsorship
approval. No safeguards or screening evidence versions changed.

The private profile was copied to persistent storage outside OneDrive so the
configured container path `/app/data/private/profile.json` exists. Secrets and
unrelated `.env` settings were preserved. Do not copy private files into images/Git.

Checks: 8 existing scheduler/DST tests passed; offline temporary-database smoke
verified enabled CLI routing, report slots, repeated-tick session cap and 20/2
daily quota behavior. Ruff and `docker compose config --quiet` passed. After
Docker Desktop was started, the updated image built successfully. An isolated,
network-disabled container smoke check verified UID 1000, screening limits,
CLI defaults, migrations to a temporary SQLite database, migration consistency
and health. No private profile or `.env` was present in the image. Production
storage was not mounted. Build the image on the deployment host before starting
the worker. No additional API calls or emails were used for configuration checks.

No cloud server or permanent OS schedule was provisioned. Azure deployment needs
an always-on Docker host, persistent data storage, private configuration and the
two tick commands documented in [deployment](deployment.md). Run health/migrations
and build the image there before installing the schedules.

Learning checkpoint: CLI reads the enable flag/budget; `load_batch_config` reads
the conservative application cap; `screen_due` selects and budgets each session.
`run-due` keeps monitoring/reports independent. Private pilot receipts are under
the external data directory's `verification/activation-pilot-*.json`.
