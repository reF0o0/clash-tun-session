#!/usr/bin/env python3
"""Install the skill and build its native helper without changing TUN."""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NAME = 'clash-tun-session'
SOURCE = Path(__file__).resolve().parent / NAME
FILES = ['SKILL.md', 'references/usage.md', 'scripts/tun_session.py',
         'scripts/clash_tun_ax.swift', 'scripts/test_tun_session.py']
AGENTS_HEADING = '## 按需 TUN：浏览器控制连接恢复'
AGENTS_ENTRY = '''
## 按需 TUN：浏览器控制连接恢复

浏览器控制出现已知网络连接故障、且用户允许临时使用 TUN 时，读取已安装的 `clash-tun-session/SKILL.md`，通过 `tun-session` 管理租约。遵守用户选择的 auto/ask/off 模式；没有明确授权时不得自行切换为 auto。结束只释放自己的租约，恢复原状态，不误关原本开启或其他聊天仍在使用的 TUN。普通聊天、写代码、联网搜索和仅原生应用控制不触发。
'''


def main():
    root = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill-dir', type=Path, default=root / 'skills' / NAME)
    parser.add_argument('--bin-dir', type=Path, default=root / 'bin')
    parser.add_argument('--backup-dir', type=Path, default=root / 'backups' / NAME)
    parser.add_argument('--state-dir', type=Path, default=root / 'tun-session', help='Existing session journal to check before updating')
    parser.add_argument('--agents-file', type=Path, help='Optionally append a scoped reminder to this AGENTS.md')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('This installer requires macOS.')
    compiler = shutil.which('swiftc')
    if compiler is None:
        raise SystemExit('swiftc is missing. Install the Apple Command Line Tools first.')
    target = args.skill_dir.expanduser().resolve()
    if args.skill_dir.expanduser().is_symlink():
        raise SystemExit('The skill directory is a symlink; review it before installing.')
    if target == SOURCE:
        raise SystemExit('Install to the skill directory, not over the source checkout.')
    entry = args.bin_dir.expanduser() / 'tun-session'
    expected = target / 'scripts/tun_session.py'
    if entry.exists() or entry.is_symlink():
        if not entry.is_symlink() or entry.resolve() != expected:
            raise SystemExit('An unrelated tun-session command already exists; nothing replaced.')
    journal = args.state_dir.expanduser() / 'state.json'
    if journal.exists():
        state = json.loads(journal.read_text())
        if state.get('owned') or state.get('leases'):
            raise SystemExit('A TUN session is active or awaiting recovery; finish it before updating.')
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = args.backup_dir.expanduser() / stamp
    with tempfile.TemporaryDirectory(prefix='.tun-install-', dir=target.parent) as temporary:
        staging = Path(temporary) / NAME
        for relative in FILES:
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / relative, destination)
        subprocess.run([compiler, str(staging / 'scripts/clash_tun_ax.swift'),
                        '-o', str(staging / 'scripts/clash-tun-ax')], check=True)
        (staging / 'scripts/tun_session.py').chmod(0o755)
        previous = None
        if target.exists():
            backup.mkdir(mode=0o700, parents=True)
            previous = backup / NAME
            shutil.move(str(target), str(previous))
        try:
            os.replace(staging, target)
        except Exception:
            if previous is not None:
                shutil.move(str(previous), str(target))
            raise
    entry.parent.mkdir(parents=True, exist_ok=True)
    if not entry.is_symlink():
        entry.symlink_to(expected)
    if args.agents_file:
        agents = args.agents_file.expanduser()
        if agents.is_symlink():
            raise SystemExit('Skill installed; AGENTS.md is a symlink and was not changed.')
        original = agents.read_text() if agents.exists() else ''
        if AGENTS_HEADING not in original:
            if agents.exists():
                backup.mkdir(mode=0o700, parents=True, exist_ok=True)
                saved = backup / 'AGENTS.md'
                shutil.copy2(agents, saved)
                saved.chmod(0o600)
            agents.parent.mkdir(parents=True, exist_ok=True)
            agents.write_text(original.rstrip() + '\n\n' + AGENTS_ENTRY.lstrip())
    print(json.dumps({'installed_skill': str(target), 'command': str(entry),
                      'tun_changed': False, 'new_session_default_mode': 'ask',
                      'note': 'Existing mode preferences are preserved. Check Accessibility permission before using the switch.'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
