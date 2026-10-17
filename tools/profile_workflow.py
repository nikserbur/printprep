"""Time the whole user workflow on synthetic 24 MP photos (no personal data).

Measures: app start, folder scan, thumbnails, first preview, switching photos, slider
response (interactive and full), 1:1 tile, export throughput. Usage:
    python tools/profile_workflow.py [count] [megapixels]
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from PIL import Image


def make_photos(folder, count, mp):
    w = int((mp * 1e6 * 1.5) ** .5)
    h = int(w / 1.5)
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.stack([xx / w, yy / h, .5 + .4 * np.sin(xx / 300)], axis=2) * 180 + 30
    for i in range(count):
        img = np.clip(base * (0.8 + 0.02 * i) + rng.normal(0, 4, (h, w, 3)), 0, 255).astype(np.uint8)
        Image.fromarray(img).save(folder / f'photo_{i:03d}.jpg', quality=92)
    return w, h


def wait(app, cond, timeout=120):
    end = time.monotonic() + timeout
    quiet = 0
    while time.monotonic() < end:
        app.processEvents()
        quiet = quiet + 1 if cond() else 0
        if quiet >= 3:
            return
        time.sleep(.002)
    raise TimeoutError


def main(count=20, mp=24):
    results = {}
    with tempfile.TemporaryDirectory(prefix='pp-profile-') as temp:
        folder = Path(temp) / 'photos'
        folder.mkdir()
        t = time.perf_counter()
        w, h = make_photos(folder, count, mp)
        print(f'fixtures: {count} × {w}×{h} in {time.perf_counter() - t:.1f}s')
        os.environ['APPDATA'] = str(Path(temp) / 'appdata')
        t = time.perf_counter()
        from PySide6.QtCore import QSettings, QStandardPaths
        QStandardPaths.setTestModeEnabled(True)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(Path(temp) / 'ini'))
        from PySide6.QtWidgets import QApplication
        from printprep.ui.app import setup
        from printprep.ui.main_window import MainWindow
        app = QApplication([])
        setup(app)
        window = MainWindow()
        window.resize(1600, 960)
        window.show()
        app.processEvents()
        results['start (import + window)'] = time.perf_counter() - t
        idle = lambda: window.service.is_idle() and not window.preview_timer.isActive() and \
            (window.scan_worker is None or not window.scan_worker.is_alive())
        t = time.perf_counter()
        window.load_folder(folder)
        wait(app, lambda: window.photos and window.current == 0)
        results['scan folder'] = time.perf_counter() - t
        wait(app, lambda: window.viewer.fit_img is not None and idle())
        results['first preview (decode + analysis + render)'] = time.perf_counter() - t
        t = time.perf_counter()
        wait(app, lambda: len(window.strip.model_.thumbs) >= count, 300)
        results[f'all {count} thumbnails'] = time.perf_counter() - t
        window.apply_preset('builtin:lab_10x15')
        wait(app, idle)
        times = []
        for i in range(1, 6):
            t = time.perf_counter()
            window.strip.select_row(i)
            wait(app, lambda: window.viewer.fit_img is not None and idle())
            times.append(time.perf_counter() - t)
        results['switch photo, rapid (median of 5)'] = float(np.median(times))
        times = []
        for i in range(6, 10):
            end = time.monotonic() + 1.5           # look at the photo for a moment, as people do
            while time.monotonic() < end:
                app.processEvents()
                time.sleep(.005)
            t = time.perf_counter()
            window.strip.select_row(i)
            wait(app, lambda: window.viewer.fit_img is not None and idle())
            times.append(time.perf_counter() - t)
        results['switch photo after viewing (median of 4)'] = float(np.median(times))
        times = []
        slider = window.inspector.batch_controls['exposure']
        for v in (.2, .4, .6, .8):
            t = time.perf_counter()
            slider.setValue(v, emit=True)
            wait(app, lambda: window.service.is_idle() and not window.preview_timer.isActive() or window.preview_timer.remainingTime() > 100, 30)
            times.append(time.perf_counter() - t)
        results['slider drag step (interactive)'] = float(np.median(times))
        t = time.perf_counter()
        slider.editingFinished.emit()
        wait(app, idle)
        results['slider release (full preview)'] = time.perf_counter() - t
        t = time.perf_counter()
        window.viewer.set_zoom(1.0)
        wait(app, lambda: window.viewer.roi_img is not None and idle())
        results['1:1 view tile'] = time.perf_counter() - t
        window.viewer.set_zoom('fit')
        wait(app, idle)
        t = time.perf_counter()
        window.export()
        wait(app, lambda: not (window.export_job and window.export_job.running()) and idle(), 900)
        dt = time.perf_counter() - t
        results[f'export {count} photos (lab 10×15, auto)'] = dt
        results['export throughput, photos/min'] = count / dt * 60
        window.close()
    print()
    for k, v in results.items():
        unit = '' if 'photos/min' in k else ' s'
        print(f'{k:45s} {v:8.2f}{unit}')


if __name__ == '__main__':
    main(*(int(a) for a in sys.argv[1:]))
