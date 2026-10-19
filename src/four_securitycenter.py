#!/usr/bin/env python3
"""Read-only, bounded NAS scanner. State and reports stay on the Pi."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import time

STATUSES = ('CLEAN', 'MALWARE_DETECTED', 'YARA_MATCH', 'SKIPPED_SIZE_LIMIT',
            'SKIPPED_POLICY', 'PARTIALLY_SCANNED', 'SCAN_ERROR', 'PENDING')


def command(args, timeout=20, **kw):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kw)


def verify_mount(cfg):
    mount = Path(cfg['mount'])
    if not mount.is_dir():
        raise RuntimeError('SCAN_ERROR: mount directory unavailable')
    # stat/is_dir on the automount point itself need not activate autofs. Opening
    # the directory triggers it before findmnt inspects the covering filesystem.
    # Callers bound health/preflight with a timeout; this never writes to the NAS.
    with os.scandir(mount):
        pass
    r = command(['findmnt', '-J', '-T', str(mount), '-o', 'SOURCE,TARGET,FSTYPE,OPTIONS'])
    rows = json.loads(r.stdout).get('filesystems', []) if r.returncode == 0 else []
    # Some util-linux versions report the systemd autofs entry alongside the
    # filesystem mounted over it. Permit that wrapper at this exact target;
    # still require one unambiguous backing filesystem and validate it below.
    automounts = [row for row in rows if row.get('fstype') == 'autofs']
    rows = [row for row in rows if row.get('fstype') != 'autofs']
    if (len(rows) != 1 or len(automounts) > 1 or
            any(Path(row.get('target', '')) != mount for row in automounts)):
        raise RuntimeError('SCAN_ERROR: mount missing or ambiguous')
    m = rows[0]
    if (m['fstype'] != 'cifs' or m['source'] != cfg['source'] or
            Path(m['target']) != mount or 'ro' not in m['options'].split(',') or
            'rw' in m['options'].split(',')):
        raise RuntimeError('SCAN_ERROR: expected read-only CIFS source/target not mounted')
    for relative in cfg['expected_dirs']:
        if not (mount / relative).is_dir():
            raise RuntimeError('SCAN_ERROR: expected NAS directory missing: ' + relative)
    return m


def engine_versions(cfg):
    cv = command(['clamscan', '--version'])
    yv = command(['yara', '--version'])
    if cv.returncode or yv.returncode:
        raise RuntimeError('SCAN_ERROR: scanner version check failed')
    rules = Path(cfg['rules']).read_bytes()
    dbs = [p for p in Path(cfg['clam_database']).iterdir() if p.suffix in ('.cvd', '.cld')]
    if not dbs:
        raise RuntimeError('SCAN_ERROR: no ClamAV databases')
    daily = [p for p in dbs if p.stem == 'daily']
    if not daily:
        raise RuntimeError('SCAN_ERROR: daily signatures missing')
    age = time.time() - max(p.stat().st_mtime for p in daily)
    if age > cfg['signature_max_age_hours'] * 3600:
        raise RuntimeError('SCAN_ERROR: daily signatures stale')
    db_stamp = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in dbs)
    details = {'clamav': cv.stdout.strip(), 'yara': yv.stdout.strip(),
               'rules_sha256': hashlib.sha256(rules).hexdigest(), 'databases': db_stamp,
               'yara_coverage': cfg.get('rules_description', 'unspecified rule coverage')}
    policy = {k: cfg[k] for k in ('clam_max_bytes', 'clam_scan_bytes', 'yara_max_bytes', 'engine_timeout')}
    policy['clam_scan_time_ms'] = cfg.get('clam_scan_time_ms', 120000)
    return details, hashlib.sha256(json.dumps([details, policy], sort_keys=True).encode()).hexdigest()


def combine(clam, yara):
    if clam == 'MALWARE_DETECTED':
        return clam
    if yara == 'YARA_MATCH':
        return yara
    if 'SCAN_ERROR' in (clam, yara):
        return 'SCAN_ERROR'
    if clam == yara == 'CLEAN':
        return 'CLEAN'
    if clam == yara == 'SKIPPED_SIZE_LIMIT':
        return 'SKIPPED_SIZE_LIMIT'
    return 'PARTIALLY_SCANNED'


def interpret(engine, rc, output):
    if engine == 'clam':
        found = [s for s in output.splitlines() if s.endswith(' FOUND')]
        real = [s for s in found if 'Heuristics.Limits.Exceeded' not in s]
        if real:
            return 'MALWARE_DETECTED'
        if 'Heuristics.Limits.Exceeded' in output:
            size_limits = ('Heuristics.Limits.Exceeded.MaxFileSize', 'Heuristics.Limits.Exceeded.MaxScanSize')
            return 'SKIPPED_SIZE_LIMIT' if rc in (0, 1) and any(x in output for x in size_limits) else 'SCAN_ERROR'
        if rc == 0 and not output.strip():
            return 'CLEAN'
        return 'SCAN_ERROR'
    if rc != 0:
        return 'SCAN_ERROR'
    return 'YARA_MATCH' if output.strip() else 'CLEAN'


def scan_fd(fd, size, cfg, deadline):
    results = {}
    evidence = {}
    for engine in ('clam', 'yara'):
        limit = cfg['clam_max_bytes'] if engine == 'clam' else cfg['yara_max_bytes']
        if size > limit or (engine == 'clam' and size >= 2_000_000_000):
            results[engine] = 'SKIPPED_SIZE_LIMIT'
            evidence[engine] = 'file exceeds configured or engine size limit'
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results[engine] = 'SCAN_ERROR'
            evidence[engine] = 'job time budget exhausted'
            continue
        target = '/proc/self/fd/' + str(fd)
        if engine == 'clam':
            args = ['clamscan', '--infected', '--no-summary', '--alert-exceeds-max',
                    '--max-filesize=' + str(cfg['clam_max_bytes']),
                    '--max-scansize=' + str(cfg['clam_scan_bytes']),
                    '--max-scantime=' + str(cfg.get('clam_scan_time_ms', 120000)), target]
        else:
            args = ['yara', '--print-meta', '--timeout=' + str(cfg['engine_timeout']), cfg['rules'], target]
        try:
            r = command(args, timeout=min(cfg['engine_timeout'], remaining), pass_fds=(fd,))
            output = r.stdout + r.stderr
            results[engine] = interpret(engine, r.returncode, output)
            evidence[engine] = {'exit': r.returncode, 'output': output[-4000:]}
        except (subprocess.TimeoutExpired, OSError) as e:
            results[engine] = 'SCAN_ERROR'
            evidence[engine] = str(e)
    return results, evidence


def database(path):
    db = sqlite3.connect(path)
    db.execute('''CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY, share TEXT, size INTEGER, mtime INTEGER,
        stable_since REAL, versions TEXT, status TEXT, clam TEXT, yara TEXT,
        last_attempt REAL, last_success REAL, reason TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, time REAL, path TEXT, kind TEXT, detail TEXT)''')
    db.commit()
    return db


def within(path, root):
    return path == root or root in path.parents


def scan(cfg, dry=False, target=None, discover_only=False):
    versions, fingerprint = engine_versions(cfg)
    verify_mount(cfg)
    mount = Path(cfg['mount'])
    roots = [mount / p for p in cfg['roots']]
    if any(not within(p.resolve(), mount) for p in roots):
        raise RuntimeError('SCAN_ERROR: root escapes mount')
    if target:
        candidate = Path(target).absolute()
        if not any(within(candidate, root) for root in roots):
            raise RuntimeError('SCAN_ERROR: selected target outside allowed roots')
        roots = [candidate]
    db = database(cfg['state_db'])
    now = time.time()
    deadline = time.monotonic() + cfg['max_runtime_seconds']
    summary = {'dry_run': dry, 'counts': {}, 'versions': versions, 'visited': 0,
               'scan_attempts': 0, 'cached': 0, 'discovery_truncated': False}

    def count(status):
        summary['counts'][status] = summary['counts'].get(status, 0) + 1

    def walk_error(error):
        raise RuntimeError('SCAN_ERROR: cannot enumerate directory: ' + str(error))

    def candidates():
        for root in roots:
            if not root.exists():
                raise RuntimeError('SCAN_ERROR: selected root missing: ' + str(root))
            if root.is_file() or root.is_symlink():
                yield root
            else:
                for base, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
                    dirs[:] = sorted(d for d in dirs if not Path(base, d).is_symlink())
                    for name in sorted(names):
                        yield Path(base, name)

    # Prioritize never-scanned and oldest attempts so daily signature updates
    # cannot repeatedly consume the budget on only the first alphabetic files.
    pending_paths = []
    for path in candidates():
        if len(pending_paths) >= cfg['max_files_per_run'] or time.monotonic() >= deadline:
            summary['discovery_truncated'] = True
            break
        pending_paths.append(path)
    attempted_times = dict(db.execute('SELECT path,COALESCE(last_attempt,0) FROM files'))
    def priority(path):
        root_priority = next((i for i, root in enumerate(roots) if within(path, root)), len(roots))
        return (attempted_times.get(str(path), 0), root_priority, str(path))
    pending_paths.sort(key=priority)
    for path in pending_paths:
        if time.monotonic() >= deadline or summary['visited'] >= cfg['max_files_per_run']:
            summary['discovery_truncated'] = True
            break
        summary['visited'] += 1
        if path.is_symlink():
            count('SKIPPED_POLICY')
            continue
        # Revalidate before every file: a lost mount must not look like an empty clean folder.
        verify_mount(cfg)
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode):
            count('SKIPPED_POLICY')
            continue
        key = str(path)
        old = db.execute('SELECT size,mtime,stable_since,versions,status,last_success FROM files WHERE path=?', (key,)).fetchone()
        changed = old is None or old[:2] != (st.st_size, st.st_mtime_ns)
        since = now if changed else old[2]
        if changed and old:
            db.execute('INSERT INTO events(time,path,kind,detail) VALUES(?,?,?,?)',
                       (now, key, 'FILE_CHANGED', 'size or modification time changed'))
        stable = now - since >= cfg['stable_seconds'] and now - st.st_mtime >= cfg['stable_seconds']
        result, engines, evidence = 'PENDING', {}, {}
        attempted, success = None, old[5] if old else None
        if not changed and stable and old[3] == fingerprint and old[4] not in ('SCAN_ERROR', 'PENDING'):
            result = old[4]
            summary['cached'] += 1
            count(result)
            continue
        if stable and not dry and not discover_only:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                before = os.fstat(fd)
                if (before.st_size, before.st_mtime_ns) != (st.st_size, st.st_mtime_ns):
                    since = now
                else:
                    attempted = time.time()
                    engines, evidence = scan_fd(fd, st.st_size, cfg, deadline)
                    after = os.fstat(fd)
                    current = path.lstat()
                    _, after_fingerprint = engine_versions(cfg)
                    if after_fingerprint != fingerprint:
                        result, since = 'PENDING', now
                        evidence['reason'] = 'engine/rules/signatures changed during scanning'
                    elif ((after.st_size, after.st_mtime_ns, after.st_ino) !=
                            (before.st_size, before.st_mtime_ns, before.st_ino) or
                            (current.st_size, current.st_mtime_ns, current.st_ino) !=
                            (before.st_size, before.st_mtime_ns, before.st_ino)):
                        result, since = 'PENDING', now
                        evidence['reason'] = 'file changed during scanning'
                    else:
                        result = combine(engines['clam'], engines['yara'])
                        if result == 'CLEAN':
                            success = attempted
                    summary['scan_attempts'] += 1
            finally:
                os.close(fd)
        elif stable and dry:
            evidence['reason'] = 'eligible; dry-run does not execute engines'
        if not dry:
            db.execute('''INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (key, cfg['source'], st.st_size, st.st_mtime_ns, since,
                        fingerprint if attempted else '', result, engines.get('clam'),
                        engines.get('yara'), attempted, success, json.dumps(evidence)))
            db.execute('INSERT INTO events(time,path,kind,detail) VALUES(?,?,?,?)',
                       (now, key, result, json.dumps(evidence)))
            db.commit()
        count(result)
    if not dry:
        db.execute('DELETE FROM events WHERE time < ?', (now - cfg['retention_days'] * 86400,))
        db.commit()
    db.close()
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='/etc/four-securitycenter/scanner.json')
    p.add_argument('action', choices=('scan', 'discover', 'status', 'health', 'alerts'))
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--target')
    a = p.parse_args()
    try:
        cfg = json.loads(Path(a.config).read_text())
        if a.action in ('scan', 'discover'):
            with open(cfg['lock_file'], 'a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError('SCAN_ERROR: another scan is running')
                result = scan(cfg, a.dry_run, a.target, a.action == 'discover')
            print(json.dumps(result, indent=2))
            counts = result['counts']
            return 2 if counts.get('SCAN_ERROR') else 1 if counts.get('MALWARE_DETECTED') or counts.get('YARA_MATCH') else 0
        if a.action == 'health':
            m = verify_mount(cfg)
            v, _ = engine_versions(cfg)
            print(json.dumps({'mount': m, 'engines': v, 'time': time.time()}, indent=2))
        else:
            db = database(cfg['state_db'])
            db.row_factory = sqlite3.Row
            if a.action == 'status':
                data = [dict(r) for r in db.execute('SELECT status,COUNT(*) AS files FROM files GROUP BY status')]
            else:
                data = [dict(r) for r in db.execute("SELECT * FROM events WHERE kind IN ('MALWARE_DETECTED','YARA_MATCH','SCAN_ERROR','PARTIALLY_SCANNED','SKIPPED_SIZE_LIMIT','FILE_CHANGED') ORDER BY id DESC LIMIT 100")]
            print(json.dumps(data, indent=2))
            db.close()
        return 0
    except Exception as e:
        print(json.dumps({'status': 'SCAN_ERROR', 'reason': str(e)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
