#!/usr/bin/python3
"""Manage persistent IPv4 routes for IP, CIDR and DNS destinations."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

PROTO = 186
METRIC = 42760
VERSION = '0.1.0'
ROOT = Path('/etc/routekeeper')
STATE = Path('/var/lib/routekeeper')
IP = '/usr/sbin/ip'


def run(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=20)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or 'Command failed: ' + ' '.join(args))
    return p.stdout


def read(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def destination(value):
    try:
        return str(ipaddress.IPv4Network(value, strict=False))
    except ValueError:
        if '/' in value or ':' in value or re.fullmatch(r'[0-9.]+', value):
            raise ValueError('Invalid IPv4 address/CIDR: ' + value)
        value = value.rstrip('.').encode('idna').decode().lower()
        if len(value) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x) for x in value.split('.')):
            raise ValueError('Invalid DNS hostname: ' + value)
        return value


def resolve(value):
    if '/' in value:
        return [value]
    output = run(['/usr/bin/getent', 'ahostsv4', value])
    ips = sorted({str(ipaddress.IPv4Address(line.split()[0])) + '/32'
                  for line in output.splitlines() if line.strip()})
    if not ips:
        raise RuntimeError('DNS returned no IPv4 addresses')
    return ips


def routes():
    return json.loads(run([IP, '-N', '-j', '-4', 'route', 'show', 'table', 'main']))


def route_key(r):
    return (str(ipaddress.IPv4Network('0.0.0.0/0' if r['dst'] == 'default' else r['dst'], strict=False)),
            r.get('gateway'), r.get('dev'))


def owned(r):
    return str(r.get('protocol')) == str(PROTO) and r.get('metric') == METRIC


def change(action, key):
    dst, gw, dev = key
    run([IP, '-4', 'route', action, dst, 'via', gw, 'dev', dev,
         'proto', str(PROTO), 'metric', str(METRIC), 'table', 'main'])


def reconcile(config, old):
    desired = set()
    entries = {}
    errors = []
    for dest, name in config['destinations'].items():
        gateway = config['gateways'][name]
        entry = {'gateway': name, 'addresses': [], 'error': None}
        try:
            entry['addresses'] = resolve(dest)
            entry['resolved_at'] = time.time()
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            previous = old.get('entries', {}).get(dest, {})
            entry['addresses'] = previous.get('addresses', [])
            entry['resolved_at'] = previous.get('resolved_at')
            entry['error'] = str(e)
            errors.append(f'{dest}: {e}')
        entries[dest] = entry
        for address in entry['addresses']:
            desired.add((address, gateway['address'], gateway['interface']))
    # Refuse ambiguous ownership where two hostnames resolve to the same IP
    # but request different gateways.
    by_dest = {}
    for key in desired:
        by_dest.setdefault(key[0], set()).add(key)
    conflicts = {d for d, keys in by_dest.items() if len(keys) > 1}
    for d in conflicts:
        errors.append(f'{d}: conflicting gateways; leaving existing routes untouched')
    current = {route_key(r) for r in routes() if owned(r)}
    failed = set(conflicts)
    for key in sorted(desired - current):
        if key[0] in conflicts:
            continue
        try:
            replaced = {r for r in current if r[0] == key[0]}
            change('replace' if replaced else 'add', key)
            current -= replaced
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            failed.add(key[0])
            errors.append(f'add {key[0]}: {e}')
    for key in sorted(current - desired):
        # On a partial failure retain old routes so DNS rotation cannot
        # strand a destination before all replacement addresses are installed.
        if failed:
            continue
        try:
            change('del', key)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            errors.append(f'remove {key[0]}: {e}')
    result = {'updated_at': time.time(), 'entries': entries, 'errors': errors}
    write(STATE / 'status.json', result)
    for error in errors:
        print(error, file=sys.stderr, flush=True)
    return result


def locked():
    ROOT.mkdir(parents=True, exist_ok=True)
    f = (ROOT / '.lock').open('a')
    fcntl.flock(f, fcntl.LOCK_EX)
    return f


def load():
    return read(ROOT / 'config.json', {'gateways': {}, 'destinations': {}})


def status(config, name=None, as_json=False):
    state = read(STATE / 'status.json', {})
    actual = routes()
    if as_json:
        print(json.dumps({'config': config, 'status': state,
                          'managed_routes': [r for r in actual if owned(r)]}, indent=2))
        return
    service = subprocess.run(['/usr/bin/systemctl', 'is-active', 'routekeeper.service'],
                             capture_output=True, text=True).stdout.strip()
    print('Service: ' + (service or 'unknown'))
    stamp = state.get('updated_at')
    print('Last refresh: ' + (time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime(stamp)) if stamp else 'never'))
    if name and name not in config['gateways']:
        raise ValueError('Unknown gateway: ' + name)
    active = {route_key(r) for r in actual if owned(r)}
    for label, gw in config['gateways'].items():
        if name and label != name:
            continue
        print(f"\n{label}: via {gw['address']} dev {gw['interface']}")
        selected = [(d, n) for d, n in config['destinations'].items() if n == label]
        if not selected:
            print('  (no destinations)')
        for dest, _ in selected:
            entry = state.get('entries', {}).get(dest, {})
            print('  ' + dest)
            for addr in entry.get('addresses', []):
                flag = 'installed' if (addr, gw['address'], gw['interface']) in active else 'missing'
                print(f'    {addr} [{flag}]')
            if entry.get('error'):
                print('    DNS error; retaining last known addresses: ' + entry['error'])
        external = [r for r in actual if not owned(r) and r.get('gateway') == gw['address'] and r.get('dev') == gw['interface']]
        if external:
            print('  Other routes through this gateway (not managed by routekeeper):')
            for r in external:
                print('    ' + r['dst'])
    for error in state.get('errors', []):
        print('ERROR: ' + error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version=VERSION)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('status', help='Show service, gateways, destinations and active IPs')
    p.add_argument('gateway', nargs='?')
    p.add_argument('--json', action='store_true')
    p = sub.add_parser('gateway', help='Manage named gateways')
    gs = p.add_subparsers(dest='action', required=True)
    g = gs.add_parser('add')
    g.add_argument('name')
    g.add_argument('address')
    g.add_argument('--dev', required=True)
    g = gs.add_parser('remove')
    g.add_argument('name')
    gs.add_parser('list')
    p = sub.add_parser('add', help='Add IP/CIDR/DNS destinations')
    p.add_argument('destinations', nargs='+')
    p.add_argument('--via', required=True, help='Named gateway')
    p = sub.add_parser('remove', help='Remove destinations and their managed routes')
    p.add_argument('destinations', nargs='+')
    sub.add_parser('refresh', help='Resolve DNS and reconcile routes now')
    sub.add_parser('cleanup', help='Remove all routekeeper routes (stop service first)')
    p = sub.add_parser('daemon', help='Run the system service')
    p.add_argument('--interval', type=int, default=60)
    args = parser.parse_args()
    if args.command == 'status' or (args.command == 'gateway' and args.action == 'list'):
        status(load(), getattr(args, 'gateway', None), getattr(args, 'json', False))
        return
    if os.geteuid() != 0:
        raise ValueError('This operation requires root; run with sudo.')
    if args.command == 'daemon' and args.interval < 10:
        raise ValueError('Refresh interval must be at least 10 seconds')
    if args.command == 'cleanup':
        with locked():
            for r in routes():
                if owned(r):
                    change('del', route_key(r))
            write(STATE / 'status.json', {})
        print('Managed routes removed. Configuration preserved.')
        return 0
    while True:
        with locked():
            config = load()
            if args.command == 'gateway':
                if args.action == 'add':
                    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.name):
                        raise ValueError('Gateway names may contain letters, digits, _ and -')
                    address = str(ipaddress.IPv4Address(args.address))
                    run([IP, 'link', 'show', 'dev', args.dev])
                    config['gateways'][args.name] = {'address': address, 'interface': args.dev}
                else:
                    if args.name not in config['gateways']:
                        raise ValueError('Unknown gateway: ' + args.name)
                    if args.name in config['destinations'].values():
                        raise ValueError('Remove or reassign this gateway\'s destinations first')
                    del config['gateways'][args.name]
            elif args.command == 'add':
                if args.via not in config['gateways']:
                    raise ValueError('Unknown gateway: ' + args.via)
                normalized = [destination(d) for d in args.destinations]
                for d in normalized:
                    config['destinations'][d] = args.via
            elif args.command == 'remove':
                normalized = [destination(d) for d in args.destinations]
                for d in normalized:
                    if d not in config['destinations']:
                        raise ValueError('Unknown destination: ' + d)
                for d in normalized:
                    del config['destinations'][d]
            if args.command not in ('refresh', 'daemon'):
                write(ROOT / 'config.json', config)
            result = reconcile(config, read(STATE / 'status.json', {}))
        if args.command != 'daemon':
            if result['errors']:
                print('Configuration saved; refresh reported errors. See routekeeper status.', file=sys.stderr)
                return 1
            print('Routes synchronized.')
            return 0
        time.sleep(args.interval)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print('routekeeper: ' + str(exc), file=sys.stderr)
        sys.exit(1)
