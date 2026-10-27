"""Shared fixtures: offscreen Qt with real fonts, isolated preferences, synthetic photos."""
import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if sys.platform == 'win32':
    os.environ.setdefault('QT_QPA_FONTDIR', r'C:\Windows\Fonts')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from PIL import Image


@pytest.fixture(scope='session', autouse=True)
def desktop_runtime(tmp_path_factory):
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QStandardPaths
    from PySide6.QtWidgets import QApplication
    root = tmp_path_factory.mktemp('prefs')
    QStandardPaths.setTestModeEnabled(True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root))
    app = QApplication.instance() or QApplication([])
    from printprep.ui.app import setup
    setup(app)
    yield app
    from printprep.neural import release
    release()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    """Every test gets its own QSettings store and app-data folder."""
    from PySide6.QtCore import QSettings, QStandardPaths
    # ui.store.prefs() follows the default format and path, so this redirects every store.
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / 'prefs'))
    monkeypatch.setattr(QStandardPaths, 'writableLocation', staticmethod(lambda *_: str(tmp_path / 'appdata')))
    # The tests assert Russian source strings. Without a stored choice the app follows the host
    # locale (English on CI runners), and apply_appearance() re-reads it, so pin the language here.
    from printprep import i18n
    from printprep.ui.store import prefs
    prefs().setValue('language', 'ru')
    i18n.set_language('ru')


def gradient_image(w=1200, h=800, seed=0, noise=0.):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, w, dtype=np.float32)
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    img = np.stack(np.broadcast_arrays(.15 + .7 * x[None, :], .1 + .6 * y, .2 + .5 * (1 - x[None, :]) * (1 - y)), axis=2)
    img = img * 255 + rng.normal(0, noise, img.shape)
    img[h // 3:h // 2, w // 3:w // 2] = (235, 235, 235)
    img[h // 2:2 * h // 3, w // 2:2 * w // 3] = (20, 20, 20)
    return np.clip(img, 0, 255).astype(np.uint8)


@pytest.fixture
def photo_folder(tmp_path):
    folder = tmp_path / 'Фото с пробелом'
    folder.mkdir()
    Image.fromarray(gradient_image(1200, 800)).save(folder / 'a_landscape.jpg', quality=95)
    Image.fromarray(gradient_image(600, 900, seed=1)).save(folder / 'b_portrait.png')
    Image.fromarray(gradient_image(300, 200, seed=2)).save(folder / 'c_small.jpg', quality=90)
    return folder


def wait_idle(app, window, timeout=60):
    import time
    end = time.monotonic() + timeout
    quiet = 0
    while time.monotonic() < end:
        app.processEvents()
        scanning = window.scan_worker is not None and window.scan_worker.is_alive()
        exporting = window.export_job is not None and window.export_job.running()
        idle = not scanning and not exporting and window.service.is_idle() and not window.preview_timer.isActive()
        # Results are queued signals: stay idle across several event-loop passes before trusting it.
        quiet = quiet + 1 if idle else 0
        if quiet >= 6:
            return
        time.sleep(.01)
    raise AssertionError('UI did not become idle')
