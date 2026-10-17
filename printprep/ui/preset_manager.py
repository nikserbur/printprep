"""Preset manager dialog: everything about presets in one place."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem,
                               QMessageBox, QVBoxLayout, QWidget)

from ..presets import describe, export_preset, read_preset_file
from . import icons
from .controls import Chip, FlowRow, button, hline, label
from .theme import T


class PresetManager(QDialog):
    def __init__(self, library, active_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Управление пресетами')
        self.setMinimumSize(760, 480)
        self.library = library
        self.apply_id = None
        self.changed = False
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(16)
        left = QVBoxLayout()
        left.addWidget(label('ВСЕ ПРЕСЕТЫ', 'Eyebrow'))
        self.list = QListWidget()
        self.list.setMinimumWidth(280)
        self.list.setStyleSheet(f'''QListWidget {{ background: {T["panel"]}; border: 1px solid {T["border"]}; border-radius: 10px; padding: 6px; }}
            QListWidget::item {{ padding: 8px 10px; border-radius: 6px; color: {T["text"]}; }}
            QListWidget::item:selected {{ background: rgba(61,139,253,0.18); }}
            QListWidget::item:hover {{ background: {T["hover"]}; }}''')
        self.list.currentItemChanged.connect(self._show)
        self.list.itemDoubleClicked.connect(lambda _: self._apply())
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button('Импорт…', self._import, icon_name='upload'))
        row.addStretch()
        left.addLayout(row)
        outer.addLayout(left, 1)
        right = QVBoxLayout()
        right.setSpacing(8)
        self.name = label('', 'Big')
        self.group = label('', 'Hint')
        self.note = label('', 'Muted', wrap=True)
        self.chips = FlowRow(spacing=4)
        right.addWidget(self.name)
        right.addWidget(self.group)
        right.addWidget(self.note)
        right.addWidget(self.chips)
        right.addWidget(hline())
        self.apply_btn = button('Применить ко всем фото', self._apply, 'Primary', 'check')
        self.rename_btn = button('Переименовать…', self._rename, icon_name='edit')
        self.duplicate_btn = button('Дублировать в «Мои»', self._duplicate, icon_name='copy')
        self.export_btn = button('Экспорт в файл…', self._export, icon_name='download')
        self.delete_btn = button('Удалить…', self._delete, 'Danger', 'trash')
        for b in (self.apply_btn, self.rename_btn, self.duplicate_btn, self.export_btn, self.delete_btn):
            right.addWidget(b)
        right.addWidget(label('Встроенные пресеты не меняются: дублируйте и настраивайте копию. '
                              'Файл пресета можно отправить коллегам — они импортируют его здесь.', 'Hint', wrap=True))
        right.addStretch()
        close = button('Готово', self.accept)
        right.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        outer.addLayout(right, 1)
        self._fill(active_id)

    def _fill(self, select=None):
        self.list.clear()
        group = None
        first = current = None
        for preset in self.library.all():
            if preset.group != group:
                group = preset.group
                header = QListWidgetItem(group.upper())
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                header.setForeground(Qt.GlobalColor.gray)
                self.list.addItem(header)
            item = QListWidgetItem(icons.icon('layers' if preset.builtin else 'star'), preset.name)
            item.setData(Qt.ItemDataRole.UserRole, preset.id)
            self.list.addItem(item)
            first = first or item
            if preset.id == select:
                current = item
        if current or first:
            self.list.setCurrentItem(current or first)

    def _preset(self):
        item = self.list.currentItem()
        pid = item.data(Qt.ItemDataRole.UserRole) if item else None
        return self.library.get(pid) if pid else None

    def _show(self, *_):
        p = self._preset()
        enabled = p is not None
        for b in (self.apply_btn, self.duplicate_btn, self.export_btn):
            b.setEnabled(enabled)
        self.rename_btn.setEnabled(enabled and not p.builtin)
        self.delete_btn.setEnabled(enabled and not p.builtin)
        if not p:
            return
        self.name.setText(p.name)
        self.group.setText(('Встроенный · ' if p.builtin else 'Мой · ') + p.group)
        self.note.setText(p.note)
        self.chips.clear()
        for text in describe(p.settings).split(' · '):
            self.chips.add(Chip(text, 'neutral'))

    def _apply(self):
        p = self._preset()
        if p:
            self.apply_id = p.id
            self.accept()

    def _rename(self):
        p = self._preset()
        if not p or p.builtin:
            return
        name, ok = QInputDialog.getText(self, 'Переименовать пресет', 'Новое название:', text=p.name)
        if ok and name.strip() and name.strip() != p.name:
            try:
                new = self.library.rename(p.id, name)
                self.changed = True
                self._fill(new)
            except Exception as e:
                QMessageBox.warning(self, 'Print Prep', str(e))

    def _duplicate(self):
        p = self._preset()
        if p:
            new = self.library.put(self.library.unique_name(p.name + ' — копия'), p.settings, p.note)
            self.changed = True
            self._fill(new)

    def _delete(self):
        p = self._preset()
        if p and not p.builtin and QMessageBox.question(self, 'Удалить пресет?', f'Удалить «{p.name}»?') == QMessageBox.StandardButton.Yes:
            self.library.delete(p.id)
            self.changed = True
            self._fill()

    def _export(self):
        p = self._preset()
        if not p:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Экспорт пресета', f'{p.name}.printprep.json', 'Пресет Print Prep (*.json)')
        if path:
            export_preset(Path(path), p.name, p.settings, p.note)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Импорт пресета', '', 'Print Prep (*.json)')
        if not path:
            return
        try:
            name, settings, _ = read_preset_file(Path(path))
            name = self.library.unique_name(name) if name in self.library.user else name
            new = self.library.put(name, settings, describe(settings))
            self.changed = True
            self._fill(new)
        except Exception as e:
            QMessageBox.warning(self, 'Print Prep', f'Не удалось импортировать: {e}')
