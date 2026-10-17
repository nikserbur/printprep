"""Print Prep desktop entry point; --self-test also works in the frozen Windows build."""
import sys


def self_test():
    import tempfile
    from pathlib import Path
    import numpy as np
    from PIL import Image
    from printprep.export import export_batch
    from printprep.imageio import inspect
    from printprep.model import BUILTIN_PRESETS
    from printprep import neural
    with tempfile.TemporaryDirectory(prefix='printprep-') as temp:
        folder = Path(temp)
        gradient = np.linspace(40, 220, 1200, dtype=np.float32)
        image = np.stack([np.tile(gradient, (800, 1)), np.full((800, 1200), 120, np.float32),
                          np.tile(gradient[::-1], (800, 1))], axis=2).astype(np.uint8)
        Image.fromarray(image).save(folder / 'sample.jpg', quality=92)
        photos = [inspect(folder / 'sample.jpg')]
        output, report = export_batch(folder, photos, BUILTIN_PRESETS['lab_10x15']['settings'], {}, preset_name='self-test')
        assert report['results'][0]['status'] == 'ok', report['results'][0]
        with Image.open(output / 'sample.jpg') as im:
            assert im.size == (1795, 1205), im.size
            assert im.info.get('icc_profile')
        tile = np.random.default_rng(0).random((24, 24, 3)).astype(np.float32)
        assert neural.upscale(tile).shape == (96, 96, 3)
        assert neural.enhance((tile * 255).astype(np.uint8))['full'].shape == (96, 96, 3)
        neural.detect_faces(np.zeros((120, 160, 3), np.uint8))
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QCoreApplication, QEvent
        from printprep.ui.app import setup
        from printprep.ui.main_window import MainWindow
        app = QApplication.instance() or QApplication([])
        from PySide6.QtGui import QImageReader
        formats = {bytes(f).decode() for f in QImageReader.supportedImageFormats()}
        assert 'svg' in formats, 'Qt SVG image plugin missing (combo arrows, icons)'
        setup(app)
        window = MainWindow()
        window.show()
        app.processEvents()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        neural.release()
    print('Print Prep self-test: PASS')


def uninstall(quiet=False):
    """Remove an installation made by PrintPrep-Setup.exe ("Apps & features" calls this).

    Only a folder carrying the installer's marker is removed, so a portable copy or a source
    checkout can never be deleted by accident. Presets and settings stay for a later reinstall.
    """
    import json
    import os
    import subprocess
    from pathlib import Path
    app_dir = Path(sys.executable).resolve().parent
    marker = app_dir / '.printprep-install'
    if not getattr(sys, 'frozen', False) or not marker.exists():
        return 1
    info = json.loads(marker.read_text(encoding='utf-8'))
    if not quiet:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from printprep import i18n
        from printprep.i18n import tr
        from printprep.ui.store import prefs
        QApplication.instance() or QApplication(sys.argv)
        i18n.set_language(prefs().value('language', '') or i18n.default_language())
        answer = QMessageBox.question(None, 'Print Prep',
                                      tr('Удалить Print Prep с этого компьютера? Ваши пресеты и настройки сохранятся.'))
        if answer != QMessageBox.StandardButton.Yes:
            return 0
    for link in info.get('shortcuts', []):
        try:
            Path(link).unlink()
        except OSError:
            pass
    if info.get('registered'):
        try:
            import winreg
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Uninstall\PrintPrep')
        except OSError:
            pass
    # The folder holds this very exe: a detached shell removes it once the process has exited.
    subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & rd /s /q "{app_dir}"', cwd=os.environ.get('TEMP') or 'C:\\',
                     creationflags=0x08000000 | 0x00000008, close_fds=True)
    if not quiet:
        QMessageBox.information(None, 'Print Prep', tr('Print Prep удалён.'))
    return 0


if __name__ == '__main__':
    if '--uninstall' in sys.argv:
        raise SystemExit(uninstall(quiet='--quiet' in sys.argv))
    if '--self-test' in sys.argv:
        self_test()
    else:
        from printprep.ui import run
        raise SystemExit(run())
