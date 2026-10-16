from __future__ import annotations

import json
import threading
from dataclasses import asdict, replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QThread, Signal, Qt, QTimer, QRectF, QSettings, QSize, QUrl, QLineF, QCoreApplication, QEvent
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QFormLayout, QGroupBox, QScrollArea, QListWidget, QListWidgetItem, QSplitter,
    QProgressBar, QMessageBox, QDialog, QDialogButtonBox, QSlider, QSizePolicy, QInputDialog, QStackedWidget, QGridLayout, QButtonGroup, QFrame)

from .enhance import PRESETS, DEFAULTS, analyze
from .engine import (Settings, Edit, Photo, scan, load_rgb, render, assess, layout, crop_box,
                     oriented, effective_edit, proof, export_batch)

from .theme import STYLE

BATCH_PRESETS = {
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


class Preview(QLabel):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(240, 200)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('background: #0c1017; border: 1px solid #293244; border-radius: 10px; color: #758299;')
        self.picture = None
        self.setText('Выберите папку с фотографиями\n\nJPEG · TIFF · PNG · WebP · BMP')

    def set_image(self, im):
        self.picture = QPixmap.fromImage(image_to_qimage(im))
        self.update_picture()

    def update_picture(self):
        if self.picture:
            self.setPixmap(self.picture.scaled(self.size() - QSize(32, 32), Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_picture()


class CropCanvas(QWidget):
    changed = Signal(float, float)

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
    def __init__(self, im, settings, edit, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Print Prep · Кадрирование и коррекция')
        self.resize(940, 740)
        self.base = im
        self.edit = replace(edit)
        self.settings = replace(settings, fit='cover')
        self.edit = effective_edit(oriented(im, self.edit), self.settings, self.edit)
        outer = QVBoxLayout(self)
        outer.addWidget(label('Каждому снимку — свой кадр', 'title'))
        outer.addWidget(label('Перетаскивайте рамку. Ползунок приближает кадр. Изменения применяются только к этому снимку.', 'muted'))
        self.canvas = CropCanvas(oriented(self.base, self.edit), self.settings, self.edit)
        outer.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        row.addWidget(button('↶ 90°', lambda: self.rotate(-90)))
        row.addWidget(button('↷ 90°', lambda: self.rotate(90)))
        row.addWidget(label('Приближение'))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(100, 500)
        self.zoom.setValue(round(self.edit.zoom * 100))
        self.zoom.valueChanged.connect(self.set_zoom)
        row.addWidget(self.zoom, 1)
        row.addWidget(button('Сбросить', self.reset))
        outer.addLayout(row)
        form = QFormLayout()
        self.sliders = {}
        for key, title, low, high, factor in [('exposure', 'Экспозиция, EV', -200, 200, 100),
                                             ('contrast', 'Контраст', 50, 150, 100),
                                             ('saturation', 'Насыщенность', 0, 150, 100)]:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(low, high)
            slider.setValue(round(getattr(self.edit, key) * factor))
            slider.valueChanged.connect(lambda v, k=key, f=factor: setattr(self.edit, k, v / f))
            self.sliders[key] = slider
            form.addRow(title, slider)
        outer.addLayout(form)
        outer.addWidget(label('Коррекции цвета видны в основном предпросмотре после «Применить». Рамка показывает обрезку; при вписывании используется только поворот и коррекция.', 'muted'))
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('Применить')
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        outer.addWidget(controls)

    def set_zoom(self, value):
        self.edit.zoom = value / 100
        self.edit.manual_crop = True
        self.canvas.update()

    def rotate(self, value):
        self.edit.rotation = (self.edit.rotation + value) % 360
        self.edit.center_x = self.edit.center_y = .5
        self.edit.manual_crop = True
        self.canvas.im = oriented(self.base, self.edit)
        self.canvas.update()

    def reset(self):
        self.edit = Edit()
        self.canvas.edit = self.edit
        self.canvas.im = self.base
        self.zoom.setValue(100)
        for key, slider in self.sliders.items():
            slider.setValue(round(getattr(self.edit, key) * 100))
        self.canvas.update()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Print Prep — подготовка фотографий к печати')
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'assets' / 'printprep.png')))
        available = self.screen().availableGeometry()
        self.setMinimumSize(900, 600)
        self.resize(min(1280, max(900, available.width() - 40)), min(900, max(600, available.height() - 50)))
        self.setAcceptDrops(True)
        self.folder = None
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
        self.apply_settings(Settings())
        try:
            saved = self.store.value('settings')
            if saved:
                self.apply_settings(Settings(**json.loads(saved)))
        except (TypeError, ValueError):
            pass

    def _build(self):
        self.mode = 'welcome'
        self.busy = False
        self.operation = None
        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle('Print Prep · Настройки всей партии')
        self.settings_dialog.resize(560, min(780, max(480, self.screen().availableGeometry().height() - 60)))
        self.recursive = QCheckBox('Искать также во вложенных папках')
        self._build_settings()
        settings_layout = QVBoxLayout(self.settings_dialog)
        settings_layout.setContentsMargins(20, 16, 20, 16)
        settings_layout.addWidget(label('Настроить пресет', 'title'))
        settings_layout.addWidget(label('Эти параметры применятся ко всей папке. Индивидуальные кадры сохранятся.', 'muted'))
        settings_layout.addWidget(self.settings_scroll, 1)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        controls.button(QDialogButtonBox.StandardButton.Ok).setText('Применить к партии')
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText('Отмена')
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
            step = label(title)
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
        for i, (key, (name, note, settings)) in enumerate(BATCH_PRESETS.items()):
            card = PresetCard(name, note)
            card.clicked.connect(lambda checked, k=key: self.choose_batch_preset(k))
            self.card_group.addButton(card)
            self.batch_cards[key] = card
            grid.addWidget(card, i // 2, i % 2)
        bl.addLayout(grid)
        mine = QHBoxLayout()
        mine.addWidget(self.recipe_library, 1)
        self.tune_btn = button('Настроить пресет…', self.open_settings)
        mine.addWidget(self.tune_btn)
        bl.addLayout(mine)
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
        self.original_check = QCheckBox('Исходник')
        self.proof_check = QCheckBox('ICC-проба')
        self.proof_check.setToolTip('Приближённая ICC-проба в sRGB; не заменяет пробный отпечаток.')
        self.original_check.toggled.connect(self.schedule_preview)
        self.proof_check.toggled.connect(self.schedule_preview)
        toggles.addWidget(self.original_check)
        toggles.addWidget(self.proof_check)
        toggles.addStretch()
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
            widget.setStyleSheet(f'font-size: 14px; font-weight: {700 if i == step else 500}; color: {"#245e45" if i == step else "#99a395"};')

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
        if self.settings_dialog.exec() != QDialog.DialogCode.Accepted:
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
        self.apply_settings(replace(BATCH_PRESETS[key][2]))
        self.recipe_library.setCurrentIndex(0)
        self.status.setText('Пресет применится ко всем фотографиям. Можно сразу запускать.')

    def refresh_batch_summary(self):
        if not hasattr(self, 'batch_summary'):
            return
        s = self.settings()
        self.card_group.setExclusive(False)
        for key, card in self.batch_cards.items():
            card.setChecked(s == BATCH_PRESETS[key][2])
        self.card_group.setExclusive(True)
        match = next((value[0] for value in BATCH_PRESETS.values() if s == value[2]), 'Свои настройки')
        place = 'весь кадр, возможны поля' if s.fit == 'contain' else 'заполнение с обрезкой'
        color = 'sRGB' if s.output_space == 'sRGB' else f'ICC: {Path(s.icc_path).name or "не выбран"}'
        self.batch_summary.setText(f'{match}  ·  {s.width_mm:g} × {s.height_mm:g} мм  ·  {s.dpi} PPI\n{place}  ·  {s.format}  ·  {color}')
        try:
            s.validate()
        except Exception as e:
            self.batch_warnings.setText(str(e))
            return
        low = crop = 0
        for photo in self.photos:
            info = assess(photo.size, s, self.edits.get(str(photo.path), Edit()))
            low += info['ppi'] < 240
            crop += info['crop_percent'] > 15
        notes = []
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(320)
        panel = QWidget()
        panel.setObjectName('shell')
        pb = QVBoxLayout(panel)
        pb.setContentsMargins(8, 0, 8, 0)
        pb.addWidget(label('ПАРАМЕТРЫ ПРЕСЕТА', 'eyebrow'))
        self.preset = QComboBox()
        for name, data in [('10 × 15 см', (100, 150)), ('10 × 15,2 см / 4 × 6″', (101.6, 152.4)),
                           ('13 × 18 см', (130, 180)), ('15 × 21 см', (150, 210)),
                           ('20 × 30 см', (200, 300)), ('A4 · 210 × 297 мм', (210, 297)),
                           ('A3 · 297 × 420 мм', (297, 420)), ('Квадрат · 150 × 150 мм', (150, 150)),
                           ('Свой размер', None)]:
            self.preset.addItem(name, data)
        pb.addWidget(self.preset)
        self.recipe_library = QComboBox()
        self.refresh_library()
        self.recipe_library.activated.connect(self.load_library)
        pb.addWidget(self.recipe_library)
        library_buttons = QHBoxLayout()
        library_buttons.addWidget(button('＋ Мой пресет', self.save_library))
        library_buttons.addWidget(button('Удалить пресет', self.delete_library))
        pb.addLayout(library_buttons)
        group = QGroupBox('Размер и композиция')
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.width = self.number(10, 1500, 100, ' мм')
        self.height = self.number(10, 1500, 150, ' мм')
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 720)
        self.dpi.setValue(300)
        self.dpi.setToolTip('Плотность пикселей файла (PPI). Это не разрешение печатной головки в DPI.')
        self.fit = QComboBox()
        self.fit.addItem('Вписать · без обрезки', 'contain')
        self.fit.addItem('Заполнить · обрезать края', 'cover')
        self.auto_orientation = QCheckBox('По ориентации каждого снимка')
        self.auto_orientation.setChecked(True)
        self.border = self.number(0, 100, 0, ' мм')
        self.background = QComboBox()
        for name, color in [('Белый', '#ffffff'), ('Чёрный', '#000000'), ('Серый', '#808080')]:
            self.background.addItem(name, color)
        self.geometry_disclosure = Disclosure('Поля и точные размеры')
        geometry_form = QFormLayout(self.geometry_disclosure.body)
        geometry_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        geometry_form.addRow('Ширина', self.width)
        geometry_form.addRow('Высота', self.height)
        form.addRow('PPI файла', self.dpi)
        form.addRow(self.auto_orientation)
        form.addRow('Размещение', self.fit)
        geometry_form.addRow('Поля внутри листа', self.border)
        geometry_form.addRow('Цвет полей', self.background)
        form.addRow(self.geometry_disclosure)
        pb.addWidget(group)
        group = QGroupBox('Цвет и файл')
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.space = QComboBox()
        self.space.addItem('sRGB · фотолаборатория', 'sRGB')
        self.space.addItem('ICC машины / бумаги · RGB или CMYK', 'ICC')
        self.icc_path = ''
        self.icc_button = button('Выбрать ICC-профиль…', self.choose_icc)
        self.icc_label = label('Профиль не выбран', 'muted')
        self.intent = QComboBox()
        self.intent.addItem('Относительный + BPC', 1)
        self.intent.addItem('Перцепционный + BPC', 0)
        self.format = QComboBox()
        self.format.addItems(['JPEG', 'TIFF'])
        self.quality = QSpinBox()
        self.quality.setRange(1, 95)
        self.quality.setValue(95)
        form.addRow(self.space)
        form.addRow(self.icc_button)
        form.addRow(self.icc_label)
        self.icc_intent_label = label('Преобразование')
        form.addRow(self.icc_intent_label, self.intent)
        form.addRow('Экспорт', self.format)
        form.addRow('Качество JPEG', self.quality)
        pb.addWidget(group)
        group = QGroupBox('Коррекция фото')
        form = QFormLayout(group)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.enhancement_preset = QComboBox()
        for key, (name, _) in PRESETS.items():
            self.enhancement_preset.addItem(name, key)
        self.enhancement_preset.addItem('Свои параметры', 'custom')
        form.addRow(self.enhancement_preset)
        self.algorithm_controls = {}
        self.advanced_correction = Disclosure('Точная цветокоррекция')
        advanced_form = QFormLayout(self.advanced_correction.body)
        advanced_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for key, title in [('enhancement_strength', 'Сила, %'), ('shadows', 'Свет в тенях, %'),
                           ('highlights', 'Сжать света, %'), ('clarity', 'Микроконтраст, %'),
                           ('vibrance', 'Вибрация цвета, %'), ('warmth', 'Теплее / холоднее'),
                           ('tint', 'Маджента / зелень'), ('chroma_denoise', 'Цветовой шум, %')]:
            spin = QSpinBox()
            spin.setRange(-100 if key in ('warmth', 'tint') else 0, 100)
            spin.setValue(70 if key == 'enhancement_strength' else 0)
            spin.valueChanged.connect(self.algorithm_changed)
            self.algorithm_controls[key] = spin
            (form if key == 'enhancement_strength' else advanced_form).addRow(title, spin)
        self.auto_wb = QCheckBox('Осторожный авто-ББ')
        self.auto_wb.setToolTip('По почти нейтральным участкам. При слабых данных не применяется. Может убрать намеренную теплоту света.')
        self.auto_tone = QCheckBox('Осторожный автотон, ±0,35 EV')
        self.auto_wb.toggled.connect(self.algorithm_changed)
        self.auto_tone.toggled.connect(self.algorithm_changed)
        advanced_form.addRow(self.auto_wb)
        advanced_form.addRow(self.auto_tone)
        form.addRow(self.advanced_correction)
        pb.addWidget(group)
        self.enhancement_preset.currentIndexChanged.connect(self.algorithm_preset_changed)
        self.ai_disclosure = Disclosure('Нейроувеличение · по необходимости')
        ai_form = QFormLayout(self.ai_disclosure.body)
        ai_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.upscaler = QComboBox()
        self.upscaler.addItem('Lanczos · обычное увеличение', 'lanczos')
        self.upscaler.addItem('FSRCNN ×2 · компактная нейросеть', 'fsrcnn')
        self.neural_strength = QSpinBox()
        self.neural_strength.setRange(0, 100)
        self.neural_strength.setValue(60)
        ai_form.addRow(self.upscaler)
        ai_form.addRow('Сила, %', self.neural_strength)
        ai_form.addRow(label('Только для увеличения кадра до 8 Мп. Модель работает локально на CPU; может менять фактуру. Эффект оценивайте на готовом файле при 100%.', 'muted'))
        self.upscaler.currentIndexChanged.connect(self.schedule_preview)
        self.neural_strength.valueChanged.connect(self.schedule_preview)
        pb.addWidget(self.ai_disclosure)
        group = Disclosure('Ещё: кадр, резкость и увеличение')
        vb = QVBoxLayout(group.body)
        self.smart = QCheckBox('Умный подбор кадра')
        self.smart.setToolTip('По распределению деталей, без распознавания лиц. Только для заполнения; ручная правка имеет приоритет.')
        self.enhance = QCheckBox('Мягкий автоконтраст')
        self.enhance.setToolTip('25% яркостной автокоррекции. Может изменить авторскую обработку; проверьте предпросмотр.')
        self.sharpen = QCheckBox('Лёгкая резкость после ресайза')
        self.upscale = QCheckBox('Разрешить увеличение')
        self.upscale.setChecked(True)
        self.upscale.setToolTip('Если выключено, слишком маленькие снимки пропускаются с записью в отчёт.')
        for widget in (self.smart, self.enhance, self.sharpen, self.upscale):
            vb.addWidget(widget)
        pb.addWidget(group)
        pb.addWidget(label('Для минилаба обычно нужен sRGB. CMYK включайте только по требованию типографии. Размер бумаги уточняйте у оператора.', 'muted'))
        presets_row = QHBoxLayout()
        presets_row.addWidget(button('Сохранить рецепт', self.save_recipe))
        presets_row.addWidget(button('Загрузить', self.load_recipe))
        pb.addLayout(presets_row)
        pb.addStretch()
        for combo in panel.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        self.settings_scroll = scroll

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
            output_space=self.space.currentData(), icc_path=self.icc_path, intent=self.intent.currentData(),
            auto_enhance=self.enhance.isChecked(), sharpen=self.sharpen.isChecked(), smart_crop=self.smart.isChecked(),
            allow_upscale=self.upscale.isChecked(),
            enhancement_preset=self.enhancement_preset.currentData(),
            auto_wb=self.auto_wb.isChecked(), auto_tone=self.auto_tone.isChecked(),
            upscaler=self.upscaler.currentData(), neural_strength=self.neural_strength.value() / 100,
            **{key: spin.value() / 100 for key, spin in self.algorithm_controls.items()})

    def apply_settings(self, s):
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
        self.icc_button.setVisible(icc_visible)
        self.icc_label.setVisible(icc_visible)
        self.intent.setVisible(icc_visible)
        if hasattr(self, 'icc_intent_label'):
            self.icc_intent_label.setVisible(icc_visible)
        self.summary_timer.start()
        if self.mode == 'review':
            self.timer.start()

    def start_preview(self):
        if self.mode != 'review':
            return
        photo = self.selected()
        if not photo:
            return
        if self.preview_worker and self.preview_worker.isRunning():
            self.preview_pending = True
            return
        self.preview_pending = False
        version = self.preview_version
        settings = self.settings()
        edit = replace(self.edits.get(str(photo.path), Edit()))
        show_original = self.original_check.isChecked()
        show_proof = self.proof_check.isChecked() and settings.output_space == 'ICC'
        def work():
            settings.validate()
            im, notes = load_rgb(photo.path, 1800)
            if show_original:
                out = oriented(im, edit)
            else:
                out = render(im, settings, edit, 1400, notes=notes)
                if show_proof:
                    out = proof(out, settings)
            diagnostics = analyze(im)
            notes.append(f"Анализ исходника: глубокие тени {diagnostics['shadow_percent']}%, почти белые участки {diagnostics['highlight_percent']}%.")
            info = assess(photo.size, settings, edit)
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

    def preview_finished(self):
        if self.preview_pending:
            self.timer.start(20)

    def edit_photo(self):
        photo = self.selected()
        if not photo:
            return
        try:
            self.settings().validate()
            # Uses the already bounded preview decoder, never modifies the source.
            im, _ = load_rgb(photo.path, 1800)
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
            return json.loads(self.store.value('preset_library', '{}'))
        except (TypeError, ValueError):
            return {}

    def refresh_library(self):
        self.recipe_library.clear()
        self.recipe_library.addItem('Мои пресеты · загрузить…', None)
        for name in sorted(self.library()):
            self.recipe_library.addItem(name, name)

    def save_library(self):
        try:
            settings = self.settings()
            settings.validate()
            name, ok = QInputDialog.getText(self, 'Сохранить пресет', 'Название машины / бумаги / обработки:')
            name = name.strip()[:100]
            if not ok or not name:
                return
            library = self.library()
            if name in library and QMessageBox.question(self, 'Заменить пресет?', f'Обновить «{name}»?') != QMessageBox.StandardButton.Yes:
                return
            library[name] = asdict(settings)
            self.store.setValue('preset_library', json.dumps(library, ensure_ascii=False))
            self.refresh_library()
            self.status.setText(f'Пресет «{name}» сохранён в библиотеку. Для переноса на другой ПК сохраните рецепт JSON.')
        except Exception as e:
            self.error(str(e))

    def load_library(self, index):
        name = self.recipe_library.itemData(index)
        if not name:
            return
        try:
            settings = Settings(**self.library()[name])
            settings.validate()
            self.apply_settings(settings)
            self.status.setText(f'Загружен пресет «{name}». Индивидуальные кадры сохранены.')
        except Exception as e:
            self.error(str(e))

    def delete_library(self):
        library = self.library()
        names = sorted(library)
        if not names:
            self.status.setText('В библиотеке пока нет пользовательских пресетов.')
            return
        name, ok = QInputDialog.getItem(self, 'Удалить пресет', 'Выберите:', names, 0, False)
        if ok:
            del library[name]
            self.store.setValue('preset_library', json.dumps(library, ensure_ascii=False))
            self.refresh_library()

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
            self.apply_settings(settings)
            self.status.setText('Рецепт загружен. Кадры сопоставлены по относительным именам файлов текущей папки.')
        except Exception as e:
            self.error(str(e))

    def error(self, text):
        QMessageBox.warning(self, 'Print Prep', text)

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
