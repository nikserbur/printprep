"""Print Prep desktop entry point; --self-test works in frozen Windows builds."""
import sys


def self_test():
    import tempfile
    from pathlib import Path
    from PIL import Image
    from printprep.engine import Settings, scan, export_batch
    with tempfile.TemporaryDirectory(prefix='printprep-') as temp:
        folder = Path(temp)
        Image.new('RGB', (1200, 800), '#b87956').save(folder / 'sample.jpg')
        photos, errors = scan(folder)
        output, report = export_batch(folder, photos, Settings(), {})
        assert not errors and report['results'][0]['status'] == 'ok'
        with Image.open(next(output.glob('*.jpg'))) as im:
            assert im.size == (1772, 1181)
            assert im.info.get('icc_profile')
        from printprep.upscale import upscale2x
        assert upscale2x(Image.new('RGB', (16, 16), '#9a806f')).size == (32, 32)
        from PySide6.QtWidgets import QApplication
        from printprep.ui import MainWindow
        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.show()
        app.processEvents()
        window.close()
    print('Print Prep self-test: PASS')


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        self_test()
    else:
        from printprep.ui import run
        raise SystemExit(run())
