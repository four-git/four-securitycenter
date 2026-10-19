# four-securitycenter

A resource-conscious **Raspberry Pi 4 (4 GB)** home security appliance project for **read-only Synology NAS file scanning** and **passive network intrusion detection**.

> **Status (October18,2026):** Phase3 scanning framework deployed and acceptance-tested on the Pi with owner authorization. Schedules remain disabled. Large-media coverage is two narrow YARA triage rules, not comprehensive antivirus. See [operations and observed tests](docs/PHASE3-OPERATIONS.md) and [rule coverage](docs/RULE-COVERAGE.md). Suricata remains disabled; network visibility is unverified.

## Confirmed environment

- Scanner host: **`four-securitycenter`**, IP **`192.168.4.51`**, **Debian GNU/Linux 13 (trixie), 13.5**.
- NAS: **Synology DS220+**, host **`four-nas`**, IP **`192.168.4.46`**, DSM 7.x.
- NAS services: Jellyfin, qBittorrent, Prowlarr. CPU-heavy scanning belongs on Pi, not NAS.
- Networking: eero; switch/mirror support unknown. **No full-LAN monitoring claim until packet capture is validated**.

## Start here

Docker suite implementation: see [Docker installation and migration](docs/DOCKER-RUNBOOK.md). Automatic scans remain disabled; ARM64 and live Pi acceptance are pending.

1. Read **[Deployment & Operations Runbook](docs/INSTALLATION-RUNBOOK.md)**.
2. Confirm `uname -m`, network connection and mount paths; run Debian updates on the Pi.
3. Create a read-only DSM account, verify SMB shares and validate a small scanner test.
4. Only then configure Suricata after documenting actual traffic-capture visibility.
5. Give Codex **[Implementation Brief](docs/CODEX-BUILD-SPEC.md)** to build the remaining automation.

## Current stack decision

**ClamAV + FreshClam** (batch AV), **classic YARA** (Debian-packaged curated rules), **Suricata + suricata-update** (passive IDS once visibility verified). YARA-X is a future evaluation, not assumed to be Debian-packaged. Keep memory under control and report scan limitations honestly.

## Safe first Pi update

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt autoremove --purge   # review removals
sudo apt autoclean
sudo reboot
```

## Not in this starter

- NAS share names/credentials (must be supplied from DSM, never committed)
- Broad production malware-rule coverage (the incremental runner and disabled systemd timer units now exist)
- Working network IDS capture without verified mirrored traffic
- Monitoring UI, notifications or external accounts (to be selected)

## Safety

Read-only NAS SMB account; passive monitoring only; no automatic deletion/blocking; no public web ports; no secrets/logs/media/packet captures committed to Git.
