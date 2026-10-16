from __future__ import annotations

import json
import threading
from dataclasses import asdict, replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QThread, Signal, Qt, QTimer, QRectF, QSettings, QSize, QUrl, QLineF, QCoreApplication, QEvent
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QDesktopServices, QIcon, QShortcut, QKeySequence, QAction
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QFormLayout, QGroupBox, QScrollArea, QListWidget, QListWidgetItem, QSplitter,
    QProgressBar, QMessageBox, QDialog, QDialogButtonBox, QSlider, QSizePolicy, QInputDialog, QStackedWidget, QGridLayout, QButtonGroup, QFrame, QTabWidget, QListView, QAbstractItemView, QMenu)

from .enhance import PRESETS, DEFAULTS, analyze
from .engine import (Settings, Edit, Photo, scan, load_rgb, render, assess, layout, crop_box,
                     oriented, effective_edit, proof, export_batch, adjust, without_enhancements)

from .widgets import Choice as QComboBox, ValueSpin as QSpinBox, DecimalSpin as QDoubleSpinBox, PhotoView, HeightStack
from .theme import STYLE
from . import __version__

BATCH_PRESETS = {
    "original": ("Без уменьшения", "Исходные пиксели · JPEG 95 · sRGB", Settings(size_mode='original')),
    "4k": ("4K · длинная сторона", "3840 px · пропорции сохранены", Settings(size_mode='long_edge', long_edge=3840)),
    "photo_10x15": ("Фото 10 × 15", "Весь кадр · JPEG · sRGB", Settings()),
    "photo_13x18": ("Фото 13 × 18", "Весь кадр · JPEG · sRGB", Settings(width_mm=130, height_mm=180)),
    "photo_20x30": ("Фото 20 × 30", "Крупный отпечаток · JPEG · sRGB", Settings(width_mm=200, height_mm=300)),
    "gentle": ("Мягкое улучшение", "10 × 15 · бережная коррекция света и цвета", Settings(enhancement_preset="balanced", **PRESETS["balanced"][1])),
}



def image_to_qimage(im: Image.Image):
    rgb = im.convert('RGB')
    return QImage(rgb.tobytes(), rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy()


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(True)
    return widget


def button(text, callback, primary=False):
    b = QPushButton(text)
    b.clicked.connect(callback)
    if primary:
        b.setObjectName('primary')
    return b


class PresetCard(QPushButton):
    def __init__(self, title, note):
        super().__init__()
        self.setObjectName('presetCard')
        self.setCheckable(True)
        self.setMinimumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        box = QVBoxLayout(self)
        box.setContentsMargins(21, 17, 21, 17)
        box.setSpacing(7)
        for text, name in ((title, 'cardTitle'), (note, 'cardNote')):
            widget = label(text, name)
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            box.addWidget(widget)
        self.setAccessibleName(title + '. ' + note)


class Task(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, int, object)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception as e:
            self.error.emit(str(e))


class Disclosure(QWidget):
    def __init__(self, title):
        super().__init__()
        self.title = title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.toggle = QPushButton('▸ ' + title)
        self.toggle.setCheckable(True)
        self.toggle.setStyleSheet('text-align: left; padding: 8px;')
        self.body = QWidget()
        self.body.setVisible(False)
        self.toggle.toggled.connect(self.set_open)
        outer.addWidget(self.toggle)
        outer.addWidget(self.body)

    def set_open(self, opened):
        self.toggle.setChecked(opened)
        self.toggle.setText(('▾ ' if opened else '▸ ') + self.title)
        self.body.setVisible(opened)


Preview = PhotoView


class CropCanvas(QWidget):
    changed = Signal(float, float)
    gesture_started = Signal()

    def __init__(self, im, settings, edit):
        super().__init__()
        self.im = im
        self.settings = settings
        self.edit = edit
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.drag = None
        self.rect = QRectF()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.contentsRect(), QColor('#0c1017'))
        pix = QPixmap.fromImage(image_to_qimage(self.im))
        scale = min((self.width() - 32) / pix.width(), (self.height() - 32) / pix.height())
        w, h = pix.width() * scale, pix.height() * scale
        self.rect = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        painter.drawPixmap(self.rect, pix, QRectF(pix.rect()))
        _, inner, _ = layout(self.im.size, self.settings)
        box = crop_box(self.im.size, inner[0] / inner[1], self.edit)
        x, y = self.rect.x(), self.rect.y()
        r = QRectF(x + box[0] * scale, y + box[1] * scale, (box[2] - box[0]) * scale, (box[3] - box[1]) * scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRect(QRectF(x, y, w, r.top() - y))
        painter.drawRect(QRectF(x, r.bottom(), w, y + h - r.bottom()))
        painter.drawRect(QRectF(x, r.top(), r.left() - x, r.height()))
        painter.drawRect(QRectF(r.right(), r.top(), x + w - r.right(), r.height()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor('#a1efd0'), 2))
        painter.drawRect(r)
        painter.setPen(QPen(QColor(255, 255, 255, 110), 1))
        for frac in (1 / 3, 2 / 3):
            painter.drawLine(QLineF(r.left() + frac * r.width(), r.top(), r.left() + frac * r.width(), r.bottom()))
            painter.drawLine(QLineF(r.left(), r.top() + frac * r.height(), r.right(), r.top() + frac * r.height()))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect.contains(event.position()):
            self.gesture_started.emit()
            self.drag = event.position(), self.edit.center_x, self.edit.center_y
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self.drag:
            pos, x, y = self.drag
            self.edit.center_x = min(1, max(0, x + (event.position().x() - pos.x()) / self.rect.width()))
            self.edit.center_y = min(1, max(0, y + (event.position().y() - pos.y()) / self.rect.height()))
            self.edit.manual_crop = True
            self.changed.emit(self.edit.center_x, self.edit.center_y)
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag = None
        self.unsetCursor()


class CropDialog(QDialog):
    """Transactional photo editor. Exact background render, responsive controls."""
    def __init__(self, im, settings, edit, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Print Prep · Снимок и живой предпросмотр')
        screen = self.screen().availableGeometry()
        self.resize(min(1240, max(820, screen.width() - 40)), min(850, max(580, screen.height() - 45)))
        self.base = im
        self.frame_base = im.copy()
        self.frame_base.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        self.settings = replace(settings)
        crop_settings = replace(settings, fit='cover')
        self.edit = effective_edit(oriented(im, edit), crop_settings, replace(edit))
        self.undo_stack = []
        self.live_worker = None
        self.live_pending = False
        self.live_version = 0
        self._closing_code = None
        self.last_result = None
        self.last_before = None
        self._before_cache = None
        self.live_timer = QTimer(self)
        self.live_timer.setSingleShot(True)
        self.live_timer.setInterval(100)
        self.live_timer.timeout.connect(self.start_live_preview)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        heading = QHBoxLayout()
        heading.addWidget(label('Снимок: кадр и коррекция', 'title'), 1)
        self.undo_btn = button('Отменить правку', self.undo)
        self.undo_btn.setEnabled(False)
        heading.addWidget(self.undo_btn)
        outer.addLayout(heading)
        split = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 10, 0)
        toolbar = QHBoxLayout()
        self.view_mode = QComboBox()
        self.view_mode.addItem('Результат', 0)
        self.view_mode.addItem('Кадрирование · перетащите рамку', 1)
        self.before_check = QCheckBox('Без улучшений')
        self.before_check.toggled.connect(self.display_live_result)
        self.zoom_view = QComboBox()
        self.zoom_view.addItem('Вписать', 'fit')
        self.zoom_view.addItem('100%', 1.)
        self.zoom_view.addItem('200%', 2.)
        toolbar.addWidget(self.view_mode, 1)
        toolbar.addWidget(self.before_check)
        toolbar.addWidget(self.zoom_view)
        left_layout.addLayout(toolbar)
        self.images = QStackedWidget()
        self.result_view = Preview()
        self.canvas = CropCanvas(oriented(self.frame_base, self.edit), crop_settings, self.edit)
        self.canvas.gesture_started.connect(self.checkpoint)
        self.canvas.changed.connect(self.frame_moved)
        self.images.addWidget(self.result_view)
        self.images.addWidget(self.canvas)
        self.view_mode.currentIndexChanged.connect(lambda: self.images.setCurrentIndex(self.view_mode.currentData()))
        self.zoom_view.currentIndexChanged.connect(lambda: self.result_view.set_zoom(self.zoom_view.currentData()))
        left_layout.addWidget(self.images, 1)
        self.live_status = label('Рассчитываем точный результат…', 'muted')
        self.live_status.setWordWrap(True)
        left_layout.addWidget(self.live_status)
        split.addWidget(left)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setMinimumWidth(265)
        right_scroll.setMaximumWidth(340)
        right = QWidget()
        right.setObjectName('shell')
        controls = QVBoxLayout(right)
        controls.setContentsMargins(8, 0, 8, 0)
        controls.addWidget(label('ТОЛЬКО ЭТОТ СНИМОК', 'eyebrow'))
        turns = QHBoxLayout()
        turns.addWidget(button('↶ 90°', lambda: self.rotate(-90)))
        turns.addWidget(button('↷ 90°', lambda: self.rotate(90)))
        controls.addLayout(turns)
        controls.addWidget(label('Приближение кадра'))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(100, 500)
        self.zoom.setValue(round(self.edit.zoom * 100))
        self.zoom.sliderPressed.connect(self.checkpoint)
        self.zoom.valueChanged.connect(self.set_zoom)
        controls.addWidget(self.zoom)
        controls.addWidget(label('Изменение рамки включает обрезку для этого снимка. «100%» сверху меняет только масштаб просмотра.', 'muted'))
        self.sliders = {}
        self.value_labels = {}
        for key, title, low, high in [('exposure', 'Экспозиция, EV', -200, 200),
                                      ('contrast', 'Контраст', 50, 150), ('saturation', 'Насыщенность', 0, 150)]:
            row = QHBoxLayout()
            row.addWidget(label(title), 1)
            value = label(f'{getattr(self.edit, key):.2f}')
            self.value_labels[key] = value
            row.addWidget(value)
            controls.addLayout(row)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(low, high)
            slider.setValue(round(getattr(self.edit, key) * 100))
            slider.sliderPressed.connect(self.checkpoint)
            slider.valueChanged.connect(lambda v, k=key: self.change_value(k, v))
            self.sliders[key] = slider
            controls.addWidget(slider)
        self.neural_check = QCheckBox('Нейро ×2 для этого снимка')
        self.neural_check.setChecked(self.edit.use_neural if self.edit.use_neural is not None else settings.upscaler == 'fsrcnn')
        self.neural_check.toggled.connect(self.change_neural)
        controls.addSpacing(12)
        controls.addWidget(self.neural_check)
        self.neural_amount = QSlider(Qt.Orientation.Horizontal)
        self.neural_amount.setRange(0, 100)
        self.neural_amount.setValue(round((self.edit.neural_strength if self.edit.neural_strength is not None else settings.neural_strength) * 100))
        self.neural_amount.sliderPressed.connect(self.checkpoint)
        self.neural_amount.valueChanged.connect(self.change_neural_strength)
        controls.addWidget(self.neural_amount)
        controls.addWidget(label('Нейро ×2 работает только при увеличении. Отключите флажок, чтобы убрать его для этого фото. Сравнивайте при 100%.', 'muted'))
        controls.addStretch()
        controls.addWidget(button('Сбросить правки снимка', self.reset))
        right_scroll.setWidget(right)
        split.addWidget(right_scroll)
        split.setSizes([850, 290])
        outer.addWidget(split, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Применить к снимку')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена · вернуться без изменений')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo)
        self.queue_live_preview()

    def checkpoint(self):
        if not self.undo_stack or self.undo_stack[-1] != self.edit:
            self.undo_stack.append(replace(self.edit))
            self.undo_stack = self.undo_stack[-30:]
        self.undo_btn.setEnabled(bool(self.undo_stack))

    def sync_edit_controls(self):
        for key, slider in self.sliders.items():
            slider.blockSignals(True)
            slider.setValue(round(getattr(self.edit, key) * 100))
            slider.blockSignals(False)
            self.value_labels[key].setText(f'{getattr(self.edit, key):.2f}')
        for control, value in ((self.zoom, round(self.edit.zoom * 100)),
                               (self.neural_amount, round((self.edit.neural_strength if self.edit.neural_strength is not None else self.settings.neural_strength) * 100))):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self.neural_check.blockSignals(True)
        self.neural_check.setChecked(self.edit.use_neural if self.edit.use_neural is not None else self.settings.upscaler == 'fsrcnn')
        self.neural_check.blockSignals(False)
        self.canvas.edit = self.edit
        self.canvas.im = oriented(self.frame_base, self.edit)
        self.canvas.update()

    def undo(self):
        if self.undo_stack:
            self.edit = self.undo_stack.pop()
            self.sync_edit_controls()
            self.undo_btn.setEnabled(bool(self.undo_stack))
            self.queue_live_preview()

    def change_value(self, key, value):
        if not self.sliders[key].isSliderDown():
            self.checkpoint()
        setattr(self.edit, key, value / 100)
        self.value_labels[key].setText(f'{value / 100:.2f}')
        self.queue_live_preview()

    def change_neural(self, checked):
        self.checkpoint()
        self.edit.use_neural = checked
        self.queue_live_preview()

    def change_neural_strength(self, value):
        if not self.neural_amount.isSliderDown():
            self.checkpoint()
        self.edit.neural_strength = value / 100
        self.queue_live_preview()

    def frame_moved(self, *_):
        self.edit.fit = 'cover'
        self.queue_live_preview()

    def set_zoom(self, value):
        if not self.zoom.isSliderDown():
            self.checkpoint()
        self.edit.zoom = value / 100
        self.edit.manual_crop = True
        self.edit.fit = 'cover'
        self.canvas.update()
        self.queue_live_preview()

    def rotate(self, value):
        self.checkpoint()
        self.edit.rotation = (self.edit.rotation + value) % 360
        self.edit.center_x = self.edit.center_y = .5
        self.edit.manual_crop = True
        self.canvas.im = oriented(self.frame_base, self.edit)
        self.canvas.update()
        self.queue_live_preview()

    def reset(self):
        self.checkpoint()
        self.edit = Edit()
        self.sync_edit_controls()
        self.queue_live_preview()

    def queue_live_preview(self):
        if self._closing_code is not None:
            return
        self.live_version += 1
        self.live_status.setText('Обновляем результат…')
        self.live_timer.start()

    def start_live_preview(self):
        if self._closing_code is not None:
            return
        if self.live_worker and self.live_worker.isRunning():
            self.live_pending = True
            return
        self.live_pending = False
        version = self.live_version
        edit = replace(self.edit)
        settings = replace(self.settings)
        geometry = (edit.rotation, edit.center_x, edit.center_y, edit.zoom, edit.fit, edit.manual_crop)
        cache = self._before_cache
        def work():
            notes = []
            result = render(self.base, settings, edit, notes=notes)
            if cache and cache[0] == geometry:
                before = cache[1]
            else:
                baseline_edit = replace(edit, exposure=0, contrast=1, saturation=1, use_neural=False, neural_strength=0)
                before = render(self.base, without_enhancements(settings), baseline_edit)
            full = adjust(oriented(self.frame_base, edit), settings, edit)
            return result, before, full, notes, geometry
        self.live_worker = Task(work, self)
        self.live_worker.result.connect(lambda result: self.live_ready(version, result))
        self.live_worker.error.connect(lambda error: self.live_error(version, error))
        self.live_worker.finished.connect(self.live_finished)
        self.live_worker.start()

    def live_ready(self, version, result):
        if version != self.live_version or self._closing_code is not None:
            return
        self.last_result, self.last_before, full, notes, geometry = result
        self._before_cache = geometry, self.last_before
        self.canvas.im = full
        self.canvas.update()
        self.display_live_result()
        self.live_status.setText(f'Точный расчёт: {self.last_result.width} × {self.last_result.height} px · рабочий sRGB. ' + ' '.join(notes))

    def display_live_result(self, *_):
        image = self.last_before if self.before_check.isChecked() else self.last_result
        if image is not None:
            self.result_view.set_image(image)

    def live_error(self, version, error):
        if version == self.live_version:
            self.live_status.setText(error)

    def live_finished(self):
        if self._closing_code is not None:
            super().done(self._closing_code)
        elif self.live_pending:
            self.live_timer.start(10)

    def done(self, code):
        self.live_timer.stop()
        self.live_pending = False
        self.live_version += 1
        self._closing_code = code
        if self.live_worker and self.live_worker.isRunning():
            self.buttons.setEnabled(False)
            self.live_status.setText('Завершаем текущий расчёт…')
        else:
            super().done(code)

    def closeEvent(self, event):
        if self.live_worker and self.live_worker.isRunning():
            self.done(QDialog.DialogCode.Rejected)
            event.ignore()
        else:
            self.live_timer.stop()
            event.accept()



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'Print Prep {__version__} — подготовка фотографий к печати')
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'assets' / 'printprep.png')))
        available = self.screen().availableGeometry()
        self.setMinimumSize(900, 600)
        self.resize(min(1280, max(900, available.width() - 40)), min(900, max(600, available.height() - 50)))
        self.setAcceptDrops(True)
        self.folder = None
        self.active_preset_key = None
        self._applying = False
        self._source_cache = None
        self.photos = []
        self.edits = {}
        self.last_output = None
        self.worker = None
        self.preview_worker = None
        self.preview_pending = False
        self.preview_version = 0
        self.cancel_event = threading.Event()
        self.store = QSettings('PrintPrep', 'PrintPrep')
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.start_preview)
        self.summary_timer = QTimer(self)
        self.summary_timer.setSingleShot(True)
        self.summary_timer.setInterval(120)
        self.summary_timer.timeout.connect(self.refresh_batch_summary)
        self._build()
        self.apply_settings(Settings(size_mode='original'))
        self.active_preset_key = 'builtin:original'
        self.refresh_library()
        try:
            saved = self.store.value('settings')
            if saved:
                self.apply_settings(Settings(**json.loads(saved)))
                self.active_preset_key = self.store.value('active_preset', None)
                self.refresh_library()
        except (TypeError, ValueError):
            pass

    def _build(self):
        self.mode = 'welcome'
        self.busy = False
        self.operation = None
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle('Print Prep · Настройки всей партии')
        self.settings_dialog.resize(min(1120, max(760, self.screen().availableGeometry().width() - 50)), min(820, max(540, self.screen().availableGeometry().height() - 60)))
        self.recursive = QCheckBox('Искать также во вложенных папках')
        self._build_settings()
        settings_layout = QVBoxLayout(self.settings_dialog)
        settings_layout.setContentsMargins(20, 16, 20, 16)
        self.settings_title = label('Изменить пресет', 'title')
        settings_layout.addWidget(self.settings_title)
        settings_layout.addWidget(label('Эти параметры применятся ко всей папке. Индивидуальные кадры сохранятся.', 'muted'))
        settings_body = QSplitter()
        settings_body.addWidget(self.settings_scroll)
        settings_right = QWidget()
        settings_right_layout = QVBoxLayout(settings_right)
        self.settings_compare = QCheckBox('Без улучшений')
        self.settings_compare.toggled.connect(self.schedule_preview)
        compare_row = QHBoxLayout()
        compare_row.addWidget(self.settings_compare)
        self.settings_proof = QCheckBox('ICC-проба')
        self.settings_proof.setChecked(True)
        self.settings_proof.toggled.connect(self.schedule_preview)
        compare_row.addWidget(self.settings_proof)
        compare_row.addStretch()
        settings_right_layout.addLayout(compare_row)
        self.settings_preview = Preview()
        settings_right_layout.addWidget(self.settings_preview, 1)
        self.settings_preview_status = label('Предпросмотр выбранного снимка', 'muted')
        self.settings_preview_status.setFixedHeight(72)
        settings_right_layout.addWidget(self.settings_preview_status)
        settings_body.addWidget(settings_right)
        settings_body.setSizes([440, 600])
        settings_layout.addWidget(settings_body, 1)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('Применить к партии')
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена · вернуться')
        self.settings_save_btn = controls.addButton('Сохранить в мой пресет', QDialogButtonBox.ButtonRole.ActionRole)
        self.settings_save_btn.clicked.connect(self.save_settings_preset)
        controls.accepted.connect(self.accept_settings)
        controls.rejected.connect(self.settings_dialog.reject)
        settings_layout.addWidget(controls)
        root = QWidget()
        root.setObjectName('shell')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame()
        header.setObjectName('header')
        hl = QHBoxLayout(header)
        hl.setContentsMargins(30, 19, 30, 19)
        mark = label('▧')
        mark.setStyleSheet('color: #39794f; font-size: 30px; font-weight: 700;')
        hl.addWidget(mark)
        hl.addWidget(label('Print Prep', 'brand'))
        hl.addSpacing(20)
        hl.addWidget(label('Подготовка фотографий к печати', 'muted'), 1)
        badge = label('Локальная обработка', 'tag')
        badge.setWordWrap(False)
        hl.addWidget(badge)
        hl.addSpacing(12)
        hl.addWidget(button('Справка', self.help))
        outer.addWidget(header)
        middle = QHBoxLayout()
        middle.setSpacing(0)
        self.rail = QFrame()
        self.rail.setObjectName('rail')
        self.rail.setFixedWidth(195)
        rl = QVBoxLayout(self.rail)
        rl.setContentsMargins(25, 36, 20, 24)
        rl.addWidget(label('ВАША ПАРТИЯ', 'eyebrow'))
        rl.addSpacing(20)
        self.step_labels = []
        for title, note in [('01  Папка', 'Соберите фотографии'), ('02  Пресет', 'Один для всей партии'), ('03  Результат', 'Готовые копии рядом')]:
            step = button(title, lambda checked=False, n=len(self.step_labels): self.navigate(n))
            step.setObjectName('railStep')
            self.step_labels.append(step)
            rl.addWidget(step)
            rl.addWidget(label(note, 'muted'))
            rl.addSpacing(26)
        rl.addStretch()
        rl.addWidget(label('Оригиналы остаются\nбез изменений.', 'muted'))
        middle.addWidget(self.rail)
        self.pages = QStackedWidget()
        middle.addWidget(self.pages, 1)
        outer.addLayout(middle, 1)
        self.welcome_page = QWidget()
        welcome_outer = QVBoxLayout(self.welcome_page)
        welcome_outer.setContentsMargins(0, 0, 0, 0)
        self.welcome_scroll = QScrollArea()
        self.welcome_scroll.setWidgetResizable(True)
        self.welcome_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        welcome_content = QWidget()
        welcome_content.setObjectName('shell')
        self.welcome_scroll.setWidget(welcome_content)
        welcome_outer.addWidget(self.welcome_scroll)
        wl = QVBoxLayout(welcome_content)
        wl.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        wl.setContentsMargins(64, 30, 64, 30)
        wl.addStretch()
        wl.addWidget(label('ОДНА ПАПКА. ОДИН ПРЕСЕТ.', 'eyebrow'))
        wl.addSpacing(10)
        wl.addWidget(label('Подготовьте фотографии\nк печати за один проход.', 'hero'))
        wl.addSpacing(10)
        wl.addWidget(label('Откройте папку, выберите готовый пресет и запустите обработку.\nЕсли нужно — сначала просмотрите и подгоните отдельные кадры.', 'muted'))
        wl.addSpacing(26)
        drop = QFrame()
        drop.setObjectName('dropzone')
        dl = QVBoxLayout(drop)
        dl.setContentsMargins(35, 25, 35, 25)
        folder_icon = label('▱')
        folder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        folder_icon.setStyleSheet('font-size: 58px; color: #82a579;')
        dl.addWidget(folder_icon)
        drop_title = label('Перетащите сюда папку с фотографиями', 'title')
        drop_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(drop_title)
        types = label('JPEG, TIFF, PNG, WebP и BMP', 'muted')
        types.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(types)
        dl.addSpacing(12)
        self.open_btn = button('Выбрать папку', self.choose_folder, True)
        self.open_btn.setMinimumWidth(210)
        dl.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        dl.addWidget(self.recursive, 0, Qt.AlignmentFlag.AlignHCenter)
        wl.addWidget(drop)
        self.welcome_feedback = label('', 'muted')
        wl.addWidget(self.welcome_feedback)
        wl.addStretch()
        wl.addWidget(label('Готовые файлы появятся в новой подпапке внутри выбранной папки.', 'muted'))
        self.pages.addWidget(self.welcome_page)
        self.batch_page = QWidget()
        batch_outer = QVBoxLayout(self.batch_page)
        batch_outer.setContentsMargins(0, 0, 0, 0)
        self.batch_scroll = QScrollArea()
        self.batch_scroll.setWidgetResizable(True)
        self.batch_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.batch_content = QWidget()
        self.batch_content.setObjectName('shell')
        self.batch_scroll.setWidget(self.batch_content)
        batch_outer.addWidget(self.batch_scroll)
        bl = QVBoxLayout(self.batch_content)
        bl.setSizeConstraint(QVBoxLayout.SizeConstraint.SetMinimumSize)
        bl.setContentsMargins(42, 26, 42, 22)
        bl.setSpacing(16)
        bl.addWidget(label('ПРЕСЕТ ДЛЯ ВСЕЙ ПАПКИ', 'eyebrow'))
        bl.addWidget(label('Выберите, как подготовить фотографии', 'title'))
        folder_card = QFrame()
        folder_card.setObjectName('card')
        fc = QHBoxLayout(folder_card)
        fc.setContentsMargins(21, 16, 21, 16)
        folder_text = QVBoxLayout()
        self.batch_count = label('0 фотографий', 'metric')
        self.folder_label = label('', 'muted')
        folder_text.addWidget(self.batch_count)
        folder_text.addWidget(self.folder_label)
        fc.addLayout(folder_text, 1)
        self.change_folder_btn = button('Другая папка', self.choose_folder)
        fc.addWidget(self.change_folder_btn)
        self.rescan_btn = button('↻', self.rescan)
        self.rescan_btn.setToolTip('Обновить список файлов в выбранной папке')
        fc.addWidget(self.rescan_btn)
        bl.addWidget(folder_card)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.batch_cards = {}
        self.card_group = QButtonGroup(self)
        self.card_group.setExclusive(True)
        for i, key in enumerate(('original', 'photo_10x15', '4k', 'gentle')):
            name, note, settings = BATCH_PRESETS[key]
            card = PresetCard(name, note)
            card.clicked.connect(lambda checked, k=key: self.choose_batch_preset(k))
            self.card_group.addButton(card)
            self.batch_cards[key] = card
            grid.addWidget(card, i // 2, i % 2)
        bl.addLayout(grid)
        bl.addWidget(label('ВЫБРАННЫЙ ПРЕСЕТ', 'eyebrow'))
        mine = QHBoxLayout()
        mine.addWidget(self.recipe_library, 1)
        self.tune_btn = button('Изменить…', self.open_settings)
        mine.addWidget(self.tune_btn)
        bl.addLayout(mine)
        preset_actions = QHBoxLayout()
        self.update_preset_btn = button('Сохранить изменения', self.update_library)
        preset_actions.addWidget(self.update_preset_btn)
        preset_actions.addWidget(button('Сохранить как новый…', self.save_library))
        preset_actions.addStretch()
        menu_button = button('Ещё…', lambda: None)
        self.preset_menu = QMenu(menu_button)
        self.rename_preset_action = self.preset_menu.addAction('Переименовать выбранный…', self.rename_library)
        self.preset_menu.addAction('Удалить свой пресет…', self.delete_library)
        self.preset_menu.addSeparator()
        self.preset_menu.addAction('Экспортировать рецепт…', self.save_recipe)
        self.preset_menu.addAction('Импортировать рецепт…', self.load_recipe)
        menu_button.setMenu(self.preset_menu)
        preset_actions.addWidget(menu_button)
        bl.addLayout(preset_actions)
        summary_card = QFrame()
        summary_card.setObjectName('card')
        sc = QVBoxLayout(summary_card)
        sc.setContentsMargins(20, 15, 20, 15)
        self.batch_summary = label('')
        self.batch_summary.setStyleSheet('font-weight: 600; color: #3e5945;')
        sc.addWidget(self.batch_summary)
        self.batch_warnings = label('', 'muted')
        sc.addWidget(self.batch_warnings)
        bl.addWidget(summary_card)
        bl.addStretch()
        batch_tools = QHBoxLayout()
        batch_tools.addWidget(button('Проверить партию', self.preflight))
        batch_tools.addWidget(button('Загрузить рецепт…', self.load_recipe))
        batch_tools.addStretch()
        batch_tools.addWidget(label('Каждый запуск создаёт новую папку с результатами.', 'muted'))
        bl.addLayout(batch_tools)
        self.pages.addWidget(self.batch_page)
        self._build_review()
        self.pages.addWidget(self.review_page)
        self.progress_page = QWidget()
        pl = QVBoxLayout(self.progress_page)
        pl.setContentsMargins(70, 40, 70, 40)
        pl.addStretch()
        pl.addWidget(label('PRINT PREP РАБОТАЕТ', 'eyebrow'))
        self.progress_title = label('Готовим фотографии к печати', 'hero')
        pl.addWidget(self.progress_title)
        pl.addSpacing(16)
        self.progress_detail = label('Чтение файлов…', 'muted')
        pl.addWidget(self.progress_detail)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(10)
        pl.addWidget(self.progress)
        pl.addSpacing(15)
        self.cancel_btn = button('Остановить после текущего файла', self.cancel)
        pl.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignLeft)
        pl.addWidget(label('Окно можно оставить открытым. Готовые файлы сохранятся даже при остановке.', 'muted'))
        pl.addStretch()
        self.pages.addWidget(self.progress_page)
        self.done_page = QWidget()
        done = QVBoxLayout(self.done_page)
        done.setContentsMargins(64, 40, 64, 40)
        done.addStretch()
        done.addWidget(label('ГОТОВО', 'eyebrow'))
        self.done_title = label('Фотографии подготовлены', 'hero')
        done.addWidget(self.done_title)
        self.done_summary = label('', 'title')
        done.addWidget(self.done_summary)
        self.done_path = label('', 'muted')
        done.addWidget(self.done_path)
        done.addSpacing(24)
        self.output_btn = button('Открыть папку с результатами', self.open_output, True)
        self.output_btn.setEnabled(False)
        done.addWidget(self.output_btn, 0, Qt.AlignmentFlag.AlignLeft)
        done.addSpacing(10)
        done.addWidget(button('Вернуться к партии', self.show_batch), 0, Qt.AlignmentFlag.AlignLeft)
        done.addWidget(button('Выбрать другую папку', self.choose_folder), 0, Qt.AlignmentFlag.AlignLeft)
        done.addStretch()
        done.addWidget(label('Оригиналы сохранены. Подробности обработки — в report.csv и report.json.', 'muted'))
        self.pages.addWidget(self.done_page)
        self.action_bar = QFrame()
        self.action_bar.setObjectName('actionbar')
        al = QHBoxLayout(self.action_bar)
        al.setContentsMargins(28, 17, 28, 17)
        self.status = label('Выберите папку с фотографиями.', 'muted')
        al.addWidget(self.status, 1)
        self.review_btn = button('Просмотреть и подогнать', self.toggle_review)
        al.addWidget(self.review_btn)
        self.export_btn = button('Подготовить к печати →', self.export, True)
        self.export_btn.setEnabled(False)
        al.addWidget(self.export_btn)
        outer.addWidget(self.action_bar)
        self.action_bar.setVisible(False)
        self.preset.currentIndexChanged.connect(self.preset_changed)
        for widget in (self.width, self.height, self.border, self.dpi, self.quality):
            widget.valueChanged.connect(self.schedule_preview)
        for widget in (self.fit, self.background, self.space, self.intent, self.format):
            widget.currentIndexChanged.connect(self.schedule_preview)
        for widget in (self.auto_orientation, self.smart, self.enhance, self.sharpen, self.upscale):
            widget.toggled.connect(self.schedule_preview)
        self.show_page('welcome')
        self.selection_changed()

    def _build_review(self):
        self.review_page = QWidget()
        out = QVBoxLayout(self.review_page)
        out.setContentsMargins(30, 22, 30, 18)
        row = QHBoxLayout()
        row.addWidget(label('Просмотрите только то, что нужно', 'title'), 1)
        row.addWidget(button('Настройки партии…', self.open_settings))
        out.addLayout(row)
        self.review_splitter = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.count_label = label('Фотографии', 'muted')
        ll.addWidget(self.count_label)
        self.list = QListWidget()
        self.list.setIconSize(QSize(64, 64))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.currentRowChanged.connect(self.selection_changed)
        self.list.itemDoubleClicked.connect(lambda _: self.edit_photo())
        ll.addWidget(self.list)
        self.edit_btn = button('Кадр и коррекция…', self.edit_photo)
        self.reset_btn = button('Сбросить правку', self.reset_photo)
        ll.addWidget(self.edit_btn)
        ll.addWidget(self.reset_btn)
        self.review_splitter.addWidget(left)
        right = QWidget()
        rr = QVBoxLayout(right)
        rr.setContentsMargins(10, 0, 0, 0)
        toggles = QHBoxLayout()
        self.original_check = QCheckBox('Без улучшений')
        self.proof_check = QCheckBox('ICC-проба')
        self.proof_check.setToolTip('Приближённая ICC-проба в sRGB; не заменяет пробный отпечаток.')
        self.original_check.toggled.connect(self.schedule_preview)
        self.proof_check.toggled.connect(self.schedule_preview)
        toggles.addWidget(self.original_check)
        toggles.addWidget(self.proof_check)
        toggles.addStretch()
        self.preview_zoom = QComboBox()
        self.preview_zoom.addItem('Вписать', 'fit')
        self.preview_zoom.addItem('100% · пиксель в пиксель', 1.)
        self.preview_zoom.addItem('200%', 2.)
        self.preview_zoom.currentIndexChanged.connect(lambda: self.preview.set_zoom(self.preview_zoom.currentData()))
        toggles.addWidget(self.preview_zoom)
        rr.addLayout(toggles)
        self.preview = Preview()
        rr.addWidget(self.preview, 1)
        self.photo_title = label('Выберите фотографию')
        self.photo_title.setStyleSheet('font-weight: 650; font-size: 17px;')
        rr.addWidget(self.photo_title)
        self.info = label('', 'muted')
        rr.addWidget(self.info)
        self.warning = label('')
        self.warning.setStyleSheet('color: #946c2a; font-size: 12px;')
        rr.addWidget(self.warning)
        self.review_splitter.addWidget(right)
        self.review_splitter.setSizes([230, 690])
        out.addWidget(self.review_splitter, 1)

    def show_page(self, mode):
        self.mode = mode
        page = {'welcome': self.welcome_page, 'batch': self.batch_page, 'review': self.review_page,
                'progress': self.progress_page, 'done': self.done_page}[mode]
        self.pages.setCurrentWidget(page)
        self.action_bar.setVisible(mode in ('batch', 'review'))
        self.review_btn.setText('← Вернуться к пресетам' if mode == 'review' else 'Просмотреть и подогнать')
        step = 0 if mode == 'welcome' or (mode == 'progress' and self.operation == 'scan') else 2 if mode == 'done' else 1
        for i, widget in enumerate(self.step_labels):
            widget.setStyleSheet(f'text-align: left; border: none; background: transparent; padding: 0; font-size: 14px; font-weight: {700 if i == step else 500}; color: {"#245e45" if i == step else "#99a395"};')

    def navigate(self, step):
        if self.busy:
            return
        if step == 0:
            self.timer.stop()
            self.preview_version += 1
            self.preview_pending = False
            self.show_page('welcome')
        elif step == 1 and self.photos:
            self.show_batch()
        elif step == 2 and self.last_output:
            self.show_page('done')

    def show_batch(self):
        self.timer.stop()
        self.preview_version += 1
        self.preview_pending = False
        self.show_page('batch' if self.photos else 'welcome')
        self.refresh_batch_summary()

    def show_review(self):
        if not self.photos or self.busy:
            return
        self.show_page('review')
        if self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        else:
            self.schedule_preview()

    def toggle_review(self):
        self.show_batch() if self.mode == 'review' else self.show_review()

    def open_settings(self):
        before = self.settings()
        active_before = self.active_preset_key
        self.settings_title.setText('Изменить · ' + self.preset_name())
        self.timer.start(0)
        if self.settings_dialog.exec() != QDialog.DialogCode.Accepted:
            self.active_preset_key = active_before
            self.apply_settings(before)
        self.refresh_batch_summary()

    def accept_settings(self):
        try:
            self.settings().validate()
        except Exception as e:
            self.error(str(e))
            return
        self.settings_dialog.accept()

    def choose_batch_preset(self, key):
        self.active_preset_key = 'builtin:' + key
        self.apply_settings(replace(BATCH_PRESETS[key][2]))
        self.refresh_library()
        self.refresh_batch_summary()
        self.status.setText('Пресет применится ко всем фотографиям. Можно сразу запускать.')

    def refresh_batch_summary(self):
        if not hasattr(self, 'batch_summary'):
            return
        s = self.settings()
        if self.preset_snapshot(self.active_preset_key) is None:
            self.active_preset_key = next(('builtin:' + key for key, value in BATCH_PRESETS.items() if s == value[2]), None)
        baseline = self.preset_snapshot(self.active_preset_key)
        dirty = baseline is not None and s != baseline
        self.card_group.setExclusive(False)
        for key, card in self.batch_cards.items():
            card.setChecked(self.active_preset_key == 'builtin:' + key)
        self.card_group.setExclusive(True)
        self.recipe_library.blockSignals(True)
        for i in range(self.recipe_library.count()):
            key = self.recipe_library.itemData(i)
            if key and key.startswith('builtin:'):
                name = BATCH_PRESETS[key[8:]][0]
            elif key:
                name = 'Мой · ' + key
            else:
                continue
            self.recipe_library.setItemText(i, name + (' · изменён' if dirty and key == self.active_preset_key else ''))
        self.recipe_library.setCurrentIndex(max(0, self.recipe_library.findData(self.active_preset_key)))
        self.recipe_library.blockSignals(False)
        self.update_preset_btn.setEnabled(dirty)
        own = self.active_preset_key and not self.active_preset_key.startswith('builtin:')
        self.update_preset_btn.setText('Сохранить изменения' if own else 'Сохранить копию…')
        self.rename_preset_action.setEnabled(bool(own))
        name = self.preset_name() + (' · есть несохранённые изменения' if dirty else '')
        self.settings_title.setText('Изменить · ' + name)
        self.settings_save_btn.setText('Сохранить изменения в пресет' if own else 'Сохранить как новый…')
        if s.size_mode == 'original':
            dimensions = 'исходное разрешение · без уменьшения'
        elif s.size_mode == 'long_edge':
            dimensions = f'{s.long_edge} px по длинной стороне'
        elif s.size_mode == 'pixels':
            dimensions = f'{s.pixel_width} × {s.pixel_height} px'
        else:
            dimensions = f'{s.width_mm:g} × {s.height_mm:g} мм · {s.dpi} PPI'
        place = 'весь кадр, возможны поля' if s.fit == 'contain' else 'заполнение с обрезкой'
        color = 'sRGB' if s.output_space == 'sRGB' else f'ICC: {Path(s.icc_path).name or "не выбран"}'
        self.batch_summary.setText(f'{name}\n{dimensions} · {place} · {s.format} · {color}')
        try:
            s.validate()
        except Exception as e:
            self.batch_warnings.setText(str(e))
            return
        low = crop = down = 0
        for photo in self.photos:
            info = assess(photo.size, s, self.edits.get(str(photo.path), Edit()))
            low += info['ppi'] < 240
            crop += info['crop_percent'] > 15
            down += info['downscale']
        notes = []
        if down:
            notes.append(f'Будут уменьшены: {down}. Для сохранения деталей выберите «Без уменьшения».')
        if low:
            notes.append(f'Ниже 240 PPI: {low}')
        if crop:
            notes.append(f'Проверьте обрезку: {crop}')
        if self.edits:
            notes.append(f'Индивидуальных правок: {sum(str(p.path) in self.edits for p in self.photos)}')
        self.batch_warnings.setText('  ·  '.join(notes) if notes else 'Всё готово к запуску. Оригиналы останутся без изменений.')
        self.batch_count.setText(f'{len(self.photos)} фото в партии')
        self.export_btn.setText(f'Подготовить {len(self.photos)} фото →')

    def _build_settings(self):
        self.settings_scroll = QTabWidget()
        self.settings_scroll.setDocumentMode(True)
        def page(title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            body = QWidget()
            body.setObjectName('shell')
            box = QVBoxLayout(body)
            box.setContentsMargins(12, 18, 12, 14)
            box.setSpacing(14)
            scroll.setWidget(body)
            self.settings_scroll.addTab(scroll, title)
            return box
        size_page = page('Размер')
        self.size_mode = QComboBox()
        for title, key in [('Без уменьшения · исходные пиксели', 'original'), ('Печатный размер · миллиметры', 'print'),
                           ('Точный размер · пиксели', 'pixels'), ('Длинная сторона · пропорции сохранены', 'long_edge')]:
            self.size_mode.addItem(title, key)
        size_page.addWidget(label('Как задаём размер результата', 'eyebrow'))
        size_page.addWidget(self.size_mode)
        self.size_mode.currentIndexChanged.connect(self.size_mode_changed)
        self.size_panels = HeightStack()
        self.size_panels.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        size_page.addWidget(self.size_panels)
        self.preset = QComboBox()
        for title, value in [('10 × 15 см', (100, 150)), ('4 × 6″ / 101,6 × 152,4 мм', (101.6, 152.4)),
                              ('13 × 18 см', (130, 180)), ('15 × 21 см', (150, 210)), ('20 × 30 см', (200, 300)),
                              ('A4 · 210 × 297 мм', (210, 297)), ('A3 · 297 × 420 мм', (297, 420)),
                              ('Квадрат · 150 × 150 мм', (150, 150)), ('Свой размер', None)]:
            self.preset.addItem(title, value)
        self.width = self.number(10, 1500, 100, ' мм')
        self.height = self.number(10, 1500, 150, ' мм')
        self.border = self.number(0, 100, 0, ' мм')
        self.background = QComboBox()
        for title, value in [('Белый', '#ffffff'), ('Чёрный', '#000000'), ('Серый', '#808080')]:
            self.background.addItem(title, value)
        original = QWidget()
        ol = QVBoxLayout(original)
        ol.addWidget(label('Сохраняем исходное число пикселей. При кадрировании остаются пиксели выбранной области; уменьшения до 10×15 не будет.', 'muted'))
        self.size_panels.addWidget(original)
        paper = QWidget()
        paper_form = QFormLayout(paper)
        paper_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        paper_form.addRow('Формат бумаги', self.preset)
        paper_form.addRow('Ширина', self.width)
        paper_form.addRow('Высота', self.height)
        self.geometry_disclosure = Disclosure('Поля')
        geometry = QFormLayout(self.geometry_disclosure.body)
        geometry.addRow('Поля внутри листа', self.border)
        geometry.addRow('Цвет полей', self.background)
        paper_form.addRow(self.geometry_disclosure)
        self.size_panels.addWidget(paper)
        pixels = QWidget()
        pixel_form = QFormLayout(pixels)
        self.pixel_width = QSpinBox()
        self.pixel_height = QSpinBox()
        for spin, value in ((self.pixel_width, 3840), (self.pixel_height, 2160)):
            spin.setRange(1, 32768)
            spin.setValue(value)
            spin.setSuffix(' px')
            spin.valueChanged.connect(self.schedule_preview)
        pixel_form.addRow('Ширина', self.pixel_width)
        pixel_form.addRow('Высота', self.pixel_height)
        pixel_form.addRow(label('Для ровно 3840×2160 отключите «По ориентации снимка». «Заполнить» обрежет края, «Вписать» добавит поля.', 'muted'))
        self.size_panels.addWidget(pixels)
        edge = QWidget()
        ef = QFormLayout(edge)
        self.long_edge = QSpinBox()
        self.long_edge.setRange(1, 32768)
        self.long_edge.setValue(3840)
        self.long_edge.setSuffix(' px')
        self.long_edge.valueChanged.connect(self.schedule_preview)
        ef.addRow('Длинная сторона', self.long_edge)
        ef.addRow(label('4K здесь означает 3840 пикселей по длинной стороне; вторая сторона рассчитывается по пропорциям снимка.', 'muted'))
        self.size_panels.addWidget(edge)
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 720)
        self.dpi.setValue(300)
        self.dpi.setToolTip('В пиксельных режимах это метаданные плотности; число пикселей не меняется.')
        self.fit = QComboBox()
        self.fit.addItem('Вписать · весь кадр', 'contain')
        self.fit.addItem('Заполнить · обрезать края', 'cover')
        self.auto_orientation = QCheckBox('По ориентации снимка')
        self.auto_orientation.setChecked(True)
        extra = QFormLayout()
        extra.addRow('Размещение', self.fit)
        extra.addRow(self.auto_orientation)
        extra.addRow('PPI файла', self.dpi)
        size_page.addLayout(extra)
        size_page.addStretch()
        color_page = page('Цвет и файл')
        color = QFormLayout()
        color.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.space = QComboBox()
        self.space.addItem('sRGB · обычные фото и лаборатории', 'sRGB')
        self.space.addItem('ICC машины / бумаги · RGB или CMYK', 'ICC')
        self.icc_path = ''
        self.icc_button = button('Выбрать ICC…', self.choose_icc)
        self.icc_label = label('Профиль не выбран', 'muted')
        self.intent = QComboBox()
        self.intent.addItem('Относительный + BPC', 1)
        self.intent.addItem('Перцепционный + BPC', 0)
        self.format = QComboBox()
        self.format.addItems(['JPEG', 'TIFF'])
        self.quality = QSpinBox()
        self.quality.setRange(1, 95)
        self.quality.setValue(95)
        self.icc_intent_label = label('Преобразование')
        color.addRow('Цвет результата', self.space)
        color.addRow(self.icc_button)
        color.addRow(self.icc_label)
        color.addRow(self.icc_intent_label, self.intent)
        color.addRow('Формат файла', self.format)
        color.addRow('Качество JPEG', self.quality)
        color_page.addLayout(color)
        color_page.addWidget(label('TIFF LZW — без потерь. JPEG 95 — компактнее, с потерями. ICC выбирайте по требованию получателя; случайный CMYK может испортить цвет.', 'muted'))
        color_page.addStretch()
        correction_page = page('Коррекция')
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.enhancement_preset = QComboBox()
        for key, (name, _) in PRESETS.items():
            self.enhancement_preset.addItem(name, key)
        self.enhancement_preset.addItem('Свои параметры', 'custom')
        form.addRow('Начальная настройка', self.enhancement_preset)
        self.algorithm_controls = {}
        self.advanced_correction = Disclosure('Ручные параметры коррекции')
        advanced = QFormLayout(self.advanced_correction.body)
        for key, title in [('enhancement_strength', 'Общая сила, %'), ('shadows', 'Свет в тенях, %'),
                           ('highlights', 'Сжать света, %'), ('clarity', 'Микроконтраст, %'),
                           ('vibrance', 'Вибрация цвета, %'), ('warmth', 'Теплота'), ('tint', 'Оттенок'),
                           ('chroma_denoise', 'Цветовой шум, %')]:
            spin = QSpinBox()
            spin.setRange(-100 if key in ('warmth', 'tint') else 0, 100)
            spin.setValue(70 if key == 'enhancement_strength' else 0)
            spin.valueChanged.connect(self.algorithm_changed)
            self.algorithm_controls[key] = spin
            (form if key == 'enhancement_strength' else advanced).addRow(title, spin)
        self.auto_wb = QCheckBox('Осторожный авто-ББ')
        self.auto_tone = QCheckBox('Автотон, максимум ±0,35 EV')
        for checkbox in (self.auto_wb, self.auto_tone):
            checkbox.toggled.connect(self.algorithm_changed)
            advanced.addRow(checkbox)
        form.addRow(self.advanced_correction)
        correction_page.addLayout(form)
        self.smart = QCheckBox('Подобрать кадр по деталям')
        self.enhance = QCheckBox('Мягкий автоконтраст')
        self.sharpen = QCheckBox('Лёгкая выходная резкость')
        self.upscale = QCheckBox('Разрешить увеличение маленьких фото')
        self.upscale.setChecked(True)
        for widget in (self.smart, self.enhance, self.sharpen, self.upscale):
            correction_page.addWidget(widget)
        correction_page.addWidget(label('Параметры обновляют изображение справа. Проверяйте естественность кожи, теней и белых участков.', 'muted'))
        correction_page.addStretch()
        self.enhancement_preset.currentIndexChanged.connect(self.algorithm_preset_changed)
        neural_page = page('Нейро ×2')
        self.ai_disclosure = Disclosure('Параметры нейроувеличения')
        nf = QFormLayout(self.ai_disclosure.body)
        self.upscaler = QComboBox()
        self.upscaler.addItem('Выключено · обычный Lanczos', 'lanczos')
        self.upscaler.addItem('FSRCNN ×2 · локальная CPU-модель', 'fsrcnn')
        self.neural_strength = QSpinBox()
        self.neural_strength.setRange(0, 100)
        self.neural_strength.setValue(60)
        nf.addRow('Сила, %', self.neural_strength)
        neural_page.addWidget(self.upscaler)
        neural_page.addWidget(self.ai_disclosure)
        neural_page.addWidget(label('Работает только при увеличении, а не при уменьшении или сохранении исходных пикселей. Точный предпросмотр использует ту же модель, что и экспорт. Для сравнения включите «Без улучшений» и масштаб 100%.', 'muted'))
        neural_page.addWidget(label('FSRCNN — компактный увеличитель, не универсальный реставратор. Может изменить мелкую фактуру. Кадр больше 8 Мп обрабатывается Lanczos с предупреждением.', 'muted'))
        neural_page.addStretch()
        self.upscaler.currentIndexChanged.connect(self.schedule_preview)
        self.neural_strength.valueChanged.connect(self.schedule_preview)
        self.recipe_library = QComboBox()
        self.recipe_library.setObjectName('activePreset')
        self.refresh_library()
        self.recipe_library.activated.connect(self.load_library)

    def size_mode_changed(self):
        if self._applying:
            return
        if self.size_mode.currentData() != 'print':
            self.border.setValue(0)
        self.sync_size_mode()
        self.schedule_preview()

    def sync_size_mode(self):
        key = self.size_mode.currentData()
        self.size_panels.setCurrentIndex({'original': 0, 'print': 1, 'pixels': 2, 'long_edge': 3}.get(key, 0))
        self.size_panels.updateGeometry()
        self.auto_orientation.setEnabled(key in ('print', 'pixels'))
        self.border.setEnabled(key == 'print')

    def number(self, low, high, value, suffix):
        w = QDoubleSpinBox()
        w.setRange(low, high)
        w.setDecimals(1)
        w.setValue(value)
        w.setSuffix(suffix)
        return w

    def settings(self):
        return Settings(width_mm=self.width.value(), height_mm=self.height.value(), dpi=self.dpi.value(),
            fit=self.fit.currentData(), auto_orientation=self.auto_orientation.isChecked(), border_mm=self.border.value(),
            background=self.background.currentData(), format=self.format.currentText(), quality=self.quality.value(),
            size_mode=self.size_mode.currentData(), pixel_width=self.pixel_width.value(), pixel_height=self.pixel_height.value(), long_edge=self.long_edge.value(),
            output_space=self.space.currentData(), icc_path=self.icc_path, intent=self.intent.currentData(),
            auto_enhance=self.enhance.isChecked(), sharpen=self.sharpen.isChecked(), smart_crop=self.smart.isChecked(),
            allow_upscale=self.upscale.isChecked(),
            enhancement_preset=self.enhancement_preset.currentData(),
            auto_wb=self.auto_wb.isChecked(), auto_tone=self.auto_tone.isChecked(),
            upscaler=self.upscaler.currentData(), neural_strength=self.neural_strength.value() / 100,
            **{key: spin.value() / 100 for key, spin in self.algorithm_controls.items()})

    def apply_settings(self, s):
        self._applying = True
        self.size_mode.setCurrentIndex(self.size_mode.findData(s.size_mode))
        self.pixel_width.setValue(s.pixel_width)
        self.pixel_height.setValue(s.pixel_height)
        self.long_edge.setValue(s.long_edge)
        self.width.setValue(s.width_mm)
        self.height.setValue(s.height_mm)
        self.dpi.setValue(s.dpi)
        self.fit.setCurrentIndex(self.fit.findData(s.fit))
        self.auto_orientation.setChecked(s.auto_orientation)
        self.border.setValue(s.border_mm)
        self.background.setCurrentIndex(self.background.findData(s.background))
        self.format.setCurrentText(s.format)
        self.quality.setValue(s.quality)
        self.space.setCurrentIndex(self.space.findData(s.output_space))
        self.icc_path = s.icc_path
        self.icc_label.setText(Path(s.icc_path).name if s.icc_path else 'Профиль не выбран')
        self.intent.setCurrentIndex(self.intent.findData(s.intent))
        self.enhance.setChecked(s.auto_enhance)
        self.sharpen.setChecked(s.sharpen)
        self.smart.setChecked(s.smart_crop)
        self.upscale.setChecked(s.allow_upscale)
        for key, spin in self.algorithm_controls.items():
            spin.blockSignals(True)
            spin.setValue(round(getattr(s, key) * 100))
            spin.blockSignals(False)
        for widget, value in ((self.auto_wb, s.auto_wb), (self.auto_tone, s.auto_tone)):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
        self.upscaler.setCurrentIndex(self.upscaler.findData(s.upscaler))
        self.neural_strength.setValue(round(s.neural_strength * 100))
        self.enhancement_preset.blockSignals(True)
        self.enhancement_preset.setCurrentIndex(self.enhancement_preset.findData(s.enhancement_preset))
        self.enhancement_preset.blockSignals(False)
        index = next((i for i in range(self.preset.count()) if self.preset.itemData(i) and tuple(self.preset.itemData(i)) == (s.width_mm, s.height_mm)), -1)
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(index if index >= 0 else self.preset.count() - 1)
        self.preset.blockSignals(False)
        self.geometry_disclosure.set_open(index < 0 or s.border_mm > 0)
        self.ai_disclosure.set_open(s.upscaler != 'lanczos')
        self._applying = False
        self.sync_size_mode()
        self.schedule_preview()

    def algorithm_preset_changed(self):
        key = self.enhancement_preset.currentData()
        if key == 'custom':
            return
        values = {**DEFAULTS, **PRESETS[key][1]}
        for name, spin in self.algorithm_controls.items():
            if name == 'enhancement_strength':
                continue
            spin.blockSignals(True)
            spin.setValue(round(values[name] * 100))
            spin.blockSignals(False)
        for widget, value in ((self.auto_wb, values['auto_wb']), (self.auto_tone, values['auto_tone'])):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
        self.schedule_preview()

    def algorithm_changed(self, *_):
        self.enhancement_preset.blockSignals(True)
        self.enhancement_preset.setCurrentIndex(self.enhancement_preset.findData('custom'))
        self.enhancement_preset.blockSignals(False)
        self.schedule_preview()

    def preset_changed(self):
        data = self.preset.currentData()
        if data:
            self.width.setValue(data[0])
            self.height.setValue(data[1])
        else:
            self.geometry_disclosure.set_open(True)

    def choose_icc(self):
        path, _ = QFileDialog.getOpenFileName(self, 'ICC машины / бумаги', '', 'ICC (*.icc *.icm);;Все файлы (*)')
        if path:
            candidate = replace(self.settings(), output_space='ICC', icc_path=path)
            try:
                candidate.validate()
            except Exception as e:
                self.error(str(e))
                return
            self.icc_path = path
            self.icc_label.setText(Path(path).name)
            self.icc_label.setToolTip(path)
            self.space.setCurrentIndex(1)
            self.schedule_preview()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Папка с фотографиями', str(self.folder or Path.home()))
        if folder:
            self.load_folder(Path(folder))

    def rescan(self):
        if self.folder:
            self.load_folder(self.folder)

    def load_folder(self, folder):
        if self.worker and self.worker.isRunning():
            return
        self.timer.stop()
        self.preview_version += 1
        self.preview_pending = False
        self.operation = 'scan'
        self.welcome_feedback.clear()
        self._source_cache = None
        self.folder = folder.resolve()
        self.folder_label.setText(str(self.folder))
        self.folder_label.setToolTip(str(self.folder))
        self.cancel_event.clear()
        self.photos = []
        self.list.clear()
        self.set_busy(True, 'Чтение фотографий…')
        recursive = self.recursive.isChecked()
        self.worker = Task(lambda: scan(self.folder, recursive, self.cancel_event), self)
        self.worker.result.connect(self.scanned)
        self.worker.error.connect(self.error)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.worker.start()

    def scanned(self, result):
        self.photos, errors = result
        self.count_label.setText(f'Фотографии · {len(self.photos)}')
        for p in self.photos:
            item = QListWidgetItem(f'{p.path.name}\n{p.size[0]} × {p.size[1]} px')
            item.setToolTip(f'{p.path}\n{p.profile}')
            self.list.addItem(item)
        self.status.setText(f'Найдено: {len(self.photos)}. Не прочитано: {len(errors)}.' + (' Чтение остановлено.' if self.cancel_event.is_set() else ''))
        self.list.setCurrentRow(-1)
        self.show_batch()
        if not self.photos:
            self.status.setText('Поддерживаемых фотографий не найдено. Выберите другую папку.')
            self.welcome_feedback.setText('В выбранной папке нет поддерживаемых фотографий. Попробуйте другую папку или включите поиск в подпапках.')
            self.show_page('welcome')
        if errors:
            box = QMessageBox(self)
            box.setWindowTitle('Некоторые файлы не прочитаны')
            box.setText(f'Пропущено файлов: {len(errors)}. Остальные доступны для обработки.')
            box.setDetailedText('\n'.join(f"{e['file']}: {e['error']}" for e in errors))
            box.exec()

    def selected(self):
        index = self.list.currentRow()
        return self.photos[index] if 0 <= index < len(self.photos) else None

    def selection_changed(self, *_):
        selected = self.selected()
        self.edit_btn.setEnabled(selected is not None)
        self.reset_btn.setEnabled(selected is not None)
        self.schedule_preview()

    def schedule_preview(self, *_):
        if self._applying:
            return
        index = next((i for i in range(self.preset.count()) if self.preset.itemData(i) and tuple(self.preset.itemData(i)) == (self.width.value(), self.height.value())), self.preset.count() - 1)
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(index)
        self.preset.blockSignals(False)
        self.preview_version += 1
        self.proof_check.setEnabled(self.space.currentData() == 'ICC')
        self.smart.setEnabled(self.fit.currentData() == 'cover')
        self.quality.setEnabled(self.format.currentText() == 'JPEG')
        self.ai_disclosure.title = 'Нейроувеличение · FSRCNN ×2 включено' if self.upscaler.currentData() == 'fsrcnn' else 'Нейроувеличение · по необходимости'
        self.ai_disclosure.set_open(self.ai_disclosure.toggle.isChecked())
        icc_visible = self.space.currentData() == 'ICC'
        self.settings_proof.setVisible(icc_visible)
        self.icc_button.setVisible(icc_visible)
        self.icc_label.setVisible(icc_visible)
        self.intent.setVisible(icc_visible)
        if hasattr(self, 'icc_intent_label'):
            self.icc_intent_label.setVisible(icc_visible)
        self.summary_timer.start()
        self.sync_size_mode()
        if self.mode == 'review' or self.settings_dialog.isVisible():
            self.timer.start()

    def start_preview(self):
        if self.mode != 'review' and not self.settings_dialog.isVisible():
            return
        photo = self.selected() or (self.photos[0] if self.photos and self.settings_dialog.isVisible() else None)
        if not photo:
            return
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_pending = True
            return
        self.preview_pending = False
        version = self.preview_version
        settings = self.settings()
        edit = replace(self.edits.get(str(photo.path), Edit()))
        show_before = self.settings_compare.isChecked() if self.settings_dialog.isVisible() else self.original_check.isChecked()
        show_proof = (self.settings_proof.isChecked() if self.settings_dialog.isVisible() else self.proof_check.isChecked()) and settings.output_space == 'ICC'
        self.settings_preview_status.setText('Рассчитываем точный предпросмотр…')
        self.warning.setText('Рассчитываем изменения…' + (' Нейро ×2 может занять несколько секунд.' if settings.upscaler == 'fsrcnn' or edit.use_neural else ''))
        def work():
            settings.validate()
            stat = photo.path.stat()
            key = (str(photo.path), stat.st_mtime_ns, stat.st_size)
            cached = self._source_cache
            if cached is None or cached[0] != key:
                source, source_notes = load_rgb(photo.path)
                self._source_cache = key, source, source_notes
            else:
                _, source, source_notes = cached
            notes = list(source_notes)
            if show_before:
                before_edit = replace(edit, exposure=0, contrast=1, saturation=1, use_neural=False, neural_strength=0)
                out = render(source, without_enhancements(settings), before_edit)
            else:
                out = render(source, settings, edit, notes=notes)
            if show_proof:
                out = proof(out, settings)
            info = assess(photo.size, settings, edit)
            notes.append('ICC-проба в sRGB (приближённо).' if show_proof else 'Цвет предпросмотра: рабочий sRGB.')
            notes.append(f'Исходник {photo.size[0]} × {photo.size[1]} px → результат {out.width} × {out.height} px.')
            if info['downscale']:
                notes.append('Этот пресет уменьшает снимок. Для исходных пикселей выберите «Без уменьшения».')
            return out, info, notes
        self.preview_worker = Task(work, self)
        self.preview_worker.result.connect(lambda result: self.preview_ready(version, photo, result))
        self.preview_worker.error.connect(lambda e: self.preview_error(version, e))
        self.preview_worker.finished.connect(self.preview_finished)
        self.preview_worker.start()

    def preview_ready(self, version, photo, result):
        if version != self.preview_version:
            return
        im, info, notes = result
        self.preview.set_image(im)
        self.settings_preview.set_image(im)
        self.settings_preview_status.setText(f'Точный результат · {im.width} × {im.height} px\n' + '\n'.join(notes[:2]))
        self.settings_preview_status.setToolTip('\n'.join(notes))
        self.photo_title.setText(photo.path.name)
        w, h = info['pixels']
        self.info.setText(f"{w} × {h} px · исходная детализация ≈ {info['ppi']} PPI · обрезка {info['crop_percent']}%\n{photo.profile}")
        all_notes = notes + info['warnings']
        visible = all_notes[:3]
        if len(all_notes) > 3:
            visible.append(f'Ещё предупреждений: {len(all_notes) - 3} (наведите курсор).')
        self.warning.setText('\n'.join(visible))
        self.warning.setToolTip('\n'.join(all_notes))
        item = self.list.currentItem()
        if item:
            item.setIcon(QIcon(QPixmap.fromImage(image_to_qimage(im)).scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))

    def preview_error(self, version, error):
        if version == self.preview_version:
            self.warning.setText(error)
            self.settings_preview_status.setText(error)

    def preview_finished(self):
        if self.preview_pending:
            self.timer.start(20)

    def edit_photo(self):
        photo = self.selected()
        if not photo:
            return
        try:
            self.settings().validate()
            cached = self._source_cache
            im = cached[1] if cached is not None and cached[0][0] == str(photo.path) else load_rgb(photo.path)[0]
            dialog = CropDialog(im, self.settings(), self.edits.get(str(photo.path), Edit()), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.edits[str(photo.path)] = dialog.edit
                self.list.currentItem().setText(f'✎ {photo.path.name}\n{photo.size[0]} × {photo.size[1]} px')
                self.schedule_preview()
        except Exception as e:
            self.error(str(e))

    def reset_photo(self):
        photo = self.selected()
        if photo:
            self.edits.pop(str(photo.path), None)
            self.list.currentItem().setText(f'{photo.path.name}\n{photo.size[0]} × {photo.size[1]} px')
            self.schedule_preview()

    def set_busy(self, busy, text=None):
        self.busy = busy
        for widget in (self.open_btn, self.change_folder_btn, self.rescan_btn, self.recursive, self.tune_btn):
            widget.setEnabled(not busy)
        for card in self.batch_cards.values():
            card.setEnabled(not busy)
        self.recipe_library.setEnabled(not busy)
        self.export_btn.setEnabled(not busy and bool(self.photos))
        self.review_btn.setEnabled(not busy and bool(self.photos))
        self.cancel_btn.setEnabled(busy)
        if text:
            self.status.setText(text)
            self.progress_detail.setText(text)
        if busy:
            self.timer.stop()
            self.preview_version += 1
            self.preview_pending = False
            self.progress_title.setText('Собираем фотографии' if self.operation == 'scan' else 'Готовим фотографии к печати')
            self.progress.setRange(0, 0)
            self.show_page('progress')
        else:
            self.progress.setRange(0, 100)
            if self.mode == 'progress':
                self.show_batch()
            self.refresh_batch_summary()

    def preflight(self):
        if not self.photos:
            self.status.setText('Сначала выберите папку с фотографиями.')
            return
        try:
            settings = self.settings()
            settings.validate()
            details = []
            low = crop = up = 0
            for photo in self.photos:
                info = assess(photo.size, settings, self.edits.get(str(photo.path), Edit()))
                low += info['ppi'] < 240
                crop += info['crop_percent'] > 15
                up += info['upscale']
                notes = photo.warnings + info['warnings']
                details.append(f"{photo.path.name}: {info['ppi']} PPI, обрезка {info['crop_percent']}%" +
                               ('\n  ' + ' | '.join(notes) if notes else ''))
            box = QMessageBox(self)
            box.setWindowTitle('Print Prep · Проверка партии')
            box.setText(f'Фотографий: {len(self.photos)}\nНиже 240 PPI: {low}\nОбрезка более 15%: {crop}\nТребуют увеличения: {up}')
            box.setInformativeText('Это оценка геометрии и метаданных. Ошибки полного декодирования/записи будут отражены при экспорте. Откройте подробности для списка.')
            box.setDetailedText('\n\n'.join(details))
            box.exec()
        except Exception as e:
            self.error(str(e))

    def export(self):
        if not self.folder or not self.photos:
            return
        settings = self.settings()
        try:
            settings.validate()
        except Exception as e:
            self.error(str(e))
            return
        edits = {k: replace(v) for k, v in self.edits.items()}
        photos = list(self.photos)
        folder = self.folder
        self.store.setValue('settings', json.dumps(asdict(settings)))
        self.cancel_event.clear()
        self.operation = 'export'
        self.set_busy(True, 'Подготовка файлов…')
        self.worker = Task(lambda: export_batch(folder, photos, settings, edits, self.cancel_event,
            lambda i, n, row: self.worker.progress.emit(i, n, row)), self)
        self.worker.progress.connect(self.export_progress)
        self.worker.result.connect(self.export_done)
        self.worker.error.connect(self.error)
        self.worker.finished.connect(lambda: self.set_busy(False))
        self.worker.start()

    def export_progress(self, i, total, row):
        self.progress.setRange(0, total)
        self.progress.setValue(i)
        self.status.setText(f"{i} / {total} · {Path(row['source']).name}")
        self.progress_detail.setText(f"{i} из {total}  ·  {Path(row['source']).name}")

    def export_done(self, result):
        self.last_output, report = result
        self.output_btn.setEnabled(True)
        rows = report['results']
        ok = sum(r['status'] == 'ok' for r in rows)
        errors = sum(r['status'] == 'error' for r in rows)
        skipped = sum(r['status'] == 'skipped' for r in rows)
        self.done_title.setText('Обработка остановлена' if report['cancelled'] else 'Фотографии подготовлены' if ok else 'Обработка завершена с ошибками')
        self.done_summary.setText(f'Готово: {ok}   ·   Ошибок: {errors}   ·   Пропущено: {skipped}')
        self.done_path.setText(str(self.last_output))
        self.status.setText(self.done_summary.text())
        self.show_page('done')

    def cancel(self):
        self.cancel_event.set()
        self.cancel_btn.setEnabled(False)
        self.status.setText('Остановка после текущего файла…')
        self.progress_detail.setText('Остановка после текущего файла…')

    def open_output(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output)))

    def library(self):
        try:
            data = json.loads(self.store.value('preset_library', '{}'))
            return data if isinstance(data, dict) else {}
        except (TypeError, ValueError):
            return {}

    def preset_snapshot(self, key):
        if not key:
            return None
        if key.startswith('builtin:'):
            entry = BATCH_PRESETS.get(key[8:])
            return replace(entry[2]) if entry else None
        values = self.library().get(key)
        try:
            return Settings(**values) if values is not None else None
        except (TypeError, ValueError):
            return None

    def preset_name(self):
        key = self.active_preset_key
        if key and key.startswith('builtin:') and key[8:] in BATCH_PRESETS:
            return BATCH_PRESETS[key[8:]][0]
        return key or 'Свои настройки'

    def refresh_library(self):
        self.recipe_library.blockSignals(True)
        self.recipe_library.clear()
        self.recipe_library.addItem('Свои настройки · сохраните как пресет', None)
        self.recipe_library.model().item(0).setEnabled(False)
        for key, (name, note, settings) in BATCH_PRESETS.items():
            self.recipe_library.addItem(name, 'builtin:' + key)
        if self.library():
            self.recipe_library.insertSeparator(self.recipe_library.count())
        for name in sorted(self.library()):
            self.recipe_library.addItem('Мой · ' + name, name)
        if self.preset_snapshot(self.active_preset_key) is None and hasattr(self, 'size_mode'):
            current = self.settings()
            self.active_preset_key = next(('builtin:' + k for k, value in BATCH_PRESETS.items() if current == value[2]), None)
        index = self.recipe_library.findData(self.active_preset_key)
        self.recipe_library.setCurrentIndex(max(0, index))
        self.recipe_library.blockSignals(False)

    def save_library(self):
        try:
            settings = self.settings()
            settings.validate()
            name, ok = QInputDialog.getText(self.settings_dialog if self.settings_dialog.isVisible() else self, 'Сохранить новый пресет', 'Название:')
            name = name.strip()[:100]
            if not ok or not name:
                return False
            if name.startswith('builtin:'):
                raise ValueError('Выберите название без служебного префикса builtin:.')
            library = self.library()
            if name in library and QMessageBox.question(self, 'Заменить пресет?', f'Обновить «{name}»?') != QMessageBox.StandardButton.Yes:
                return False
            library[name] = asdict(settings)
            self.store.setValue('preset_library', json.dumps(library, ensure_ascii=False))
            self.active_preset_key = name
            self.refresh_library()
            self.refresh_batch_summary()
            self.status.setText(f'«{name}» сохранён и выбран для всей партии.')
            return True
        except Exception as e:
            self.error(str(e))
            return False

    def update_library(self):
        key = self.active_preset_key
        if not key or key.startswith('builtin:'):
            return self.save_library()
        try:
            settings = self.settings()
            settings.validate()
            library = self.library()
            if key not in library:
                return self.save_library()
            library[key] = asdict(settings)
            self.store.setValue('preset_library', json.dumps(library, ensure_ascii=False))
            self.refresh_library()
            self.refresh_batch_summary()
            self.status.setText(f'Изменения сохранены в «{key}».')
            return True
        except Exception as e:
            self.error(str(e))
            return False

    def save_settings_preset(self):
        if self.update_library():
            self.settings_dialog.accept()

    def load_library(self, index):
        key = self.recipe_library.itemData(index)
        settings = self.preset_snapshot(key)
        if settings is None:
            return
        try:
            settings.validate()
            self.active_preset_key = key
            self.apply_settings(settings)
            self.refresh_batch_summary()
            self.status.setText(f'Выбран «{self.preset_name()}». Кнопка «Изменить» открывает его параметры.')
        except Exception as e:
            self.error(str(e))

    def rename_library(self):
        old = self.active_preset_key
        library = self.library()
        if old not in library:
            return
        name, ok = QInputDialog.getText(self, 'Переименовать пресет', 'Новое название:')
        name = name.strip()[:100]
        if not ok or not name or name == old:
            return
        if name in library or name.startswith('builtin:'):
            self.error('Такое имя занято или зарезервировано. Выберите другое.')
            return
        library[name] = library.pop(old)
        self.store.setValue('preset_library', json.dumps(library, ensure_ascii=False))
        self.active_preset_key = name
        self.refresh_library()
        self.refresh_batch_summary()

    def delete_library(self):
        library = self.library()
        if not library:
            return
        names = sorted(library)
        name, ok = QInputDialog.getItem(self, 'Удалить пресет', 'Выберите:', names, 0, False)
        if ok:
            del library[name]
            self.store.setValue('preset_library', json.dumps(library, ensure_ascii=False))
            if self.active_preset_key == name:
                self.active_preset_key = None
            self.refresh_library()
            self.refresh_batch_summary()

    def save_recipe(self):
        try:
            settings = self.settings()
            settings.validate()
            path, _ = QFileDialog.getSaveFileName(self, 'Сохранить настройки и кадры', 'printprep-recipe.json', 'JSON (*.json)')
            if path:
                edits = {}
                if self.folder:
                    for photo in self.photos:
                        if str(photo.path) in self.edits:
                            edits[str(photo.path.relative_to(self.folder))] = asdict(self.edits[str(photo.path)])
                Path(path).write_text(json.dumps({'version': 1, 'settings': asdict(settings), 'edits': edits}, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            self.error(str(e))

    def load_recipe(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Загрузить рецепт', '', 'JSON (*.json)')
        if not path:
            return
        try:
            if Path(path).stat().st_size > 5_000_000:
                raise ValueError('Файл рецепта слишком большой.')
            data = json.loads(Path(path).read_text(encoding='utf-8'))
            if data.get('version') != 1:
                raise ValueError('Неизвестная версия рецепта.')
            settings = Settings(**data['settings'])
            settings.validate()
            edits = {}
            if self.folder:
                allowed = {str(p.path.relative_to(self.folder)): str(p.path) for p in self.photos}
                for relative, values in data.get('edits', {}).items():
                    edit = Edit(**values)
                    edit.validate()
                    if relative in allowed:
                        edits[allowed[relative]] = edit
            self.edits = edits
            self.active_preset_key = None
            self.apply_settings(settings)
            self.status.setText('Рецепт загружен. Кадры сопоставлены по относительным именам файлов текущей папки.')
        except Exception as e:
            self.error(str(e))

    def error(self, text):
        QMessageBox.warning(self.settings_dialog if self.settings_dialog.isVisible() else self, 'Print Prep', text)

    def help(self):
        QMessageBox.information(self, 'Print Prep · Как подготовить фотографии',
            '1. Выберите папку. При необходимости включите подпапки до выбора.\n'
            '2. Выберите пресет для всей партии и сразу запустите подготовку.\n'
            '3. Для другого размера, ICC или улучшений откройте «Настроить пресет».\n'
            '4. «Вписать» сохраняет весь кадр с полями; «Заполнить» обрезает до формата.\n'
            '5. В просмотре двойной щелчок по снимку — кадр, поворот и коррекция.\n'
            '6. Нажмите «Подготовить к печати». Результат — в новой PrintPrep_* внутри выбранной папки.\n\n'
            'Для фотолаборатории оставьте sRGB, если оператор не требует иного. ICC для экранной пробы '
            'не обязательно предназначен для преобразования файла. CMYK — только с подходящим профилем '
            'и по требованию типографии. Не допускайте повторного управления цветом в драйвере.\n\n'
            'PPI файла ≠ DPI принтера. Увеличение не восстанавливает детали. Печать без полей в драйвере '
            'может дополнительно обрезать края. Нет прямой отправки на принтер, RAW/HEIC, 16-битного '
            'рабочего процесса и распознавания лиц. Подробности — README.txt и docs/RESEARCH.md.')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(Path(u.toLocalFile()).is_dir() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.worker and self.worker.isRunning():
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                self.load_folder(path)
                break

    def closeEvent(self, event):
        running = self.worker and self.worker.isRunning()
        preview_running = self.preview_worker and self.preview_worker.isRunning()
        if running or preview_running:
            if running:
                self.cancel()
            self.status.setText('Дождитесь завершения текущей операции и закройте окно ещё раз.')
            event.ignore()
            return
        self.timer.stop()
        self.summary_timer.stop()
        self.store.setValue('settings', json.dumps(asdict(self.settings())))
        self.store.setValue('active_preset', self.active_preset_key or '')
        event.accept()


def run():
    app = QApplication.instance() or QApplication([])
    app.setApplicationName('Print Prep')
    app.setOrganizationName('PrintPrep')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    try:
        return app.exec()
    finally:
        # Destroy native widgets and the calling thread's cached DNN while
        # their runtimes are alive, rather than relying on interpreter order.
        from .upscale import release_network
        release_network()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
