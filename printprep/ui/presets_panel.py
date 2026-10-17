"""Left panel: preset library grouped by purpose. One click applies a preset to the batch."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QListWidget, QListWidgetItem, QMenu, QPushButton, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from . import icons
from .controls import button, label, tool
from .theme import T

ROLE_PRESET = Qt.ItemDataRole.UserRole
ROLE_HEADER = Qt.ItemDataRole.UserRole + 1


class PresetDelegate(QStyledItemDelegate):
    def __init__(self, panel):
        super().__init__(panel.list)
        self.panel = panel

    def sizeHint(self, option, index):
        if index.data(ROLE_HEADER):
            return QSize(200, 34)
        return QSize(200, 54)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect)
        header = index.data(ROLE_HEADER)
        if header:
            f = QFont(option.font)
            f.setPointSizeF(8)
            f.setWeight(QFont.Weight.DemiBold)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, .8)
            p.setFont(f)
            p.setPen(QColor(T['text3']))
            p.drawText(r.adjusted(14, 10, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, header.upper())
            p.restore()
            return
        preset = index.data(ROLE_PRESET)
        if preset is None:
            f = QFont(option.font)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(QColor(T['text3']))
            p.drawText(r.adjusted(16, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                       index.data(Qt.ItemDataRole.DisplayRole) or '')
            p.restore()
            return
        active = preset.id == self.panel.active_id
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        card = r.adjusted(8, 2, -8, -2)
        if active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(76, 141, 255, 38))
            p.drawRoundedRect(card, 8, 8)
            p.setBrush(QColor(T['accent']))
            p.drawRoundedRect(QRectF(card.left(), card.top() + 10, 3, card.height() - 20), 1.5, 1.5)
        elif hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T['hover']))
            p.drawRoundedRect(card, 8, 8)
        f = QFont(option.font)
        f.setWeight(QFont.Weight.DemiBold if active else QFont.Weight.Medium)
        p.setFont(f)
        p.setPen(QColor(T['text']))
        name = preset.name
        if active and self.panel.dirty:
            name += '  •'
        reserve = 34 if (hover or active) else 10
        title_rect = card.adjusted(14, 7, -reserve, -card.height() / 2)
        p.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(title_rect.width())))
        f2 = QFont(option.font)
        f2.setPointSizeF(8.25)
        p.setFont(f2)
        p.setPen(QColor(T['text3']))
        note_rect = card.adjusted(14, card.height() / 2, -reserve, -6)
        p.drawText(note_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(preset.note, Qt.TextElideMode.ElideRight, int(note_rect.width())))
        if hover or active:
            gear = QRectF(card.right() - 28, card.center().y() - 10, 20, 20)
            p.drawPixmap(gear.toRect(), icons.pixmap('more', T['text'] if hover else T['text3'], 20))
        p.restore()


class PresetPanel(QWidget):
    applyRequested = Signal(str)
    saveRequested = Signal()          # save changes into the active user preset
    saveAsRequested = Signal()
    revertRequested = Signal()
    renameRequested = Signal(str)
    deleteRequested = Signal(str)
    duplicateRequested = Signal(str)
    exportRequested = Signal(str)
    importRequested = Signal()
    manageRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('LeftPanel')
        self.active_id = None
        self.dirty = False
        self.presets = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 12, 0, 10)
        outer.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(16, 0, 8, 0)
        head.addWidget(label('ПРЕСЕТЫ', 'Eyebrow'))
        head.addStretch()
        self.add_btn = QPushButton(' Новый')
        self.add_btn.setIcon(icons.icon('plus', T['text2'], T['text']))
        self.add_btn.setObjectName('Ghost')
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setToolTip('Сохранить текущие настройки как новый пресет')
        self.add_btn.clicked.connect(self.saveAsRequested.emit)
        head.addWidget(self.add_btn)
        outer.addLayout(head)
        self.list = QListWidget()
        self.list.setItemDelegate(PresetDelegate(self))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemClicked.connect(self._clicked)
        self.list.viewport().installEventFilter(self)
        self.list.setAccessibleName('Список пресетов')
        outer.addWidget(self.list, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(10, 4, 10, 0)
        manage = QPushButton(' Управление пресетами')
        manage.setIcon(icons.icon('layers', T['text2'], T['text']))
        manage.setObjectName('Ghost')
        manage.setCursor(Qt.CursorShape.PointingHandCursor)
        manage.clicked.connect(self.manageRequested.emit)
        foot.addWidget(manage, 1)
        outer.addLayout(foot)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.list.viewport() and event.type() == QEvent.Type.MouseButtonRelease                 and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            item = self.list.itemAt(pos)
            if item and item.data(ROLE_PRESET) and pos.x() > self.list.viewport().width() - 40:
                self._menu(pos)
                return True
        return super().eventFilter(obj, event)

    def set_presets(self, presets, active_id, dirty):
        self.presets = presets
        self.list.clear()
        group = None
        for preset in presets:
            if preset.group != group:
                group = preset.group
                header = QListWidgetItem()
                header.setData(ROLE_HEADER, group)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self.list.addItem(header)
            item = QListWidgetItem(preset.name)
            item.setData(ROLE_PRESET, preset)
            item.setToolTip(f'{preset.name}\n{preset.note}')
            self.list.addItem(item)
        if not any(p.group == 'Мои' for p in presets):
            header = QListWidgetItem()
            header.setData(ROLE_HEADER, 'Мои')
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(header)
            note = QListWidgetItem('Настройте справа и нажмите «+» —\nпресет появится здесь')
            note.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(note)
        self.set_state(active_id, dirty)

    def set_state(self, active_id, dirty):
        self.active_id, self.dirty = active_id, dirty
        self.list.viewport().update()
        for i in range(self.list.count()):
            preset = self.list.item(i).data(ROLE_PRESET)
            if preset and preset.id == active_id:
                self.list.scrollToItem(self.list.item(i))
                break

    def _clicked(self, item):
        preset = item.data(ROLE_PRESET)
        if preset:
            self.applyRequested.emit(preset.id)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        preset = item.data(ROLE_PRESET) if item else None
        if not preset:
            return
        menu = QMenu(self)
        menu.addAction(icons.icon('check'), 'Применить ко всем фото', lambda: self.applyRequested.emit(preset.id))
        menu.addAction(icons.icon('copy'), 'Дублировать в «Мои»', lambda: self.duplicateRequested.emit(preset.id))
        if not preset.builtin:
            menu.addAction(icons.icon('edit'), 'Переименовать…', lambda: self.renameRequested.emit(preset.id))
            menu.addAction(icons.icon('trash'), 'Удалить…', lambda: self.deleteRequested.emit(preset.id))
        menu.addSeparator()
        menu.addAction(icons.icon('download'), 'Экспортировать в файл…', lambda: self.exportRequested.emit(preset.id))
        menu.addAction(icons.icon('layers'), 'Управление пресетами…', self.manageRequested.emit)
        menu.exec(self.list.viewport().mapToGlobal(pos))
