"""Application bootstrap: theme, language, fonts, icons for the style sheet, window rebuild."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QProcess, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from .. import i18n
from . import icons
from .theme import T, app_font, apply_theme, palette, stylesheet

WINDOW = [None]     # the live main window; replaced on rebuild


def _style_assets():
    folder = Path(tempfile.gettempdir()) / f'printprep-ui-{T["name"]}'
    folder.mkdir(exist_ok=True)
    chevron = icons.write_svg(folder / 'chevron.svg', 'chevron_down', T['text2'])
    check = icons.write_svg(folder / 'check.svg', 'check', '#ffffff', 3)
    up = icons.write_svg(folder / 'chevron_up.svg', 'chevron_up', T['text2'])
    check_accent = icons.write_svg(folder / 'check_accent.svg', 'check', T['accent_hover'], 2.6)
    return chevron, check, up, check_accent


def apply_appearance(app):
    """Theme and language from the stored preferences; safe to call again at runtime."""
    from .app_settings import language_choice, theme_choice
    choice = theme_choice()
    try:
        # Unknown hands the title bar and native dialogs back to the Windows setting.
        app.styleHints().setColorScheme({'dark': Qt.ColorScheme.Dark, 'light': Qt.ColorScheme.Light}
                                        .get(choice, Qt.ColorScheme.Unknown))
    except Exception:
        pass
    apply_theme(choice)
    i18n.set_language(language_choice())
    # Number fields follow the interface language (102.0 in English, 102,0 in Russian).
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates) if i18n.LANG == 'en'
                       else QLocale(QLocale.Language.Russian, QLocale.Country.Russia))
    app.setPalette(palette())
    app.setStyleSheet(stylesheet(*_style_assets()))


def setup(app):
    app.setApplicationName('Print Prep')
    app.setOrganizationName('PrintPrep')
    app.setStyle('Fusion')
    app.setFont(app_font())
    apply_appearance(app)
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('PrintPrep.PrintPrep.2')
        except Exception:
            pass


def rebuild(old):
    """Recreate the main window after a theme or language change, keeping folder and photo."""
    app = QApplication.instance()
    folder, row = old.folder, old.current
    app.setQuitOnLastWindowClosed(False)
    try:
        if not old.close():
            return old
        apply_appearance(app)
        from .main_window import MainWindow
        window = MainWindow()
        window.show()
        if folder:
            window.load_folder(folder, select=row)
        WINDOW[0] = window
    finally:
        app.setQuitOnLastWindowClosed(True)
    old.deleteLater()
    return window


def restart(old):
    """Relaunch the app (after a language change) on the same folder and photo."""
    folder, row = old.folder, max(0, old.current)
    if not old.close():
        return
    if getattr(sys, 'frozen', False):
        program, args = sys.executable, []
    else:
        program, args = sys.executable, [str(Path(sys.argv[0]).resolve())]
    if folder:
        args += [f'--select={row}', str(folder)]
    QProcess.startDetached(program, args)
    QApplication.instance().quit()


def _select_arg():
    for arg in sys.argv[1:]:
        if arg.startswith('--select='):
            try:
                return max(0, int(arg.split('=', 1)[1]))
            except ValueError:
                return 0
    return 0


def run():
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv)
    setup(app)
    from .splash import Splash
    splash = Splash()
    splash.show()
    app.processEvents()

    def heavy_imports():
        from . import main_window   # numpy, OpenCV, the pipeline
        return main_window
    window = splash.wait_for(heavy_imports).MainWindow()
    WINDOW[0] = window
    splash.finish_into(window)
    if len(sys.argv) > 1 and Path(sys.argv[-1]).is_dir():
        window.load_folder(Path(sys.argv[-1]), select=_select_arg())
    QTimer.singleShot(700, window.maybe_show_tutorial)
    try:
        return app.exec()
    finally:
        from ..neural import release
        release()
        if WINDOW[0] is not None:
            WINDOW[0].deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
