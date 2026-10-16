"""Right panel: batch preset settings and per-photo adjustments, applied live."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ..model import ADJUST_RANGES, LOOKS, PAPER_SIZES, Edit, Settings, mm_to_px
from . import icons
from .controls import (Chip, ChipToggle, FlowRow, ParamSlider, Section, Segmented, Switch, button, hline, label,
                       tool)
from .theme import T

GRADIENTS = {'temperature': ['#3d7bff', '#9aa3b5', '#ffc23d'], 'tint': ['#3fbf5f', '#a3a3ab', '#d24fc6']}
LIGHT = ('exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks')
COLOR = ('temperature', 'tint', 'vibrance', 'saturation')
DETAIL = ('clarity', 'dehaze', 'denoise', 'color_denoise')
PIXEL_PRESETS = [('4K UHD · 3840 × 2160', 3840, 2160), ('Full HD · 1920 × 1080', 1920, 1080),
                 ('8K · 7680 × 4320', 7680, 4320), ('Instagram 4:5 · 1080 × 1350', 1080, 1350),
                 ('Квадрат · 2048 × 2048', 2048, 2048), ('A4 при 300 PPI · 2480 × 3508', 2480, 3508)]
ASPECTS = [('Как у снимка', None), ('1:1', 1.0), ('4:5', .8), ('3:2', 1.5), ('16:9', 16 / 9)]


def _spin(low, high, suffix='', decimals=0, step=1):
    w = QDoubleSpinBox() if decimals else QSpinBox()
    w.setRange(low, high)
    if decimals:
        w.setDecimals(decimals)
    w.setSingleStep(step)
    w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    w.setMinimumWidth(64)
    w.wheelEvent = lambda e: e.ignore()
    return w


def _combo(items):
    c = QComboBox()
    for text, data in items:
        c.addItem(text, data)
    c.wheelEvent = lambda e: e.ignore()
    # Shrink with the panel instead of forcing it wider than the window; the popup stays wide.
    c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(6)
    c.view().setMinimumWidth(max(220, c.view().sizeHintForColumn(0) + 32))
    return c


def _row(title, widget, hint=None):
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(8, 0, 0, 0)
    lay.setSpacing(8)
    t = label(title, 'Muted')
    t.setMinimumWidth(86)
    if hint:
        t.setToolTip(hint)
        widget.setToolTip(hint)
    lay.addWidget(t)
    lay.addWidget(widget, 1)
    return box


def _scroll(widget):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


class Inspector(QWidget):
    settingsEdited = Signal(object, bool)      # Settings, commit
    editEdited = Signal(object, bool)          # Edit, commit
    action = Signal(str)
    scopeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('RightPanel')
        self.setMinimumWidth(330)
        self.setMaximumWidth(420)
        self.settings = Settings()
        self.edit = Edit()
        self.photo = None
        self.scope = 'batch'
        self._updating = False
        self.store = QSettings('PrintPrep', 'PrintPrep2')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(14, 12, 14, 10)
        tl.setSpacing(8)
        self.scope_switch = Segmented([('Все фото', 'batch', 'Настройки пресета — для всей папки'),
                                       ('Этот снимок', 'photo', 'Правки только выбранного снимка поверх пресета')])
        self.scope_switch.setValue('batch')
        self.scope_switch.changed.connect(self.set_scope)
        tl.addWidget(self.scope_switch)
        self.scope_hint = label('', 'Hint', wrap=True)
        tl.addWidget(self.scope_hint)
        outer.addWidget(top)
        outer.addWidget(hline())
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.batch_controls = {}
        self.photo_controls = {}
        self._build_batch()
        self._build_photo()
        self.set_scope('batch', emit=False)

    # ------------------------------------------------------------ helpers
    def _section(self, key, title, icon_name, opened=True):
        stored = self.store.value(f'section/{key}', None)
        section = Section(title, icon_name, opened if stored is None else stored in (True, 'true'))
        section.toggled.connect(lambda v, k=key: self.store.setValue(f'section/{k}', v))
        return section

    def _slider(self, key, controls, photo=False):
        title, low, high, step, unit = ADJUST_RANGES[key]
        s = ParamSlider(title, low, high, step, 0, unit, gradient=GRADIENTS.get(key))
        s.valueChanged.connect(lambda v, k=key, p=photo: self._adjust_changed(k, v, p, False))
        s.editingFinished.connect(lambda k=key, p=photo: self._adjust_changed(k, None, p, True))
        controls[key] = s
        return s

    # ------------------------------------------------------------ batch page
    def _build_batch(self):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 16)
        lay.setSpacing(0)
        c = self.batch_controls

        # Size & framing
        sec = self._section('size', 'Размер и кадр', 'crop')
        c['size_mode'] = Segmented([('Оригинал', 'original', 'Сохранить исходные пиксели'), ('Печать', 'print', 'Размер отпечатка в мм и PPI'),
                                    ('Пиксели', 'pixels', 'Точный размер в пикселях'), ('Сторона', 'long_edge', 'Длинная сторона в пикселях')], compact=True)
        c['size_mode'].changed.connect(lambda v: self._set('size_mode', v, commit=True))
        sec.layout.addWidget(c['size_mode'])
        self.print_box = QWidget()
        pl = QVBoxLayout(self.print_box)
        pl.setContentsMargins(0, 4, 0, 0)
        pl.setSpacing(6)
        c['paper'] = _combo([(n, (w, h)) for n, w, h in PAPER_SIZES] + [('Свой размер', None)])
        c['paper'].activated.connect(self._paper_chosen)
        pl.addWidget(_row('Формат', c['paper']))
        dims = QWidget()
        dl = QHBoxLayout(dims)
        dl.setContentsMargins(8, 0, 0, 0)
        dl.setSpacing(6)
        dl.addWidget(label('Размер, мм', 'Muted'), 0)
        dl.itemAt(0).widget().setMinimumWidth(86)
        c['width_mm'] = _spin(10, 2000, '', 1, 1)
        c['height_mm'] = _spin(10, 2000, '', 1, 1)
        c['width_mm'].valueChanged.connect(lambda v: self._set('width_mm', float(v), commit=True))
        c['height_mm'].valueChanged.connect(lambda v: self._set('height_mm', float(v), commit=True))
        dl.addWidget(c['width_mm'], 1)
        dl.addWidget(label('×', 'Hint'))
        dl.addWidget(c['height_mm'], 1)
        swap = tool('swap', 'Поменять стороны местами', self._swap_sides, size=16)
        dl.addWidget(swap)
        pl.addWidget(dims)
        c['dpi'] = _spin(72, 1200, ' PPI')
        c['dpi'].valueChanged.connect(lambda v: self._set('dpi', int(v), commit=True))
        pl.addWidget(_row('Разрешение', c['dpi'], 'Плотность пикселей файла (не DPI принтера). Для фотопечати — 300.'))
        self.pixel_note = label('', 'Hint', wrap=True)
        pl.addWidget(self.pixel_note)
        sec.layout.addWidget(self.print_box)
        self.pixels_box = QWidget()
        xl = QVBoxLayout(self.pixels_box)
        xl.setContentsMargins(0, 4, 0, 0)
        xl.setSpacing(6)
        c['pixel_preset'] = _combo([('Свой размер', None)] + [(n, (w, h)) for n, w, h in PIXEL_PRESETS])
        c['pixel_preset'].activated.connect(self._pixel_preset_chosen)
        xl.addWidget(_row('Шаблон', c['pixel_preset']))
        pdims = QWidget()
        pdl = QHBoxLayout(pdims)
        pdl.setContentsMargins(8, 0, 0, 0)
        pdl.setSpacing(6)
        pdl.addWidget(label('Размер, px', 'Muted'))
        pdl.itemAt(0).widget().setMinimumWidth(86)
        c['pixel_width'] = _spin(16, 32768)
        c['pixel_height'] = _spin(16, 32768)
        c['pixel_width'].valueChanged.connect(lambda v: self._set('pixel_width', int(v), commit=True))
        c['pixel_height'].valueChanged.connect(lambda v: self._set('pixel_height', int(v), commit=True))
        pdl.addWidget(c['pixel_width'], 1)
        pdl.addWidget(label('×', 'Hint'))
        pdl.addWidget(c['pixel_height'], 1)
        xl.addWidget(pdims)
        sec.layout.addWidget(self.pixels_box)
        self.edge_box = QWidget()
        el = QVBoxLayout(self.edge_box)
        el.setContentsMargins(0, 4, 0, 0)
        c['long_edge'] = _spin(16, 32768, ' px')
        c['long_edge'].valueChanged.connect(lambda v: self._set('long_edge', int(v), commit=True))
        el.addWidget(_row('Длинная сторона', c['long_edge']))
        quick = QHBoxLayout()
        quick.setContentsMargins(100, 0, 0, 0)
        for value in (2048, 3840, 6000):
            b = QPushButton(f'{value}')
            b.setObjectName('Ghost')
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self._set('long_edge', v, commit=True, refresh=True))
            quick.addWidget(b)
        quick.addStretch()
        el.addLayout(quick)
        sec.layout.addWidget(self.edge_box)
        self.original_note = label('Пиксели не меняются. Можно обрезать отдельные снимки во вкладке «Этот снимок».', 'Hint', wrap=True)
        sec.layout.addWidget(self.original_note)
        self.fit_box = QWidget()
        fl = QVBoxLayout(self.fit_box)
        fl.setContentsMargins(0, 6, 0, 0)
        fl.setSpacing(4)
        c['fit'] = Segmented([('Заполнить', 'cover', 'Заполнить формат, обрезав лишнее'), ('Вписать', 'contain', 'Весь кадр, с полями')], compact=True)
        c['fit'].changed.connect(lambda v: self._set('fit', v, commit=True))
        fl.addWidget(c['fit'])
        c['smart_crop'] = Switch('Умный кадр: лица и главное в кадре')
        c['smart_crop'].toggled.connect(lambda v: self._set('smart_crop', v, commit=True))
        fl.addWidget(c['smart_crop'])
        c['auto_orientation'] = Switch('Поворачивать формат под снимок')
        c['auto_orientation'].toggled.connect(lambda v: self._set('auto_orientation', v, commit=True))
        fl.addWidget(c['auto_orientation'])
        borders = QWidget()
        bl = QHBoxLayout(borders)
        bl.setContentsMargins(8, 0, 0, 0)
        bl.setSpacing(6)
        bl.addWidget(label('Поля, мм', 'Muted'))
        bl.itemAt(0).widget().setMinimumWidth(86)
        c['border_mm'] = _spin(0, 100, '', 1, .5)
        c['border_mm'].valueChanged.connect(lambda v: self._set('border_mm', float(v), commit=True))
        bl.addWidget(c['border_mm'], 1)
        c['background'] = _combo([('Белые', '#ffffff'), ('Чёрные', '#000000'), ('Серые', '#808080')])
        c['background'].activated.connect(lambda _: self._set('background', c['background'].currentData(), commit=True))
        bl.addWidget(c['background'], 1)
        self.border_row = borders
        fl.addWidget(borders)
        sec.layout.addWidget(self.fit_box)
        c['allow_upscale'] = Switch('Разрешить увеличение маленьких фото')
        c['allow_upscale'].toggled.connect(lambda v: self._set('allow_upscale', v, commit=True))
        sec.layout.addWidget(c['allow_upscale'])
        lay.addWidget(sec)

        # Light & colour
        sec = self._section('light', 'Свет и цвет', 'sun')
        reset = tool('reset', 'Сбросить свет и цвет', lambda: self._reset_adjust(LIGHT + COLOR), size=15)
        sec.add_header_widget(reset)
        auto = QWidget()
        auto.setObjectName('Card')
        al = QVBoxLayout(auto)
        al.setContentsMargins(10, 8, 10, 10)
        al.setSpacing(6)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap('sparkles', T['accent_hover'], 18))
        head.addWidget(ic)
        c['auto'] = Switch('Умная авто-коррекция')
        c['auto'].setToolTip('Анализирует каждый снимок отдельно: баланс белого (обученная модель + нейтральные участки),\n'
                             'экспозиция с учётом лиц, тени/света, контраст, сочность, дымка и шум.')
        c['auto'].toggled.connect(lambda v: self._set_adjust('auto', v, commit=True))
        head.addWidget(c['auto'], 1)
        al.addLayout(head)
        c['auto_strength'] = ParamSlider('Сила', 0, 100, 1, 70, '%')
        c['auto_strength'].default = 70
        c['auto_strength'].valueChanged.connect(lambda v: self._set_adjust('auto_strength', v, commit=False))
        c['auto_strength'].editingFinished.connect(lambda: self._set_adjust('auto_strength', None, commit=True))
        al.addWidget(c['auto_strength'])
        toggles = QHBoxLayout()
        toggles.setSpacing(4)
        for key, text, tip in (('auto_wb', 'Баланс белого', 'Нейтрализовать цветной оттенок освещения'),
                               ('auto_light', 'Свет', 'Экспозиция, тени, света, контраст, дымка'),
                               ('auto_color', 'Цвет', 'Сочность для блёклых снимков'),
                               ('auto_noise', 'Шум', 'Шумоподавление по оценке шума снимка')):
            chip = ChipToggle(text)
            chip.setToolTip(tip)
            chip.toggled.connect(lambda v, k=key: self._set_adjust(k, v, commit=True))
            c[key] = chip
            toggles.addWidget(chip)
        toggles.addStretch()
        al.addLayout(toggles)
        self.batch_auto_caption = label('Для текущего снимка авто сделало:', 'Hint')
        al.addWidget(self.batch_auto_caption)
        self.batch_auto_notes = FlowRow()
        al.addWidget(self.batch_auto_notes)
        self.auto_card = auto
        sec.layout.addWidget(auto)
        sec.layout.addSpacing(4)
        for key in LIGHT:
            sec.layout.addWidget(self._slider(key, c))
        sec.layout.addSpacing(6)
        for key in COLOR:
            sec.layout.addWidget(self._slider(key, c))
        lay.addWidget(sec)

        sec = self._section('detail', 'Детали и шум', 'detail', opened=False)
        sec.add_header_widget(tool('reset', 'Сбросить детали', lambda: self._reset_adjust(DETAIL), size=15))
        for key in DETAIL:
            sec.layout.addWidget(self._slider(key, c))
        lay.addWidget(sec)

        sec = self._section('look', 'Стиль', 'palette', opened=False)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.look_buttons = {}
        for i, (key, (name, _)) in enumerate(LOOKS.items()):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f'''QPushButton {{ padding: 8px 6px; font-size: 12px; }}
                QPushButton:checked {{ background: rgba(76,141,255,0.18); border-color: {T["accent"]}; color: #cfe0ff; }}''')
            b.clicked.connect(lambda _=False, k=key: self._set_adjust('look', k, commit=True))
            self.look_buttons[key] = b
            grid.addWidget(b, i // 3, i % 3)
        sec.layout.addLayout(grid)
        c['look_strength'] = ParamSlider('Сила стиля', 0, 100, 1, 100, '%')
        c['look_strength'].default = 100
        c['look_strength'].valueChanged.connect(lambda v: self._set_adjust('look_strength', v, commit=False))
        c['look_strength'].editingFinished.connect(lambda: self._set_adjust('look_strength', None, commit=True))
        sec.layout.addWidget(c['look_strength'])
        lay.addWidget(sec)

        sec = self._section('neural', 'Нейросеть', 'cpu', opened=False)
        c['upscaler'] = Segmented([('Выкл', 'off'), ('Быстро ×2', 'fsrcnn', 'FSRCNN ×2 — лёгкая, быстрая'),
                                   ('Качество ×4', 'esrgan', 'Real-ESRGAN ×4 — восстанавливает детали, чистит JPEG-артефакты и шум')], compact=True)
        c['upscaler'].changed.connect(lambda v: self._set('upscaler', v, commit=True))
        sec.layout.addWidget(c['upscaler'])
        c['neural_strength'] = ParamSlider('Сила', 0, 100, 1, 100, '%')
        c['neural_strength'].default = 100
        c['neural_strength'].valueChanged.connect(lambda v: self._set('neural_strength', v, commit=False))
        c['neural_strength'].editingFinished.connect(lambda: self._set('neural_strength', None, commit=True))
        sec.layout.addWidget(c['neural_strength'])
        c['neural_always'] = Switch('Чистить и без увеличения')
        c['neural_always'].setToolTip('Пропустить снимок через нейросеть, даже если он не увеличивается:\n'
                                      'убирает JPEG-артефакты и шум у плохих исходников. Медленно; до 6 Мп.')
        c['neural_always'].toggled.connect(lambda v: self._set('neural_always', v, commit=True))
        sec.layout.addWidget(c['neural_always'])
        self.neural_hint = label('Работает локально на процессоре. Эффект виден в масштабе 100% — '
                                 'там же показывается прогресс.', 'Hint', wrap=True)
        sec.layout.addWidget(self.neural_hint)
        sec.layout.addWidget(button('Посмотреть в 100%', lambda: self.action.emit('view100'), icon_name='eye'))
        lay.addWidget(sec)

        sec = self._section('output', 'Печать и файл', 'printer')
        c['format'] = Segmented([('JPEG', 'JPEG', 'Компактно, для лабораторий и печати'), ('TIFF', 'TIFF', 'Без потерь, 8 или 16 бит'),
                                 ('PNG', 'PNG', 'Без потерь, 8 или 16 бит')], compact=True)
        c['format'].changed.connect(self._format_changed)
        sec.layout.addWidget(c['format'])
        c['quality'] = ParamSlider('Качество JPEG', 50, 100, 1, 95)
        c['quality'].default = 95
        c['quality'].valueChanged.connect(lambda v: self._set('quality', int(v), commit=False))
        c['quality'].editingFinished.connect(lambda: self._set('quality', None, commit=True))
        sec.layout.addWidget(c['quality'])
        c['bit_depth'] = Segmented([('8 бит', 8), ('16 бит', 16, 'Больше градаций для ретуши и архива')], compact=True)
        c['bit_depth'].changed.connect(lambda v: self._set('bit_depth', v, commit=True))
        self.depth_row = _row('Глубина', c['bit_depth'])
        sec.layout.addWidget(self.depth_row)
        c['output_space'] = Segmented([('sRGB', 'sRGB', 'Стандарт лабораторий и экранов'), ('ICC принтера', 'ICC', 'Преобразовать в профиль машины и бумаги')], compact=True)
        c['output_space'].changed.connect(self._space_changed)
        sec.layout.addWidget(_row('Цвет', c['output_space']))
        self.icc_box = QWidget()
        il = QVBoxLayout(self.icc_box)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(6)
        icc_row = QHBoxLayout()
        icc_row.setContentsMargins(8, 0, 0, 0)
        self.icc_label = label('Профиль не выбран', 'Hint')
        self.icc_label.setWordWrap(True)
        icc_row.addWidget(self.icc_label, 1)
        icc_row.addWidget(button('Выбрать…', self._choose_icc, icon_name='file'))
        il.addLayout(icc_row)
        c['intent'] = _combo([('Относительный + BPC', 1), ('Перцепционный + BPC', 0)])
        c['intent'].activated.connect(lambda _: self._set('intent', c['intent'].currentData(), commit=True))
        il.addWidget(_row('Метод', c['intent'], 'Относительный — точнее для фото; перцепционный — мягче для насыщенных цветов вне охвата.'))
        sec.layout.addWidget(self.icc_box)
        sec.layout.addSpacing(4)
        c['sharpen'] = Segmented([('Выкл', 'off'), ('Экран', 'screen'), ('Глянец', 'glossy'), ('Мат', 'matte')], compact=True)
        c['sharpen'].changed.connect(lambda v: self._set('sharpen', v, commit=True))
        sec.layout.addWidget(_row('Резкость для', c['sharpen'], 'Выходная резкость после изменения размера: радиус зависит от PPI и бумаги.'))
        c['sharpen_amount'] = Segmented([('Слабо', 'low'), ('Норма', 'standard'), ('Сильно', 'high')], compact=True)
        c['sharpen_amount'].changed.connect(lambda v: self._set('sharpen_amount', v, commit=True))
        self.amount_row = _row('Сила', c['sharpen_amount'])
        sec.layout.addWidget(self.amount_row)
        c['print_brightness'] = ParamSlider('Яркость отпечатка', 0, 40, 1, 0, '%')
        c['print_brightness'].setToolTip('Отпечаток темнее светящегося экрана. Поднимает средние тона,\n'
                                         'не трогая чёрное и белое. Подберите по пробному отпечатку.')
        c['print_brightness'].valueChanged.connect(lambda v: self._set('print_brightness', v, commit=False))
        c['print_brightness'].editingFinished.connect(lambda: self._set('print_brightness', None, commit=True))
        sec.layout.addWidget(c['print_brightness'])
        c['keep_exif'] = Switch('Сохранять EXIF (без GPS)')
        c['keep_exif'].toggled.connect(lambda v: self._set('keep_exif', v, commit=True))
        sec.layout.addWidget(c['keep_exif'])
        lay.addWidget(sec)
        lay.addStretch()
        self.pages.addWidget(_scroll(body))

    # ------------------------------------------------------------ photo page
    def _build_photo(self):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 16)
        lay.setSpacing(0)
        c = self.photo_controls
        card = QWidget()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(4)
        self.photo_name = label('', 'Title')
        self.photo_meta = label('', 'Hint', wrap=True)
        cl.addWidget(self.photo_name)
        cl.addWidget(self.photo_meta)
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.reset_photo_btn = button('Сбросить', lambda: self.action.emit('reset_photo'), icon_name='reset')
        self.to_preset_btn = button('В пресет', lambda: self.action.emit('to_preset'), icon_name='layers')
        self.to_preset_btn.setToolTip('Перенести цветовые правки этого снимка в пресет — для всех фото')
        self.copy_btn = button('Копировать', lambda: self.action.emit('copy_edits'))
        self.copy_btn.setIcon(icons.icon('copy'))
        self.copy_btn.setToolTip('Применить правки этого снимка к выбранным в ленте (Ctrl+Shift+V)')
        actions.addWidget(self.reset_photo_btn)
        actions.addWidget(self.to_preset_btn)
        actions.addWidget(self.copy_btn)
        cl.addLayout(actions)
        lay.addWidget(card)
        lay.addWidget(hline())

        sec = self._section('photo_frame', 'Кадр', 'crop')
        row = QHBoxLayout()
        row.setSpacing(6)
        self.crop_btn = button('Изменить кадр', lambda: self.action.emit('crop'), icon_name='crop')
        self.crop_btn.setCheckable(True)
        row.addWidget(self.crop_btn, 1)
        row.addWidget(tool('rotate_left', 'Повернуть против часовой (Ctrl+[)', lambda: self.action.emit('rotate_left')))
        row.addWidget(tool('rotate_right', 'Повернуть по часовой (Ctrl+])', lambda: self.action.emit('rotate_right')))
        sec.layout.addLayout(row)
        c['angle'] = ParamSlider('Горизонт', -20, 20, .1, 0, '°', decimals=1)
        c['angle'].valueChanged.connect(lambda v: self._edit_set('angle', v, False))
        c['angle'].editingFinished.connect(lambda: self._edit_set('angle', None, True))
        sec.layout.addWidget(c['angle'])
        c['fit'] = Segmented([('Как в пресете', None), ('Заполнить', 'cover'), ('Вписать', 'contain')], compact=True)
        c['fit'].changed.connect(lambda v: self._edit_set('fit', v, True))
        self.photo_fit_row = c['fit']
        sec.layout.addWidget(c['fit'])
        c['aspect'] = Segmented(ASPECTS, compact=True)
        c['aspect'].changed.connect(lambda v: self._edit_set('aspect', v, True))
        self.photo_aspect = c['aspect']
        sec.layout.addWidget(c['aspect'])
        sec.layout.addWidget(button('Сбросить кадр', lambda: self.action.emit('reset_frame'), 'Ghost', 'reset'))
        lay.addWidget(sec)

        sec = self._section('photo_light', 'Свет и цвет', 'sun')
        sec.layout.addWidget(label('Авто-коррекция для этого снимка:', 'Hint'))
        self.photo_auto_notes = FlowRow()
        sec.layout.addWidget(self.photo_auto_notes)
        for key in LIGHT:
            sec.layout.addWidget(self._slider(key, c, photo=True))
        sec.layout.addSpacing(6)
        for key in COLOR:
            sec.layout.addWidget(self._slider(key, c, photo=True))
        lay.addWidget(sec)
        sec = self._section('photo_detail', 'Детали и шум', 'detail', opened=False)
        for key in DETAIL:
            sec.layout.addWidget(self._slider(key, c, photo=True))
        lay.addWidget(sec)
        sec = self._section('photo_neural', 'Нейросеть', 'cpu', opened=False)
        c['neural'] = Segmented([('Как в пресете', None), ('Вкл', True), ('Выкл', False)], compact=True)
        c['neural'].changed.connect(lambda v: self._edit_set('neural', v, True))
        sec.layout.addWidget(c['neural'])
        sec.layout.addWidget(button('Посмотреть в 100%', lambda: self.action.emit('view100'), icon_name='eye'))
        lay.addWidget(sec)
        lay.addWidget(label('   Размер, стиль и формат файла задаются для всей партии.', 'Hint'))
        lay.addStretch()
        self.pages.addWidget(_scroll(body))

    # ------------------------------------------------------------ state in
    def set_scope(self, scope, emit=True):
        if scope == 'photo' and self.photo is None:
            scope = 'batch'
        self.scope = scope
        self.scope_switch.setValue(scope)
        self.pages.setCurrentIndex(0 if scope == 'batch' else 1)
        self.scope_hint.setText('Пресет: применяется ко всем фото папки.' if scope == 'batch'
                                else 'Правки только этого снимка — поверх пресета. Метка на шкале — значение пресета.')
        if emit:
            self.scopeChanged.emit(scope)

    def set_state(self, settings: Settings, edit: Edit | None, photo=None, analysis=None, auto_offsets=None):
        self._updating = True
        try:
            self.settings = replace(settings, adjust=replace(settings.adjust))
            self.edit = replace(edit or Edit(), offsets=dict((edit or Edit()).offsets))
            self.photo = photo
            self.scope_switch.setItemEnabled('photo', photo is not None)
            self._sync_batch()
            self._sync_photo()
            self.set_auto_notes(analysis, auto_offsets)
        finally:
            self._updating = False

    def set_auto_notes(self, analysis, auto_offsets=None):
        for flow in (self.batch_auto_notes, self.photo_auto_notes):
            flow.clear()
        if not self.settings.adjust.auto:
            note = Chip('Авто выключено', 'neutral')
            self.photo_auto_notes.add(note)
            return
        if analysis is None:
            for flow in (self.batch_auto_notes, self.photo_auto_notes):
                flow.add(Chip('Анализ при просмотре снимка…', 'neutral'))
            return
        notes = list(analysis.get('notes', []))
        offsets = auto_offsets or {}
        for key in ('shadows', 'highlights', 'contrast', 'vibrance', 'denoise'):
            value = offsets.get(key, 0)
            if abs(value) >= 5:
                notes.append(f'{ADJUST_RANGES[key][0]} {value:+.0f}'.replace('-', '−'))
        if not notes:
            notes = ['Снимок в порядке — правки минимальны']
        for flow in (self.batch_auto_notes, self.photo_auto_notes):
            for text in notes:
                flow.add(Chip(text, 'neutral'))

    def _sync_batch(self):
        s, c = self.settings, self.batch_controls
        c['size_mode'].setValue(s.size_mode)
        for key in ('width_mm', 'height_mm', 'dpi', 'pixel_width', 'pixel_height', 'long_edge', 'border_mm'):
            c[key].blockSignals(True)
            c[key].setValue(getattr(s, key))
            c[key].blockSignals(False)
        paper = next((i for i in range(c['paper'].count()) if c['paper'].itemData(i)
                      and tuple(c['paper'].itemData(i)) in ((s.width_mm, s.height_mm), (s.height_mm, s.width_mm))), c['paper'].count() - 1)
        c['paper'].setCurrentIndex(paper)
        pix = next((i for i in range(c['pixel_preset'].count()) if c['pixel_preset'].itemData(i)
                    and tuple(c['pixel_preset'].itemData(i)) == (s.pixel_width, s.pixel_height)), 0)
        c['pixel_preset'].setCurrentIndex(pix)
        mode = s.size_mode
        self.print_box.setVisible(mode == 'print')
        self.pixels_box.setVisible(mode == 'pixels')
        self.edge_box.setVisible(mode == 'long_edge')
        self.original_note.setVisible(mode == 'original')
        self.fit_box.setVisible(mode in ('print', 'pixels'))
        self.border_row.setVisible(mode == 'print')
        c['allow_upscale'].setVisible(mode != 'original')
        if mode == 'print':
            w, h = mm_to_px(s.width_mm, s.dpi), mm_to_px(s.height_mm, s.dpi)
            self.pixel_note.setText(f'Файл: {w} × {h} px · {w * h / 1e6:.1f} Мп')
        c['fit'].setValue(s.fit)
        c['smart_crop'].setEnabled(s.fit == 'cover')
        for key in ('smart_crop', 'auto_orientation', 'allow_upscale', 'neural_always', 'keep_exif'):
            c[key].blockSignals(True)
            c[key].setChecked(getattr(s, key))
            c[key].blockSignals(False)
        idx = c['background'].findData(s.background)
        c['background'].setCurrentIndex(max(0, idx))
        a = s.adjust
        c['auto'].blockSignals(True)
        c['auto'].setChecked(a.auto)
        c['auto'].blockSignals(False)
        c['auto_strength'].setValue(a.auto_strength)
        for key in ('auto_strength', 'auto_wb', 'auto_light', 'auto_color', 'auto_noise'):
            c[key].setEnabled(a.auto)
        for key in ('auto_wb', 'auto_light', 'auto_color', 'auto_noise'):
            c[key].blockSignals(True)
            c[key].setChecked(getattr(a, key))
            c[key].blockSignals(False)
        self.batch_auto_notes.setVisible(a.auto)
        self.batch_auto_caption.setVisible(a.auto)
        for key in LIGHT + COLOR + DETAIL:
            c[key].setBaseline(None)
            c[key].setValue(getattr(a, key))
        for key, b in self.look_buttons.items():
            b.setChecked(key == a.look)
        c['look_strength'].setValue(a.look_strength)
        c['look_strength'].setEnabled(a.look != 'none')
        c['upscaler'].setValue(s.upscaler)
        c['neural_strength'].setValue(s.neural_strength)
        c['neural_strength'].setEnabled(s.upscaler != 'off')
        c['neural_always'].setEnabled(s.upscaler != 'off')
        c['format'].setValue(s.format)
        c['quality'].setValue(s.quality)
        c['quality'].setVisible(s.format == 'JPEG')
        c['bit_depth'].setValue(s.bit_depth)
        self.depth_row.setVisible(s.format != 'JPEG')
        c['bit_depth'].setItemEnabled(16, s.output_space == 'sRGB')
        c['output_space'].setValue(s.output_space)
        self.icc_box.setVisible(s.output_space == 'ICC')
        self.icc_label.setText(Path(s.icc_path).name if s.icc_path else 'Профиль не выбран')
        self.icc_label.setToolTip(s.icc_path)
        c['intent'].setCurrentIndex(max(0, c['intent'].findData(s.intent)))
        c['sharpen'].setValue(s.sharpen)
        c['sharpen_amount'].setValue(s.sharpen_amount)
        self.amount_row.setVisible(s.sharpen != 'off')
        c['print_brightness'].setValue(s.print_brightness)

    def _sync_photo(self):
        c, e, a = self.photo_controls, self.edit, self.settings.adjust
        if self.photo is not None:
            p = self.photo
            self.photo_name.setText(p.path.name)
            self.photo_meta.setText(f'{p.size[0]} × {p.size[1]} px · {p.megapixels:.1f} Мп · {p.bits} бит · {p.profile}')
        has_edits = not e.is_default()
        self.reset_photo_btn.setEnabled(has_edits)
        self.to_preset_btn.setEnabled(bool(e.offsets))
        c['angle'].setValue(e.angle)
        c['fit'].setValue(e.fit)
        c['aspect'].setValue(e.aspect)
        frame_modes = self.settings.size_mode in ('print', 'pixels')
        self.photo_fit_row.setVisible(frame_modes)
        self.photo_aspect.setVisible(not frame_modes)
        for key in LIGHT + COLOR + DETAIL:
            base = getattr(a, key)
            _, low, high, _, _ = ADJUST_RANGES[key]
            c[key].setBaseline(base)
            c[key].setValue(min(high, max(low, base + e.offsets.get(key, 0))))
        c['neural'].setValue(e.neural)

    def set_crop_mode(self, on):
        self.crop_btn.blockSignals(True)
        self.crop_btn.setChecked(on)
        self.crop_btn.blockSignals(False)

    # ------------------------------------------------------------ state out
    def _set(self, key, value, commit, refresh=False):
        if self._updating:
            return
        if value is None:
            value = getattr(self.settings, key)
        if key == 'size_mode' and value != 'print':
            self.settings.border_mm = 0
        if key == 'format' and value == 'JPEG':
            self.settings.bit_depth = 8
        setattr(self.settings, key, value)
        if key in ('size_mode', 'fit', 'upscaler', 'format', 'output_space', 'sharpen', 'width_mm', 'height_mm', 'dpi') or refresh:
            self._updating = True
            self._sync_batch()
            self._updating = False
        self.settingsEdited.emit(replace(self.settings, adjust=replace(self.settings.adjust)), commit)

    def _set_adjust(self, key, value, commit):
        if self._updating:
            return
        if value is not None:
            setattr(self.settings.adjust, key, value)
        if key in ('auto', 'look'):
            self._updating = True
            self._sync_batch()
            self._updating = False
        self.settingsEdited.emit(replace(self.settings, adjust=replace(self.settings.adjust)), commit)

    def _adjust_changed(self, key, value, photo, commit):
        if self._updating:
            return
        if not photo:
            self._set_adjust(key, value, commit)
            return
        if value is not None:
            delta = value - getattr(self.settings.adjust, key)
            if abs(delta) < 1e-6:
                self.edit.offsets.pop(key, None)
            else:
                self.edit.offsets[key] = round(delta, 4)
        self.to_preset_btn.setEnabled(bool(self.edit.offsets))
        self.reset_photo_btn.setEnabled(not self.edit.is_default())
        self.editEdited.emit(replace(self.edit, offsets=dict(self.edit.offsets)), commit)

    def _edit_set(self, key, value, commit):
        if self._updating:
            return
        if value is not None or key in ('fit', 'aspect', 'neural'):
            if key == 'angle' and value is None:
                pass
            else:
                setattr(self.edit, key, value)
        if key == 'aspect':
            self.edit.manual_crop = self.edit.manual_crop or value is not None
        self.reset_photo_btn.setEnabled(not self.edit.is_default())
        self.editEdited.emit(replace(self.edit, offsets=dict(self.edit.offsets)), commit)

    def _reset_adjust(self, keys):
        if self.scope == 'photo':
            for key in keys:
                self.edit.offsets.pop(key, None)
            self._updating = True
            self._sync_photo()
            self._updating = False
            self.editEdited.emit(replace(self.edit, offsets=dict(self.edit.offsets)), True)
            return
        for key in keys:
            setattr(self.settings.adjust, key, 0)
        self._updating = True
        self._sync_batch()
        self._updating = False
        self.settingsEdited.emit(replace(self.settings, adjust=replace(self.settings.adjust)), True)

    def _paper_chosen(self, index):
        data = self.batch_controls['paper'].itemData(index)
        if not data:
            return
        w, h = data
        if (self.settings.width_mm > self.settings.height_mm) != (w > h) and w != h:
            w, h = h, w
        self.settings.width_mm, self.settings.height_mm = float(w), float(h)
        self._set('width_mm', float(w), commit=True, refresh=True)

    def _pixel_preset_chosen(self, index):
        data = self.batch_controls['pixel_preset'].itemData(index)
        if not data:
            return
        self.settings.pixel_width, self.settings.pixel_height = data
        self._set('pixel_width', data[0], commit=True, refresh=True)

    def _swap_sides(self):
        s = self.settings
        s.width_mm, s.height_mm = s.height_mm, s.width_mm
        self._set('width_mm', s.width_mm, commit=True, refresh=True)

    def _format_changed(self, value):
        self._set('format', value, commit=True)

    def _space_changed(self, value):
        if value == 'ICC' and not self.settings.icc_path:
            if not self._choose_icc():
                self._updating = True
                self.batch_controls['output_space'].setValue('sRGB')
                self._updating = False
                return
            return
        if value == 'ICC':
            self.settings.bit_depth = 8
            if self.settings.format == 'PNG':
                self.settings.format = 'TIFF'
        self._set('output_space', value, commit=True)

    def _choose_icc(self):
        path, _ = QFileDialog.getOpenFileName(self, 'ICC-профиль принтера и бумаги', '', 'ICC (*.icc *.icm);;Все файлы (*)')
        if not path:
            return False
        candidate = replace(self.settings, output_space='ICC', icc_path=path, bit_depth=8,
                            format='TIFF' if self.settings.format == 'PNG' else self.settings.format)
        try:
            candidate.validate()
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Print Prep', str(e))
            return False
        self.settings = candidate
        self._set('icc_path', path, commit=True, refresh=True)
        return True
