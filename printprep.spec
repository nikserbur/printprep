# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for Print Prep: one folder (fast start), only what the app uses.

Removed on purpose: the OpenCV FFmpeg video DLL, Qt Quick/QML/Network/PDF/OpenGL modules,
software OpenGL, Direct3D compiler, OpenSSL (hashes use Python's built-in SHA-2), Qt translations and unused plugins. The app paints with
QWidgets/QPainter and reads images through Pillow/OpenCV, so none of these are loaded.
"""
from pathlib import PurePath

EXCLUDE_MODULES = [
    'tkinter', '_tkinter', 'ssl', '_ssl', '_hashlib', 'PIL.ImageTk', 'PIL._tkinter_finder', 'matplotlib', 'scipy', 'pandas', 'IPython',
    'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf', 'PySide6.QtDBus', 'PySide6.QtSql',
    'PySide6.QtTest', 'PySide6.QtXml', 'PySide6.QtConcurrent', 'PySide6.QtPrintSupport', 'PySide6.QtUiTools',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtSvgWidgets', 'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets', 'PySide6.QtLabsStyleKit', 'PySide6.QtQmlFeatures', 'PySide6.QtQuickTest',
]
DROP_FILES = ('opencv_videoio_ffmpeg', 'opengl32sw', 'd3dcompiler', 'libssl', 'libcrypto', 'qt6quick', 'qt6qml', 'qt6pdf', 'qt6network',
              'qt6opengl', 'qt6virtualkeyboard', 'qt6dbus', 'qt6labs', 'qt6sql', 'qt6test', 'qt6xml')
KEEP_PLUGINS = ('platforms', 'imageformats', 'iconengines', 'styles')
KEEP_IMAGE_PLUGINS = ('qsvg', 'qico')


def wanted(entry):
    dest = entry[0].replace('\\', '/').lower()
    name = PurePath(dest).name
    if any(name.startswith(prefix) for prefix in DROP_FILES):
        return False
    if '/translations/' in dest or dest.endswith('.qm'):
        return False
    if '/plugins/' in dest:
        group = dest.split('/plugins/', 1)[1].split('/', 1)[0]
        if group not in KEEP_PLUGINS:
            return False
        if group == 'imageformats' and not any(k in name for k in KEEP_IMAGE_PLUGINS):
            return False
        if group == 'platforms' and not any(k in name for k in ('qwindows', 'qoffscreen')):
            return False
    return True


a = Analysis(
    ['print_prep.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDE_MODULES,
    noarchive=False,
    optimize=1,
)
a.binaries = [b for b in a.binaries if wanted(b)]
a.datas = [d for d in a.datas if wanted(d)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PrintPrep',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='assets/windows_version.txt',
    icon=['assets/printprep.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PrintPrep',
)
