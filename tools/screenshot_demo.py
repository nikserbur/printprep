"""Generate an illustrative UI capture from synthetic, non-personal fixtures."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from printprep.ui import MainWindow, STYLE
from printprep.engine import Settings, SRGB_BYTES

with tempfile.TemporaryDirectory() as temp:
    folder = Path(temp)
    for index in range(4):
        im = Image.new('RGB', (1800, 1200))
        d = ImageDraw.Draw(im)
        for y in range(1200):
            t = y / 1200
            d.line((0, y, 1800, y), fill=(int(190-80*t), int(194-45*t), int(186-30*t)))
        d.ellipse((1240, 140, 1450, 350), fill='#eee6c4')
        d.polygon([(0,740),(350,400),(650,770),(1020,300),(1600,820),(1800,540),(1800,1200),(0,1200)], fill='#496b70')
        d.polygon([(0,920),(300,730),(700,1000),(1150,620),(1600,970),(1800,800),(1800,1200),(0,1200)], fill='#2c5259')
        d.polygon([(0,1050),(450,880),(950,1140),(1450,900),(1800,1100),(1800,1200),(0,1200)], fill='#193b44')
        im.save(folder / ['01_Горное_озеро.jpg','02_Пейзаж.jpg','03_Вечер.jpg','04_Тишина.jpg'][index], icc_profile=SRGB_BYTES)
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.resize(1280, 900)
    window.apply_settings(Settings())
    window.show()
    app.processEvents()
    destination = Path(__file__).resolve().parents[1] / 'docs'
    window.grab().save(str(destination / 'start.png'))
    window.load_folder(folder)
    end = time.monotonic() + 15
    while time.monotonic() < end:
        app.processEvents()
        if not window.busy and window.mode == 'batch':
            break
        time.sleep(.01)
    window.folder_label.setText('Фотографии / Съёмка в горах')
    window.grab().save(str(destination / 'interface.png'))
    window.show_review()
    while time.monotonic() < end:
        app.processEvents()
        if window.preview.picture and not window.timer.isActive() and not window.preview_worker.isRunning():
            break
        time.sleep(.01)
    window.grab().save(str(destination / 'review.png'))
    window.close()
