#!/usr/bin/python3
"""Exercise real kernel routes in an ephemeral namespace, never on the host."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def inside():
    spec = importlib.util.spec_from_file_location('rk', Path(__file__).resolve().parents[1] / 'routekeeper.py')
    rk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rk)
    with tempfile.TemporaryDirectory() as directory:
        rk.STATE = Path(directory)
        config = {'gateways': {'test': {'address': '192.0.2.1', 'interface': 'rk0'}},
                  'destinations': {'198.51.100.0/24': 'test'}}
        run(rk.IP, 'route', 'add', '203.0.113.0/24', 'via', '192.0.2.1', 'dev', 'rk0')
        assert not rk.reconcile(config, {})['errors']
        assert len([r for r in rk.routes() if rk.owned(r)]) == 1
        assert not rk.reconcile(config, {})['errors']
        config['gateways']['test']['address'] = '192.0.2.2'
        assert not rk.reconcile(config, {})['errors']
        assert [r for r in rk.routes() if rk.owned(r)][0]['gateway'] == '192.0.2.2'
        config['destinations'] = {}
        assert not rk.reconcile(config, {})['errors']
        assert not any(rk.owned(r) for r in rk.routes())
        assert any(r.get('dst') == '203.0.113.0/24' for r in rk.routes())
        print('Kernel integration passed: add, repeat, change gateway, remove, preserve foreign routes.')


if __name__ == '__main__':
    if '--inside' in sys.argv:
        inside()
    else:
        if os.geteuid() != 0:
            sys.exit('Run as root; creates an isolated temporary network namespace.')
        name = 'rk-test-' + uuid.uuid4().hex[:10]
        created = False
        try:
            run('/usr/sbin/ip', 'netns', 'add', name)
            created = True
            run('/usr/sbin/ip', '-n', name, 'link', 'add', 'rk0', 'type', 'dummy')
            run('/usr/sbin/ip', '-n', name, 'addr', 'add', '192.0.2.10/24', 'dev', 'rk0')
            run('/usr/sbin/ip', '-n', name, 'link', 'set', 'rk0', 'up')
            print(run('/usr/sbin/ip', 'netns', 'exec', name, sys.executable, str(Path(__file__).resolve()), '--inside'))
        finally:
            if created:
                run('/usr/sbin/ip', 'netns', 'del', name)
