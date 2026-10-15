#!/bin/bash
set -eu
src="$(cd -- "$(dirname -- "$0")" && pwd)"
# Reject paths unsafe for shell, desktop and systemd command syntaxes.
case "$src" in *[!a-zA-Z0-9_./-]*) echo 'Use a checkout path with only letters, digits, _, -, / and .' >&2; exit 1;; esac
if [ ! -f "$src/.env" ]; then
    echo 'First run: cp .env.example .env, then edit your office Wi-Fi and daily target.' >&2
    exit 1
fi
/usr/bin/python3 -c "import sys; sys.path.insert(0, '$src'); import settings"
install -d -m 700 "$HOME/.local/share/arbetstid" "$HOME/.config/systemd/user" "$HOME/.local/bin" "$HOME/.local/share/applications"
cat > "$HOME/.config/systemd/user/arbetstid.service" <<EOF
[Unit]
Description=Local work-time tracker

[Service]
Type=simple
ExecStart=/usr/bin/python3 "$src/arbetstid.py" daemon
Restart=on-failure
RestartSec=10
TimeoutStopSec=20
UMask=0077

[Install]
WantedBy=default.target
EOF
cat > "$HOME/.local/bin/arbetstid" <<EOF
#!/bin/sh
exec /usr/bin/python3 "$src/arbetstid.py" "\$@"
EOF
chmod 700 "$HOME/.local/bin/arbetstid"
cat > "$HOME/.local/share/applications/arbetstid.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Arbetstid
Comment=Visa din lokala arbetstidslogg
Exec=konsole --hold -e /usr/bin/python3 "$src/arbetstid.py" report
Icon=office-calendar
Terminal=false
Categories=Office;
EOF
for action in start stop; do
    if [ "$action" = start ]; then label='Börja jobba hemifrån'; else label='Avsluta arbetspass'; fi
    cat > "$HOME/.local/share/applications/arbetstid-$action.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$label
Exec=konsole --hold -e /usr/bin/python3 "$src/arbetstid.py" $action
Icon=office-calendar
Terminal=false
Categories=Office;
EOF
done
systemctl --user daemon-reload
systemctl --user enable --now arbetstid.service
