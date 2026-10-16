"""Custom controls: parameter slider, collapsible section, segmented control, switch,
chips, spinner and toast. Painted by hand for a consistent, modern look."""
from __future__ import annotations

import math

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal,
                            Property)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import icons
from .theme import T, color


def label(text='', name=None, wrap=False):
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def tool(icon_name, tip, callback=None, checkable=False, size=18):
    b = QToolButton()
    b.setIcon(icons.icon(icon_name, size=size))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tip)
    b.setAccessibleName(tip.split('\n')[0])
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if callback:
        (b.toggled if checkable else b.clicked).connect(callback)
    return b


def button(text, callback=None, kind=None, icon_name=None):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if icon_name:
        tint = '#ffffff' if kind == 'Primary' else T['text2']
        b.setIcon(icons.icon(icon_name, tint, '#ffffff' if kind == 'Primary' else T['text']))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if callback:
        b.clicked.connect(callback)
    return b


def hline():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f'background: {T["border"]};')
    return line


# ---------------------------------------------------------------- slider
class ParamSlider(QWidget):
    """Labelled slider: drag, click-to-jump, double-click resets, wheel only when focused,
    arrows nudge (Shift ×10), click the number to type a value."""
    valueChanged = Signal(float)
    editingFinished = Signal()
    pressed = Signal()

    def __init__(self, title, low, high, step=1., default=0., unit='', decimals=None, gradient=None, parent=None):
        super().__init__(parent)
        self.title, self.low, self.high, self.step = title, float(low), float(high), float(step)
        self.default = float(default)
        self.baseline = None           # preset value marker in photo scope
        self.unit = unit
        self.decimals = decimals if decimals is not None else (2 if step < .1 else 1 if step < 1 else 0)
        self.gradient = gradient
        self._value = float(default)
        self._drag = False
        self._hover = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.editor = QLineEdit(self)
        self.editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.editor.setFixedWidth(64)
        self.editor.hide()
        self.editor.editingFinished.connect(self._commit_editor)
        self.setToolTip(f'{title}\nДвойной щелчок — сбросить · стрелки — точная настройка')

    def sizeHint(self):
        return QSize(260, 44)

    def value(self):
        return self._value

    def setValue(self, value, emit=False):
        value = min(self.high, max(self.low, round(float(value) / self.step) * self.step))
        if abs(value - self._value) < 1e-9:
            return
        self._value = value
        self.update()
        if emit:
            self.valueChanged.emit(value)

    def setBaseline(self, value):
        self.baseline = value
        self.update()

    def text(self):
        v = self._value
        sign = '+' if v > 0 and self.low < 0 else ''
        body = f'{v:.{self.decimals}f}'.replace('-', '−')
        return f'{sign}{body}{(" " + self.unit) if self.unit else ""}'

    def _track(self):
        return QRectF(8, self.height() - 14, self.width() - 16, 4)

    def _x(self, value):
        t = self._track()
        return t.left() + (value - self.low) / (self.high - self.low) * t.width()

    def _value_at(self, x):
        t = self._track()
        frac = min(1, max(0, (x - t.left()) / max(1, t.width())))
        return self.low + frac * (self.high - self.low)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        changed = abs(self._value - (self.baseline if self.baseline is not None else self.default)) > 1e-9
        p.setFont(self.font())
        p.setPen(QColor(T['text2'] if enabled else T['text3']))
        p.drawText(QRectF(8, 2, self.width() - 90, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.title)
        if not self.editor.isVisible():
            p.setPen(QColor(T['accent_hover'] if changed and enabled else (T['text'] if enabled else T['text3'])))
            p.drawText(QRectF(self.width() - 92, 2, 84, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self.text())
        t = self._track()
        path = QPainterPath()
        path.addRoundedRect(t, 2, 2)
        if self.gradient:
            g = QLinearGradient(t.topLeft(), t.topRight())
            for i, c in enumerate(self.gradient):
                g.setColorAt(i / (len(self.gradient) - 1), QColor(c))
            p.fillPath(path, g)
            if not enabled:
                p.fillPath(path, QColor(0, 0, 0, 140))
        else:
            p.fillPath(path, QColor('#3a3c43'))
            zero = min(self.high, max(self.low, 0.0))
            x0, x1 = sorted((self._x(zero), self._x(self._value)))
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(x0, t.top(), max(0., x1 - x0), t.height()), 2, 2)
            p.fillPath(fill, QColor(T['accent'] if enabled else '#4a4d55'))
        if self.baseline is not None:
            bx = self._x(self.baseline)
            p.setPen(QPen(QColor(T['text3']), 2))
            p.drawLine(QPointF(bx, t.top() - 4), QPointF(bx, t.bottom() + 4))
        x = self._x(self._value)
        r = 7 if (self._hover or self._drag or self.hasFocus()) else 6
        p.setPen(QPen(QColor(T['accent'] if self.hasFocus() else '#00000000'), 2))
        p.setBrush(QColor('#f4f5f7' if enabled else '#6b6e76'))
        p.drawEllipse(QPointF(x, t.center().y()), r, r)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if e.position().y() < 22 and e.position().x() > self.width() - 92:
            self._open_editor()
            return
        self.setFocus()
        self._drag = True
        self.pressed.emit()
        self.setValue(self._value_at(e.position().x()), emit=True)

    def mouseMoveEvent(self, e):
        hover = self._track().adjusted(-8, -10, 8, 10).contains(e.position())
        if hover != self._hover:
            self._hover = hover
            self.update()
        if self._drag:
            self.setValue(self._value_at(e.position().x()), emit=True)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.update()
            self.editingFinished.emit()

    def mouseDoubleClickEvent(self, e):
        if e.position().y() < 22 and e.position().x() > self.width() - 92:
            return
        self.pressed.emit()
        target = self.baseline if self.baseline is not None else self.default
        self.setValue(target, emit=True)
        self._value = target
        self.update()
        self.valueChanged.emit(target)
        self.editingFinished.emit()

    def leaveEvent(self, _):
        self._hover = False
        self.update()

    def wheelEvent(self, e):
        if not self.hasFocus():
            e.ignore()
            return
        steps = e.angleDelta().y() / 120
        self.pressed.emit()
        self.setValue(self._value + steps * self.step * (10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1), emit=True)
        self.editingFinished.emit()

    def keyPressEvent(self, e):
        big = 10 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        delta = {Qt.Key.Key_Left: -1, Qt.Key.Key_Down: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: 1}.get(e.key())
        if delta is not None:
            self.pressed.emit()
            self.setValue(self._value + delta * self.step * big, emit=True)
            self.editingFinished.emit()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_editor()
        else:
            super().keyPressEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()

    def _open_editor(self):
        self.editor.setGeometry(self.width() - 72, 0, 64, 22)
        self.editor.setText(f'{self._value:.{self.decimals}f}')
        self.editor.show()
        self.editor.setFocus()
        self.editor.selectAll()
        self.update()

    def _commit_editor(self):
        if not self.editor.isVisible():
            return
        text = self.editor.text().replace(',', '.').replace('−', '-').strip()
        self.editor.hide()
        try:
            value = float(text)
        except ValueError:
            self.update()
            return
        self.pressed.emit()
        self.setValue(value, emit=True)
        self.editingFinished.emit()
        self.update()


# ---------------------------------------------------------------- switch
class Switch(QAbstractButton):
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.
        self.anim = QPropertyAnimation(self, b'knob', self)
        self.anim.setDuration(140)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(text)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.text()) + 56, 28)

    def _get(self):
        return self._pos

    def _set(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def _animate(self, checked):
        self.anim.stop()
        self.anim.setStartValue(self._pos)
        self.anim.setEndValue(1. if checked else 0.)
        self.anim.start()

    def setChecked(self, checked):
        blocked = self.signalsBlocked()
        super().setChecked(checked)
        if blocked or not self.isVisible():
            self._pos = 1. if checked else 0.
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = 34, 20
        track = QRectF(self.width() - w - 4, (self.height() - h) / 2, w, h)
        on = QColor(T['accent']) if self.isEnabled() else QColor('#2a3a58')
        off = QColor('#3a3c43')
        mix = QColor(
            round(off.red() + (on.red() - off.red()) * self._pos),
            round(off.green() + (on.green() - off.green()) * self._pos),
            round(off.blue() + (on.blue() - off.blue()) * self._pos))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix)
        p.drawRoundedRect(track, h / 2, h / 2)
        p.setBrush(QColor('#ffffff' if self.isEnabled() else '#8a8d95'))
        x = track.left() + 3 + self._pos * (w - h)
        p.drawEllipse(QRectF(x, track.top() + 3, h - 6, h - 6))
        if self.text():
            p.setPen(QColor(T['text'] if self.isEnabled() else T['text3']))
            p.drawText(QRectF(8, 0, self.width() - w - 16, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        if self.hasFocus():
            p.setPen(QPen(QColor(T['accent']), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(track.adjusted(-2, -2, 2, 2), h / 2 + 2, h / 2 + 2)


# ---------------------------------------------------------------- segmented
class Segmented(QFrame):
    changed = Signal(object)

    def __init__(self, items, parent=None, compact=False):
        super().__init__(parent)
        self.setObjectName('Segmented')
        pad = '4px 8px' if compact else '5px 10px'
        self.setStyleSheet(f'''
            #Segmented {{ background: {T["raised"]}; border: 1px solid {T["border_strong"]}; border-radius: 8px; }}
            #Segmented QPushButton {{ background: transparent; border: none; border-radius: 6px; padding: {pad};
                                     color: {T["text2"]}; min-height: 18px; font-weight: 500; }}
            #Segmented QPushButton:hover {{ color: {T["text"]}; background: {T["hover"]}; }}
            #Segmented QPushButton:checked {{ background: #3a3d45; color: {T["text"]}; }}
            #Segmented QPushButton:disabled {{ color: #50535b; }}
        ''')
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for item in items:
            text, value = item[0], item[1]
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if len(item) > 2:
                b.setToolTip(item[2])
            b.clicked.connect(lambda _=False, v=value: self.changed.emit(v))
            self.group.addButton(b)
            self.buttons[value] = b
            row.addWidget(b, 1)

    def value(self):
        for v, b in self.buttons.items():
            if b.isChecked():
                return v
        return None

    def setValue(self, value):
        b = self.buttons.get(value)
        if b:
            b.setChecked(True)
        else:
            self.group.setExclusive(False)
            for x in self.buttons.values():
                x.setChecked(False)
            self.group.setExclusive(True)

    def setItemEnabled(self, value, enabled):
        if value in self.buttons:
            self.buttons[value].setEnabled(enabled)


# ---------------------------------------------------------------- section
class Section(QWidget):
    """Collapsible inspector section with optional header widgets."""
    toggled = Signal(bool)

    def __init__(self, title, icon_name=None, opened=True, parent=None):
        super().__init__(parent)
        self.title = title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QPushButton()
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setCheckable(True)
        self.header.setChecked(opened)
        self.header.setStyleSheet(f'''
            QPushButton {{ background: transparent; border: none; border-radius: 0; text-align: left;
                          padding: 10px 14px 10px 36px; font-weight: 600; color: {T["text"]}; min-height: 22px; }}
            QPushButton:hover {{ background: {T["hover"]}; }}''')
        self.header.setText(title)
        self.header.toggled.connect(self.set_open)
        self.icon_name = icon_name
        head = QHBoxLayout(self.header)
        head.setContentsMargins(10, 0, 10, 0)
        head.setSpacing(6)
        self.chevron = QLabel()
        self.chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        head.addWidget(self.chevron)
        head.addStretch()
        self.extra = QHBoxLayout()
        self.extra.setSpacing(4)
        head.addLayout(self.extra)
        outer.addWidget(self.header)
        self.body = QWidget()
        self.layout = QVBoxLayout(self.body)
        self.layout.setContentsMargins(14, 2, 14, 14)
        self.layout.setSpacing(6)
        outer.addWidget(self.body)
        outer.addWidget(hline())
        self.set_open(opened)

    def add_header_widget(self, widget):
        self.extra.addWidget(widget)

    def set_open(self, opened):
        self.header.blockSignals(True)
        self.header.setChecked(opened)
        self.header.blockSignals(False)
        self.body.setVisible(opened)
        self.chevron.setPixmap(icons.pixmap('chevron_down' if opened else 'chevron_right', T['text3'], 14))
        self.toggled.emit(opened)

    def is_open(self):
        return self.body.isVisible()


# ---------------------------------------------------------------- chips
class Chip(QLabel):
    STYLES = {
        'neutral': (T['raised'], T['text2'], T['border_strong']),
        'accent': ('rgba(76,141,255,0.15)', '#8fb6ff', 'rgba(76,141,255,0.35)'),
        'warning': ('rgba(242,177,74,0.14)', '#f5c475', 'rgba(242,177,74,0.35)'),
        'success': ('rgba(60,207,138,0.14)', '#6fdca8', 'rgba(60,207,138,0.35)'),
        'danger': ('rgba(255,107,107,0.14)', '#ff9a9a', 'rgba(255,107,107,0.35)'),
    }

    def __init__(self, text='', kind='neutral', parent=None):
        super().__init__(text, parent)
        self.set_kind(kind)

    def set_kind(self, kind):
        bg, fg, border = self.STYLES[kind]
        self.setStyleSheet(f'QLabel {{ background: {bg}; color: {fg}; border: 1px solid {border}; border-radius: 10px;'
                           f' padding: 2px 9px; font-size: 12px; }}')


class ChipToggle(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f'''
            QPushButton {{ background: {T["raised"]}; color: {T["text2"]}; border: 1px solid {T["border_strong"]};
                          border-radius: 12px; padding: 3px 10px; min-height: 16px; font-size: 12px; }}
            QPushButton:hover {{ color: {T["text"]}; }}
            QPushButton:checked {{ background: rgba(76,141,255,0.16); color: #9fc0ff; border-color: rgba(76,141,255,0.45); }}
            QPushButton:disabled {{ color: #50535b; }}''')


class FlowRow(QWidget):
    """Wrapping row of small widgets (chips)."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.spacing = spacing
        self.items = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def clear(self):
        for w in self.items:
            w.setParent(None)
            w.deleteLater()
        self.items = []
        self.updateGeometry()

    def add(self, widget):
        widget.setParent(self)
        widget.show()
        self.items.append(widget)
        self._layout(self.width())
        self.updateGeometry()

    def _layout(self, width, apply=True):
        x = y = line = 0
        for w in self.items:
            hint = w.sizeHint()
            if x and x + hint.width() > width:
                x, y = 0, y + line + self.spacing
                line = 0
            if apply:
                w.setGeometry(x, y, hint.width(), hint.height())
            x += hint.width() + self.spacing
            line = max(line, hint.height())
        return y + line

    def resizeEvent(self, e):
        self._layout(e.size().width())

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(width, apply=False)

    def sizeHint(self):
        return QSize(200, max(0, self._layout(max(200, self.width()), apply=False)))


# ---------------------------------------------------------------- spinner / toast
class Spinner(QWidget):
    def __init__(self, size=16, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        self.angle = (self.angle + 9) % 360
        self.update()

    def showEvent(self, e):
        self.timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self.timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(2, 2, self.width() - 4, self.height() - 4)
        p.setPen(QPen(QColor(255, 255, 255, 40), 2))
        p.drawEllipse(r)
        pen = QPen(QColor(T['accent_hover']), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, -self.angle * 16, 100 * 16)


class Toast(QFrame):
    """Bottom notification inside the main window."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('Toast')
        self.setStyleSheet(f'''#Toast {{ background: {T["raised"]}; border: 1px solid {T["border_strong"]}; border-radius: 12px; }}''')
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 10, 10)
        row.setSpacing(10)
        self.icon = QLabel()
        row.addWidget(self.icon)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title = label('', None)
        self.title.setStyleSheet('font-weight: 600;')
        self.detail = label('', 'Muted')
        texts.addWidget(self.title)
        texts.addWidget(self.detail)
        row.addLayout(texts, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        row.addLayout(self.actions)
        close = tool('close', 'Закрыть', self.hide, size=16)
        row.addWidget(close)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, title, detail='', kind='success', actions=(), timeout=6000):
        icon_name, tint = {'success': ('check', T['success']), 'warning': ('warning', T['warning']),
                           'danger': ('warning', T['danger']), 'info': ('sparkles', T['accent_hover'])}[kind]
        self.icon.setPixmap(icons.pixmap(icon_name, tint, 20))
        self.title.setText(title)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        while self.actions.count():
            w = self.actions.takeAt(0).widget()
            if w:
                w.deleteLater()
        for text, callback, kind_name in actions:
            b = button(text, callback, kind_name)
            self.actions.addWidget(b)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        if timeout:
            self.timer.start(timeout)
        else:
            self.timer.stop()

    def reposition(self):
        parent = self.parentWidget()
        if not parent:
            return
        w = min(max(420, self.sizeHint().width()), parent.width() - 40)
        self.resize(w, self.sizeHint().height())
        self.move((parent.width() - w) // 2, parent.height() - self.height() - 28)
