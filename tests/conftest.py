"""Own Qt and OpenCV native lifetimes explicitly for the test session."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest


@pytest.fixture(scope='session', autouse=True)
def desktop_runtime():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QEvent
    app = QApplication.instance() or QApplication([])
    yield app
    from printprep.upscale import release_network
    release_network()
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    """Tests never replace a user's remembered settings or preset library."""
    from PySide6.QtCore import QSettings
    import printprep.ui
    monkeypatch.setattr(printprep.ui, 'QSettings', lambda *args: QSettings(str(tmp_path / 'printprep.ini'), QSettings.Format.IniFormat))
