# ADR 0001 — Start with a modular Python monolith

- **Status:** Proposed — awaiting owner approval
- **Date:** 2026-10-27

## Context

JobsFinder.io is a personal research/monitoring utility. It needs independently testable collection, persistence, screening, and delivery logic but does not initially need independently deployable services or multi-user infrastructure.

## Options

1. Multiple microservices/agent services: independent deployment and scaling, but more operational cost and failure modes.
2. **One Python application with well-defined internal modules and a shared database:** easier iteration, testing and deployment; can split later if evidence demands it.
3. One large script: fastest initial prototype, but difficult to test/extend across multiple ATS integrations and policies.

## Proposed choice

Option 2. Continue using `uv` and `src/jobsfinder_io/`, adding packages only when needed. Use CLI/scheduled entry points and typed component boundaries. Do not choose a separate queue/broker/server until required by workload or reliability tests.

## Consequences

- Positive: fewer moving parts, inexpensive, repeatable local development, simpler AI-agent changes.
- Tradeoff: individual modules share deployment and database lifecycle; scaling components separately would require refactoring later.
- Migration trigger: measured throughput, uptime or source-isolation needs that cannot reasonably be met by bounded concurrency and retryable jobs within one deployment.
