import concurrent.futures
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).with_name('tun_session.py')
spec = importlib.util.spec_from_file_location('tun_session', MODULE)
tun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tun)


class FakeBackend:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.revision = 0
        self.changes = []
        self.fail_enable = False
        self.fail_disable = False

    def read(self):
        return {'enabled': self.enabled, 'revision': str(self.revision)}

    def set(self, enabled):
        if not enabled and self.fail_disable:
            raise tun.LeaseError('simulated restore failure')
        self.enabled = enabled
        self.revision += 1
        self.changes.append(enabled)
        if enabled and self.fail_enable:
            raise tun.LeaseError('simulated partial enable failure')
        return self.read()


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = 1000.0
        self.backend = FakeBackend()
        self.alive = True
        self.manager = tun.Manager(Path(self.tmp.name), self.backend,
            clock=lambda: self.now, ensure_guard=lambda: None,
            owner_alive=lambda lease: self.alive)
        self.manager.set_mode('auto')

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_install_requires_approval_by_default(self):
        backend = FakeBackend()
        manager = tun.Manager(Path(self.tmp.name) / 'new-install', backend, ensure_guard=lambda: None)
        self.assertEqual(manager.status()['mode'], 'ask')
        with self.assertRaises(tun.LeaseError):
            manager.acquire('new-user')
        self.assertEqual(backend.changes, [])

    def test_last_release_restores_original_off(self):
        a = self.manager.acquire('chat-a')['lease']
        b = self.manager.acquire('chat-b')['lease']
        self.manager.release(a)
        self.assertTrue(self.backend.enabled)
        self.manager.release(b)
        self.assertFalse(self.backend.enabled)
        self.assertEqual(self.backend.changes, [True, False])

    def test_original_on_is_never_closed(self):
        self.backend.enabled = True
        lease = self.manager.acquire('chat-a')['lease']
        self.manager.release(lease)
        self.assertTrue(self.backend.enabled)
        self.assertEqual(self.backend.changes, [])

    def test_expiry_restores_without_release(self):
        self.manager.acquire('chat-a', ttl=5)
        self.now += 6
        self.manager.watch_once()
        self.assertFalse(self.backend.enabled)

    def test_renew_keeps_active_task_open(self):
        lease = self.manager.acquire('chat-a', ttl=5)['lease']
        self.now += 4
        self.manager.renew(lease, ttl=5)
        self.now += 2
        self.manager.watch_once()
        self.assertTrue(self.backend.enabled)

    def test_dead_owner_restores(self):
        self.manager.acquire('chat-a', owner_pid=123)
        self.alive = False
        self.manager.watch_once()
        self.assertFalse(self.backend.enabled)

    def test_external_revision_change_is_preserved(self):
        lease = self.manager.acquire('chat-a')['lease']
        self.backend.revision += 1
        self.manager.release(lease)
        self.assertTrue(self.backend.enabled)
        self.assertFalse(self.manager.status()['owned'])

    def test_external_off_prevents_reenable_for_existing_session(self):
        self.manager.acquire('chat-a')
        self.backend.enabled = False
        self.backend.revision += 1
        self.manager.watch_once()
        with self.assertRaises(tun.LeaseError):
            self.manager.acquire('chat-b')
        self.assertFalse(self.backend.enabled)

    def test_keep_transfers_control_to_user(self):
        lease = self.manager.acquire('chat-a')['lease']
        self.manager.keep()
        self.manager.release(lease)
        self.assertTrue(self.backend.enabled)

    def test_off_and_ask_modes_prevent_unapproved_activation(self):
        self.manager.set_mode('off')
        with self.assertRaises(tun.LeaseError):
            self.manager.acquire('chat-a', approved=True)
        self.manager.set_mode('ask')
        with self.assertRaises(tun.LeaseError):
            self.manager.acquire('chat-a')
        self.assertEqual(self.backend.changes, [])

    def test_partial_enable_failure_rolls_back(self):
        self.backend.fail_enable = True
        with self.assertRaises(tun.LeaseError):
            self.manager.acquire('chat-a')
        self.assertFalse(self.backend.enabled)

    def test_restore_failure_retains_recovery_record(self):
        lease = self.manager.acquire('chat-a')['lease']
        self.backend.fail_disable = True
        with self.assertRaises(tun.LeaseError):
            self.manager.release(lease)
        self.assertTrue(self.manager.status()['owned'])
        self.backend.fail_disable = False
        self.manager.watch_once()
        self.assertFalse(self.backend.enabled)

    def test_force_is_required_to_restore_active_leases(self):
        self.manager.acquire('chat-a')
        with self.assertRaises(tun.LeaseError):
            self.manager.restore()
        self.manager.restore(force=True)
        self.assertFalse(self.backend.enabled)

    def test_concurrent_clients_do_not_close_each_other(self):
        with concurrent.futures.ThreadPoolExecutor() as pool:
            leases = list(pool.map(lambda n: self.manager.acquire(str(n))['lease'], range(8)))
            list(pool.map(self.manager.release, leases))
        self.assertEqual(self.backend.changes, [True, False])

    def test_watchdog_read_failures_stop_with_recovery_record(self):
        self.manager.acquire('chat-a')
        def fail():
            raise tun.LeaseError('simulated unreadable settings')
        self.backend.read = fail
        with patch.object(tun.time, 'sleep', lambda _: None):
            tun.watch(self.manager)
        with self.manager.locked():
            self.assertEqual(self.manager.load()['phase'], 'recovery-required')
        self.assertFalse(tun.guard_running(self.manager.directory))


if __name__ == '__main__':
    unittest.main()
