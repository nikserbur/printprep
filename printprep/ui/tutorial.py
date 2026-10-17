"""First-run tour: a dimmed overlay with a spotlight that walks across the main areas."""
from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QEvent, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..i18n import tr
from . import icons
from .controls import button, label, tool
from .theme import T

STEPS = (
    (None, 'sparkles', 'Добро пожаловать в Print Prep',
     'За минуту покажем главное. Оригиналы никогда не меняются — готовые файлы сохраняются в отдельную папку.'),
    ('folder_btn', 'folder', 'Откройте папку',
     'Нажмите здесь или просто перетащите папку со снимками в окно. Недавние папки — в меню со стрелкой.'),
    ('presets', 'layers', 'Выберите пресет',
     'Пресет — набор настроек для всех фото сразу: размер отпечатка, цвет, резкость. Выбранный обведён рамкой. '
     'Группы встроенных пресетов можно свернуть щелчком по заголовку.'),
    ('inspector', 'sliders', 'Настройте пресет',
     'Справа — настройки выбранного пресета. Любое изменение сразу применяется ко всем фото папки. '
     'Чтобы поправить один снимок, переключитесь на «Этот снимок».'),
    ('viewer', 'compare', 'Смотрите результат на лету',
     'Шторка «до/после» двигается мышью. Двойной щелчок — 100% в этой точке; там же видна работа нейросети.'),
    ('strip_box', 'image', 'Листайте снимки',
     'Стрелки ← → или щелчок по миниатюре. Значки на миниатюрах предупреждают о малом разрешении и правках.'),
    ('export_btn', 'printer', 'Подготовьте к печати',
     'Обработает все снимки выбранным пресетом. Результат появится в подпапке PrintPrep_… рядом с оригиналами.'),
)


class Tour(QWidget):
    def __init__(self, window, on_finish=None):
        super().__init__(window)
        self.window_ = window
        self.on_finish = on_finish
        self.index = 0
        self.spot = QRectF()
        self.pulse = 0.
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.card = QFrame(self)
        self.card.setObjectName('TourCard')
        self.card.setStyleSheet(f'#TourCard {{ background: {T["raised"]}; border: 1px solid {T["border_strong"]}; border-radius: 14px; }}')
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.card.setGraphicsEffect(shadow)
        self.card.setFixedWidth(400)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.icon = QLabel()
        head.addWidget(self.icon)
        self.title = label('', 'Title')
        self.title.setWordWrap(True)
        head.addWidget(self.title, 1)
        self.skip = tool('close', tr('Пропустить обучение (Esc)'), self.finish, size=16)
        head.addWidget(self.skip, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        self.text = label('', 'Muted', wrap=True)
        lay.addWidget(self.text)
        lay.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.dots = QLabel()
        row.addWidget(self.dots)
        row.addStretch()
        self.back = button(tr('Назад'), lambda: self.go(self.index - 1), 'Ghost')
        self.next = button(tr('Далее'), lambda: self.go(self.index + 1), 'Primary', 'arrow_right')
        self.next.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        for b in (self.back, self.next):
            row.addWidget(b)
        lay.addLayout(row)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(320)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._move_spot)
        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(33)
        self.pulse_timer.timeout.connect(self._tick)
        window.installEventFilter(self)

    # ------------------------------------------------------------------ flow
    def start(self):
        self.setGeometry(self.window_.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.pulse_timer.start()
        self.go(0, animate=False)

    def go(self, index, animate=True):
        if index >= len(STEPS):
            self.finish()
            return
        self.index = max(0, index)
        target, icon_name, title, text = STEPS[self.index]
        self.icon.setPixmap(icons.pixmap(icon_name, T['accent_hover'], 22))
        self.title.setText(tr(title))
        self.text.setText(tr(text))
        n = len(STEPS)
        self.dots.setText(' '.join('●' if i == self.index else '○' for i in range(n)))
        self.dots.setStyleSheet(f'color: {T["accent"]}; font-size: 9px; letter-spacing: 1px;')
        self.back.setVisible(self.index > 0)
        self.next.setText(tr('Начать работу') if self.index == n - 1 else tr('Далее'))
        end = self._target_rect(target)
        if animate and not self.spot.isNull() and not end.isNull():
            self.anim.stop()
            self.anim.setStartValue(self.spot)
            self.anim.setEndValue(end)
            self.anim.start()
        else:
            self._move_spot(end)
        self.next.setFocus()

    def finish(self):
        self.pulse_timer.stop()
        self.window_.removeEventFilter(self)
        self.hide()
        self.deleteLater()
        if self.on_finish:
            self.on_finish()

    # ---------------------------------------------------------------- layout
    def _target_rect(self, name):
        widget = getattr(self.window_, name, None) if name else None
        if widget is None or not widget.isVisible():
            return QRectF()
        top_left = widget.mapTo(self.window_, widget.rect().topLeft())
        return QRectF(QRect(top_left, widget.size())).adjusted(-6, -6, 6, 6).intersected(QRectF(self.rect()).adjusted(3, 3, -3, -3))

    def _move_spot(self, rect):
        self.spot = QRectF(rect)
        self._place_card()
        self.update()

    def _place_card(self):
        cw = self.card.width()
        ch = self.card.layout().totalHeightForWidth(cw)
        self.card.setFixedHeight(ch)
        W, H = self.width(), self.height()
        s = self.spot
        if s.isNull():
            x, y = (W - cw) / 2, (H - ch) / 2
        elif s.right() + 18 + cw < W:
            x, y = s.right() + 18, s.center().y() - ch / 2
        elif s.left() - 18 - cw > 0:
            x, y = s.left() - 18 - cw, s.center().y() - ch / 2
        elif s.bottom() + 18 + ch < H:
            x, y = s.center().x() - cw / 2, s.bottom() + 18
        else:
            x, y = s.center().x() - cw / 2, s.top() - 18 - ch
        if s.width() > W * .45 and s.height() > H * .45:
            x, y = s.center().x() - cw / 2, s.bottom() - ch - 30   # big targets: card inside, near the bottom
        self.card.move(int(min(max(16, x), W - cw - 16)), int(min(max(16, y), H - ch - 16)))

    def _tick(self):
        self.pulse = (self.pulse + .033) % (2 * math.pi)
        if not self.spot.isNull():
            self.update(self.spot.adjusted(-12, -12, 12, 12).toRect())

    # ----------------------------------------------------------------- events
    def eventFilter(self, obj, event):
        if obj is self.window_ and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.window_.rect())
            target = STEPS[self.index][0]
            self._move_spot(self._target_rect(target))
        return False

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.finish()
        elif e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.go(self.index + 1)
        elif e.key() == Qt.Key.Key_Left:
            self.go(self.index - 1)

    def mousePressEvent(self, e):
        e.accept()          # the tour is modal: clicks outside the card do nothing

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shade = QPainterPath()
        shade.setFillRule(Qt.FillRule.OddEvenFill)
        shade.addRect(QRectF(self.rect()))
        if not self.spot.isNull():
            shade.addRoundedRect(self.spot, 12, 12)
        p.fillPath(shade, QColor(0, 0, 0, 150 if T['name'] == 'dark' else 120))
        if not self.spot.isNull():
            k = (math.sin(self.pulse * 3) + 1) / 2
            ring = QColor(T['accent_hover'])
            ring.setAlphaF(.55 + .45 * k)
            p.setPen(QPen(ring, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(self.spot, 12, 12)
            glow = QColor(T['accent'])
            glow.setAlphaF(.25 * (1 - k))
            p.setPen(QPen(glow, 6))
            p.drawRoundedRect(self.spot.adjusted(-3 - 3 * k, -3 - 3 * k, 3 + 3 * k, 3 + 3 * k), 14, 14)
