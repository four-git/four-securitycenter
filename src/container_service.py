"""Container lifecycle. Scheduling is opt-in; the scanner owns the shared lock."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

CONFIG = '/etc/four-securitycenter/scanner.json'
RUNNER = str(Path(__file__).with_name('four_securitycenter.py'))
stopping = False
child = None


def terminate(signum, frame):
    global stopping
    stopping = True
    if child is not None and child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)


def run(args):
    global child
    child = subprocess.Popen(args, start_new_session=True)
    try:
        while child.poll() is None:
            if stopping:
                try:
                    return child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
            time.sleep(0.2)
        return child.returncode
    finally:
        child.wait()
        child = None


def signature_health():
    daily = [p for p in Path('/var/lib/clamav').glob('daily.*') if p.suffix in ('.cvd', '.cld')]
    if not daily or time.time() - max(p.stat().st_mtime for p in daily) > 72 * 3600:
        raise RuntimeError('BLOCKED: missing or stale daily signatures')


def scheduler():
    intervals = {action: int(os.environ.get(env, '0')) for action, env in (
        ('scan', 'SCAN_INTERVAL_SECONDS'), ('discover', 'DISCOVER_INTERVAL_SECONDS'))}
    if any(value < 0 or 0 < value < 60 for value in intervals.values()):
        raise ValueError('Intervals must be zero (disabled) or at least 60 seconds')
    due = {action: time.monotonic() + interval for action, interval in intervals.items()}
    print(json.dumps({'schedules': intervals, 'coverage': 'Narrow YARA triage; ClamAV file ceiling remains'}), flush=True)
    while not stopping:
        for action, interval in intervals.items():
            if stopping:
                break
            if interval and time.monotonic() >= due[action]:
                rc = run([sys.executable, RUNNER, '--config', CONFIG, action])
                print(json.dumps({'action': action, 'exit_code': rc}), flush=True)
                due[action] = time.monotonic() + interval
        time.sleep(1)
    return 0


def main():
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    action = sys.argv[1] if len(sys.argv) > 1 else 'scheduler'
    if action == 'scheduler':
        return scheduler()
    if action == 'signatures':
        return run(['freshclam', '--daemon', '--foreground=true', '--config-file=/etc/clamav/freshclam.conf'])
    if action == 'signature-health':
        signature_health()
        return 0
    if action == 'ids':
        interface = os.environ.get('CAPTURE_INTERFACE', '')
        if not interface or not Path('/sys/class/net', interface).is_dir():
            raise ValueError('Explicit, validated capture interface required')
        return run(['suricata', '-c', '/etc/suricata/suricata.yaml', '-i', interface])
    return run([sys.executable, RUNNER, '--config', CONFIG, *sys.argv[1:]])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        sys.exit(2)
