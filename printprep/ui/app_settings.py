"""Application preferences: theme, language, animations, tutorial. Stored in QSettings."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QDialog, QHBoxLayout, QLabel, QVBoxLayout

from .. import i18n
from ..i18n import tr
from . import icons
from .controls import Segmented, Switch, button, hline, label
from .store import prefs
from .theme import DARK, LIGHT, T

THEMES = (('system', 'Как в Windows'), ('light', 'Светлая'), ('dark', 'Тёмная'))


def theme_choice():
    value = prefs().value('theme', 'system') or 'system'
    return value if value in dict(THEMES) else 'system'


def language_choice():
    return prefs().value('language', '') or i18n.default_language()


def animations_on():
    return prefs().value('animations', True, type=bool)


class ThemeCard(QAbstractButton):
    """A miniature of the workspace in the given theme, so the choice is visual."""

    def __init__(self, value, text, parent=None):
        super().__init__(parent)
        self.value = value
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(text)

    def sizeHint(self):
        return QSize(132, 112)

    def _mini(self, p, r, tokens):
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        p.fillPath(path, QColor(tokens['bg']))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), 11), QColor(tokens['panel']))
        p.fillRect(QRectF(r.left(), r.top() + 11, r.width() * .24, r.height()), QColor(tokens['panel']))
        p.fillRect(QRectF(r.right() - r.width() * .28, r.top() + 11, r.width() * .28, r.height()), QColor(tokens['panel']))
        photo = QRectF(r.left() + r.width() * .31, r.top() + 18, r.width() * .36, r.height() - 30)
        p.fillRect(photo, QColor('#7d8fb3'))
        p.fillRect(QRectF(photo.left(), photo.center().y() + 4, photo.width(), photo.height() / 2 - 4), QColor('#4f6b5a'))
        p.setBrush(QColor(tokens['accent']))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(r.left() + 4, r.top() + 16, r.width() * .24 - 8, 6), 2, 2)
        p.drawRoundedRect(QRectF(r.right() - 26, r.top() + 3, 22, 5), 2, 2)
        for i in range(3):
            p.setBrush(QColor(tokens['border_strong']))
            p.drawRoundedRect(QRectF(r.right() - r.width() * .28 + 4, r.top() + 18 + i * 9, r.width() * .28 - 8, 4), 2, 2)
        p.restore()
        p.setPen(QPen(QColor(tokens['border_strong']), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 6, 6)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        p.setPen(QPen(QColor(T['accent'] if on else T['border']), 2 if on else 1))
        soft = QColor(T['accent'])
        soft.setAlpha(34)
        p.setBrush(soft if on else QColor(T['hover'] if self.underMouse() else T['raised']))
        p.drawRoundedRect(r, 10, 10)
        mini = QRectF(r.left() + 10, r.top() + 10, r.width() - 20, r.height() - 40)
        if self.value == 'system':
            self._mini(p, mini, LIGHT)
            p.save()
            clip = QPainterPath()
            clip.moveTo(mini.center().x() + 14, mini.top())
            clip.lineTo(mini.right() + 1, mini.top())
            clip.lineTo(mini.right() + 1, mini.bottom() + 1)
            clip.lineTo(mini.center().x() - 14, mini.bottom() + 1)
            clip.closeSubpath()
            p.setClipPath(clip)
            self._mini(p, mini, DARK)
            p.restore()
        else:
            self._mini(p, mini, LIGHT if self.value == 'light' else DARK)
        p.setPen(QColor(T['text'] if on else T['text2']))
        f = p.font()
        f.setWeight(f.Weight.DemiBold if on else f.Weight.Medium)
        p.setFont(f)
        p.drawText(QRectF(r.left(), mini.bottom() + 6, r.width(), 24), Qt.AlignmentFlag.AlignCenter, self.text())


class AppSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Настройки приложения'))
        self.setMinimumWidth(500)
        self.tutorial_requested = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(12)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap('sliders', T['accent_hover'], 24))
        head.addWidget(ic)
        head.addWidget(label(tr('Настройки приложения'), 'Title'), 1)
        lay.addLayout(head)

        lay.addWidget(label(tr('ТЕМА'), 'Eyebrow'))
        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.theme_group = QButtonGroup(self)
        current = theme_choice()
        for value, text in THEMES:
            card = ThemeCard(value, tr(text))
            card.setChecked(value == current)
            self.theme_group.addButton(card)
            cards.addWidget(card)
        lay.addLayout(cards)
        lay.addWidget(label(tr('Рамка вокруг снимка остаётся нейтрально-серой в любой теме — так цвет оценивается честно.'),
                            'Hint', wrap=True))
        lay.addWidget(hline())

        lay.addWidget(label(tr('ЯЗЫК ИНТЕРФЕЙСА'), 'Eyebrow'))
        self.language = Segmented([(name, code) for code, name in i18n.LANGUAGES])
        self.language.setValue(language_choice())
        lay.addWidget(self.language)
        lay.addWidget(label(tr('После смены языка приложение быстро перезапустится и откроет ту же папку.'), 'Hint', wrap=True))
        lay.addWidget(hline())

        self.animations = Switch(tr('Анимации загрузки и переходов'))
        self.animations.setChecked(animations_on())
        self.animations.setToolTip(tr('Выключите на очень слабом компьютере или если анимации отвлекают.'))
        lay.addWidget(self.animations)
        tutorial = button(tr('Показать обучение ещё раз'), self._tutorial, 'Ghost', 'help')
        tutorial.setToolTip(tr('Короткий тур по окну: пресеты, просмотр, настройки и экспорт'))
        row0 = QHBoxLayout()
        row0.addWidget(tutorial)
        row0.addStretch()
        lay.addLayout(row0)

        lay.addSpacing(4)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button(tr('Отмена'), self.reject, 'Ghost'))
        row.addWidget(button(tr('Применить'), self.accept, 'Primary', 'check'))
        lay.addLayout(row)

    def _tutorial(self):
        self.tutorial_requested = True
        self.accept()

    def values(self):
        theme = next((b.value for b in self.theme_group.buttons() if b.isChecked()), 'system')
        return dict(theme=theme, language=self.language.value() or 'ru', animations=self.animations.isChecked())

    def save(self):
        """Store the choices; returns the set of changes that need the window rebuilt."""
        store = prefs()
        v = self.values()
        changed = {k for k, now in (('theme', theme_choice()), ('language', language_choice())) if v[k] != now}
        store.setValue('theme', v['theme'])
        store.setValue('language', v['language'])
        store.setValue('animations', v['animations'])
        return changed
