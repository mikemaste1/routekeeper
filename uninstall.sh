#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run sudo sh uninstall.sh' >&2
    exit 1
fi
systemctl disable --now routekeeper.service
if [ -x /usr/local/bin/routekeeper ]; then
    /usr/local/bin/routekeeper cleanup
fi
rm -f /etc/systemd/system/routekeeper.service /usr/local/bin/routekeeper
systemctl daemon-reload
echo 'Uninstalled. Configuration and state are preserved in /etc/routekeeper and /var/lib/routekeeper.'
