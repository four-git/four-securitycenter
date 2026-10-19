# four-securitycenter

A Raspberry Pi 4 / 4 GB security suite for read-only Synology NAS file scanning, with optional passive network IDS.

**Start with [Docker setup and operation](docs/DOCKER-RUNBOOK.md).** It covers prerequisites, scripted host setup, the NAS mount, image build, startup and recovery.

The setup scripts are:

```bash
# On the Pi, from /opt/four-securitycenter:
sudo bash scripts/pre-req.sh --dry-run --migrate-native
sudo bash scripts/pre-req.sh --migrate-native
# Enter NAS credentials with sudoedit if needed, then:
sudo bash scripts/pre-req.sh --mount
sudo bash scripts/install-suite.sh --dry-run
sudo bash scripts/install-suite.sh
sudo ./suite start
sudo ./suite doctor
```

For a fresh host, omit `--migrate-native`. Follow the guide's copy/staging step before these commands. Preparation prints progress, preserves existing config/data, and snapshots the native installation before migration. Automatic scans and Suricata remain disabled.

Target: `four-securitycenter` / `192.168.4.51`, Debian 13 ARM64. NAS: `four-nas` / `192.168.4.46`, share `//192.168.4.46/data`, mounted read-only at `/mnt/four-securitycenter/downloads`.

After validation, install **`four-securitycenter.service`** using the [systemd setup commands](docs/DOCKER-RUNBOOK.md#install-the-four-securitycenter-service). Then use `sudo systemctl start four-securitycenter`, `stop four-securitycenter` or `restart four-securitycenter` for lifecycle control. Automatic scan schedules are configured separately.

**Status:** The ARM64 image was built and container health/mount checks passed on the Pi on October 19, 2026. Full scan, resource and recovery acceptance remains in progress. Prior native scanner results are recorded in the [Docker guide](docs/DOCKER-RUNBOOK.md#prior-native-validation).

ClamAV is configured up to 1.9 GB/file. The two local YARA rules provide narrow MKV/MP4 payload triage up to 8 GB, not comprehensive antivirus coverage. See [rule coverage](docs/RULE-COVERAGE.md). Suricata requires verified traffic capture before use.

No automatic NAS writes, deletion, quarantine, blocking, public web ports or sample uploads are configured. Credentials stay on the Pi and out of Git/images.
