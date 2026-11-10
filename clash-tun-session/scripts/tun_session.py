#!/usr/bin/env python3
"""Finite TUN leases. Only the native Clash switch changes network state."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

CODEX_ROOT = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
DEFAULT_STATE = CODEX_ROOT / 'tun-session'
SCRIPT = Path(__file__).resolve()


class LeaseError(RuntimeError):
    pass


def pid_identity(pid):
    try:
        os.kill(int(pid), 0)
        return subprocess.check_output(['ps', '-p', str(pid), '-o', 'lstart='], text=True).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def client_pid():
    pid = os.getppid()
    for _ in range(12):
        row = subprocess.run(['ps', '-p', str(pid), '-o', 'ppid=,comm='], capture_output=True, text=True).stdout.strip().split(None, 1)
        if len(row) != 2:
            return None
        if '/Applications/ChatGPT.app/' in row[1] and row[1].endswith('/codex'):
            return pid
        pid = int(row[0])
        if pid <= 1:
            return None
    return None


def boolean(text, key):
    match = re.search(r'^' + re.escape(key) + r':\s*(true|false)\s*$', text, re.M)
    if not match:
        raise LeaseError('Clash preference is missing an explicit boolean: ' + key)
    return match[1] == 'true'


class ClashBackend:
    def __init__(self):
        self.base = Path.home() / 'Library/Application Support/io.github.clash-verge-rev.clash-verge-rev'
        self.driver = SCRIPT.with_name('clash-tun-ax')

    def read(self):
        preference = self.base / 'verge.yaml'
        text = preference.read_text()
        enabled = boolean(text, 'enable_tun_mode')
        generated = (self.base / 'clash-verge.yaml').read_text()
        block = re.search(r'^tun:\s*\n((?:[ \t]+[^\n]*(?:\n|$))*)', generated, re.M)
        match = re.search(r'^\s+enable:\s*(true|false)\s*$', block[1], re.M) if block else None
        if not match:
            raise LeaseError('Generated Clash config does not expose the TUN state')
        return {'enabled': enabled, 'generated_enabled': match[1] == 'true',
                'consistent': enabled == (match[1] == 'true'),
                'revision': str(preference.stat().st_mtime_ns),
                'system_proxy': boolean(text, 'enable_system_proxy')}

    def set(self, enabled):
        if not self.driver.is_file():
            raise LeaseError('Native TUN driver is missing; rebuild from the skill source')
        result = subprocess.run([str(self.driver), 'set', 'on' if enabled else 'off'], capture_output=True, text=True, timeout=28)
        if result.returncode:
            raise LeaseError(result.stderr.strip()[:700] or 'Native Clash switch failed')
        deadline = time.monotonic() + 10
        last = None
        stable_since = None
        while time.monotonic() < deadline:
            current = self.read()
            if current['enabled'] == enabled and current['consistent']:
                if last == current['revision']:
                    if time.monotonic() - stable_since >= 0.4:
                        return current
                else:
                    last = current['revision']; stable_since = time.monotonic()
            else:
                last = None
            time.sleep(0.1)
        raise LeaseError('Clash UI and generated TUN state did not settle together')


class Manager:
    def __init__(self, directory, backend, *, clock=time.time, ensure_guard=None, owner_alive=None):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_uid != os.getuid():
            raise LeaseError('State directory must belong to the current user and must not be a symlink')
        os.chmod(self.directory, 0o700)
        self.backend = backend
        self.clock = clock
        self.ensure_guard = ensure_guard if ensure_guard is not None else self._start_guard
        self.owner_alive = owner_alive or (lambda lease: not lease.get('owner_pid') or pid_identity(lease['owner_pid']) == lease.get('owner_start'))

    @contextlib.contextmanager
    def locked(self):
        fd = os.open(self.directory / 'state.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def load(self):
        path = self.directory / 'state.json'
        if not path.exists():
            return {'version': 1, 'mode': 'ask', 'owned': False, 'original': None,
                    'leases': {}, 'revision': None, 'interrupted': False, 'phase': 'idle',
                    'restore_attempts': 0, 'last_error': None}
        if path.is_symlink():
            raise LeaseError('Refusing a symlinked state file')
        state = json.loads(path.read_text())
        if state.get('version') != 1 or not isinstance(state.get('leases'), dict):
            raise LeaseError('State format is invalid; do not guess the previous TUN owner')
        return state

    def save(self, state):
        fd, filename = tempfile.mkstemp(prefix='.state-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(filename, self.directory / 'state.json')
        finally:
            if os.path.exists(filename): os.unlink(filename)

    def _prune(self, state):
        now = self.clock()
        state['leases'] = {key: lease for key, lease in state['leases'].items()
                           if lease['expires'] > now and now >= lease['issued'] - 60 and self.owner_alive(lease)}

    def _observe(self, state, current):
        if state['owned'] and state['phase'] not in ['enabling', 'restore-pending', 'recovery-required']:
            if not current['enabled'] or current['revision'] != state['revision']:
                state.update(owned=False, interrupted=True, phase='external-change',
                             last_error='External Clash setting change detected; automatic shutdown relinquished')

    def _finish(self, state, *, explicit=False):
        if state['leases'] or not state['owned']:
            return
        current = self.backend.read()
        if not explicit:
            self._observe(state, current)
        if not state['owned']:
            return
        try:
            if current['enabled']:
                self.backend.set(False)
            state.update(owned=False, phase='idle', restore_attempts=0, last_error=None)
        except Exception as error:
            state['restore_attempts'] += 1
            state['phase'] = 'recovery-required' if state['restore_attempts'] >= 3 else 'restore-pending'
            state['last_error'] = str(error)[:700]
            raise LeaseError('TUN restore failed; recovery journal retained: ' + str(error)) from error

    def status(self):
        with self.locked():
            state = self.load(); current = self.backend.read()
            return self._result(state, current)

    def _result(self, state, current=None):
        return {'mode': state['mode'], 'enabled': (current or self.backend.read())['enabled'],
                'owned': state['owned'], 'originally_enabled': state['original'], 'phase': state['phase'],
                'leases': [{'lease': key, 'owner': lease['owner'], 'remaining_seconds': max(0, round(lease['expires'] - self.clock()))}
                           for key, lease in state['leases'].items()], 'last_error': state['last_error']}

    def acquire(self, owner, ttl=900, approved=False, owner_pid=None):
        if not owner or len(owner) > 200 or not 5 <= ttl <= 7200:
            raise LeaseError('Owner is required; TTL must be between 5 and 7200 seconds')
        with self.locked():
            state = self.load()
            if state['mode'] == 'off' or (state['mode'] == 'ask' and not approved):
                raise LeaseError('Automatic TUN use is disabled or requires explicit approval')
            if state['phase'] == 'recovery-required':
                raise LeaseError('A previous recovery failed; inspect status and restore explicitly before starting another session')
            self._prune(state)
            current = self.backend.read()
            self._observe(state, current)
            if state['interrupted'] and state['leases']:
                self.save(state)
                raise LeaseError('TUN was changed externally during this session; do not turn it back on automatically')
            if not current.get('consistent', True):
                raise LeaseError('Clash preference and generated TUN config disagree; no switch was changed')
            if not state['leases']:
                self._finish(state)
                current = self.backend.read()
                state.update(original=current['enabled'], owned=False, interrupted=False,
                             phase='active', last_error=None, restore_attempts=0)
            token = uuid.uuid4().hex
            now = self.clock()
            state['leases'][token] = {'owner': owner, 'issued': now, 'expires': now + ttl,
                                     'owner_pid': owner_pid, 'owner_start': pid_identity(owner_pid) if owner_pid else None}
            if not current['enabled']:
                state.update(owned=True, phase='enabling')
            self.save(state)  # Journal intent before any network mutation.
            try:
                self.ensure_guard()
                if state['owned'] and state['phase'] == 'enabling':
                    current = self.backend.set(True)
                    state.update(revision=current['revision'], phase='active')
                state['leases'][token]['expires'] = self.clock() + ttl
                self.save(state)
            except Exception:
                state['leases'].pop(token, None)
                try:
                    self._finish(state, explicit=True)
                finally:
                    self.save(state)
                raise
            return {'lease': token, **self._result(state)}

    def release(self, token):
        with self.locked():
            state = self.load(); state['leases'].pop(token, None)
            self._prune(state)
            try:
                self._finish(state)
            finally:
                self.save(state)
            return self._result(state)

    def renew(self, token, ttl=900):
        if not 5 <= ttl <= 7200: raise LeaseError('TTL must be between 5 and 7200 seconds')
        with self.locked():
            state = self.load(); self._prune(state)
            if token not in state['leases']: raise LeaseError('Lease has expired; do not silently reactivate it')
            self._observe(state, self.backend.read())
            state['leases'][token]['expires'] = self.clock() + ttl
            self.save(state)
            return self._result(state)

    def keep(self):
        with self.locked():
            state = self.load()
            state.update(owned=False, original=self.backend.read()['enabled'], phase='user-controlled', last_error=None)
            self.save(state)
            return self._result(state)

    def restore(self, force=False):
        with self.locked():
            state = self.load(); self._prune(state)
            if state['leases'] and not force: raise LeaseError('Other active leases exist; release your own lease or explicitly use --force')
            if force: state['leases'] = {}
            try:
                self._finish(state, explicit=True)
            finally:
                self.save(state)
            return self._result(state)

    def set_mode(self, mode):
        if mode not in ['auto', 'ask', 'off']: raise LeaseError('Unknown TUN mode')
        with self.locked():
            state = self.load(); state['mode'] = mode; self.save(state)
            return self._result(state)

    def manual(self, enabled, force=False):
        with self.locked():
            state = self.load(); self._prune(state)
            if not enabled and state['leases'] and not force: raise LeaseError('Active leases exist; explicit --force is required to stop their TUN')
            current = self.backend.set(enabled)
            state.update(owned=False, original=enabled, interrupted=not enabled and bool(state['leases']),
                         phase='user-controlled', last_error=None)
            if not enabled and force: state['leases'] = {}
            self.save(state); return self._result(state, current)

    def watch_once(self):
        with self.locked():
            state = self.load(); self._prune(state)
            try:
                self._observe(state, self.backend.read())
                self._finish(state)
            finally:
                self.save(state)
            return bool(state['leases'] or (state['owned'] and state['phase'] != 'recovery-required'))

    def _start_guard(self):
        if guard_running(self.directory): return
        log = self.directory / 'watchdog.log'
        if log.exists() and log.stat().st_size > 65536: log.write_text('')
        fd = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            subprocess.Popen([sys.executable, str(SCRIPT), '--state-dir', str(self.directory), '_watch'],
                             stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True, close_fds=True)
        finally:
            os.close(fd)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if guard_running(self.directory): return
            time.sleep(0.05)
        raise LeaseError('Recovery watchdog did not start; TUN activation cancelled')


def guard_running(directory):
    fd = os.open(Path(directory) / 'watchdog.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
    finally:
        os.close(fd)


def watch(manager):
    fd = os.open(manager.directory / 'watchdog.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        consecutive_errors = 0
        while True:
            try:
                if not manager.watch_once():
                    # Release the guard lock while holding the state lock. An
                    # acquiring client must not observe a guard about to exit.
                    with manager.locked():
                        state = manager.load()
                        if not state['leases'] and not state['owned']:
                            fcntl.flock(fd, fcntl.LOCK_UN)
                            return
                        if state['phase'] == 'recovery-required':
                            fcntl.flock(fd, fcntl.LOCK_UN)
                            return
                consecutive_errors = 0
            except Exception as error:
                consecutive_errors += 1
                print(json.dumps({'time': time.time(), 'error': str(error)[:700]}), flush=True)
                with manager.locked():
                    state = manager.load()
                    if consecutive_errors >= 3:
                        state.update(phase='recovery-required', last_error=str(error)[:700])
                        manager.save(state)
                    if state['phase'] == 'recovery-required':
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        return
                time.sleep(2)
            time.sleep(1)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description='Clash Verge temporary TUN sessions; changes only the existing TUN switch')
    parser.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('status')
    acquire = sub.add_parser('acquire'); acquire.add_argument('--owner', required=True)
    acquire.add_argument('--ttl', type=int, default=900); acquire.add_argument('--approved', action='store_true')
    acquire.add_argument('--owner-pid', type=int)
    for name in ['release', 'renew']:
        command = sub.add_parser(name); command.add_argument('lease')
        if name == 'renew': command.add_argument('--ttl', type=int, default=900)
    sub.add_parser('keep')
    mode = sub.add_parser('mode'); mode.add_argument('value', choices=['auto', 'ask', 'off'])
    for name in ['restore', 'off']:
        command = sub.add_parser(name); command.add_argument('--force', action='store_true')
    sub.add_parser('on'); sub.add_parser('_watch', help=argparse.SUPPRESS)
    args = parser.parse_args()
    manager = Manager(args.state_dir, ClashBackend())
    if args.action == '_watch': watch(manager); return
    if args.action == 'status': result = manager.status(); result['watchdog_running'] = guard_running(args.state_dir)
    elif args.action == 'acquire': result = manager.acquire(args.owner, args.ttl, args.approved, args.owner_pid or client_pid())
    elif args.action == 'release': result = manager.release(args.lease)
    elif args.action == 'renew': result = manager.renew(args.lease, args.ttl)
    elif args.action == 'mode': result = manager.set_mode(args.value)
    elif args.action == 'keep': result = manager.keep()
    elif args.action == 'restore': result = manager.restore(args.force)
    else: result = manager.manual(args.action == 'on', getattr(args, 'force', False))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try: main()
    except (LeaseError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)[:1000]}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
