"""Right panel: preset card, histogram, batch preset settings and per-photo adjustments."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QScrollArea, QSpinBox, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..model import ADJUST_RANGES, LOOKS, NEURAL_MIN_SCALE, PAPER_SIZES, Edit, Settings, mm_to_px
from . import icons
from .controls import (Chip, ChipToggle, Dropdown, FlowRow, Histogram, ParamSlider, Section, Segmented, Switch, button,
                       hline, label, tool)
from .store import prefs
from .theme import ACCENTS, T, rgba
from ..i18n import tr

GRADIENTS = {'temperature': ['#3d7bff', '#9aa3b5', '#ffc23d'], 'tint': ['#3fbf5f', '#a3a3ab', '#d24fc6']}
LIGHT = ('exposure', 'contrast', 'highlights', 'shadows', 'whites', 'blacks')
COLOR = ('temperature', 'tint', 'vibrance', 'saturation')
DETAIL = ('clarity', 'dehaze', 'denoise', 'color_denoise')
PIXEL_PRESETS = [('4K UHD · 3840 × 2160', (3840, 2160)), ('Full HD · 1920 × 1080', (1920, 1080)),
                 ('8K · 7680 × 4320', (7680, 4320)), ('Instagram 4:5 · 1080 × 1350', (1080, 1350)),
                 ('Квадрат · 2048 × 2048', (2048, 2048)), ('A4 при 300 PPI · 2480 × 3508', (2480, 3508))]
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


def _row(title, widget, hint=None):
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(8, 0, 0, 0)
    lay.setSpacing(8)
    t = label(title, 'Muted')
    t.setFixedWidth(92)
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


def _note(text):
    w = label(text, 'Hint', wrap=True)
    w.setContentsMargins(8, 0, 0, 0)
    return w


class Inspector(QWidget):
    settingsEdited = Signal(object, bool)      # Settings, commit
    editEdited = Signal(object, bool)          # Edit, commit
    action = Signal(str)
    presetAction = Signal(str)
    scopeChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('RightPanel')
        self.setMinimumWidth(340)
        self.setMaximumWidth(440)
        self.settings = Settings()
        self.edit = Edit()
        self.photo = None
        self.scope = 'batch'
        self._updating = False
        self.store = prefs()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._preset_card())
        outer.addWidget(hline())
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(8)
        self.histogram = Histogram()
        tl.addWidget(self.histogram)
        self.scope_switch = Segmented([(tr('Все фото'), 'batch', tr('Настройки пресета — для всей папки')),
                                       (tr('Этот снимок'), 'photo', tr('Правки только выбранного снимка поверх пресета'))])
        self.scope_switch.setValue('batch')
        self.scope_switch.changed.connect(self.set_scope)
        tl.addWidget(self.scope_switch)
        self.scope_banner = QLabel()
        self.scope_banner.setWordWrap(True)
        self.scope_banner.setTextFormat(Qt.TextFormat.RichText)
        tl.addWidget(self.scope_banner)
        outer.addWidget(top)
        outer.addWidget(hline())
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.batch_controls = {}
        self.photo_controls = {}
        self._build_batch()
        self._build_photo()
        self.set_scope('batch', emit=False)

    # ------------------------------------------------------------ preset card
    def _preset_card(self):
        card = QWidget()
        card.setObjectName('PresetCard')
        card.setStyleSheet(f'#PresetCard {{ background: {T["panel"]}; }}')
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(label(tr('ПРЕСЕТ ДЛЯ ВСЕХ ФОТО'), 'Eyebrow'))
        self.preset_name = label(tr('Свои настройки'), None)
        self.preset_name.setStyleSheet(f'font-size: 15px; font-weight: 650; color: {T["text"]};')
        texts.addWidget(self.preset_name)
        row.addLayout(texts, 1)
        self.preset_menu_btn = QToolButton()
        self.preset_menu_btn.setText(tr('Пресет '))
        self.preset_menu_btn.setIcon(icons.icon('sliders', T['text2'], T['text']))
        self.preset_menu_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.preset_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.preset_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preset_menu_btn.setStyleSheet(f'QToolButton {{ border: 1px solid {T["border_strong"]}; background: {T["raised"]}; color: {T["text"]};'
                                           f' padding: 5px 10px; border-radius: 7px; }} QToolButton:hover {{ background: {T["hover"]}; }}')
        self.preset_menu_btn.setToolTip(tr('Настройки пресета: сохранить, переименовать, дублировать, экспорт, удалить'))
        menu = QMenu(self.preset_menu_btn)
        self.preset_actions = {}
        for key, text, icon_name in (('save', tr('Сохранить изменения'), 'save'), ('save_as', tr('Сохранить как новый…'), 'plus'),
                                     (None, None, None), ('rename', tr('Переименовать…'), 'edit'),
                                     ('duplicate', tr('Дублировать'), 'copy'), ('revert', tr('Сбросить изменения'), 'reset'),
                                     (None, None, None), ('export', tr('Экспорт в файл…'), 'download'),
                                     ('import', tr('Импорт из файла…'), 'upload'), ('delete', tr('Удалить…'), 'trash'),
                                     (None, None, None), ('manage', tr('Управление пресетами…'), 'layers')):
            if key is None:
                menu.addSeparator()
                continue
            act = menu.addAction(icons.icon(icon_name), text, lambda k=key: self.presetAction.emit(k))
            self.preset_actions[key] = act
        self.preset_menu_btn.setMenu(menu)
        row.addWidget(self.preset_menu_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(row)
        self.preset_summary = FlowRow(spacing=4)
        lay.addWidget(self.preset_summary)
        self.dirty_row = QWidget()
        dv = QVBoxLayout(self.dirty_row)
        dv.setContentsMargins(0, 4, 0, 0)
        dv.setSpacing(6)
        self.dirty_label = label(tr('Изменён'), None, wrap=True)
        self.dirty_label.setStyleSheet(f'color: {T["warning"]}; font-size: 12px;')
        dv.addWidget(self.dirty_label)
        dr = QHBoxLayout()
        dr.setSpacing(6)
        dr.addStretch()
        self.revert_btn = button(tr('Сбросить'), lambda: self.presetAction.emit('revert'), 'Ghost', 'reset')
        self.save_btn = button(tr('Сохранить'), lambda: self.presetAction.emit('save'), 'Primary', 'save')
        dr.addWidget(self.revert_btn)
        dr.addWidget(self.save_btn)
        dv.addLayout(dr)
        lay.addWidget(self.dirty_row)
        return card

    def set_preset_info(self, name, dirty, own, summary):
        self.preset_name.setText(name + ('  •' if dirty else ''))
        self.preset_name.setToolTip(name)
        self.dirty_row.setVisible(bool(dirty))
        self.save_btn.setText(tr('Сохранить') if own else tr('Сохранить как мой…'))
        self.dirty_label.setText(tr('Есть несохранённые изменения пресета.') if own else
                                 tr('Встроенный пресет изменён — сохраните как свой, чтобы не потерять.'))
        self.preset_actions['save'].setEnabled(bool(dirty and own))
        for key in ('rename', 'delete'):
            self.preset_actions[key].setEnabled(bool(own))
        self.preset_actions['revert'].setEnabled(bool(dirty))
        self.preset_summary.clear()
        for text in summary:
            self.preset_summary.add(Chip(text, 'neutral'))

    def set_histogram(self, data):
        self.histogram.set_data(data)

    # ------------------------------------------------------------ helpers
    def _section(self, key, title, icon_name, accent, opened=True):
        stored = self.store.value(f'section/{key}', None)
        section = Section(title, icon_name, opened if stored is None else stored in (True, 'true'), accent=accent)
        section.toggled.connect(lambda v, k=key: self.store.setValue(f'section/{k}', v))
        return section

    def _slider(self, key, controls, photo=False):
        title, low, high, step, unit = ADJUST_RANGES[key]
        s = ParamSlider(tr(title), low, high, step, 0, unit, gradient=GRADIENTS.get(key))
        s.valueChanged.connect(lambda v, k=key, p=photo: self._adjust_changed(k, v, p, False))
        s.editingFinished.connect(lambda k=key, p=photo: self._adjust_changed(k, None, p, True))
        controls[key] = s
        return s

    def _value_slider(self, controls, key, title, low, high, default, unit, setter):
        s = ParamSlider(title, low, high, 1, default, unit)
        s.default = default
        s.valueChanged.connect(lambda v: setter(key, v, False))
        s.editingFinished.connect(lambda: setter(key, None, True))
        controls[key] = s
        return s

    # ------------------------------------------------------------ batch page
    def _build_batch(self):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 20)
        lay.setSpacing(0)
        c = self.batch_controls

        sec = self._section('size', tr('Размер и кадр'), 'crop', ACCENTS['size'])
        self.size_section = sec
        c['size_mode'] = Segmented([(tr('Оригинал'), 'original', tr('Сохранить исходные пиксели')), (tr('Печать'), 'print', tr('Размер отпечатка в мм и PPI')),
                                    (tr('Пиксели'), 'pixels', tr('Точный размер в пикселях')), (tr('Сторона'), 'long_edge', tr('Длинная сторона в пикселях'))], compact=True)
        c['size_mode'].changed.connect(lambda v: self._set('size_mode', v, commit=True))
        sec.layout.addWidget(c['size_mode'])
        self.print_box = QWidget()
        pl = QVBoxLayout(self.print_box)
        pl.setContentsMargins(0, 4, 0, 0)
        pl.setSpacing(6)
        c['paper'] = Dropdown([tr('Фотопечать')] + [(tr(n), (w, h)) for n, w, h in PAPER_SIZES[:8]] + [None, tr('Офисные форматы')]
                              + [(tr(n), (w, h)) for n, w, h in PAPER_SIZES[8:]], placeholder=tr('Свой размер'))
        c['paper'].changed.connect(self._paper_chosen)
        pl.addWidget(_row(tr('Формат'), c['paper']))
        dims = QWidget()
        dl = QHBoxLayout(dims)
        dl.setContentsMargins(8, 0, 0, 0)
        dl.setSpacing(6)
        t = label(tr('Размер, мм'), 'Muted')
        t.setFixedWidth(92)
        dl.addWidget(t)
        c['width_mm'] = _spin(10, 2000, '', 1, 1)
        c['height_mm'] = _spin(10, 2000, '', 1, 1)
        c['width_mm'].valueChanged.connect(lambda v: self._set('width_mm', float(v), commit=True))
        c['height_mm'].valueChanged.connect(lambda v: self._set('height_mm', float(v), commit=True))
        dl.addWidget(c['width_mm'], 1)
        dl.addWidget(label('×', 'Hint'))
        dl.addWidget(c['height_mm'], 1)
        dl.addWidget(tool('swap', tr('Поменять стороны местами'), self._swap_sides, size=16))
        pl.addWidget(dims)
        c['dpi'] = _spin(72, 1200, ' PPI')
        c['dpi'].valueChanged.connect(lambda v: self._set('dpi', int(v), commit=True))
        pl.addWidget(_row(tr('Разрешение'), c['dpi'], tr('Плотность пикселей файла (не DPI принтера). Для фотопечати — 300.')))
        self.pixel_note = _note('')
        pl.addWidget(self.pixel_note)
        sec.layout.addWidget(self.print_box)
        self.pixels_box = QWidget()
        xl = QVBoxLayout(self.pixels_box)
        xl.setContentsMargins(0, 4, 0, 0)
        xl.setSpacing(6)
        c['pixel_preset'] = Dropdown([(tr(n), v) for n, v in PIXEL_PRESETS], placeholder=tr('Свой размер'))
        c['pixel_preset'].changed.connect(self._pixel_preset_chosen)
        xl.addWidget(_row(tr('Шаблон'), c['pixel_preset']))
        pdims = QWidget()
        pdl = QHBoxLayout(pdims)
        pdl.setContentsMargins(8, 0, 0, 0)
        pdl.setSpacing(6)
        t = label(tr('Размер, px'), 'Muted')
        t.setFixedWidth(92)
        pdl.addWidget(t)
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
        el.addWidget(_row(tr('Длинная сторона'), c['long_edge']))
        quick = QHBoxLayout()
        quick.setContentsMargins(108, 0, 0, 0)
        for value in (2048, 3840, 6000):
            b = QPushButton(f'{value}')
            b.setObjectName('Ghost')
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, v=value: self._set('long_edge', v, commit=True, refresh=True))
            quick.addWidget(b)
        quick.addStretch()
        el.addLayout(quick)
        sec.layout.addWidget(self.edge_box)
        self.original_note = _note(tr('Пиксели не меняются. Обрезать отдельные снимки можно во вкладке «Этот снимок».'))
        sec.layout.addWidget(self.original_note)
        self.fit_box = QWidget()
        fl = QVBoxLayout(self.fit_box)
        fl.setContentsMargins(0, 6, 0, 0)
        fl.setSpacing(4)
        c['fit'] = Segmented([(tr('Заполнить'), 'cover', tr('Заполнить формат, обрезав лишнее')), (tr('Вписать'), 'contain', tr('Весь кадр, с полями'))], compact=True)
        c['fit'].changed.connect(lambda v: self._set('fit', v, commit=True))
        fl.addWidget(c['fit'])
        c['smart_crop'] = Switch(tr('Умный кадр: лица и главное'))
        c['smart_crop'].toggled.connect(lambda v: self._set('smart_crop', v, commit=True))
        fl.addWidget(c['smart_crop'])
        c['auto_orientation'] = Switch(tr('Поворачивать формат под снимок'))
        c['auto_orientation'].toggled.connect(lambda v: self._set('auto_orientation', v, commit=True))
        fl.addWidget(c['auto_orientation'])
        borders = QWidget()
        bl = QHBoxLayout(borders)
        bl.setContentsMargins(8, 0, 0, 0)
        bl.setSpacing(6)
        t = label(tr('Поля, мм'), 'Muted')
        t.setFixedWidth(92)
        bl.addWidget(t)
        c['border_mm'] = _spin(0, 100, '', 1, .5)
        c['border_mm'].valueChanged.connect(lambda v: self._set('border_mm', float(v), commit=True))
        bl.addWidget(c['border_mm'], 1)
        c['background'] = Dropdown([(tr('Белый'), '#ffffff'), (tr('Чёрный'), '#000000'), (tr('Серый'), '#808080')])
        c['background'].changed.connect(lambda v: self._set('background', v, commit=True))
        bl.addWidget(c['background'], 1)
        self.border_row = borders
        fl.addWidget(borders)
        sec.layout.addWidget(self.fit_box)
        c['allow_upscale'] = Switch(tr('Разрешить увеличение маленьких фото'))
        c['allow_upscale'].toggled.connect(lambda v: self._set('allow_upscale', v, commit=True))
        sec.layout.addWidget(c['allow_upscale'])
        lay.addWidget(sec)

        sec = self._section('light', tr('Свет и цвет'), 'sun', ACCENTS['light'])
        sec.add_header_widget(tool('reset', tr('Сбросить свет и цвет'), lambda: self._reset_adjust(LIGHT + COLOR), size=15))
        auto = QWidget()
        auto.setObjectName('AutoCard')
        auto.setStyleSheet(f'#AutoCard {{ background: {rgba(ACCENTS["neural"], .07)}; border: 1px solid {rgba(ACCENTS["neural"], .28)}; border-radius: 10px; }}')
        al = QVBoxLayout(auto)
        al.setContentsMargins(10, 8, 10, 10)
        al.setSpacing(6)
        head = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap('sparkles', ACCENTS['neural'], 18))
        head.addWidget(ic)
        c['auto'] = Switch(tr('Умная авто-коррекция'))
        c['auto'].setToolTip(tr('Анализирует каждый снимок отдельно: баланс белого (голосование нейтральных цветов),\n'
                             'экспозиция с учётом лиц и запаса светов, авто-уровни, тени и света, сочность, шум.\n'
                             'Хорошие снимки почти не трогает.'))
        c['auto'].toggled.connect(lambda v: self._set_adjust('auto', v, commit=True))
        head.addWidget(c['auto'], 1)
        al.addLayout(head)
        c['auto_strength'] = ParamSlider(tr('Сила'), 0, 100, 1, 80, '%')
        c['auto_strength'].default = 80
        c['auto_strength'].valueChanged.connect(lambda v: self._set_adjust('auto_strength', v, commit=False))
        c['auto_strength'].editingFinished.connect(lambda: self._set_adjust('auto_strength', None, commit=True))
        al.addWidget(c['auto_strength'])
        toggles = QHBoxLayout()
        toggles.setSpacing(4)
        for key, text, tip in (('auto_wb', tr('Баланс белого'), tr('Убрать цветной оттенок освещения')),
                               ('auto_light', tr('Свет'), tr('Экспозиция, уровни, тени, света, контраст')),
                               ('auto_color', tr('Цвет'), tr('Сочность для блёклых снимков')),
                               ('auto_noise', tr('Шум'), tr('Шумоподавление по оценке шума снимка'))):
            chip = ChipToggle(text)
            chip.setToolTip(tip)
            chip.toggled.connect(lambda v, k=key: self._set_adjust(k, v, commit=True))
            c[key] = chip
            toggles.addWidget(chip)
        toggles.addStretch()
        al.addLayout(toggles)
        self.batch_auto_caption = label(tr('Для текущего снимка:'), 'Hint')
        al.addWidget(self.batch_auto_caption)
        self.batch_auto_notes = FlowRow()
        al.addWidget(self.batch_auto_notes)
        sec.layout.addWidget(auto)
        sec.layout.addSpacing(4)
        for key in LIGHT:
            sec.layout.addWidget(self._slider(key, c))
        sec.layout.addSpacing(6)
        for key in COLOR:
            sec.layout.addWidget(self._slider(key, c))
        lay.addWidget(sec)

        sec = self._section('detail', tr('Детали и шум'), 'detail', ACCENTS['detail'], opened=False)
        sec.add_header_widget(tool('reset', tr('Сбросить детали'), lambda: self._reset_adjust(DETAIL), size=15))
        for key in DETAIL:
            sec.layout.addWidget(self._slider(key, c))
        lay.addWidget(sec)

        sec = self._section('look', tr('Стиль'), 'palette', ACCENTS['style'], opened=False)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.look_buttons = {}
        for i, (key, (name, _)) in enumerate(LOOKS.items()):
            b = QPushButton(tr(name))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f'''QPushButton {{ padding: 8px 4px; font-size: 12px; }}
                QPushButton:checked {{ background: {rgba(ACCENTS["style"], .18)}; border-color: {ACCENTS["style"]}; color: {T["text"]}; }}''')
            b.clicked.connect(lambda _=False, k=key: self._set_adjust('look', k, commit=True))
            self.look_buttons[key] = b
            grid.addWidget(b, i // 3, i % 3)
        sec.layout.addLayout(grid)
        sec.layout.addWidget(self._value_slider(c, 'look_strength', tr('Сила стиля'), 0, 100, 100, '%', self._set_adjust_value))
        lay.addWidget(sec)

        sec = self._section('neural', tr('Нейросеть'), 'cpu', ACCENTS['neural'], opened=False)
        self.neural_section = sec
        c['neural'] = Switch(tr('Улучшать нейросетью'))
        c['neural'].setToolTip(tr('Real-ESRGAN: восстанавливает детали, убирает JPEG-артефакты и шум.\nВключается для снимков, которые увеличиваются в {NEURAL_MIN_SCALE:g}× и больше.', NEURAL_MIN_SCALE=NEURAL_MIN_SCALE))
        c['neural'].toggled.connect(lambda v: self._set('neural', v, commit=True))
        sec.layout.addWidget(c['neural'])
        self.neural_state = QLabel()
        self.neural_state.setWordWrap(True)
        self.neural_state.setContentsMargins(8, 2, 0, 2)
        sec.layout.addWidget(self.neural_state)
        sec.layout.addWidget(_note(tr('Лучшие настройки выставлены автоматически. Считается один раз для снимка, '
                                   'потом любые правки — мгновенно. Детали удобно смотреть в масштабе 1:1.')))
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(button(tr('Посмотреть 1:1'), lambda: self.action.emit('view100'), icon_name='eye'), 1)
        self.neural_more = button(tr('Дополнительно…'), self._neural_dialog, icon_name='sliders')
        row.addWidget(self.neural_more, 1)
        sec.layout.addLayout(row)
        lay.addWidget(sec)

        sec = self._section('output', tr('Печать и файл'), 'printer', ACCENTS['output'])
        c['format'] = Segmented([('JPEG', 'JPEG', tr('Компактно, для лабораторий и печати')), ('TIFF', 'TIFF', tr('Без потерь, 8 или 16 бит')),
                                 ('PNG', 'PNG', tr('Без потерь, 8 или 16 бит'))], compact=True)
        c['format'].changed.connect(lambda v: self._set('format', v, commit=True))
        sec.layout.addWidget(c['format'])
        sec.layout.addWidget(self._value_slider(c, 'quality', tr('Качество JPEG'), 50, 100, 95, '', self._set_value))
        c['bit_depth'] = Segmented([(tr('8 бит'), 8), (tr('16 бит'), 16, tr('Больше градаций для ретуши и архива'))], compact=True)
        c['bit_depth'].changed.connect(lambda v: self._set('bit_depth', v, commit=True))
        self.depth_row = _row(tr('Глубина'), c['bit_depth'])
        sec.layout.addWidget(self.depth_row)
        c['output_space'] = Segmented([('sRGB', 'sRGB', tr('Стандарт лабораторий и экранов')), (tr('ICC принтера'), 'ICC', tr('Преобразовать в профиль машины и бумаги'))], compact=True)
        c['output_space'].changed.connect(self._space_changed)
        sec.layout.addWidget(_row(tr('Цвет'), c['output_space']))
        self.icc_box = QWidget()
        il = QVBoxLayout(self.icc_box)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(6)
        icc_row = QHBoxLayout()
        icc_row.setContentsMargins(8, 0, 0, 0)
        self.icc_label = label(tr('Профиль не выбран'), 'Hint')
        self.icc_label.setWordWrap(True)
        icc_row.addWidget(self.icc_label, 1)
        icc_row.addWidget(button(tr('Выбрать…'), self._choose_icc, icon_name='file'))
        il.addLayout(icc_row)
        c['intent'] = Dropdown([(tr('Относительный + BPC'), 1, tr('Точнее для фото')), (tr('Перцепционный + BPC'), 0, tr('Мягче для насыщенных цветов вне охвата'))])
        c['intent'].changed.connect(lambda v: self._set('intent', v, commit=True))
        il.addWidget(_row(tr('Метод'), c['intent']))
        sec.layout.addWidget(self.icc_box)
        sec.layout.addSpacing(4)
        c['sharpen'] = Segmented([(tr('Выкл'), 'off'), (tr('Экран'), 'screen'), (tr('Глянец'), 'glossy'), (tr('Мат'), 'matte')], compact=True)
        c['sharpen'].changed.connect(lambda v: self._set('sharpen', v, commit=True))
        sec.layout.addWidget(_row(tr('Резкость для'), c['sharpen'], tr('Выходная резкость после изменения размера: радиус зависит от PPI и бумаги.')))
        c['sharpen_amount'] = Segmented([(tr('Слабо'), 'low'), (tr('Норма'), 'standard'), (tr('Сильно'), 'high')], compact=True)
        c['sharpen_amount'].changed.connect(lambda v: self._set('sharpen_amount', v, commit=True))
        self.amount_row = _row(tr('Сила'), c['sharpen_amount'])
        sec.layout.addWidget(self.amount_row)
        pb = self._value_slider(c, 'print_brightness', tr('Яркость отпечатка'), 0, 40, 0, '%', self._set_value)
        pb.setToolTip(tr('Отпечаток темнее светящегося экрана. Поднимает средние тона,\n'
                      'не трогая чёрное и белое. Подберите по пробному отпечатку.'))
        sec.layout.addWidget(pb)
        c['keep_exif'] = Switch(tr('Сохранять EXIF (без GPS)'))
        c['keep_exif'].toggled.connect(lambda v: self._set('keep_exif', v, commit=True))
        sec.layout.addWidget(c['keep_exif'])
        lay.addWidget(sec)
        lay.addStretch()
        self.pages.addWidget(_scroll(body))

    # ------------------------------------------------------------ photo page
    def _build_photo(self):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 20)
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
        self.reset_photo_btn = button(tr('Сбросить'), lambda: self.action.emit('reset_photo'), icon_name='reset')
        self.to_preset_btn = button(tr('В пресет'), lambda: self.action.emit('to_preset'), icon_name='layers')
        self.to_preset_btn.setToolTip(tr('Перенести цветовые правки этого снимка в пресет — для всех фото'))
        self.copy_btn = button('', lambda: self.action.emit('copy_edits'), icon_name='copy')
        self.copy_btn.setToolTip(tr('Копировать правки этого снимка на выделенные в ленте (Ctrl+Shift+V)'))
        for b in (self.reset_photo_btn, self.to_preset_btn, self.copy_btn):
            actions.addWidget(b)
        cl.addLayout(actions)
        lay.addWidget(card)
        lay.addWidget(hline())

        sec = self._section('photo_frame', tr('Кадр'), 'crop', ACCENTS['size'])
        row = QHBoxLayout()
        row.setSpacing(6)
        self.crop_btn = button(tr('Изменить кадр'), lambda: self.action.emit('crop'), icon_name='crop')
        self.crop_btn.setCheckable(True)
        row.addWidget(self.crop_btn, 1)
        row.addWidget(tool('rotate_left', tr('Повернуть против часовой (Ctrl+[)'), lambda: self.action.emit('rotate_left')))
        row.addWidget(tool('rotate_right', tr('Повернуть по часовой (Ctrl+])'), lambda: self.action.emit('rotate_right')))
        sec.layout.addLayout(row)
        c['angle'] = ParamSlider(tr('Горизонт'), -20, 20, .1, 0, '°', decimals=1)
        c['angle'].valueChanged.connect(lambda v: self._edit_set('angle', v, False))
        c['angle'].editingFinished.connect(lambda: self._edit_set('angle', self.edit.angle, True))
        sec.layout.addWidget(c['angle'])
        c['fit'] = Segmented([(tr('Как в пресете'), None, tr('Взять режим из пресета')), (tr('Заполнить'), 'cover'), (tr('Вписать'), 'contain')], compact=True)
        c['fit'].changed.connect(lambda v: self._edit_set('fit', v, True))
        sec.layout.addWidget(c['fit'])
        c['aspect'] = Segmented([(tr(n), v) for n, v in ASPECTS], compact=True)
        c['aspect'].changed.connect(lambda v: self._edit_set('aspect', v, True))
        sec.layout.addWidget(c['aspect'])
        sec.layout.addWidget(button(tr('Сбросить кадр'), lambda: self.action.emit('reset_frame'), 'Ghost', 'reset'))
        lay.addWidget(sec)

        sec = self._section('photo_light', tr('Свет и цвет'), 'sun', ACCENTS['light'])
        sec.add_header_widget(tool('reset', tr('Сбросить свет и цвет этого снимка'), lambda: self._reset_adjust(LIGHT + COLOR), size=15))
        sec.layout.addWidget(label(tr('Авто-коррекция для этого снимка:'), 'Hint'))
        self.photo_auto_notes = FlowRow()
        sec.layout.addWidget(self.photo_auto_notes)
        for key in LIGHT:
            sec.layout.addWidget(self._slider(key, c, photo=True))
        sec.layout.addSpacing(6)
        for key in COLOR:
            sec.layout.addWidget(self._slider(key, c, photo=True))
        lay.addWidget(sec)
        sec = self._section('photo_detail', tr('Детали и шум'), 'detail', ACCENTS['detail'], opened=False)
        for key in DETAIL:
            sec.layout.addWidget(self._slider(key, c, photo=True))
        lay.addWidget(sec)
        sec = self._section('photo_neural', tr('Нейросеть'), 'cpu', ACCENTS['neural'], opened=False)
        c['neural'] = Segmented([(tr('Как в пресете'), None, tr('Взять из пресета')), (tr('Вкл'), True), (tr('Выкл'), False)], compact=True)
        c['neural'].changed.connect(lambda v: self._edit_set('neural', v, True))
        sec.layout.addWidget(c['neural'])
        self.photo_neural_state = QLabel()
        self.photo_neural_state.setWordWrap(True)
        self.photo_neural_state.setContentsMargins(8, 2, 0, 2)
        sec.layout.addWidget(self.photo_neural_state)
        sec.layout.addWidget(button(tr('Посмотреть 1:1'), lambda: self.action.emit('view100'), icon_name='eye'))
        lay.addWidget(sec)
        lay.addWidget(_note(tr('Размер, стиль и формат файла задаются для всей партии во вкладке «Все фото».')))
        lay.addStretch()
        self.pages.addWidget(_scroll(body))

    # ------------------------------------------------------------ state in
    def set_scope(self, scope, emit=True):
        if scope == 'photo' and self.photo is None:
            scope = 'batch'
        self.scope = scope
        self.scope_switch.setValue(scope)
        self.pages.setCurrentIndex(0 if scope == 'batch' else 1)
        self._update_banner()
        if emit:
            self.scopeChanged.emit(scope)

    def set_context(self, preset_name, photo_count):
        self.preset_label_name, self.photo_count = preset_name, photo_count
        self._update_banner()

    def _update_banner(self):
        name = getattr(self, 'preset_label_name', tr('Свои настройки'))
        count = getattr(self, 'photo_count', 0)
        if self.scope == 'batch':
            accent, text = T['accent'], (tr('Вы настраиваете пресет <b>«{name}»</b>. Изменения сразу применяются ко всем {count} фото папки.', name=name, count=count) if count else
                                         tr('Вы настраиваете пресет <b>«{name}»</b>. Он применится ко всем фото папки.', name=name))
        else:
            accent, text = ACCENTS['light'], tr('Правки только <b>этого снимка</b> — поверх пресета. Остальные фото не меняются.')
        self.scope_banner.setStyleSheet(f'QLabel {{ background: {rgba(accent, .12)}; border-left: 3px solid {accent}; '
                                        f'border-radius: 6px; padding: 7px 10px; color: {T["text"]}; font-size: 12px; }}')
        self.scope_banner.setText(text)

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

    def set_neural_state(self, state, reason='', progress=None, eta=None):
        """state: off | not_needed | pending | ready | running."""
        if state == 'running':
            text = tr('Считается для этого снимка: {v:.0f}%', v=progress * 100) + (tr(' · ещё ≈ {eta:.0f} с', eta=eta) if eta else '')
            color_ = ACCENTS['neural']
        elif state == 'pending':
            text, color_ = tr('Для этого снимка: ставим в очередь…'), ACCENTS['neural']
        elif state == 'ready':
            text, color_ = tr('Для этого снимка: применена ✓'), T['success']
        elif state == 'not_needed':
            text, color_ = reason or tr('Этому снимку не нужна'), T['text3']
        else:
            text, color_ = tr('Выключена'), T['text3']
        for w in (self.neural_state, self.photo_neural_state):
            w.setText(text)
            w.setStyleSheet(f'color: {color_}; font-size: 12px;')
        self.neural_section.set_subtitle({'running': tr('идёт расчёт'), 'ready': tr('применена'), 'pending': tr('в очереди')}.get(state, ''))

    def set_auto_notes(self, analysis, auto_offsets=None):
        for flow in (self.batch_auto_notes, self.photo_auto_notes):
            flow.clear()
        if not self.settings.adjust.auto:
            self.photo_auto_notes.add(Chip(tr('Авто выключено'), 'neutral'))
            return
        if analysis is None:
            for flow in (self.batch_auto_notes, self.photo_auto_notes):
                flow.add(Chip(tr('Анализ при просмотре снимка…'), 'neutral'))
            return
        notes = list(analysis.get('notes', []))
        offsets = auto_offsets or {}
        for key in ('shadows', 'highlights', 'contrast', 'vibrance', 'denoise'):
            value = offsets.get(key, 0)
            if abs(value) >= 5:
                notes.append(f'{tr(ADJUST_RANGES[key][0])} {value:+.0f}'.replace('-', '−'))
        if offsets.get('levels'):
            notes.append(tr('Уровни растянуты'))
        if not notes:
            notes = [tr('Снимок в порядке — правки не нужны')]
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
        paper = next((v for n, v in [(n, (w, h)) for n, w, h in PAPER_SIZES]
                      if v in ((s.width_mm, s.height_mm), (s.height_mm, s.width_mm))), None)
        c['paper'].setValue(paper)
        c['pixel_preset'].setValue(next((v for n, v in PIXEL_PRESETS if v == (s.pixel_width, s.pixel_height)), None))
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
            self.pixel_note.setText(tr('Файл: {w} × {h} px · {v:.1f} Мп', w=w, h=h, v=w * h / 1e6))
        c['fit'].setValue(s.fit)
        c['smart_crop'].setEnabled(s.fit == 'cover')
        for key in ('smart_crop', 'auto_orientation', 'allow_upscale', 'keep_exif', 'neural'):
            c[key].blockSignals(True)
            c[key].setChecked(getattr(s, key))
            c[key].blockSignals(False)
        c['background'].setValue(s.background)
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
        c['format'].setValue(s.format)
        c['quality'].setValue(s.quality)
        c['quality'].setVisible(s.format == 'JPEG')
        c['bit_depth'].setValue(s.bit_depth)
        self.depth_row.setVisible(s.format != 'JPEG')
        c['bit_depth'].setItemEnabled(16, s.output_space == 'sRGB')
        c['output_space'].setValue(s.output_space)
        self.icc_box.setVisible(s.output_space == 'ICC')
        self.icc_label.setText(Path(s.icc_path).name if s.icc_path else tr('Профиль не выбран'))
        self.icc_label.setToolTip(s.icc_path)
        c['intent'].setValue(s.intent)
        c['sharpen'].setValue(s.sharpen)
        c['sharpen_amount'].setValue(s.sharpen_amount)
        self.amount_row.setVisible(s.sharpen != 'off')
        c['print_brightness'].setValue(s.print_brightness)

    def _sync_photo(self):
        c, e, a = self.photo_controls, self.edit, self.settings.adjust
        if self.photo is not None:
            p = self.photo
            self.photo_name.setText(p.path.name)
            self.photo_meta.setText(tr('{v} × {v2} px · {megapixels:.1f} Мп · {bits} бит · {profile}', v=p.size[0], v2=p.size[1], megapixels=p.megapixels, bits=p.bits, profile=p.profile))
        self.reset_photo_btn.setEnabled(not e.is_default())
        self.to_preset_btn.setEnabled(bool(e.offsets))
        c['angle'].setValue(e.angle)
        c['fit'].setValue(e.fit)
        c['aspect'].setValue(e.aspect)
        frame_modes = self.settings.size_mode in ('print', 'pixels')
        c['fit'].setVisible(frame_modes)
        c['aspect'].setVisible(not frame_modes)
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
    def _emit_settings(self, commit):
        self.settingsEdited.emit(replace(self.settings, adjust=replace(self.settings.adjust)), commit)

    def _resync(self):
        self._updating = True
        self._sync_batch()
        self._updating = False

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
        if key in ('size_mode', 'fit', 'neural', 'format', 'output_space', 'sharpen', 'width_mm', 'height_mm', 'dpi') or refresh:
            self._resync()
        self._emit_settings(commit)

    def _set_value(self, key, value, commit):
        """Slider-backed Settings fields (quality, strengths, print brightness)."""
        if value is not None:
            value = int(value) if key == 'quality' else value
        self._set(key, value, commit)

    def _set_adjust(self, key, value, commit):
        if self._updating:
            return
        if value is not None:
            setattr(self.settings.adjust, key, value)
        if key in ('auto', 'look'):
            self._resync()
        self._emit_settings(commit)

    def _set_adjust_value(self, key, value, commit):
        self._set_adjust(key, value, commit)

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
        setattr(self.edit, key, value)
        if key == 'aspect' and value is not None:
            self.edit.manual_crop = True
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
        self._resync()
        self._emit_settings(True)

    def _neural_dialog(self):
        from .neural_dialog import NeuralDialog
        dialog = NeuralDialog(self.settings.neural_strength, self.settings.neural_detail, self)
        dialog.changed.connect(lambda key, value, commit: self._set(key, value, commit))
        dialog.exec()

    def _paper_chosen(self, value):
        if not value:
            return
        w, h = value
        if (self.settings.width_mm > self.settings.height_mm) != (w > h) and w != h:
            w, h = h, w
        self.settings.width_mm, self.settings.height_mm = float(w), float(h)
        self._set('width_mm', float(w), commit=True, refresh=True)

    def _pixel_preset_chosen(self, value):
        if not value:
            return
        self.settings.pixel_width, self.settings.pixel_height = value
        self._set('pixel_width', value[0], commit=True, refresh=True)

    def _swap_sides(self):
        s = self.settings
        s.width_mm, s.height_mm = s.height_mm, s.width_mm
        self._set('width_mm', s.width_mm, commit=True, refresh=True)

    def _space_changed(self, value):
        if value == 'ICC' and not self.settings.icc_path:
            if not self._choose_icc():
                self._updating = True
                self.batch_controls['output_space'].setValue('sRGB')
                self._updating = False
            return
        if value == 'ICC':
            self.settings.bit_depth = 8
            if self.settings.format == 'PNG':
                self.settings.format = 'TIFF'
        self._set('output_space', value, commit=True)

    def _choose_icc(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('ICC-профиль принтера и бумаги'), '', tr('ICC (*.icc *.icm);;Все файлы (*)'))
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
