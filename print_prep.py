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
        assert neural.upscale(tile, 'fsrcnn').shape == (48, 48, 3)
        assert neural.upscale(tile, 'esrgan').shape == (96, 96, 3)
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


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        self_test()
    else:
        from printprep.ui import run
        raise SystemExit(run())
