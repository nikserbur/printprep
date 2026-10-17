"""Build check of PrintPrep-Setup.exe: silent install into a temporary folder (no shortcuts, no
registry), self-test of the installed app, then uninstall. Exit code 0 means PASS.

Usage: python tools/check_installer.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    setup = ROOT / 'dist' / 'PrintPrep-Setup.exe'
    if not setup.exists():
        print('PrintPrep-Setup.exe not found')
        return 1
    with tempfile.TemporaryDirectory(prefix='printprep-setup-') as temp:
        target = Path(temp) / 'Print Prep'
        started = time.monotonic()
        code = subprocess.run([str(setup), '--silent', '--target', str(target), '--no-shortcuts', '--no-register',
                               '--no-launch'], timeout=600).returncode
        exe = target / 'PrintPrep.exe'
        if code != 0 or not exe.exists() or not (target / '.printprep-install').exists():
            print(f'install failed (exit {code})')
            return 1
        print(f'installed in {time.monotonic() - started:.1f} s')
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
        code = subprocess.run([str(exe), '--self-test'], env=env, timeout=600).returncode
        if code != 0:
            print(f'self-test of the installed app failed (exit {code})')
            return 1
        code = subprocess.run([str(exe), '--uninstall', '--quiet'], timeout=120).returncode
        deadline = time.monotonic() + 30
        while target.exists() and time.monotonic() < deadline:
            time.sleep(.5)
        if code != 0 or target.exists():
            print(f'uninstall failed (exit {code}, folder left: {target.exists()})')
            return 1
    print('Installer check: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
