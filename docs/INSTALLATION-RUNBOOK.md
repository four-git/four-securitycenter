# four-securitycenter — Deployment & Operations Runbook

**Version:** 0.2 (repository starter)  
**Updated:** 2026-10-17  
**Project:** `four-securitycenter`  
**Status:** Design approved for phased CLI deployment; **not yet installed or validated**.

> **Execution model:** The owner prepares and administers the Raspberry Pi over SSH. Codex may generate or refine configuration, scripts, testing and documentation in this repository. No automation should modify the Pi or NAS without explicit approval.

## 0. Scope, facts and safety gates

### Confirmed inventory

| Component | Confirmed value | Notes |
|---|---|---|
| Security appliance | `four-securitycenter` | Raspberry Pi 4 Model B; 4 GB RAM |
| Pi IP | `192.168.4.51` | Verify it stays assigned after reboot; reserve in DHCP if appropriate |
| Operating system | **Debian GNU/Linux 13 (trixie), 13.5** | Debian, **not** Raspberry Pi OS Lite |
| Target architecture | ARM64 (`aarch64` / `arm64`) | Verify using commands below |
| NAS | Synology DS220+ | DSM 7.x; exact DSM version to verify |
| NAS hostname | `four-nas` | DNS/name resolution to be verified |
| NAS IP | `192.168.4.46` | Use local SMB3 for file access |
| NAS admin URL | `https://four-nas:5001` | For administrative setup only; scanner doesn't require DSM admin |
| NAS workloads | Jellyfin, qBittorrent, Prowlarr | Avoid CPU/storage/network interference during playback |
| LAN | Home network with eero equipment | Switch, mirroring, wired layout unknown |

### Must be discovered; do not guess

- DSM SMB shared-folder **name(s)**, case-sensitive SMB path(s), and which subpaths contain completed downloads. `downloads` is **not** a confirmed share name.
- DSM read-only service-account username and permissions; password must never enter Git.
- Exact DSM version, SMB minimum/maximum protocol policy, backup settings and existing antivirus schedules.
- Pi's network interface names, actual arm64 architecture, available disk space, power supply and boot storage.
- Router/switch layout, whether SPAN/port mirroring is supported, and whether a dedicated capture NIC is available.
- Notification transport and desired retention; do not assume credentials or public endpoints.

### Security invariants

1. Scanner receives **read-only SMB credentials** and mounts. No NAS deletion, modification, auto-quarantine, or change to file permissions.
2. Passive IDS only: **no inline routing, IPS or automatic blocking**; network stays operational if Pi is off.
3. Network-wide visibility is **unavailable without a traffic feed** such as a correctly configured mirror. Pi-local packets alone do not equal LAN monitoring.
4. Clean ≠ safe: engine/rules/signature versions, skipped files and errors must be tracked. ClamAV's **2 GB individual-file cap** applies even when total scan-size limits are raised.
5. No secrets, NAS media, live captures, logs or databases committed to Git.
6. During first deployment, schedule scans away from Jellyfin use. Use only one resource-intensive file scanner at a time.

### Software decision (Debian 13, ARM64)

| Component | Initial decision | Reason |
|---|---|---|
| `clamav`, `clamav-freshclam` | Install; **CLI batch scanning first** | Directly packaged for Debian trixie ARM64; signature updater. Avoid persistent `clamav-daemon` RAM cost initially. |
| `yara` | Install classic YARA first | Debian trixie ARM64 package exists. Safe, small starting point for curated rules. |
| YARA-X | **Future optional evaluation** | Distinct product; do not assume `apt install yara-x` exists. Verify official ARM64 build & actual limits before adopting. |
| `suricata`, `suricata-update` | Install, **leave IDS disabled pending capture validation** | Debian trixie packages for ARM64; needs packet source and low-memory tuning. |
| `cifs-utils` | Install | SMB3 client for NAS share mounts. |
| Python 3 + SQLite | Design lightweight incremental scan state | Add verified scripts after initial mount and detection tests. |
| Wazuh / Security Onion / Elasticsearch | **Do not install** | Too heavy/complex for a 4 GB Pi appliance. |
| Docker | Not required in v0.2 | Prefer Debian-packaged native services. Reassess only for a justified component. |

---

## Phase 1 — Debian Pi preparation (owner-operated CLI)

### 1.1 Connect; inspect system before modifying

From a Windows PowerShell or other SSH client (substitute your Pi login):

```powershell
ssh YOUR_PI_USER@192.168.4.51
```

On the **Pi**:

```bash
hostnamectl
cat /etc/os-release
dpkg --print-architecture
uname -m
ip -br address
ip route
free -h
df -h
systemctl --failed
```

**Expected:** `four-securitycenter`, Debian `trixie`; `arm64` in dpkg and `aarch64` in uname; roughly 3.7 GiB usable RAM. If output differs, investigate before continuing. `192.168.4.51` must be on the intended network.

### 1.2 Upgrade Debian 13 within its configured repositories

```bash
sudo apt update
sudo apt full-upgrade -y
```

Review optional unused-package cleanup before consenting:

```bash
sudo apt autoremove --purge
sudo apt autoclean
sudo reboot
```

After reconnecting:

```bash
cat /etc/os-release
uname -a
apt list --upgradable
systemctl --failed
```

**Note:** `full-upgrade` applies available upgrades from enabled APT repositories. It does not, by itself, perform a Debian major-release migration. `/etc/os-release` may still say 13.5 until a subsequent point-release package changes that metadata.

**Rollback:** APT upgrades do not have a general one-command rollback. Back up critical configuration and use a boot-media image / snapshot if rollback is essential. Review package removals before cleanup.

### 1.3 Connectivity and DNS tests

```bash
ping -c 3 192.168.4.46
getent hosts four-nas
ip route get 192.168.4.46
```

DNS failure for `four-nas` is not a blocker: using `192.168.4.46` for SMB is acceptable. **Do not** alter network configuration or install a firewall blindly during an SSH session.

### 1.4 Basic operating-system protection

- Prefer SSH keys. Verify that a **second** SSH login using the key works *before* disabling password auth.
- Install unattended updates only after reviewing policy and reboot expectations; document your patch window.
- Reserve `192.168.4.51` in router DHCP, or verify the existing static IP setup. Do not reassign it without confirming access.
- Keep management on the trusted LAN/VPN; do not forward SSH or web management ports from the internet.
- Prefer a USB SSD for persistent, write-heavy event logs; microSD is workable for initial evaluation with strict log rotation.

Optional checks:

```bash
sudo journalctl -p warning -b --no-pager | tail -n 50
sudo ss -tulpn
vcgencmd measure_temp 2>/dev/null || cat /sys/class/thermal/thermal_zone0/temp
```

### 1.5 Install baseline Debian packages

```bash
sudo apt update
sudo apt install -y \
  ca-certificates curl jq cifs-utils \
  clamav clamav-freshclam \
  yara \
  suricata suricata-update \
  sqlite3 python3 python3-venv \
  tcpdump logrotate
```

**Immediately prevent unconfigured Suricata from staying active:**

```bash
sudo systemctl disable --now suricata || true
```

Verify tool versions and availability:

```bash
clamscan --version
yara --version
suricata --build-info | head -n 25
suricata-update --version
systemctl status clamav-freshclam --no-pager
```

If packages are unavailable, inspect `apt-cache policy NAME` and enabled Debian sources. Do not add unknown third-party APT repositories just to force an install.

**Phase 1 exit gate:** SSH works after reboot, OS and architecture match, no unexpected failed services, tool versions recorded, Suricata not yet running.

---

## Phase 2 — Synology SMB read-only integration

### 2.1 On DSM (manual web UI step)

1. DSM → **Control Panel → User & Group**: create a dedicated non-admin account, for example `four-securitycenter-scan` (adjust to DSM constraints).
2. Deny access to unrelated shares; grant **read-only** access solely to selected media/download shares.
3. Do **not** add the account to administrators, grant write access, or use your personal DSM admin credentials.
4. Under **Control Panel → File Services**, confirm SMB is enabled and SMB3-compatible; don't weaken NAS minimum protocol settings solely for this appliance.
5. Record the exact **SMB share names** and any distinct download-complete subdirectories.
6. Confirm the account cannot upload, rename, overwrite, or delete files using a separate disposable test share/file if possible.

**Placeholder used below:** `SHARE_NAME` must be replaced with a verified DSM shared-folder name, not a filesystem path like `/volume1/...`.

### 2.2 Create local directories and dedicated service identity on Pi

```bash
sudo useradd --system --home-dir /var/lib/four-securitycenter \
  --create-home --shell /usr/sbin/nologin four-securitycenter || true
sudo install -d -m 0755 /opt/four-securitycenter
sudo install -d -m 0750 /etc/four-securitycenter
sudo install -d -m 0750 -o four-securitycenter -g four-securitycenter /var/lib/four-securitycenter
sudo install -d -m 0750 -o four-securitycenter -g four-securitycenter /var/log/four-securitycenter
sudo install -d -m 0755 /mnt/four-securitycenter/downloads
id four-securitycenter
```

The `useradd` `|| true` shortcut is only for manual initial experimentation; Codex must implement idempotent creation that correctly distinguishes “already exists” from other errors in production scripts.

### 2.3 Store SMB credentials OUTSIDE Git

```bash
sudo install -m 0600 -o root -g root /dev/null /etc/four-securitycenter/smb.credentials
sudoedit /etc/four-securitycenter/smb.credentials
```

**Contents** (supply actual credentials in the editor):

```ini
username=DSM_READ_ONLY_USERNAME
password=DSM_READ_ONLY_PASSWORD
```

Optional `domain=WORKGROUP` only when required by your NAS setup. Never echo passwords into shell commands, `.bash_history`, screenshots, tracked source files or tickets.

### 2.4 Test a *manual* read-only mount first

```bash
sudo mount -t cifs //192.168.4.46/SHARE_NAME \
  /mnt/four-securitycenter/downloads \
  -o credentials=/etc/four-securitycenter/smb.credentials,ro,vers=3.0,nosuid,nodev,noexec

findmnt /mnt/four-securitycenter/downloads
findmnt -T /mnt/four-securitycenter/downloads -t cifs
ls -la /mnt/four-securitycenter/downloads | head
```

**Do not** scan or edit any production data yet. Confirm the mount is `cifs`, `ro`, and the share contains expected files.

Test non-destructive access as the service account after mapping uid/gid; the mount might initially present restrictive owners. Use `id -u four-securitycenter` and `id -g four-securitycenter` to configure the final mount permissions (see below).

If permission denied: verify both DSM **share-level** and **filesystem/ACL** read permissions, the exact share name, SMB credentials, and DSM logs.

To undo the trial mount:

```bash
sudo umount /mnt/four-securitycenter/downloads
```

### 2.5 Optional persistent systemd-managed mount

After the manual mount passes, obtain the service user's numeric UID/GID:

```bash
id -u four-securitycenter
id -g four-securitycenter
```

Edit `/etc/fstab` with `sudoedit /etc/fstab`, **replacing SHARE_NAME, UID_NUMBER and GID_NUMBER**:

```fstab
//192.168.4.46/SHARE_NAME /mnt/four-securitycenter/downloads cifs credentials=/etc/four-securitycenter/smb.credentials,ro,vers=3.0,uid=UID_NUMBER,gid=GID_NUMBER,file_mode=0440,dir_mode=0550,nosuid,nodev,noexec,_netdev,nofail,x-systemd.automount 0 0
```

Then (after unmounting any manual mount):

```bash
sudo systemctl daemon-reload
sudo mount -a
findmnt -T /mnt/four-securitycenter/downloads -t cifs
sudo -u four-securitycenter ls /mnt/four-securitycenter/downloads | head
```

**Guard rail for Codex scripts:** check the target really resolves to a CIFS mount and that expected test files exist. If not, fail with `SCAN_ERROR`. An empty local mount-point directory must never count as “0 clean files scanned.”

**Rollback:** remove the new `/etc/fstab` line, `sudo systemctl daemon-reload`, then `sudo umount /mnt/four-securitycenter/downloads` (when idle). Leave DSM files untouched.

**Phase 2 exit gate:** correct real share, read-only account, non-root scanner can read, scanner cannot write, boot-safe mount recovery tested.

---

## Phase 3 — Malware scan engines and safe tests

### 3.1 ClamAV signatures and service

```bash
systemctl status clamav-freshclam --no-pager
sudo journalctl -u clamav-freshclam -n 50 --no-pager
ls -lh /var/lib/clamav
clamscan --version
```

The distribution's `clamav-freshclam` service normally handles recurring updates. Do **not** start a second `freshclam` process while the service is running, or you may get a database lock. If it needs repair, stop the service deliberately, update once, and restart, following the service logs.

### 3.2 Safe EICAR test (local Pi; NOT the NAS)

The EICAR test string is a harmless industry-standard antivirus test pattern, **not malware**. Create a local sample:

```bash
mkdir -p ~/four-securitycenter-tests
printf '%s' 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' \
  > ~/four-securitycenter-tests/eicar.com.txt
clamscan -i ~/four-securitycenter-tests/eicar.com.txt
```

**Expected:** `Eicar-Test-Signature FOUND`, with exit code `1` (a positive detection); `0` means no detection and `2` indicates an error. Some test-filename/printing details vary by signature versions. No action should delete or quarantine the file. Remove the test sample afterward.

```bash
rm -f ~/four-securitycenter-tests/eicar.com.txt
```

### 3.3 First manual scan — *small, selected directory only*

**Only after verifying the mounted share and choosing a safe subdirectory:**

```bash
if findmnt -T /mnt/four-securitycenter/downloads -t cifs; then
  sudo -u four-securitycenter nice -n 15 \
    clamscan -r -i \
    --max-filesize=200M \
    --max-scansize=400M \
    --alert-exceeds-max \
    /mnt/four-securitycenter/downloads/REPLACE_WITH_SMALL_TEST_DIRECTORY
else
  echo 'ERROR: NAS SMB mount not verified; scan aborted.'
fi
```

These **200M / 400M are deliberate initial resource-policy caps**, not ClamAV's maximum capability. The internal **2 GB individual-file** hard limit still applies. Review ClamAV output and exit codes carefully: `--alert-exceeds-max` may label scan-limit violations as alerts and must not be automatically equated to confirmed malware.

**DO NOT run a first-time `clamscan -r` across the entire movie library.** Such scans can use substantial CPU, memory and NAS read bandwidth.

### 3.4 YARA — safe custom-rule proof

Classic YARA is packaged for Debian 13 ARM64. Use a local, deliberately benign rule from this repo:

```bash
yara --version
printf '%s\n' FOUR_SECURITYCENTER_YARA_TEST_SAMPLE > ~/four-securitycenter-tests/yara-sample.txt
yara --no-follow-symlinks rules/test-rule.yar ~/four-securitycenter-tests/yara-sample.txt
```

Run the second command from the repo root, or substitute the absolute rule path. **Expected:** a match naming `four_securitycenter_benign_test`.

For recursive scans, use `yara -r --no-follow-symlinks ...` and apply conservative `--skip-larger=<bytes>`, `--threads=1`, and `--timeout=<seconds>` when appropriate (confirm installed CLI with `yara --help`). Unlike ClamAV, this provides custom rule-pattern matching rather than antivirus coverage. External YARA rule packs must be reviewed, pinned and compiled/tested before use.

### 3.5 Codex implementation requirement: incremental scan runner

The first test commands are **manual**, not a complete incremental scanner. Codex should next implement a `four-securitycenter scan` CLI and associated Python/SQLite runner using these rules:

- Only selected NAS roots; explicit share inventory and mount verification.
- Avoid files actively being written: require known completed-download state or stable size + mtime over a configurable observation window.
- Store file path, share ID, size, mtime, prior engine results, signature/rule versions, last attempt, last success and failure reason.
- Identify newly created or changed files; no costly full-hash of every multi-GB video.
- Treat exit codes separately per engine; never rewrite detection as clean when another engine skipped.
- Results: `CLEAN`, `MALWARE_DETECTED`, `YARA_MATCH`, `SKIPPED_SIZE_LIMIT`, `SKIPPED_POLICY`, `PARTIALLY_SCANNED`, `SCAN_ERROR`, `PENDING`.
- No deletion, quarantine, writes or timestamp changes on SMB mount.
- Lock against overlapping jobs; finite max runtime; bounded concurrent readers.
- Log to `/var/log/four-securitycenter/`, store SQLite under `/var/lib/four-securitycenter/`, configure retention.
- Update rules/signatures **before or independently of scans**; identify stale signature status.
- Use a test fixture outside NAS shares to test all state transitions and injected failures.

### 3.6 Initial scheduling policy (implement only after scanning is validated)

- Every 1–2 hours: discover stable/completed new download candidates.
- Night: incremental file scan, rate-limited so Jellyfin stays responsive.
- Weekly: review changed protected files / integrity state.
- Daily: service-health report and check for stale rules/AV signatures.
- Serialize heavy AV and YARA jobs; do not let full scans overlap Suricata's peak workload.

Prefer `systemd` oneshot services and timers: `four-securitycenter-scan.service`, `four-securitycenter-scan.timer`, `four-securitycenter-report.service`, `four-securitycenter-report.timer`. Codex must generate units, test in dry-run mode, use a dedicated account, and document enable/disable, journal inspection and rollback. No untested timer should be enabled merely because files exist in the repo.

**Phase 3 exit gate:** EICAR detects, YARA test matches, scan limit cases are distinct from clean, incomplete mounts cause failure, successful small scan has no NAS modifications.

---

## Phase 4 — Network visibility discovery (do not skip)

First check actual interfaces and topology:

```bash
ip -br link
ip -br address
ip route
sudo ss -tulpn
```

Draw an as-built diagram showing **router/eero, switches, NAS, Pi, Wi-Fi access points and wired devices**. Determine where a traffic mirror could be inserted without changing routing.

**No SPAN / TAP available:** Suricata will only see traffic to/from the Pi plus limited broadcast/multicast on its own interface. Prefer router/DNS logs (if available), or leave network IDS disabled until a suitable feed exists. No claim of whole-house monitoring.

**Managed switch with SPAN:** Mirror carefully selected router/NAS ports to a **dedicated** Pi USB 3.0 Ethernet adapter; do not use the SSH management port as the SPAN destination. Many switches cannot mirror all Wi-Fi traffic, especially client-to-client flows and traffic that bypasses the wired mirror source.

**Traffic capture test** (replace interface, never assume `eth1`):

```bash
ip -br link
sudo tcpdump -ni MIRROR_INTERFACE -c 25
```

Generate permitted, known traffic from another home device, inspect what appears, and record visibility and link speed. Never interpret a capture of only broadcast packets as full network inspection.

**Phase 4 exit gate:** capture source, physical path, interface, observed traffic types and blind spots documented. Otherwise mark IDS as *limited/disabled*.

---

## Phase 5 — Passive Suricata, only after Phase 4

### 5.1 Keep Suricata stopped until configured

```bash
sudo systemctl disable --now suricata || true
suricata --build-info | head -n 30
sudo suricata-update
sudo suricata -T -c /etc/suricata/suricata.yaml
```

`suricata-update` normally retrieves Emerging Threats Open rules to `/var/lib/suricata/rules/`. Validate this path and `rule-files:` in the installed `/etc/suricata/suricata.yaml`.

### 5.2 Configuration edits (after backup)

```bash
sudo cp -a /etc/suricata/suricata.yaml \
  /etc/suricata/suricata.yaml.before-four-securitycenter
sudoedit /etc/suricata/suricata.yaml
```

Codex should produce a **reviewable patch for the installed Debian 13 Suricata 7.x config**, rather than replacing the whole YAML file. Confirm:

- `HOME_NET` accurately reflects the private network scope; don't hardcode a subnet based only on the NAS IP.
- `af-packet` references the *verified* mirror adapter if a mirror exists.
- IDS/alert mode only. Never `NFQUEUE`, inline AF_PACKET copy mode, packet forwarding, or prevention policies in v1.
- EVE output is enabled but **limited to useful event types** (e.g. `alert`, `stats` initially) to reduce log churn.
- CPU/threading/memcaps are benchmarked; use a conservative rule set and note dropped-packet counters.
- Rotating logs and a cap on disk consumption are enforced.

Test after **each** edit:

```bash
sudo suricata -T -c /etc/suricata/suricata.yaml
```

### 5.3 Start only after the configuration passes and capture is verified

```bash
sudo systemctl enable --now suricata
systemctl status suricata --no-pager
sudo tail -n 40 /var/log/suricata/suricata.log
sudo test -e /var/log/suricata/eve.json && \
  sudo tail -n 5 /var/log/suricata/eve.json | jq .
```

If it unexpectedly uses the management NIC or wrong mode, **stop it** and fix configuration:

```bash
sudo systemctl disable --now suricata
```

Inspect memory and captures:

```bash
free -h
ps -C suricata -o pid,rss,%cpu,etime,cmd
sudo grep -Ei 'drop|capture|packet' /var/log/suricata/stats.log | tail -n 30
```

**Validation:** Use a controlled test alert and examine its `eve.json` entry. The mere existence of `eve.json` or successful daemon startup does **not** validate network coverage. Measure packet drops under realistic traffic.

**Rollback:** stop the service, restore the backed-up YAML, rerun `suricata -T`, leave IDS disabled until capture and config are verified. Never change router firewall/routing as part of rollback.

**Phase 5 exit gate:** verified capture scope and detection, acceptable packet-loss measurements, stable RAM and temperature, no disruption to NAS or household connectivity.

---

## Phase 6 — Alerts, reports and operational health

Codex should implement a local, self-contained status command first:

```text
four-securitycenter status
four-securitycenter scan --path <approved-mount-subpath> --dry-run
four-securitycenter scan --incremental
four-securitycenter alerts --since 24h
four-securitycenter health
```

> These are **target CLI requirements**, not commands that are already installed. Implement and document before offering them as executable commands.

Minimum health fields: last successful scan, count clean/detected/skipped/errored, signatures updated at, YARA rule revision, mount availability, Suricata state, verified capture scope, packet drops, free disk, memory, CPU temp, and alert delivery status.

Suggested notifications: severity-based email or LAN-hosted ntfy. Configure one transport only after it is selected; keep tokens/secrets outside source control. Suppress duplicate low-severity events. A missed scan or lost mount must be reported as a **failure**, not a clean result.

---

## Phase 7 — Tuning, failure response and operations

### Useful daily diagnostic commands (Pi)

```bash
hostnamectl
free -h
df -h
systemctl --failed
systemctl status clamav-freshclam --no-pager
systemctl status suricata --no-pager
findmnt -T /mnt/four-securitycenter/downloads -t cifs
sudo journalctl -u suricata --since '24 hours ago' --no-pager | tail -n 80
sudo journalctl -u clamav-freshclam --since '24 hours ago' --no-pager | tail -n 80
```

If Suricata is intentionally disabled, that is expected until the mirror is validated.

### Resource policies for 4 GB RAM

- Start with `clamscan` CLI, **not** a resident `clamd` unless measurements justify the extra resident memory.
- Start with one YARA worker and modest file caps. Keep large-file attempts explicit and bounded.
- Limit simultaneous heavy jobs. Defer new scans under memory pressure; never overload the Pi into OOM loops.
- Minimize Suricata EVE output and rules, rather than collecting all HTTP/DNS/flow events indefinitely.
- Implement `systemd` CPU/memory limits only after observing peak use and verifying they don't kill healthy jobs.
- Watch for temperature throttling and SD-card write wear; favor an SSD if logs become write-heavy.
- Benchmark Jellyfin playback while a scan is underway, and record NAS CPU, SMB throughput, latency and Pi load.

### Failures and expected response

| Symptom | First action | Do not do |
|---|---|---|
| NAS share missing | `findmnt -T ... -t cifs`, check credential and network | Treat empty mountpoint as clean |
| Antivirus DB stale | `journalctl -u clamav-freshclam`, inspect network and DB | Launch multiple FreshClam processes |
| High Pi RAM / OOM | Stop scheduled scans, inspect `free`, `journalctl -k` | Add Wazuh/Elasticsearch |
| Suricata has no alerts | Check mirror coverage, capture and rules | Claim no threats across home LAN |
| High packet loss | Reduce rules/event types, verify link/mirror, profile CPU | Present detection coverage as complete |
| Suspected malware | Preserve detection record, investigate manually | Auto-delete NAS files |
| Scan exceeds limits | Mark skipped/partial; review file type and rule scope | Mark file as clean |

---

## Phase 8 — Acceptance checklist

- [ ] Debian 13 trixie and ARM64 confirmed; no unexpected failed system services.
- [ ] Host resolves/reaches NAS at `192.168.4.46`; SSH works at `192.168.4.51` after reboot.
- [ ] Dedicated DSM service account exists with narrowly scoped **read-only** permissions.
- [ ] Correct NAS share(s) mounted; missing mount causes explicit scan failure.
- [ ] FreshClam is updating; EICAR test produces expected **positive** detection.
- [ ] Benign YARA test rule matches; untrusted rule packs are not installed blindly.
- [ ] Size-limit and error conditions are distinct from a successfully scanned clean file.
- [ ] Incremental scanner detects changed/stable files, prevents overlap and survives reboot **after implemented**.
- [ ] Scanner never writes to, quarantines or deletes files on NAS.
- [ ] Network topology and capture blind spots documented before claiming LAN coverage.
- [ ] Suricata either disabled/limited **or** validated with mirror/test packets and measurable packet-drop checks.
- [ ] CPU, RAM, temperature, disk writes and Jellyfin interference benchmarked.
- [ ] Logs rotated, alerts tested and recovery procedures documented.
- [ ] No secrets, scan logs, packet captures or database content in Git.

---

## Repository conventions, ownership and Codex next steps

### Layout

```text
four-securitycenter/
├── README.md
├── .gitignore
├── docs/
│   ├── INSTALLATION-RUNBOOK.md   # this file
│   └── CODEX-BUILD-SPEC.md       # detailed implementation handoff
├── config/
│   └── example.yaml              # placeholders only; NOT live secrets
├── rules/
│   └── test-rule.yar             # harmless validation rule
└── scripts/
    └── healthcheck.sh            # noninvasive diagnostics only
```

### Further Codex implementation items (do not pretend present in starter)

1. `scripts/scan.py`: safe SMB mount checks, file stabilization, batch ClamAV/YARA scan, SQLite state, accurate classification and bounded resources.
2. Config schema and parser with tests; `four-securitycenter` CLI with human-readable and JSON output.
3. `systemd/` oneshot unit templates and timers, with service-user privileges and no scan overlap.
4. Alert normalizer (ClamAV results, YARA matches, Suricata EVE, health failures); no external posting without owner choice.
5. Scanning test fixtures (EICAR, harmless YARA, large sparse file, stale/absent mounts, scanner timeout) and safe rollback tests.
6. Minimal Suricata patches specifically targeting installed Debian package and verified capture interface.
7. Versioned rules, signature freshness telemetry and upgrade procedure.

### Documentation sources (official or upstream)

- Debian trixie ClamAV ARM64: https://packages.debian.org/trixie/arm64/clamav
- Debian trixie FreshClam: https://packages.debian.org/trixie/clamav-freshclam
- Debian trixie classic YARA ARM64: https://packages.debian.org/trixie/arm64/yara
- Debian trixie Suricata and update: https://packages.debian.org/trixie/suricata and https://packages.debian.org/trixie/arm64/suricata-update
- ClamAV's 2 GB maximum file-size behavior: https://blog.clamav.net/2023/08/
- Debian `clamscan(1)`: https://manpages.debian.org/trixie/clamav/clamscan.1.en.html
- Debian `mount.smb3(8)`: https://manpages.debian.org/trixie/cifs-utils/mount.smb3.8.en.html
- Suricata 7 documentation: https://docs.suricata.io/en/suricata-7.0.15/quickstart.html
- YARA command line: https://yara.readthedocs.io/en/latest/commandline.html

**This document is a deployment runbook/starter specification, not evidence that any command has been executed or any security feature has been deployed.**
