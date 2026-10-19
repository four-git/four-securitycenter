# Docker suite installation and migration

Repository implementation is available; ARM64 build and live Pi acceptance remain pending. No Pi changes were made during implementation. Automatic scan/discovery intervals default to zero. Native installation instructions remain in INSTALLATION-RUNBOOK.md.

## End-to-end command walkthrough

Run the numbered steps in order, stopping if a command fails. Blocks marked **Windows PowerShell** run on your desktop; all other blocks run in **Bash on the Pi**, signed in as your normal sudo-capable user. Replace `YOUR_PI_USER` with that Pi login. Docker installation and Compose lifecycle commands run on the host; the suite then executes scan commands inside the scanner container. You do not need an interactive container shell.

### 1. Copy this implementation to the Pi

Use the working files on the desktop so uncommitted Docker additions are included. This archive uses an explicit file list and excludes credentials, runtime state and `.git`. **Windows PowerShell:**

```powershell
$piLogin = 'YOUR_PI_USER@192.168.4.51'
$suiteArchive = Join-Path $env:TEMP 'four-securitycenter-suite.tar.gz'
tar -czf $suiteArchive -C 'C:\Users\danie\Desktop\stream-jellyfin\securitycenter-work' Dockerfile .dockerignore compose.yaml suite deployment-manifest.json README.md config docs rules scripts src systemd tests
scp $suiteArchive "${piLogin}:/tmp/four-securitycenter-suite.tar.gz"
ssh $piLogin
```

From here onward, run commands on the Pi. Check the target and install host utilities:

```bash
cat /etc/os-release
uname -m
dpkg --print-architecture
# Expected: Debian 13 / trixie, aarch64, arm64.
sudo apt update
sudo apt install ca-certificates curl gnupg python3 util-linux cifs-utils
```

Stage the files at the boot unit's expected path. On an existing Docker suite, use the update procedure below instead of unpacking over its release.

```bash
sudo install -d -m 0755 /opt/four-securitycenter-suite
sudo tar --no-same-owner -xzf /tmp/four-securitycenter-suite.tar.gz -C /opt/four-securitycenter-suite
sudo chown -R root:root /opt/four-securitycenter-suite
cd /opt/four-securitycenter-suite
sudo chmod +x suite scripts/install-suite.sh
```

### 2. Install Docker Engine and Compose on the host

These commands follow Docker's [official Debian repository installation](https://docs.docker.com/engine/install/debian/). If `sudo docker version` and `sudo docker compose version` already work, skip repository installation and run the verification block. If Docker hosts other workloads, review their maintenance needs before changing Docker packages.

First inspect conflicting distribution packages:

```bash
dpkg -l docker.io docker-compose docker-doc docker-buildx podman-docker containerd runc 2>/dev/null || true
```

If any listed packages are installed, review and remove those conflicting packages using `sudo apt remove PACKAGE_NAMES` before proceeding. Do not remove packages blindly from a host that already runs containers. Inspect any existing Docker repository entries before adding a new one:

```bash
sudo grep -R 'download.docker.com' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null || true
```

For a host without an existing Docker repository, add the key and Debian 13 ARM64 repository:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
gpg --show-keys --with-fingerprint /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: trixie
Components: stable
Architectures: arm64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Verify Docker and Compose:

```bash
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
sudo docker ps
```

### 3. Stop native jobs and save the native installation

Do this before changing ownership or starting container services. Save the active/enabled state first; keep the printed backup path for recovery. These commands tolerate units that were never installed, but verify the process listing before proceeding.

```bash
nativeBackup="/var/backups/four-securitycenter-native-$(date +%Y%m%d-%H%M%S)"
sudo install -d -m 0700 "$nativeBackup"
for unit in four-securitycenter-scan.timer four-securitycenter-discover.timer four-securitycenter-report.timer four-securitycenter-scan.service four-securitycenter-discover.service four-securitycenter-report.service clamav-freshclam.service; do
  printf '\n%s\n' "$unit"
  systemctl is-enabled "$unit" || true
  systemctl is-active "$unit" || true
done | sudo tee "$nativeBackup/unit-state.txt" >/dev/null
for unit in four-securitycenter-scan.timer four-securitycenter-discover.timer four-securitycenter-report.timer clamav-freshclam.service; do
  sudo systemctl disable --now "$unit" 2>/dev/null || true
done
for unit in four-securitycenter-scan.service four-securitycenter-discover.service four-securitycenter-report.service; do
  sudo systemctl stop "$unit" 2>/dev/null || true
done
pgrep -af 'freshclam|four_securitycenter.py|clamscan|yara' || true
```

If a native updater or scanner is still running, stop its owning service/job before continuing. With native processes stopped, take the snapshot:

```bash
for item in /etc/four-securitycenter /var/lib/four-securitycenter /var/lib/clamav; do
  if sudo test -e "$item"; then
    sudo cp -a --parents "$item" "$nativeBackup/"
  fi
done
sudo cp -a /etc/fstab "$nativeBackup/fstab"
printf 'Native backup: %s\n' "$nativeBackup"
```

This backup contains SMB credentials when present; keep it root-only. Native scan timers remain disabled throughout container acceptance.

### 4. Verify the service identity and read-only NAS mount

Inspect the existing identity. The installer requires UID 997 with primary GID 983:

```bash
getent passwd 997 || true
getent group 983 || true
```

On a fresh host **only when both numeric IDs and the name `scanner` are unused**, create them:

```bash
sudo groupadd --gid 983 scanner
sudo useradd --uid 997 --gid 983 --no-create-home --shell /usr/sbin/nologin scanner
```

If IDs already exist, reuse the compatible native identity. If UID 997 belongs to an unrelated account or has another primary GID, resolve that conflict before continuing; do not reassign an unrelated account.

For the existing Pi, first check its existing mount and `/etc/fstab` entry:

```bash
sudo findmnt -T /mnt/four-securitycenter/downloads -o SOURCE,TARGET,FSTYPE,OPTIONS
sudo grep -F '/mnt/four-securitycenter/downloads' /etc/fstab
```

Expected: `//192.168.4.46/data`, exact target `/mnt/four-securitycenter/downloads`, type `cifs`, and `ro`. Reuse a valid existing mount. For a fresh host, create credentials **only if they do not exist**, then edit them locally:

```bash
sudo install -d -m 0750 /etc/four-securitycenter
if ! sudo test -e /etc/four-securitycenter/smb.credentials; then
  sudo install -m 0600 -o root -g root /dev/null /etc/four-securitycenter/smb.credentials
fi
sudoedit /etc/four-securitycenter/smb.credentials
sudo chown root:root /etc/four-securitycenter/smb.credentials
sudo chmod 0600 /etc/four-securitycenter/smb.credentials
```

Enter these two lines in the editor using the NAS read-only account (replace values; never paste credentials into shell commands):

```ini
username=YOUR_READ_ONLY_DSM_USER
password=YOUR_DSM_PASSWORD
```

For a fresh host, explicitly provision the host mount point. This is host setup; neither Compose nor the suite will create a missing NAS source:

```bash
sudo install -d -m 0755 /mnt/four-securitycenter/downloads
sudoedit /etc/fstab
```

Add the following line **once**, or review/edit the existing entry. Do not add duplicate entries:

```fstab
//192.168.4.46/data /mnt/four-securitycenter/downloads cifs credentials=/etc/four-securitycenter/smb.credentials,ro,vers=3.0,uid=997,gid=983,file_mode=0440,dir_mode=0550,nosuid,nodev,noexec,_netdev,nofail,x-systemd.automount 0 0
```

For a new, currently unmounted share:

```bash
sudo systemctl daemon-reload
sudo mount /mnt/four-securitycenter/downloads
```

If changing an existing mount's options, stop scanning first, deliberately unmount/remount it, and verify again. In either case, check both source and actual account access:

```bash
sudo findmnt -T /mnt/four-securitycenter/downloads -o SOURCE,TARGET,FSTYPE,OPTIONS
sudo -u '#997' -g '#983' test -r /mnt/four-securitycenter/downloads/media
sudo -u '#997' -g '#983' test -x /mnt/four-securitycenter/downloads/torrents/complete
```

Do not continue if this shows a local filesystem, wrong source, missing directories or a writable mount.

### 5. Prepare persistent state and build the suite image

After the native snapshot, create the local directories and assign only suite state/signatures to the container identity. This deliberately changes existing ClamAV ownership; the saved native snapshot preserves original ownership for rollback. Never run this against the NAS mount.

```bash
sudo install -d -m 0750 /var/lib/four-securitycenter /var/lib/clamav
sudo chown -R 997:983 /var/lib/four-securitycenter /var/lib/clamav
sudo chmod -R u+rwX /var/lib/four-securitycenter /var/lib/clamav
cd /opt/four-securitycenter-suite
sudo bash scripts/install-suite.sh --dry-run
sudo bash scripts/install-suite.sh
sudo docker compose config --quiet
sudo cat deployment-manifest.json
```

The installer preserves existing scanner.json, resolves and records a Debian digest, builds the image, records package versions, and pins services to the built image ID. It does not start scans. Inspect the retained configuration and its file permissions (container health will verify actual access):

```bash
sudoedit /etc/four-securitycenter/scanner.json
sudo stat -c '%u:%g %a %n' /etc/four-securitycenter/scanner.json
sudo grep -E '^(SCAN_INTERVAL_SECONDS|DISCOVER_INTERVAL_SECONDS)=' .env
```

Both intervals must be `0` for initial acceptance. Configuration must retain the paths in config/scanner.json, including the NAS mount, SQLite, rules, lock and signature paths used by Compose. If the file is root-only, grant UID 997 read access before startup (for example, root:983 ownership and mode 0640).

### 6. Bring up the containers and run a first scan

```bash
cd /opt/four-securitycenter-suite
sudo ./suite start
sudo ./suite logs
sudo docker compose ps --all
```

FreshClam may need several minutes for its initial download. Wait for successful signature updates, then run the following; stop here and inspect logs if doctor fails:

```bash
sudo ./suite doctor
sudo ./suite status
sudo ./suite scan --dry-run
```

Choose one existing benign file and replace the example path below before running a real scan. A newly discovered file may remain pending until the configured 900-second stability period elapses; rerun later if necessary.

```bash
sudo ./suite scan --target '/mnt/four-securitycenter/downloads/media/REPLACE_WITH_EXISTING_BENIGN_FILE.mkv'
sudo ./suite alerts
sudo ./suite logs
```

The equivalent command executed **inside the running scanner container** is below. Prefer `suite scan` for normal use because it also performs host preflight checks:

```bash
sudo docker compose exec -T scanner python3 /opt/four-securitycenter/src/container_service.py scan --dry-run
```

### 7. Everyday up/down commands

Run from `/opt/four-securitycenter-suite`; no rebuild is needed for normal starts/stops.

| Action | Command |
|---|---|
| Bring up scanner and signature updater | `sudo ./suite start` |
| Check prerequisites and health | `sudo ./suite doctor` |
| Show containers, health and scan counts | `sudo ./suite status` |
| Preview eligible files | `sudo ./suite scan --dry-run` |
| Run a bounded scan | `sudo ./suite scan` |
| View findings | `sudo ./suite alerts` |
| View recent logs | `sudo ./suite logs` |
| Follow live logs; Ctrl+C ends viewing | `sudo docker compose logs --follow --tail 100 scanner signatures` |
| Stop all suite services; preserve data | `sudo ./suite stop` |
| Recreate containers after verified NAS remount | `sudo ./suite restart` |
| Remove stopped containers/network; preserve bind-mounted data | `sudo docker compose --profile ids down` |

To prove an ordinary stop/start preserves state:

```bash
sudo ./suite stop
sudo docker compose ps --all
sudo ./suite start
sudo ./suite doctor
sudo ./suite status
```

### 8. Optional: start at boot, then enable schedules after acceptance

First complete the acceptance gate below, including manual reboot/remount and rollback tests. Then install the boot unit at the path assumed throughout this guide:

```bash
sudo install -m 0644 systemd/four-securitycenter-suite.service /etc/systemd/system/four-securitycenter-suite.service
sudo systemctl daemon-reload
sudo systemctl enable --now four-securitycenter-suite.service
sudo systemctl status four-securitycenter-suite.service --no-pager
```

When using that boot unit, use these host service commands for routine up/down so systemd tracks its state:

```bash
sudo systemctl stop four-securitycenter-suite.service
sudo systemctl start four-securitycenter-suite.service
sudo systemctl restart four-securitycenter-suite.service
```

The unit being `active (exited)` only means its start command succeeded; check `sudo ./suite doctor` for live scanner health. Disable boot startup with `sudo systemctl disable --now four-securitycenter-suite.service`.

Schedules are separate from starting containers. After acceptance, edit `.env` and change only the interval lines, preserving image settings:

```bash
sudoedit /opt/four-securitycenter-suite/.env
```

Example opt-in settings (scan every six hours; discovery every hour):

```dotenv
SCAN_INTERVAL_SECONDS=21600
DISCOVER_INTERVAL_SECONDS=3600
```

Apply with `sudo systemctl restart four-securitycenter-suite.service` when the boot unit is installed, or `sudo ./suite restart` otherwise. Use zero for both intervals to disable schedules again. Jobs run serially and share the manual scanner lock; the first job waits one interval.

### 9. Backup, update and rollback

These operations stop containers and leave them stopped. If the boot unit is installed, stop it first so it also records the stopped state:

```bash
sudo systemctl stop four-securitycenter-suite.service  # only if installed
cd /opt/four-securitycenter-suite
sudo ./suite backup
```

Save the snapshot path printed by backup. For an image/package update from the staged source and recorded Debian digest:

```bash
sudo ./suite update
sudo cat deployment-manifest.json
```

After review, start through the installed boot unit or `suite start`, then run `suite doctor` and `suite status`. For rollback, replace the example with the actual saved snapshot:

```bash
sudo ./suite rollback /var/backups/four-securitycenter/REPLACE_WITH_SNAPSHOT_TIMESTAMP
# Start using systemctl if installed; otherwise:
sudo ./suite start
sudo ./suite doctor
sudo ./suite status
```

Keep old image IDs locally; do not prune images required by snapshots. This update command rebuilds the staged source; it does not fetch new source. Stage reviewed source changes separately, preserving `.env` and release records. Snapshot rollback restores configuration, data and image selection; keep the matching release checkout as well if changing Compose or CLI code between releases.

## Host preparation reference

Use a root-owned checkout at `/opt/four-securitycenter-suite`. Install Docker Engine and the Compose plugin using the official Debian apt repository instructions: https://docs.docker.com/engine/install/debian/. Review the signing key, Debian codename, ARM64 architecture and conflicting packages before installation. The suite deliberately does not run a downloaded installer or replace repositories. Provision/review UID 997 and GID 983; existing native accounts may already own these IDs. Install Python 3, util-linux and CIFS utilities on the host.

Keep the entire share mounted read-only at `/mnt/four-securitycenter/downloads` from `//192.168.4.46/data`, with the expected media and torrents/complete directories. SMB credentials belong only in `/etc/four-securitycenter/smb.credentials`, mode 0600, owned by root. Do not put them in `.env`, the checkout, images, or container mounts. Configure the host mount using the native runbook. The suite never creates the NAS bind source.

Run `sudo bash scripts/install-suite.sh --dry-run`, then `sudo bash scripts/install-suite.sh`. Existing scanner config is retained. The installer refuses unexpected directory ownership; review migration permissions manually. It pulls Debian 13 ARM64, records the immutable registry digest in `.env`, records installed package versions and the image ID in deployment-manifest.json, and pins services to that retained image ID. Debian packages use the current signed repository; exact resolved versions are recorded, not frozen upstream. Keep `.env`, package-versions.txt and the manifest with each release. Do not prune images needed by snapshots.

## Migration

1. Snapshot native scanner config, SQLite and signature data while native scan services and updater are stopped. Preserve native unit enablement state with `systemctl is-enabled` and `systemctl is-active` before changes. Existing native scan timers must remain disabled until acceptance.
2. Stop/disable native scan, discovery and report timers, stop running scan/discovery services, and stop/disable `clamav-freshclam.service`. Confirm no other updater runs. Ownership switches are manual and reversible. Do not start two updaters on the same directory.
3. Run `sudo ./suite start`; it checks the host CIFS mount and native services before recreating scanner/signature containers. Initial signature download may take several minutes. `sudo ./suite doctor` and `sudo ./suite status` must pass before scans. Missing/stale signatures or an unavailable NAS produce blocked/unhealthy results, never a clean result. Health checks inspect prerequisites; they do not claim content was scanned.
4. Run `sudo ./suite scan --dry-run`, then a bounded real scan with `sudo ./suite scan --target /mnt/four-securitycenter/downloads/media/REVIEWED_FILE`. Review `suite alerts` and `suite logs`. Coverage remains ClamAV up to 1.9GB and narrow YARA media payload triage up to 8GB. Cache status is not comprehensive antivirus coverage.
5. After acceptance, opt into intervals in `.env` (zero disables; minimum 60 seconds). Scan and discovery run serially and use the same file lock as manual/native runner jobs. The scheduler delays its first job by one interval and waits a full interval after completion. Termination stops its engine process group; interrupted files remain eligible for another scan. Manual scans execute inside the existing scanner container and share its resource limit.
6. Install the provided suite systemd unit only after successful reboot/remount testing: copy to `/etc/systemd/system`, reload units and enable it. It requires the NAS mount and verifies it again through `suite start`. Failed starts back off 60 seconds with a bounded retry budget. Containers use three failure restarts; unhealthy does not automatically restart them. After a NAS remount, verify the host mount and use `suite restart` to recreate the private bind.

## Operations and recovery

`suite stop` preserves all data. `suite backup` stops services and snapshots configuration, SQLite (including sidecars), signatures, the environment and deployment manifest under `/var/backups/four-securitycenter`. It leaves services stopped to allow review. Native jobs must already be stopped. `suite update` takes that snapshot, builds using the recorded Debian digest, records new package versions and pins the new image; review and start manually. To advance Debian base digest deliberately, back up, edit DEBIAN_IMAGE to a verified ARM64 digest, then update. A build failure leaves services stopped and the prior snapshot available.

`suite rollback /var/backups/four-securitycenter/TIMESTAMP` snapshots the current stopped deployment before restoring the selected trusted root-owned snapshot. It restores image selection and data, leaves services stopped, and requires the previous image to remain locally available. Do not edit snapshots or restore untrusted backup content. To return to native operation, stop the suite, restore the native snapshot with its original ownership, re-enable only the native updater after checking container termination, and restore the recorded timer state (normally disabled).

No destructive uninstall command is provided. To uninstall, stop the suite, disable/remove its host boot unit and remove containers with Compose down (without volume deletion). Keep `/etc/four-securitycenter`, `/var/lib/four-securitycenter`, `/var/lib/clamav` and backups until the owner explicitly authorizes deletion.

## Optional IDS

The `ids` profile is disabled by default. Validate actual mirror/TAP visibility first. Prepare `/etc/four-securitycenter/suricata/suricata.yaml`, rules and classification files on the host, with logging to `/var/log/suricata` and run/pid files under `/tmp`; prepare `/var/log/four-securitycenter/suricata`. Set CAPTURE_INTERFACE explicitly, test config using the built image, then invoke Compose with `--profile ids up -d suricata`. This service alone uses host networking and capture capabilities. It has no NAS or scanner-state mounts. No full-LAN visibility claim is justified without observed traffic. `suite stop` also stops IDS; normal `suite start` does not enable it.

## Acceptance gate (record results on the Pi)

- Build on Linux ARM64 and record base digest, package versions and image ID. Test command errors and health with fresh, missing and stale signatures.
- Run the scanner unit tests on Linux (`python3 -m unittest discover -s tests -p 'test_*.py'`). Verify local EICAR, benign YARA fixtures beyond 2GB, bounded actual NAS scans, cache invalidation, changing files, timeout handling and shared locking using existing tests and operations notes. Use disposable local fixtures; never place malware on the NAS.
- Observe CPU/memory and Jellyfin playback under scan load. Verify no concurrent heavy jobs, stop during a scan, container failure/restart and data persistence.
- Disconnect NAS, simulate unreachable/stale CIFS, unmount/remount, recreate scanner and reboot. Each failure must be blocked/degraded. Mount inspection alone cannot guarantee a responsive SMB server; bounded health timeouts must flag hangs.
- Restore a stopped snapshot and the native deployment. Only then enable schedules, recording actual rule coverage and tested limits.

Docker bind behavior reference: https://docs.docker.com/engine/storage/bind-mounts/.
