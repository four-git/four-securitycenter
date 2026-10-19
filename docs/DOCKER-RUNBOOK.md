# Docker suite: setup and operation

This is the current installation guide. Run host commands on **four-securitycenter, Debian 13 ARM64, Raspberry Pi 4 / 4 GB**. Docker/ARM64 build and live Pi acceptance are still pending; the scripts have not been run on your Pi as part of this change.

The setup is: **copy repo → prepare host → verify NAS mount → build image → start → validate**. No automatic scan or IDS is enabled during installation.

## What you need first

- SSH access to `192.168.4.51` with a sudo-capable Pi login.
- Internet access from the Pi for Debian/Docker packages, image downloads and ClamAV signatures.
- Free local space for Docker images, signatures and a complete copy of existing state/signatures for backup. `pre-req.sh` prints disk and RAM availability; check capacity before applying it.
- A DSM account with **read-only** access to `//192.168.4.46/data`, including `media` and `torrents/complete`. Creating that account and setting its DSM permissions is manual.
- UID **997** and GID **983** available, or the existing compatible `scanner` / `four-securitycenter` identity. Scripts stop on conflicting identities rather than reassigning accounts.

### What the scripts prepare

| Item | Location / behavior |
|---|---|
| Host dependencies | CA certificates, curl, GnuPG, Python 3, util-linux, cifs-utils |
| Docker | Official Debian apt repository, Engine, Buildx and Compose plugin; reuse a working existing installation |
| Service identity | Non-login `scanner`, UID 997 / GID 983; reuse compatible native identity |
| Configuration | `/etc/four-securitycenter`, root:983, 0750; preserve existing `scanner.json`, set root:983 / 0640 |
| NAS credentials | `/etc/four-securitycenter/smb.credentials`, root:root / 0600; preserve existing contents |
| Scanner state | `/var/lib/four-securitycenter`, UID 997 / GID 983; preserve SQLite history |
| Signatures | `/var/lib/clamav`, UID 997 / GID 983 |
| NAS mount | `/mnt/four-securitycenter/downloads`; one read-only CIFS entry in `/etc/fstab` |
| Native migration backup | `/var/backups/four-securitycenter-native-TIMESTAMP-PID`, root-only, original ownership retained |
| Container engines | ClamAV, FreshClam, YARA and optional Suricata installed in the image |

Scripts print `[pre-req]` / `[install]` progress and commands. Stop at any `[BLOCKED]` message. `--dry-run` inspects the host and previews changes without applying them; it cannot guarantee that a later package download/build will succeed. Reruns preserve credentials/configuration, reuse accounts and avoid duplicate mount entries. Preparation takes another snapshot when existing data is present.

## 1. Copy the repo to the Pi

**Windows PowerShell**, from your local repo directory:

```powershell
$piLogin = 'YOUR_PI_USER@192.168.4.51'
$suiteRepo = (Get-Location).Path
$suiteArchive = Join-Path $env:TEMP 'four-securitycenter-suite.tar.gz'
tar -czf $suiteArchive -C $suiteRepo Dockerfile .dockerignore compose.yaml suite deployment-manifest.json README.md config docs rules scripts src systemd tests
scp $suiteArchive "${piLogin}:/tmp/four-securitycenter-suite.tar.gz"
ssh $piLogin
```

All remaining blocks run in **Bash on the Pi**. Use `/opt/four-securitycenter` for the host checkout. If cloning published source, use `sudo git clone https://github.com/four-git/four-securitycenter.git /opt/four-securitycenter` only when the target does not already exist; unpublished desktop changes require the archive above.

For an already deployed Docker suite, use the update procedure below before replacing source. Do not unpack over a running deployment. For the first Docker installation, preserve any existing native source directory before extracting the archive:

```bash
if sudo test -d /opt/four-securitycenter; then
  suiteSourceBackup="/var/backups/four-securitycenter-source-$(date +%Y%m%d-%H%M%S)-$$"
  sudo install -d -m 0700 "$suiteSourceBackup"
  sudo cp -a /opt/four-securitycenter "$suiteSourceBackup/"
  printf 'Source backup: %s\n' "$suiteSourceBackup"
fi
sudo install -d -m 0755 /opt/four-securitycenter
sudo tar --no-same-owner -xzf /tmp/four-securitycenter-suite.tar.gz -C /opt/four-securitycenter
sudo chown -R root:root /opt/four-securitycenter
cd /opt/four-securitycenter
sudo chmod +x suite scripts/*.sh
```

Keep the printed source backup path alongside the configuration/data snapshot created in the next step. If you cloned instead, skip archive extraction and run `cd /opt/four-securitycenter` before continuing.

## 2. Prepare the host

For your existing native Pi installation:

```bash
sudo bash scripts/pre-req.sh --dry-run --migrate-native
sudo bash scripts/pre-req.sh --migrate-native
```

For a fresh host, omit `--migrate-native` from both commands.

`--migrate-native` records native unit enablement/active state, disables/stops the native scan/discovery/report jobs and FreshClam, checks for remaining scanner processes, then copies configuration, state, signatures and fstab before changing ownership. **Keep the printed backup path.** If preparation fails afterward, native jobs stay stopped; fix the error and rerun or use native recovery below.

The script installs Docker using its [official Debian apt repository](https://docs.docker.com/engine/install/debian/). It refuses conflicting packages or an incomplete existing Docker repository setup; it never removes packages automatically. Existing working Docker is reused. Docker is enabled at boot, but the suite is not. Host OS upgrades/reboots remain separate maintenance tasks.

## 3. Enter credentials and verify the NAS mount

If credentials already exist and work, keep them. Otherwise edit the generated root-only template:

```bash
sudoedit /etc/four-securitycenter/smb.credentials
```

Replace `CHANGE_ME` with the DSM read-only account values:

```ini
username=YOUR_READ_ONLY_DSM_USER
password=YOUR_DSM_PASSWORD
```

Never put these values in shell commands, `.env` or Git. Then run:

```bash
sudo bash scripts/pre-req.sh --mount
```

This mounts the share if necessary, verifies the exact CIFS source, target and `ro` option, and checks UID 997 can read/traverse both scan roots. It leaves an existing mount's options unchanged; a wrong/writable mount fails verification. If you deliberately change an existing fstab entry, stop scanners, unmount/remount and verify again. No script changes NAS file permissions or writes test files to your media.

## 4. Check prerequisites and build the image

```bash
sudo bash scripts/install-suite.sh --dry-run
sudo bash scripts/install-suite.sh
sudo cat deployment-manifest.json
```

The dry run checks Docker, identity, directory ownership/access, config paths, the mount, native job state and Compose syntax. A real install resolves a Debian base digest on first install, builds on ARM64, records package versions and pins services to the built image ID. It preserves existing configuration and starts no containers.

First installation creates `.env` with both schedule intervals set to `0`. Existing `.env` is preserved; check it before starting:

```bash
sudo grep -E '^(SCAN_INTERVAL_SECONDS|DISCOVER_INTERVAL_SECONDS)=' .env
```

Both must be `0` during acceptance. Image pinning retains the built artifact; rebuilding later can resolve newer Debian package versions. Keep old images and release source for recovery.

## 5. Start and check the suite

```bash
sudo ./suite start
sudo ./suite logs
sudo docker compose ps --all
```

FreshClam may take several minutes to download its first signatures. Once it succeeds:

```bash
sudo ./suite doctor
sudo ./suite status
sudo ./suite scan --dry-run
```

If doctor fails, inspect `suite logs` and resolve it before scanning. Health means prerequisites are available; it does not mean files were scanned. Containers being up is not acceptance.

Choose a known benign file and replace the example before running:

```bash
sudo ./suite scan --target '/mnt/four-securitycenter/downloads/media/REPLACE_WITH_EXISTING_FILE.mkv'
sudo ./suite alerts
```

A newly observed file can remain `PENDING` for the configured 900-second stability period. Run the same command again after 15 minutes. ClamAV is limited to the configured 1.9 GB; YARA provides only two narrow MKV/MP4 payload triage rules up to 8 GB. Large YARA-only files are partially scanned. See [rule coverage](RULE-COVERAGE.md).

## Everyday commands

Run from `/opt/four-securitycenter`:

| Action | Command |
|---|---|
| Start scanner + signatures | `sudo ./suite start` |
| Host-only checks, including native job conflicts | `sudo ./suite check` |
| Check running scanner prerequisites | `sudo ./suite doctor` |
| Containers, health and counts | `sudo ./suite status` |
| Preview a scan | `sudo ./suite scan --dry-run` |
| Run a bounded scan | `sudo ./suite scan` |
| Findings / recent logs | `sudo ./suite alerts` / `sudo ./suite logs` |
| Follow logs | `sudo docker compose logs --follow --tail 100 scanner signatures` |
| Stop everything; keep data | `sudo ./suite stop` |
| Recreate after a verified NAS remount | `sudo ./suite restart` |

The scanner has no network access, NAS/rules/signatures are read-only to it, and only state is writable. The signature updater has outbound access and can write signatures. Normal start does not enable Suricata. No web port is published.

## Acceptance, then optional boot startup and schedules

Before enabling unattended operation, record results on the Pi:

- `python3 -m unittest discover -s tests -p 'test_*.py'` passes on Linux. Ownership/restore and simulated host dry-run tests require root: `sudo python3 -m unittest discover -s tests -p 'test_suite.py'` and `sudo python3 -m unittest discover -s tests -p 'test_setup_scripts.py'`. These use disposable fixtures and inventory stubs.
- Local EICAR and harmless YARA fixtures detect correctly; bounded NAS scans, caching, changing files, timeouts and the shared job lock behave as expected. Use disposable local fixtures for detections; never put malware on the NAS. See [prior native validation](#prior-native-validation) for the earlier baseline.
- Observe CPU/RAM and Jellyfin playback under load. Check stop during a scan, restart and data persistence.
- Test NAS unavailable/stale mount, unmount/remount, container recreation and reboot. Failures must produce blocked/unhealthy results.
- Test snapshot restoration and native recovery before relying on either.

After acceptance, optionally install the boot unit:

```bash
sudo install -m 0644 systemd/four-securitycenter-suite.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now four-securitycenter-suite.service
sudo ./suite doctor
```

Once installed, use `sudo systemctl start|stop|restart four-securitycenter-suite.service` for routine lifecycle changes. `active (exited)` means the launch command succeeded; use doctor for current health.

Schedules are a separate opt-in. Edit `.env`, preserving image settings:

```bash
sudoedit /opt/four-securitycenter/.env
# Example: SCAN_INTERVAL_SECONDS=21600 and DISCOVER_INTERVAL_SECONDS=3600
sudo systemctl restart four-securitycenter-suite.service
```

Without the boot unit, apply changes with `sudo ./suite restart`. Zero disables a schedule; nonzero intervals must be at least 60 seconds. Jobs run serially and share the manual scanner lock. First execution waits one interval. Return both values to zero to disable automatic work.

## Backup, update and recovery

These operations leave containers stopped. If the boot unit is installed, stop it first:

```bash
sudo systemctl stop four-securitycenter-suite.service  # only if installed
sudo ./suite backup
# Or snapshot and rebuild the currently staged source:
sudo ./suite update
```

Save the printed snapshot path under `/var/backups/four-securitycenter`. Snapshots include credentials, config, SQLite/sidecars, signatures, `.env` and manifest, preserving numeric ownership. Keep them root-only. Updates do not fetch source or automatically advance the base digest. Stage reviewed source separately while preserving `.env`, manifest and the prior release checkout. Do not prune images needed by snapshots.

To restore a snapshot, replace the path with an actual saved snapshot:

```bash
sudo ./suite rollback /var/backups/four-securitycenter/REPLACE_WITH_SNAPSHOT
# Start through systemctl if installed; otherwise:
sudo ./suite start
sudo ./suite doctor
```

Rollback first snapshots the current stopped deployment, then restores data/config/image selection. It does not restore CLI/Compose/source files; retain the matching release checkout if those changed. Old image IDs must still exist locally.

To return to the native installation: stop the Docker suite, disable its boot unit if installed, and use the **native** backup from preparation. With both native and container jobs stopped, move the current configuration/state/signature directories into a separate root-only recovery directory, then restore the matching directories from the native backup with `cp -a` to preserve ownership. Restore whole directories rather than overlaying SQLite files and sidecars. Also move aside the Docker checkout and restore `/opt/four-securitycenter` from the source backup saved before staging. Review fstab against `BACKUP/etc/fstab`; do not overwrite unrelated later mount changes. Restore only the unit states recorded in `unit-state.txt`. Native scan timers were previously disabled. Confirm container FreshClam is stopped before starting native FreshClam.

Uninstall: stop the suite, disable its boot unit, and run `sudo docker compose --profile ids down`. Keep configuration, state, signatures and backups unless you deliberately choose to delete them.

## Prior native validation

Recorded on October 18, 2026, before Docker migration. These results validate the native scanner only; repeat the acceptance checks above for containers. The native scan, discovery and report timers were disabled at handoff.

- EICAR detection, harmless YARA detection and a clean local fixture succeeded. Wrong NAS source and concurrent scan attempts failed with exit 2.
- A 449,554,850-byte NAS video completed both engines in 241.66 seconds. A 2,390,317,630-byte NAS file skipped ClamAV, had no loaded YARA match and was correctly reported as `PARTIALLY_SCANNED` in 70.17 seconds.
- Both media triage rules matched harmless indicators beyond byte 2,200,000,000 in sparse fixtures; the benign fixture did not match. Each ran in about 19.2 seconds under a 75% CPU / 512 MiB cgroup cap. Reported mmap RSS is not equivalent to private or cgroup memory use.
- Pi unit tests covered limits, timeouts, changing files, symlinks, missing mounts, caching and scan fairness. An internal ClamAV scan timeout was corrected to report an incomplete/error result.

Discovery is bounded to 2,000 paths per run; large trees still need a paginated walker. File-change tracking uses size/mtime, not full-file cryptographic hashes. A dry run can initialize an empty local SQLite schema even though it does not run engines or change file observations. A `CLEAN` result only means the loaded engines reported no match within configured limits.

Remaining deployment checks include a disposable-file DSM server-side write-denial test, full reboot/mount recovery, resource observations during playback and the first scheduled run. Broader detection rules and verified IDS visibility remain separate work.

## Optional Suricata: separate setup

Leave it off until mirror/TAP traffic visibility is proven. Prepare host config/rules at `/etc/four-securitycenter/suricata`, writable logs at `/var/log/four-securitycenter/suricata`, log paths under `/var/log/suricata` and runtime files under `/tmp`. Set `CAPTURE_INTERFACE` in `.env`, validate configuration using the built image, then use `sudo docker compose --profile ids up -d suricata`. It alone uses host networking and capture capabilities. No claim of LAN-wide monitoring is justified without observed traffic. See [Docker bind mount behavior](https://docs.docker.com/engine/storage/bind-mounts/) for why a verified NAS remount requires scanner recreation.
