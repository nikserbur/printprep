"""Preferences store. Honours QSettings.setDefaultFormat/setPath, so tests and the
screenshot tools can redirect it away from the user's real settings (the
QSettings(organization, application) constructor always uses the registry)."""
from PySide6.QtCore import QSettings


def prefs(app='PrintPrep2'):
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, 'PrintPrep', app)
