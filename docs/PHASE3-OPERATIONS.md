# Phase 3 installation and operation

Observed on October18,2026: Debian13.7 ARM64 on four-securitycenter, UID997/GID983. SMB3 source `//192.168.4.46/data` is mounted read-only at `/mnt/four-securitycenter/downloads`. Roots are `media` and `torrents/complete`. `torrents/incomplete`, certificates and recycle bins are excluded.

## Installed layout

- `/opt/four-securitycenter/src/four_securitycenter.py`: root-owned Python runner
- `/usr/local/bin/four-securitycenter`: launcher symlink
- `/etc/four-securitycenter/scanner.json`: root-owned configuration, readable by scanner group
- `/var/lib/four-securitycenter/scans.sqlite3`: file observations, per-engine results and events
- `/var/lib/four-securitycenter/scan.lock`: common non-overlapping job lock
- `/var/log/four-securitycenter/*.log`: local output, rotated by logrotate
- `/etc/four-securitycenter/smb.credentials`: existing root-only0600 credential file, never copied to Git or read by scanner

## Commands

Run with `sudo -u four-securitycenter`:

```bash
four-securitycenter health
four-securitycenter discover
four-securitycenter scan --dry-run
four-securitycenter scan
four-securitycenter status
four-securitycenter alerts
```

`discover` records observations without running engines. A file must have unchanged size+mtime across observations at least15minutes apart, and mtime at least15minutes old. This reduces active-download scans; it does not prove a torrent is complete. Data roots must remain on the exact expected read-only CIFS mount. Missing roots, unavailable reads, wrong mount/source, and stale daily signatures fail closed. Scanner never writes to NAS, deletes, quarantines, or uploads samples.

`--dry-run` does not execute engines or change file observations; it may initialize an empty local SQLite schema. It is not proof of a successful scan. `CLEAN` means neither loaded engine reported a match within configured limits; it is never a guarantee of safety. Per-engine results and evidence stay separate. `YARA_MATCH` means review, not automatically confirmed malware. A large YARA-only file is `PARTIALLY_SCANNED`.

Validated starter limits: ClamAV1.9GB/file and total scan size,240s internal scan time; YARA8GB/file;360s external timeout per engine;900s job budget. The initial200MB policy was raised after a449,554,850-byte NAS video completed both engines in241.66s. Larger files explicitly report skipped/partial. These policy limits are independent of ClamAV's hard per-file ceiling. Oldest/unattempted files get priority across runs so a bounded job doesn't repeatedly start at the same files; new completed-download candidates precede equally unattempted library files. Discovery is bounded to2000paths/run; larger trees need a future paginated walker. File integrity events track size/mtime changes, not full cryptographic hashes of every video.

## Coverage

ClamAV uses its maintained signatures. The currently installed YARA set is only two local media payload-indicator rules. Read [RULE-COVERAGE.md](RULE-COVERAGE.md): these are narrow triage checks, not a general malware rule pack or full antivirus-equivalent coverage. No automatic rule download or commercial AV was installed. ClamAV1.4.3 is the configured Debian repository candidate; FreshClam reports a newer upstream engine. This needs normal package-maintenance review, not an unsupported third-party package workaround.

## Schedules and control

Units are named `four-securitycenter-{discover,scan,report}.{service,timer}`. Intended schedule in the Pi's America/New_York timezone: discovery every2hours; scan03:00 with up to15minutes jitter; report07:00 with up to5minutes jitter. Scan CPUQuota75% of one core, Nice15, idle I/O, MemoryMax1200MiB and15minute work budget. Only one heavy scanner runs at once. Services run as the dedicated non-root account with system and NAS paths read-only. Reports are local; no external notifications configured.

All three timers remain disabled at handoff. The framework is validated; the large-file rule coverage is still narrow. Enabling scheduled jobs is a separate deliberate step once the owner accepts that scope. There is no automatic library scan currently running.

Verify actual enablement instead of assuming timers are active:

```bash
systemctl list-timers 'four-securitycenter-*'
systemctl is-enabled four-securitycenter-{discover,scan,report}.timer
sudo tail -n 80 /var/log/four-securitycenter/scan.log
sudo journalctl -u four-securitycenter-scan.service --no-pager -n 30
```

Rollback/disable scheduled work:

```bash
sudo systemctl disable --now four-securitycenter-{discover,scan,report}.timer
sudo systemctl stop four-securitycenter-{discover,scan,report}.service
```

This does not alter the NAS mount, credentials, media or FreshClam. Configuration changes are made in the root-owned JSON. Retain the local SQLite and logs for investigation; remove them only deliberately. The scan service treats exit1 as a completed detection run; inspect alerts rather than relying on a green service state. Exit2 is an operational error.

## Verified checks

- Actual EICAR detection, harmless YARA marker detection and clean local fixture succeeded.
- Actual source-mismatch CLI health check failed with exit2/SCAN_ERROR.
- A second scan while a heavy test held the lock failed with exit2/SCAN_ERROR.
- Real NAS2,390,317,630-byte file: ClamAV skipped, YARA no loaded-rule match, aggregate PARTIALLY_SCANNED,70.17s. Size/mtime unchanged.
- Sparse2.2GB fixtures: both real triage rules match indicators placed after byte2,200,000,000; benign large fixture doesn't match. Each about19.2s under75% CPU and512MiB cgroup memory cap. mmap RSS peaked near2.06GiB; RSS is not equivalent to private/cgroup memory use.
- Small policy limits, engine timeouts, changing files, symlinks, missing mounts, incremental caching and fairness are covered by Pi unit tests.
- Initial450MB ClamAV test hit internal MaxScanTime. That is an error/incomplete scan, not a size skip or clean result; runner mapping corrected and regression-tested.

Remaining: an actual disposable-file SMB server-side write-denial test, full reboot/mount recovery, broad reviewed detection-rule coverage, and monitoring the first scheduled run. Suricata stays disabled until network capture visibility is verified; Phase4/5 are not claimed complete.
