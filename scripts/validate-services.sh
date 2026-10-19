#!/bin/sh
set -eu
cd /opt/four-securitycenter
python3 -m unittest discover -s tests -v
systemd-analyze verify /etc/systemd/system/four-securitycenter-*.service /etc/systemd/system/four-securitycenter-*.timer
systemctl start four-securitycenter-discover.service four-securitycenter-report.service
install -d /run/systemd/system/four-securitycenter-scan.service.d
override=/run/systemd/system/four-securitycenter-scan.service.d/phase3-validation.conf
trap 'rm -f "$override"; systemctl daemon-reload' EXIT
cat > "$override" <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/local/bin/four-securitycenter scan --dry-run
EOF
systemctl daemon-reload
systemctl start four-securitycenter-scan.service
systemctl show four-securitycenter-discover.service four-securitycenter-report.service four-securitycenter-scan.service -p Id -p Result -p ActiveState
