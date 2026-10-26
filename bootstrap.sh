#!/bin/sh
# Usage: curl -fsSL https://raw.githubusercontent.com/mikemaste1/routekeeper/main/bootstrap.sh | sh
set -eu
ref=${1:-v0.1.0}
case "$ref" in
    *[!a-zA-Z0-9._-]*|'') echo 'Invalid version or commit.' >&2; exit 1 ;;
esac
command -v curl >/dev/null 2>&1 || { echo 'curl is required.' >&2; exit 1; }
download_dir=$(mktemp -d)
trap 'rm -f "$download_dir/routekeeper.py" "$download_dir/routekeeper.service" "$download_dir/install.sh"; rmdir "$download_dir"' EXIT HUP INT TERM
base="https://raw.githubusercontent.com/mikemaste1/routekeeper/$ref"
for asset in routekeeper.py routekeeper.service install.sh; do
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        --connect-timeout 15 --max-time 120 "$base/$asset" -o "$download_dir/$asset"
done
if [ "$(id -u)" -eq 0 ]; then
    sh "$download_dir/install.sh"
else
    sudo sh "$download_dir/install.sh"
fi
