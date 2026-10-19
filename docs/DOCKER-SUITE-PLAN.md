# Docker suite proposal

Design proposal, October18,2026. Repository implementation added; Docker/ARM64 and live Pi acceptance are pending. See [Docker runbook](DOCKER-RUNBOOK.md). Existing Pi installation remains intact; its scan timers remain disabled.

## Recommendation

Package four-securitycenter as one Docker Compose project with separate services and one management CLI. Target Debian13/ARM64 and a4GB Pi. Container packaging provides reproducibility and lifecycle management; it does not remove scanner limits or add detection coverage.

Core services:

| Service | Responsibility | Access |
|---|---|---|
| scanner | Existing Python/SQLite runner, ClamAV batch scans, YARA; bounded scheduling, discovery and local reports | Non-root997:983; NAS and rules read-only; state/log directories writable; no Docker socket; no network required |
| signatures | FreshClam updates only | Signature directory writable; outbound network; no NAS access |
| suricata (optional profile) | Passive network IDS after capture visibility is validated | Explicit Linux capture interface/capabilities; no NAS or scanner state access; disabled by default |

Do not add a persistent clamd daemon initially: batch ClamAV already uses roughly1GB during a scan, and the Pi has4GB. Do not add heavyweight databases or dashboards. A lightweight read-only UI may follow after CLI/reporting is reliable.

## Host responsibilities

Keep SMB mounting on the Pi host. Credentials stay in root-only /etc/four-securitycenter/smb.credentials and never enter image layers, Compose environment variables or source control. Bind the entire mounted share into the scanner at the same path, read-only. A host preflight and in-container checks must both verify the expected CIFS source, mount and read-only options. A missing mount must never become an empty local directory interpreted as a clean scan. Do not automatically create a missing bind source.

The initial bind can remain private; after an SMB unmount/remount, deliberately recreate the scanner container only after host mount verification succeeds. Do not assume automatic mount propagation works. Test server-unreachable, stale mount, remount and reboot behavior explicitly.

Docker installation, OS updates, user/directory ownership, boot integration and network-interface selection remain host setup work. DSM account/share creation and password entry remain NAS/user setup steps. Do not give containers SYS_ADMIN/privileged access just to eliminate these host steps.

## Proposed repository additions

- Dockerfile based on a verified Debian13 image, ARM64 build/test; package versions and image digest recorded.
- compose.yaml with bounded CPU/memory, restart policies, health checks, read-only filesystems, dropped capabilities and persistent data paths.
- Docker-specific config preserving the existing NAS paths, UID997/GID983 and SQLite state.
- suite management CLI: install, doctor, start, stop, restart, status, scan, alerts, logs, update, backup, rollback.
- Idempotent install script with dry-run, safe Docker repository setup, checks for existing configuration, backups and manual credential handoff.
- Scheduler inside scanner service that invokes existing commands, shares their lock, handles termination and never overlaps heavy engines.
- Versioned deployment manifest and a Docker installation/runbook separate from the native runbook.

Proposed operations (not commands available yet):

```text
sudo ./scripts/install-suite.sh --dry-run
sudo ./scripts/install-suite.sh
sudo ./suite start
sudo ./suite status
sudo ./suite scan --dry-run
sudo ./suite logs
sudo ./suite stop
```

Stopping must preserve signatures, SQLite history and settings. Uninstall must preserve data unless the owner explicitly requests its deletion. Start-at-boot should verify the NAS dependency; restart-after-failure should back off, and health must show blocked/degraded instead of false clean.

## Migration and acceptance

1. Build and test ARM64 images before changing the Pi. Test command parsing, engine results and missing/stale signature handling.
2. Snapshot current configuration and SQLite; stage containers with no automatic scans.
3. Avoid duplicate FreshClam updaters or native/container scan schedulers. Switch updater ownership only after verifying the new updater and preserving rollback.
4. Test local EICAR, benign YARA fixtures beyond2GB, actual bounded NAS scans, unchanged-file caching, changing-file rejection, timeouts, resource limits and the shared job lock.
5. Test NAS disconnection/remount, clean reboot, container restart, stop during scanning, persistence and restoring the native setup.
6. Enable schedules only with accurately documented rule coverage. Verify performance during Jellyfin playback.

Existing ClamAV per-file ceiling remains. Current YARA rules provide narrow suspicious-media-payload triage up to the configured8GB policy cap, not full antivirus-equivalent coverage. Broader detection coverage is a separate workstream and must remain visible in status/reports.

References:
- https://docs.docker.com/engine/install/debian/
- https://docs.docker.com/engine/storage/bind-mounts/
