import importlib.util
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('rk', pathlib.Path(__file__).resolve().parents[1] / 'routekeeper.py')
rk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rk)


class Routes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patcher = patch.object(rk, 'STATE', pathlib.Path(self.temp.name))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.config = {'gateways': {'office': {'address': '192.0.2.1', 'interface': 'eth0'}},
                       'destinations': {'host.example': 'office'}}

    def route(self, dst, gateway='192.0.2.1', protocol=186, metric=42760):
        return {'dst': dst, 'gateway': gateway, 'dev': 'eth0', 'protocol': protocol, 'metric': metric}

    def test_normalization(self):
        for source, expected in [('192.0.2.7', '192.0.2.7/32'), ('192.0.2.7/24', '192.0.2.0/24'),
                                 ('HOST.Example.', 'host.example')]:
            self.assertEqual(rk.destination(source), expected)
        for bad in ['-flag', 'a;id', '192.0.2.999', 'host/24', '::1', 'a..b']:
            with self.assertRaises(ValueError):
                rk.destination(bad)

    def test_default_route_key(self):
        self.assertEqual(rk.route_key(self.route('default'))[0], '0.0.0.0/0')

    @patch.object(rk, 'routes', return_value=[])
    @patch.object(rk.os, 'geteuid', return_value=0)
    def test_cli_gateway_add_and_remove_destination(self, uid, routes):
        with patch.object(rk, 'ROOT', pathlib.Path(self.temp.name) / 'config'):
            with patch('sys.argv', ['routekeeper', 'gateway', 'add', 'office', '192.0.2.1', '--dev', 'eth0']), patch.object(rk, 'run', return_value=''):
                self.assertEqual(rk.main(), 0)
            with patch('sys.argv', ['routekeeper', 'add', '198.51.100.0/24', '--via', 'office']), patch.object(rk, 'change') as change:
                self.assertEqual(rk.main(), 0)
                change.assert_called_once()
            self.assertEqual(rk.load()['destinations'], {'198.51.100.0/24': 'office'})
            with patch('sys.argv', ['routekeeper', 'remove', '198.51.100.0/24']):
                self.assertEqual(rk.main(), 0)
            self.assertEqual(rk.load()['destinations'], {})

    @patch.object(rk.os, 'geteuid', return_value=1000)
    def test_cli_requires_root_for_mutations(self, uid):
        with patch('sys.argv', ['routekeeper', 'refresh']):
            with self.assertRaisesRegex(ValueError, 'requires root'):
                rk.main()

    @patch.object(rk, 'change')
    @patch.object(rk, 'routes', return_value=[])
    @patch.object(rk, 'resolve', return_value=['198.51.100.1/32', '198.51.100.2/32'])
    def test_multiple_addresses_and_idempotence(self, resolve, routes, change):
        state = rk.reconcile(self.config, {})
        self.assertEqual(change.call_count, 2)
        routes.return_value = [self.route(x) for x in state['entries']['host.example']['addresses']]
        change.reset_mock()
        rk.reconcile(self.config, state)
        change.assert_not_called()

    @patch.object(rk, 'change')
    @patch.object(rk, 'routes')
    @patch.object(rk, 'resolve', side_effect=RuntimeError('DNS unavailable'))
    def test_dns_failure_retains_last_known(self, resolve, routes, change):
        routes.return_value = [self.route('198.51.100.1/32')]
        previous = {'entries': {'host.example': {'addresses': ['198.51.100.1/32'], 'resolved_at': 1}}}
        state = rk.reconcile(self.config, previous)
        change.assert_not_called()
        self.assertTrue(state['errors'])
        self.assertEqual(state['entries']['host.example']['resolved_at'], 1)

    @patch.object(rk, 'change')
    @patch.object(rk, 'routes')
    @patch.object(rk, 'resolve', return_value=['198.51.100.2/32'])
    def test_rotation_adds_before_deleting_and_preserves_foreign(self, resolve, routes, change):
        routes.return_value = [self.route('198.51.100.1/32'), self.route('203.0.113.0/24', protocol='static'),
                               self.route('203.0.114.0/24', metric=100)]
        rk.reconcile(self.config, {})
        self.assertEqual([x.args[0] for x in change.call_args_list], ['add', 'del'])
        self.assertEqual(change.call_args_list[1].args[1][0], '198.51.100.1/32')

    @patch.object(rk, 'change', side_effect=RuntimeError('gateway unreachable'))
    @patch.object(rk, 'routes')
    @patch.object(rk, 'resolve', return_value=['198.51.100.2/32'])
    def test_install_failure_keeps_old_routes(self, resolve, routes, change):
        routes.return_value = [self.route('198.51.100.1/32')]
        result = rk.reconcile(self.config, {})
        self.assertTrue(result['errors'])
        self.assertEqual(change.call_count, 1)

    @patch.object(rk, 'change')
    @patch.object(rk, 'routes')
    @patch.object(rk, 'resolve', return_value=['198.51.100.1/32'])
    def test_gateway_change_replaces_owned_route(self, resolve, routes, change):
        routes.return_value = [self.route('198.51.100.1/32', gateway='192.0.2.2')]
        result = rk.reconcile(self.config, {})
        self.assertFalse(result['errors'])
        change.assert_called_once_with('replace', ('198.51.100.1/32', '192.0.2.1', 'eth0'))

    @patch.object(rk, 'change')
    @patch.object(rk, 'routes', return_value=[])
    @patch.object(rk, 'resolve', return_value=['198.51.100.1/32'])
    def test_conflicting_dns_gateways(self, resolve, routes, change):
        self.config['gateways']['other'] = {'address': '192.0.2.2', 'interface': 'eth0'}
        self.config['destinations']['other.example'] = 'other'
        result = rk.reconcile(self.config, {})
        change.assert_not_called()
        self.assertTrue(result['errors'])

    @patch.object(rk, 'change')
    @patch.object(rk, 'routes')
    def test_removal_only_deletes_owned_routes(self, routes, change):
        routes.return_value = [self.route('198.51.100.1/32'), self.route('203.0.113.0/24', protocol='static')]
        self.config['destinations'] = {}
        rk.reconcile(self.config, {})
        change.assert_called_once_with('del', ('198.51.100.1/32', '192.0.2.1', 'eth0'))

    @patch.object(rk, 'run')
    def test_dns_deduplicates_all_addresses(self, run):
        run.return_value = '198.51.100.1 STREAM host\n198.51.100.1 DGRAM\n198.51.100.2 STREAM\n'
        self.assertEqual(rk.resolve('host.example'), ['198.51.100.1/32', '198.51.100.2/32'])


if __name__ == '__main__':
    unittest.main()
