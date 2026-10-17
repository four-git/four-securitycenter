# Codex implementation brief — four-securitycenter

Act as a senior Debian Linux/Synology security engineer. Create a maintainable **CLI-first** appliance project from the adjacent [runbook](INSTALLATION-RUNBOOK.md). The owner executes the steps manually over SSH; **do not contact or modify** any Pi, NAS, router or external account without explicit permission.

## Immutable facts

- Pi: `four-securitycenter` / `192.168.4.51`, Raspberry Pi 4 4 GB, Debian GNU/Linux **13.5 trixie**. Validate `arm64` at deployment.
- NAS: Synology DS220+ `four-nas` / `192.168.4.46`, DSM 7.x; Jellyfin/qBittorrent/Prowlarr. DSM share names and completed-download directory **unknown**.
- Network: eero home network; **managed switch/mirror status unknown**.

## Architecture and priorities

1. **Phase 1:** Debian upgrades and security/monitoring prerequisite checks; no OS reinstall.
2. **Phase 2:** dedicated read-only DSM scanner account, SMB3-only share mounting and fail-closed mount checks.
3. **Phase 3:** Debian-packaged `clamav`, `clamav-freshclam`, `yara`; EICAR and harmless YARA tests; implement stable-file discovery, incremental scan state, bounded memory/CPU/time, engine-specific statuses, file-integrity changes, safe systemd jobs. ClamAV has 2 GB individual-file scan cap; skip/error/partial ≠ clean.
4. **Phase 4:** document exact router/switch/NIC topology. Passive capture scope must be measured.
5. **Phase 5:** `suricata` + `suricata-update` low-memory passive IDS; only start when capture interface is configured and actually sees mirror traffic. Otherwise leave off or explicitly scope to Pi-only traffic.
6. **Phase 6:** alert/reporting, resource and failure telemetry, versioned configuration, security hardening, verification and rollback.

Prefer native Debian services over containers unless evidence shows a benefit. Do not install full Wazuh, Security Onion or Elasticsearch/OpenSearch. Do not add automatic NAS deletes/quarantine, router blocks, IPS/in-line routing, new public ports, external sample uploads, or credentials in Git.

## Deliverables Codex should build next

- Production-ready scan runner and SQLite schema; stable downloads detection; lock preventing overlapping jobs; tests for faults/oversized files, skipped engines and missing SMB mounts.
- Command-line `four-securitycenter scan`, `status`, `health`, `alerts` (accurate JSON/human output).
- Debian 13/ARM64-tested systemd service/timer units and hardened service accounts; scripts should be idempotent, use dry-run options, fail appropriately, and not write to NAS.
- Suricata configuration change as a **minimal patch to installed** `/etc/suricata/suricata.yaml`, not a guessed replacement YAML.
- Optional notifications and daily summary only after owner chooses a delivery method.
- Small, repeatable acceptance tests and troubleshooting instructions with observed outcomes; don't imply tests were run unless evidence is available.

## Acceptance conditions

- Pi updates/reboots and SSH remains usable; NAS is reachable.
- Scanner account and SMB mount genuinely read-only, safe on mount failure.
- EICAR detection, YARA benign rule detection, correct handling of scan errors/limit exclusions.
- Incremental jobs don't rescan unchanged files unnecessarily, never overlap and don't break Jellyfin use.
- Network visibility honestly scoped and IDS tested using controlled packets with drop metrics.
- Signed-off resource measurements (peak RSS, load, storage writes, throughput), alarms and recoverability.

## Naming

Project/repo `four-securitycenter`; base `/opt/four-securitycenter`; configuration `/etc/four-securitycenter`; state `/var/lib/four-securitycenter`; logs `/var/log/four-securitycenter`; mounts `/mnt/four-securitycenter`; app-created units `four-securitycenter-*.service` and `.timer`. Retain package-managed unit names (`suricata.service`, etc.) unless necessary.

## Questions that must be asked or measured at execution, not fabricated

Actual SMB share(s) and complete-download path, approved DSM scanner username, subnet and router topology, adapter/interface for SPAN, available SSD/microSD storage, logs/alert destination. Provide actionable discovery commands before requiring a response.
