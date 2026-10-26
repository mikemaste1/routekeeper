# Routekeeper

Persistent Linux IPv4 routes for IP addresses, CIDR networks, and DNS/DDNS hostnames.
Define named gateways, assign destinations, and inspect resolved addresses from a CLI.
A systemd service refreshes DNS and repairs missing routes every 60 seconds.
No pip packages, containers, or DNS-server replacement required.

## Install

Requires Linux with systemd, Python 3.10+, iproute2, getent, curl, and sudo/root.
Ubuntu 22.04+ and Debian 12+ are intended targets; see CI for tested environments.

```sh
curl -fsSL https://raw.githubusercontent.com/mikemaste1/routekeeper/v0.1.0/bootstrap.sh | sh
```

The command downloads version v0.1.0 and asks sudo to install the service.
It starts with no gateways or destinations. Existing configuration is preserved on upgrades.
For a local source checkout, use `sudo sh install.sh` instead.

To review before running, download the repository, inspect `bootstrap.sh`, `install.sh`,
and `routekeeper.py`, then run the local installer. A Git commit ID can replace the tag
in both the bootstrap URL and its first argument for immutable source pinning:

```sh
curl -fsSL https://raw.githubusercontent.com/mikemaste1/routekeeper/COMMIT/bootstrap.sh | sh -s -- COMMIT
```

## Quick start

```sh
# Register your reachable LAN gateway and interface.
sudo routekeeper gateway add office 192.0.2.1 --dev eth0

# Add one or several destinations. IPs become /32 routes.
sudo routekeeper add 198.51.100.0/24 203.0.113.0/24 --via office
sudo routekeeper add 203.0.113.42 camera.example.net --via office

# Show all gateways, configured destinations and their resolved IPs.
routekeeper status
routekeeper status office
routekeeper status --json
routekeeper gateway list

# Change a destination's gateway by adding it with a different --via name.
sudo routekeeper gateway add backup 192.0.2.2 --dev eth0
sudo routekeeper add camera.example.net --via backup

# Remove positions and then an unused gateway.
sudo routekeeper remove camera.example.net 203.0.113.42
sudo routekeeper gateway remove backup

# Resolve and reconcile immediately.
sudo routekeeper refresh
```

All mutations save the configuration and immediately synchronize routes.
Re-adding a gateway updates its address/interface and its assigned routes.
A gateway cannot be removed while destinations reference it.
Commands with refresh errors return a nonzero status even though configuration was saved;
the service retries automatically.
The example addresses are documentation ranges; substitute your own reachable gateways,
interfaces, networks, and hostname.

## How it works

- Configuration: `/etc/routekeeper/config.json`; root-owned, atomically replaced.
- Last DNS answers and errors: `/var/lib/routekeeper/status.json`.
- Managed routes: main IPv4 table, numeric protocol **186**, metric **42760**.
- The daemon and CLI serialize updates with a file lock.
- DNS uses the system's `getent ahostsv4` resolver, with a 20-second subprocess timeout.
  Every distinct returned IPv4 address receives a /32 route; CNAMEs follow system resolver behavior.
- New DNS addresses are installed before obsolete routes are removed.
  If installation fails, obsolete routes are retained for that refresh.
- Failed or empty DNS lookups retain the last known addresses, including after reboot.
  They remain until resolution recovers or the destination is removed.
- Conflicting resolved addresses assigned to different gateways report an error.
- Unrelated routes are not adopted or removed. Reserve protocol 186 and metric 42760
  for this tool; do not use this pair for routes managed elsewhere.

Normal Linux longest-prefix and metric rules still apply. A pre-existing route with the
same prefix and a lower metric takes precedence. `status` says whether a managed route
is installed; use `ip route get ADDRESS` to verify which route Linux actually selects.
Existing NetworkManager routes may therefore remain preferred.

The gateway must be reachable on the specified interface. This tool does not create
tunnels, configure forwarding/NAT, or make a remote public IP into an on-link gateway.
Routing affects all traffic to an IP, including other hostnames sharing that address.
IPv6, alternate routing tables, DNS TTL scheduling, and domain wildcard policies are
not supported in v0.1.0. DNS changes are noticed at the next successful poll, subject
to resolver caching; established connections are not guaranteed to survive a change.

## Service operations

```sh
systemctl status routekeeper
journalctl -u routekeeper -f
sudo systemctl restart routekeeper
```

Stopping the service leaves routes installed. To disable it and remove its routes:

```sh
sudo systemctl disable --now routekeeper
sudo routekeeper cleanup
```

`cleanup` preserves configuration. Starting the service installs configured routes again.
Do not run a second daemon manually alongside the system service.

To change the refresh interval, run `sudo systemctl edit routekeeper` and add:

```ini
[Service]
ExecStart=
ExecStart=/usr/local/bin/routekeeper daemon --interval 120
```

Then `sudo systemctl daemon-reload && sudo systemctl restart routekeeper`.
The minimum interval is 10 seconds; actual cycles also include DNS lookup time.

## Uninstall

From a checked-out repository:

```sh
sudo sh uninstall.sh
```

This stops/disables the service, removes its tagged routes, and removes the installed
binary and unit. Configuration and state remain available for reinstalling.

## Development

```sh
python3 -m unittest discover -s tests -v
sh -n install.sh bootstrap.sh uninstall.sh
sudo python3 tests/integration.py
```

Integration tests create and destroy a uniquely named network namespace. They exercise
real kernel routing without adding routes to the host namespace. Root and network
namespace support are required. CI runs unit tests with Python 3.10, 3.12, and 3.14,
and kernel integration on Ubuntu.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contributions and [SECURITY.md](SECURITY.md)
for reporting vulnerabilities. Licensed under the [MIT license](LICENSE).
