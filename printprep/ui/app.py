"""Application bootstrap: style, fonts, dark title bar, icons for the style sheet."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from . import icons
from .theme import T, app_font, palette, stylesheet


def _style_assets():
    folder = Path(tempfile.gettempdir()) / 'printprep-ui'
    folder.mkdir(exist_ok=True)
    chevron = icons.write_svg(folder / 'chevron.svg', 'chevron_down', T['text2'])
    check = icons.write_svg(folder / 'check.svg', 'check', '#ffffff', 3)
    up = icons.write_svg(folder / 'chevron_up.svg', 'chevron_up', T['text2'])
    check_accent = icons.write_svg(folder / 'check_accent.svg', 'check', T['accent_hover'], 2.6)
    return chevron, check, up, check_accent


def setup(app):
    app.setApplicationName('Print Prep')
    app.setOrganizationName('PrintPrep')
    app.setStyle('Fusion')
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except Exception:
        pass
    app.setPalette(palette())
    app.setFont(app_font())
    app.setStyleSheet(stylesheet(*_style_assets()))
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('PrintPrep.PrintPrep.2')
        except Exception:
            pass


def run():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    setup(app)
    from .main_window import MainWindow
    window = MainWindow()
    window.show()
    if len(sys.argv) > 1 and Path(sys.argv[-1]).is_dir():
        window.load_folder(Path(sys.argv[-1]))
    try:
        return app.exec()
    finally:
        from ..neural import release
        release()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
