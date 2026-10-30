# ADR 0012 — Tested GHCR releases and outbound Azure updates

- Status: Accepted by the owner's Azure CI/CD request
- Supersedes: ADR 0007's CI-only publishing restriction

Hosted Actions runs tests/Ruff, Linux amd64 packaging and offline image checks.
Only successful main pushes publish write-once SHA tags and promote GHCR
production with a scoped GITHUB_TOKEN. The VM pulls over outbound HTTPS, without
runner SSH or a self-hosted runner. Main and registry writers are trust roots.

A root-owned standard-library Python controller polls every three minutes,
pins the digest and extracts matching Compose configuration. All scheduled work
shares a host lock to bound memory use on the 1 GiB VM. Both existing app locks
guard consistent backup/migrations; a durable marker blocks work after failure.
No schema, queue, cache, policy or quota changes.

Production containers run UID 1000, no ports, bounded memory, read-only root and
protected host environment/data files. Separate five-minute systemd ticks invoke
monitoring then screening serially. Builds happen on hosted runners only.
Timers recover after reboot; interrupted deployment requires reviewed recovery.

Failed migrations are not automatically reversed. Preserve previous image/config,
backups and failed DB; verify schema compatibility and delivery history before
rollback. No automatic data/backup pruning. Bootstrap updates remain explicit;
ordinary releases update application and runtime Compose together.
See [setup/recovery](../azure-cicd.md).

References: [GHCR](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images),
[Compose limits](https://docs.docker.com/reference/compose-file/services/),
[SQLite backup](https://www.sqlite.org/backup.html).
