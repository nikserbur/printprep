"""Render interface screenshots from synthetic, non-personal demo photos.

Usage: python tools/screenshot_demo.py [output_dir]   (offscreen; does not touch user presets)
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
from PIL import Image, ImageDraw, ImageFilter


def demo_photos(folder: Path):
    rng = np.random.default_rng(7)
    w, h = 3000, 2000
    # 1. Mountain lake, slightly flat and cool.
    im = Image.new('RGB', (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / h
        d.line((0, y, w, y), fill=(int(150 + 40 * t), int(178 + 20 * t), int(205 - 10 * t)))
    d.ellipse((2100, 260, 2400, 560), fill='#f6efd0')
    d.polygon([(0, 1200), (600, 640), (1100, 1260), (1700, 520), (2600, 1300), (3000, 900), (3000, 2000), (0, 2000)], fill='#5d7b84')
    d.polygon([(0, 1500), (500, 1200), (1200, 1600), (1900, 1000), (2600, 1550), (3000, 1300), (3000, 2000), (0, 2000)], fill='#36585f')
    d.rectangle((0, 1650, w, h), fill='#3f6f86')
    im = im.filter(ImageFilter.GaussianBlur(2))
    arr = np.asarray(im).astype(np.float32) * .85 + 25
    Image.fromarray(np.clip(arr + rng.normal(0, 2, arr.shape), 0, 255).astype(np.uint8)).save(folder / '01_Горное_озеро.jpg', quality=93)
    # 2. Warm indoor cast with a face-like subject.
    im = Image.new('RGB', (2000, 3000), '#c08a55')
    d = ImageDraw.Draw(im)
    d.rectangle((0, 1900, 2000, 3000), fill='#7a4e2c')
    d.ellipse((650, 700, 1350, 1600), fill='#e2a77c')
    d.ellipse((800, 1000, 900, 1080), fill='#3a2a20')
    d.ellipse((1100, 1000, 1200, 1080), fill='#3a2a20')
    d.ellipse((880, 1300, 1120, 1380), fill='#a8584a')
    d.rectangle((560, 1600, 1440, 3000), fill='#2f4a6b')
    im.filter(ImageFilter.GaussianBlur(3)).save(folder / '02_Портрет_тёплый_свет.jpg', quality=92)
    # 3. Dark, noisy evening street.
    arr = np.zeros((2000, 3000, 3), np.float32)
    yy, xx = np.mgrid[0:2000, 0:3000]
    arr[..., 0] = 30 + 50 * np.exp(-((xx - 2200) ** 2 + (yy - 700) ** 2) / 3e5)
    arr[..., 1] = 25 + 35 * np.exp(-((xx - 2200) ** 2 + (yy - 700) ** 2) / 3e5)
    arr[..., 2] = 35 + 20 * (yy / 2000)
    arr[1300:, :] += 18
    arr += rng.normal(0, 7, arr.shape)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(folder / '03_Вечер_шум.jpg', quality=90)
    # 4. Small, soft web picture that needs enlargement.
    im = Image.new('RGB', (900, 600), '#9ab37a')
    d = ImageDraw.Draw(im)
    for i in range(14):
        x = 40 + i * 62
        d.rectangle((x, 160, x + 40, 520), fill=('#e8d36b', '#d9604f', '#f1efe6')[i % 3])
    d.text((60, 60), 'SALE 2026', fill='#1d2b17')
    im.filter(ImageFilter.GaussianBlur(1.2)).save(folder / '04_Маленький_снимок.jpg', quality=70)
    # 5/6. Variants for the filmstrip.
    for name, tint in (('05_Пляж.jpg', (1.08, 1.0, .9)), ('06_Туман.jpg', (.9, .95, 1.0))):
        base = np.asarray(Image.open(folder / '01_Горное_озеро.jpg')).astype(np.float32)
        Image.fromarray(np.clip(base * tint + 30, 0, 255).astype(np.uint8)).save(folder / name, quality=90)


def wait(app, window, seconds=25):
    end = time.monotonic() + seconds
    quiet = 0
    while time.monotonic() < end:
        app.processEvents()
        idle = window.service.is_idle() and not window.preview_timer.isActive() and             (window.scan_worker is None or not window.scan_worker.is_alive())
        quiet = quiet + 1 if idle else 0
        if quiet >= 8:
            return
        time.sleep(.02)


def wait_neural(app, window, seconds=120):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if window.last_result is not None and window.last_result.neural == 'ready':
            break
        time.sleep(.02)
    wait(app, window)


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'docs'
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='printprep-demo-') as temp:
        os.environ['APPDATA'] = str(Path(temp) / 'appdata')
        from PySide6.QtCore import QSettings, QStandardPaths
        QStandardPaths.setTestModeEnabled(True)
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(Path(temp) / 'ini'))
        folder = Path(temp) / 'Съёмка в горах'
        folder.mkdir()
        demo_photos(folder)
        from PySide6.QtWidgets import QApplication
        from printprep.ui.app import setup
        from printprep.ui.main_window import MainWindow
        app = QApplication([])
        setup(app)
        window = MainWindow()
        window.resize(1600, 960)
        window.show()
        wait(app, window)
        window.grab().save(str(out / 'start.png'))
        window.load_folder(folder)
        wait(app, window)
        window.set_view_mode('result')
        window.apply_preset('builtin:lab_10x15')
        wait(app, window)
        window.grab().save(str(out / 'interface.png'))
        window.strip.select_row(1)
        wait(app, window)
        window.inspector.set_scope('photo')
        wait(app, window)
        window.grab().save(str(out / 'photo.png'))
        window.inspector.set_scope('batch')
        window.set_view_mode('split')
        wait(app, window)
        window.grab().save(str(out / 'compare.png'))
        window.set_view_mode('result')
        window.set_crop_mode(True)
        wait(app, window)
        window.grab().save(str(out / 'crop.png'))
        window.set_crop_mode(False)
        window.strip.select_row(3)
        window.apply_preset('builtin:upscale_small')
        window.inspector.neural_section.set_open(True)
        wait(app, window)
        app.processEvents()
        window.grab().save(str(out / 'neural_progress.png'))
        wait_neural(app, window)
        window.grab().save(str(out / 'neural.png'))
        window.viewer.set_zoom(1.0)
        wait(app, window, 60)
        window.grab().save(str(out / 'neural_1to1.png'))
        from printprep.ui.preset_manager import PresetManager
        dialog = PresetManager(window.library, window.active_id, window)
        dialog.resize(820, 520)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(out / 'presets.png'))
        dialog.close()
        window.close()
    print('saved to', out)


if __name__ == '__main__':
    main()
