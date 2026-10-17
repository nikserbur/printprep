# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build of the one-file installer PrintPrep-Setup.exe.

Carries the packaged app (dist/PrintPrep-Windows-x64.zip, made by tools/package_release.py) and a
small Tk window; Qt, NumPy and OpenCV stay out, so the installer itself is only a few MB on top.
"""
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
version_text = (ROOT / 'assets' / 'windows_version.txt').read_text(encoding='utf-8')
version_text = (version_text.replace("'Print Prep - Photo print preparation'", "'Print Prep Setup'")
                .replace("'PrintPrep.exe'", "'PrintPrep-Setup.exe'").replace("'InternalName', 'PrintPrep'", "'InternalName', 'PrintPrep-Setup'"))
version_file = ROOT / 'build' / 'setup_version.txt'
version_file.parent.mkdir(exist_ok=True)
version_file.write_text(version_text, encoding='utf-8')

a = Analysis(
    [str(ROOT / 'installer' / 'printprep_setup.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / 'dist' / 'PrintPrep-Windows-x64.zip'), '.'),
           (str(ROOT / 'assets' / 'printprep.png'), '.'),
           (str(ROOT / 'assets' / 'printprep.ico'), '.')],
    hiddenimports=[],
    excludes=['numpy', 'cv2', 'PIL', 'PySide6', 'shiboken6', 'printprep.ui', 'printprep.pipeline', 'ssl', '_ssl',
              '_hashlib', 'unittest', 'pydoc', 'email', 'http', 'xml'],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PrintPrep-Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(version_file),
    icon=[str(ROOT / 'assets' / 'printprep.ico')],
)
