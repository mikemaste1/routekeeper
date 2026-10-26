#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this installer as root (sudo ./install.sh).' >&2
    exit 1
fi
cd "$(dirname "$0")"
for dependency in /usr/bin/python3 /usr/sbin/ip /usr/bin/getent /usr/bin/systemctl; do
    if [ ! -x "$dependency" ]; then
        echo "Missing prerequisite: $dependency (install python3, iproute2, libc-bin and systemd)." >&2
        exit 1
    fi
done
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ required"'
if [ ! -d /run/systemd/system ]; then
    echo 'A running systemd system is required.' >&2
    exit 1
fi
install -d -m 755 /etc/routekeeper /var/lib/routekeeper
install -m 755 routekeeper.py /usr/local/bin/routekeeper
install -m 644 routekeeper.service /etc/systemd/system/routekeeper.service
systemctl daemon-reload
systemctl enable routekeeper.service
systemctl restart routekeeper.service
systemctl --no-pager status routekeeper.service
