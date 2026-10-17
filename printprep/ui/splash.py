"""Animated start screen. Heavy modules import in a thread while the animation runs."""
from __future__ import annotations

import math
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from .. import __version__
from ..i18n import tr
from .theme import T

ROOT = Path(__file__).resolve().parents[2]
LINES = ('Протираем объектив…', 'Раскладываем пресеты…', 'Настраиваем цвета…', 'Будим нейросеть…',
         'Считаем пиксели…', 'Готовим бумагу…')
ORBIT = (('#3a5bff', 7, 1.1), ('#ff6fa8', 6, 1.1), ('#ffc21a', 5, 1.1), ('#29c7ef', 4, 1.1))


class Splash(QWidget):
    MIN_SHOWN = .45

    def __init__(self):
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 300)
        from .app_settings import animations_on
        self.animated = animations_on()
        icon = QPixmap(str(ROOT / 'assets' / 'printprep_1024.png'))
        if icon.isNull():
            icon = QPixmap(str(ROOT / 'assets' / 'printprep.png'))
        dpr = self.devicePixelRatioF()
        self.icon = icon.scaled(round(112 * dpr), round(112 * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        self.icon.setDevicePixelRatio(dpr)
        self.t0 = time.perf_counter()
        self.phase = 0.
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)
        if self.animated:
            self.timer.start()

    def _tick(self):
        self.phase = time.perf_counter() - self.t0
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        shadow = QPainterPath()
        shadow.addRoundedRect(r.adjusted(-4, -2, 4, 6), 22, 22)
        p.fillPath(shadow, QColor(0, 0, 0, 40))
        card = QPainterPath()
        card.addRoundedRect(r, 18, 18)
        p.fillPath(card, QColor(T['panel']))
        p.setPen(QColor(T['border']))
        p.drawPath(card)
        t = self.phase
        # Icon floats gently; the logo's coloured discs orbit it like planets.
        bob = math.sin(t * 2.4) * 4 if self.animated else 0
        cx, cy = r.center().x(), r.top() + 96
        if self.animated:
            p.setPen(Qt.PenStyle.NoPen)
            for i, (colour, size, speed) in enumerate(ORBIT):
                a = t * speed + i * math.tau / len(ORBIT)
                x, y = cx + math.cos(a) * 92, cy + math.sin(a) * 34
                if math.sin(a) < 0:            # behind the icon
                    c = QColor(colour)
                    c.setAlphaF(.55)
                    p.setBrush(c)
                    p.drawEllipse(QPointF(x, y), size * .8, size * .8)
        p.drawPixmap(QPointF(cx - 56, cy - 56 + bob), self.icon)
        if self.animated:
            for i, (colour, size, speed) in enumerate(ORBIT):
                a = t * speed + i * math.tau / len(ORBIT)
                x, y = cx + math.cos(a) * 92, cy + math.sin(a) * 34
                if math.sin(a) >= 0:           # in front of it
                    p.setBrush(QColor(colour))
                    p.drawEllipse(QPointF(x, y), size, size)
        f = QFont(self.font())
        f.setPointSizeF(17)
        f.setWeight(QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QColor(T['text']))
        p.drawText(QRectF(r.left(), cy + 66, r.width(), 30), Qt.AlignmentFlag.AlignCenter, 'Print Prep')
        f.setPointSizeF(9)
        f.setWeight(QFont.Weight.Normal)
        p.setFont(f)
        p.setPen(QColor(T['text3']))
        line = tr(LINES[int(t / .7) % len(LINES)]) if self.animated else tr('Загрузка…')
        p.drawText(QRectF(r.left(), cy + 98, r.width(), 20), Qt.AlignmentFlag.AlignCenter, line)
        # Indeterminate bar: a soft comet sliding along the track.
        track = QRectF(r.left() + 120, r.bottom() - 30, r.width() - 240, 4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T['track']))
        p.drawRoundedRect(track, 2, 2)
        x = track.left() + (math.sin(t * 2.2 - math.pi / 2) + 1) / 2 * (track.width() - 60) if self.animated else track.left()
        g = QLinearGradient(x, 0, x + 60, 0)
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(.5, QColor(T['accent']))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(g)
        p.drawRoundedRect(QRectF(x, track.top(), 60, track.height()), 2, 2)
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(T['text3']))
        p.drawText(QRectF(r.left(), r.bottom() - 22, r.width() - 16, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f'v{__version__}')

    def wait_for(self, fn):
        """Run fn in a thread (imports) while keeping the animation alive; re-raise its error."""
        box = {}

        def work():
            try:
                box['value'] = fn()
            except BaseException as exc:          # surfaced on the GUI thread below
                box['error'] = exc
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        loop = QEventLoop()
        while thread.is_alive() or time.perf_counter() - self.t0 < self.MIN_SHOWN:
            loop.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 16)
            thread.join(.012)
        if 'error' in box:
            raise box['error']
        return box.get('value')

    def finish_into(self, window):
        window.show()
        if not self.animated:
            self.close()
            return
        window.setWindowOpacity(0.)
        fade_in = QPropertyAnimation(window, b'windowOpacity', window)
        fade_in.setDuration(220)
        fade_in.setStartValue(0.)
        fade_in.setEndValue(1.)
        fade_in.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        fade_out = QPropertyAnimation(self, b'windowOpacity', self)
        fade_out.setDuration(180)
        fade_out.setStartValue(1.)
        fade_out.setEndValue(0.)
        fade_out.finished.connect(self.close)
        fade_out.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
