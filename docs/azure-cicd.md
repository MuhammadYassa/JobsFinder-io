# Azure production CI/CD

Only successful main builds publish `ghcr.io/OWNER/REPO:sha-COMMIT` and promote
`:production`. The VM checks that approved reference every three minutes over
outbound HTTPS and pins its digest. No runner SSH, public application ports or
self-hosted GitHub runner. Nothing has been activated remotely yet.

## GitHub settings

- Enable Actions. Protect `main` with review and the `test-and-build` status
  check; restrict direct pushes and package writers. A main push approves release.
- CI uses only `GITHUB_TOKEN`: contents read; packages write only in the
  publishing job. PR jobs never publish. No Azure credentials in Actions.
- After first publication, review build inputs/image contents before marking
  the GHCR package public. The default-deny build context and explicit COPY
  list exclude private files; image checks verify non-root, empty runtime data,
  no `.env`, migrations and health. Never embed credentials in allowed source.
- For private GHCR, use a dedicated VM credential with **read:packages** only
  and package access (SSO authorization where required). Authenticate with
  `sudo docker login ghcr.io -u READ_ONLY_ACCOUNT --password-stdin`, supplying
  the token securely on stdin. Protect root's Docker config mode 600. No write
  token on VM. Public images need no VM GitHub credential.

SHA tags are write-once in this workflow, not registry-enforced immutable tags.
The VM's digest pin prevents tag movement from changing an active release.
References: [GitHub publishing](https://docs.github.com/en/packages/managing-github-packages-using-github-actions-workflows/publishing-and-installing-a-package-with-github-actions),
[GHCR authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## One-time Ubuntu setup

Use the existing x64 VM. Keep Azure NSG SSH/22 restricted to your public IP;
open no additional inbound ports. Permit outbound HTTPS and Gmail STARTTLS/587.
Store data on the persistent OS/managed disk, never the temporary/resource disk.
Install Docker Engine and Compose **v2.30+** using
[Docker's Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/).
Compose 2.30+ is needed for literal/raw environment values.

If Docker is not installed, set up its official apt repository:

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nSigned-By: /etc/apt/keyrings/docker.asc\n' "$VERSION_CODENAME" | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker compose version
```

Preserve an existing working Docker installation/repository.

From a reviewed checkout on the VM:

```sh
sudo apt-get update
sudo apt-get install -y python3 logrotate
sudo systemctl enable --now docker
sudo install -d -m 700 /etc/jobsfinder /opt/jobsfinder /var/lib/jobsfinder
sudo install -d -m 700 /var/lib/jobsfinder/releases /var/lib/jobsfinder/backups /var/log/jobsfinder
sudo install -d -m 700 -o 1000 -g 1000 /var/lib/jobsfinder/data
sudo install -d -m 700 -o 1000 -g 1000 /var/lib/jobsfinder/data/private /var/lib/jobsfinder/data/reports
sudo install -m 600 deploy/host.py /opt/jobsfinder/host.py
sudo install -m 600 deploy/deploy.env.example /etc/jobsfinder/deploy.env
sudo install -m 644 deploy/systemd/jobsfinder-* /etc/systemd/system/
sudo install -m 644 deploy/jobsfinder.logrotate /etc/logrotate.d/jobsfinder
sudoedit /etc/jobsfinder/deploy.env
```

Set real lowercase `JOBSFINDER_IMAGE_REPOSITORY=ghcr.io/owner/repo`. Runtime
UID/GID is fixed at **1000:1000**, independent of the SSH user's account.
Do not install legacy cron entries in addition to the timers below.

## Transfer the existing database and private files

Stop both local worker schedules and wait for active commands before the final
transfer. Use SQLite's backup API, not a file copy of a live DB/WAL. On Windows:

```powershell
uv run python deploy/backup.py "$env:LOCALAPPDATA/JobsFinder.io/data/jobsfinder.db" "$env:TEMP/jobsfinder-transfer.db"
scp "$env:TEMP/jobsfinder-transfer.db" USER@VM:jobsfinder-transfer.db
scp .env USER@VM:jobsfinder-runtime.env
scp "$env:LOCALAPPDATA/JobsFinder.io/data/private/profile.json" USER@VM:jobsfinder-profile.json
```

The backup script refuses to overwrite an existing destination; use a fresh name.
Transfer actual candidate/import files and reports with SCP too. Preserve original
databases/backups. Registry, history, queues, decisions, quotas and delivery state
are in the backup. Do not run the local workers after production cutover.

On VM, first setup only; this block refuses to overwrite an existing database:

```sh
set -e
chmod 600 ~/jobsfinder-transfer.db ~/jobsfinder-runtime.env ~/jobsfinder-profile.json
if sudo test -e /var/lib/jobsfinder/data/jobsfinder.db; then
  echo 'Existing production database: stop and preserve it.'; exit 1
fi
sudo install -m 600 -o 1000 -g 1000 ~/jobsfinder-transfer.db /var/lib/jobsfinder/data/jobsfinder.db
sudo install -m 600 -o 1000 -g 1000 ~/jobsfinder-profile.json /var/lib/jobsfinder/data/private/profile.json
sudo install -m 600 ~/jobsfinder-runtime.env /etc/jobsfinder/runtime.env
sudoedit /etc/jobsfinder/runtime.env
```

Install the transferred candidate/import files and reports under the data tree,
mode 600, owner 1000:1000. Secure/remove staging copies after verifying destinations.
Never log/paste credentials. Runtime paths are `/app/data/private/profile.json`,
`/app/data/private/candidates.json` and `/app/data/reports`. The candidates file
and any referenced imports must exist. Production Compose enforces these paths;
host data is always `/var/lib/jobsfinder/data`, ignoring old Windows DATA_DIR.

Keep Gmail and Gemini secrets only in `/etc/jobsfinder/runtime.env`, mode 600.
Retain Flash-Lite, enabled=true, batch=10, max-calls/daily=20, reserve=2, session=8,
RPM=15, TPM=250000. The controller does not load/print this file; Compose loads
it into application containers. Review pending/uncertain email state before
starting workers: existing eligible pending messages can be delivered.

## First deployment and activation

After a successful main publication and GHCR access setup:

```sh
sudo systemctl daemon-reload
sudo systemctl start jobsfinder-update.service
sudo cat /var/lib/jobsfinder/current.json
sudo tail -n 30 /var/log/jobsfinder/update.log
sudo python3 /opt/jobsfinder/host.py health
# Only after reviewing the deployment and pending mail:
sudo systemctl enable --now jobsfinder-update.timer jobsfinder-worker.timer
systemctl list-timers 'jobsfinder-*'
```

Updater and worker use one host lock. Deployment also takes both application
locks, makes an integrity-checked SQLite backup and records `BLOCKED.json` before
migration. It runs migration, schema and DB/application health checks, then
atomically selects the image and its matching versioned Compose file in
`current.json`. Source/provider failures and pending work remain visible rather
than being treated as image failure. No-new-version checks do not run containers,
backups or migrations. Previous image/config are retained locally.
Local `jobsfinder-retained:current` and `:previous` tags additionally protect
those images from ordinary dangling-image cleanup.

Every five minutes the separate worker runs `run-due`, then `screen-due` serially.
Existing America/New_York/DST logic schedules hourly polling, discovery 06:00,
screening 09:30/19:30 and reports 10:00/20:00. Busy ticks defer; durable application
receipts recover interrupted work. No direct cron/Docker writers should bypass
this controller. An orphaned running application container blocks new work until
it finishes or is reviewed. Timers resume after reboot; blocked deployment stays
blocked. There is no always-running public service to restart.

A container has 512 MiB RAM, one CPU, 128 processes, no extra swap, read-only root
and bounded tmpfs/logs. No concurrent app containers and no on-VM image builds.
Watch OOM events/durations on this small host; long screening can delay a tick.
Swap is not automatically created: first reduce batch pressure or review VM size
if sustained memory pressure occurs. Preserve existing Gemini limits.

## Confirm automatic updates

After a reviewed main push, confirm CI and `publish-production` succeed, then:

```sh
sudo cat /var/lib/jobsfinder/current.json
sudo cat /var/lib/jobsfinder/previous.json # exists after the second deployment
sudo tail -n 30 /var/log/jobsfinder/update.log /var/log/jobsfinder/worker.log
systemctl list-timers 'jobsfinder-*'
sudo test ! -e /var/lib/jobsfinder/BLOCKED.json
```

The record includes SHA, digest, deployment time and Compose path. Failed tests
never promote production; superseded main builds do not promote an old commit.
First remote publish/pull, target-host permissions, SMTP/network access and
resource usage still need verification. Local tests are not an Azure deployment.

## Failed deployment and rollback

```sh
sudo systemctl stop jobsfinder-worker.timer jobsfinder-update.timer
sudo systemctl stop jobsfinder-worker.service jobsfinder-update.service
sudo docker ps -a --filter name=jobsfinder-task
sudo cat /var/lib/jobsfinder/BLOCKED.json
```

If a container survived a killed Docker client, wait or deliberately stop it
before touching the DB. A failure marker records candidate, previous release
(null on first deployment) and backup. Workers stay paused. Do not blindly revert
only the image after migration: first prove previous-image schema compatibility.
No automatic downgrade/deletion is implemented.

If DB restoration is needed, restore the recorded pre-deployment backup into a
separate recovery directory and verify integrity. Preserve failed DB/WAL/SHM and
new history before an operator-reviewed full recovery. Restoring old receipts
can replay email or change quota accounting; reconcile them before resuming.
Never overwrite an open production DB.

After compatibility/recovery is verified, atomically select the previous state
from `previous.json` (or marker.previous) as `current.json`, archive BLOCKED.json,
then run a controlled health/worker check. Start only the worker timer first.
Keep the updater disabled until a fixed main image is approved, otherwise it
will redeploy the same bad production reference. For ordinary application-only
rollback, keep the DB and use the compatible previous image/config together.

For that **schema-compatible, application-only** case, after stopping timers and
confirming no task container is running, this guarded command checks the old
schema/health, makes a fresh backup, and selects the previous release. If the
schema check fails, stop and follow the separate DB recovery procedure above.
It intentionally performs no down-migration or database restore:

```sh
sudo python3 - <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, '/opt/jobsfinder')
from host import ROOT, atomic_json, backup, compose, lock
UTC = timezone.utc
with lock(ROOT / 'host.lock') as acquired:
    if not acquired:
        raise SystemExit('Another controller is active; stop here')
    marker_path = ROOT / 'BLOCKED.json'
    marker = json.loads(marker_path.read_text()) if marker_path.exists() else None
    previous = marker['previous'] if marker else json.loads((ROOT / 'previous.json').read_text())
    if not previous:
        raise SystemExit('No prior release: repair first deployment manually')
    compose(previous, 'alembic', 'check')
    compose(previous, 'jobsfinder-io', 'health')
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    backup(ROOT / 'data/jobsfinder.db', ROOT / 'backups' / (stamp + '-before-rollback.db'))
    atomic_json(ROOT / 'current.json', previous)
    if marker:
        marker_path.rename(ROOT / ('BLOCKED-reviewed-' + stamp + '.json'))
print('Previous compatible release selected; updater remains disabled')
PY
sudo python3 /opt/jobsfinder/host.py health
sudo systemctl start jobsfinder-worker.timer
```

## Logs, disk and maintenance

Before pulls, updater checks both Docker storage and the data filesystem for
3 GiB plus twice DB size free. Container logs use
two 5 MiB files; host logs rotate daily/10 MiB, seven copies. Review `df -h`,
`sudo docker system df` and backup sizes weekly. Backups/images/releases are
retained deliberately; remove only reviewed obsolete versions, preserving current
and previous digests and protected backup retention. Never prune volumes or
indiscriminately delete data/backups. Arrange off-host backups separately.

The root-owned controller/systemd units are a stable bootstrap installed manually
from reviewed files. App releases update their image and bundled runtime Compose
together. Future bootstrap/protocol changes require reinstalling those files
deliberately rather than running downloaded deployment hooks.

Learning checkpoint: CI promotes production; `host.update()` pins the digest and
gates migration with backup/marker; `host.tick()` uses the atomic release record.

Local acceptance: 505 tests passed, one Linux-only test skipped on Windows;
Linux locks/WAL backup were separately verified in an offline container. Ruff,
Docker build, production Compose validation, Bash syntax and read-only 512 MiB
image migration/health checks passed. Systemd verification is included in CI;
actual timer activation, GHCR publication and Azure execution remain unverified.
