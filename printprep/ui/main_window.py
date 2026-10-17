"""Main window: one workspace — presets · viewer + filmstrip · inspector."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QProgressBar, QSplitter, QToolButton, QVBoxLayout, QWidget)

from .. import __version__
from ..analysis import auto_values
from ..imageio import SUPPORTED, inspect
from ..model import BUILTIN_PRESETS, Edit, Settings
from ..pipeline import AnalysisCache, assess
from ..presets import (PresetLibrary, describe, export_preset, export_recipe, load_session, read_preset_file,
                       save_session)
from . import icons
from .controls import Chip, FlowRow, Segmented, Spinner, Toast, button, label, tool
from .filmstrip import Filmstrip
from .inspector import Inspector
from .presets_panel import PresetPanel
from .store import prefs
from .services import ExportJob, NeuralWorker, PreviewRequest, RenderService, ThumbnailLoader, batch_summary
from .preset_manager import PresetManager
from .theme import T
from .viewer import Viewer
from ..i18n import tr

ROOT = Path(__file__).resolve().parents[2]


def preset_summary(s: Settings):
    from ..model import LOOKS
    if s.size_mode == 'original':
        size = [tr('Исходный размер')]
    elif s.size_mode == 'long_edge':
        size = [tr('{long_edge} px по стороне', long_edge=s.long_edge)]
    elif s.size_mode == 'pixels':
        size = [f'{s.pixel_width}×{s.pixel_height} px']
    else:
        size = [tr('{width_mm:g}×{height_mm:g} мм', width_mm=s.width_mm, height_mm=s.height_mm), f'{s.dpi} PPI']
    parts = size + [s.format + (f' {s.quality}' if s.format == 'JPEG' else tr(' {bit_depth} бит', bit_depth=s.bit_depth))]
    if s.adjust.auto:
        parts.append(tr('Авто {auto_strength:.0f}%', auto_strength=s.adjust.auto_strength))
    if s.adjust.look != 'none':
        parts.append(tr(LOOKS[s.adjust.look][0]))
    if s.neural:
        parts.append(tr('Нейросеть'))
    if s.sharpen != 'off':
        parts.append({'screen': tr('Резкость: экран'), 'glossy': tr('Резкость: глянец'), 'matte': tr('Резкость: мат')}[s.sharpen])
    if s.output_space == 'ICC':
        parts.append(tr('ICC принтера'))
    return parts


def copy_settings(s: Settings):
    return replace(s, adjust=replace(s.adjust))


def copy_edit(e: Edit):
    return replace(e, offsets=dict(e.offsets))


class ScanWorker(threading.Thread):
    def __init__(self, folder, recursive, callback, progress):
        super().__init__(daemon=True, name='printprep-scan')
        self.folder, self.recursive, self.callback, self.progress = folder, recursive, callback, progress
        self.cancelled = False

    def run(self):
        photos, errors = [], []
        try:
            paths = sorted((p for p in (self.folder.rglob('*') if self.recursive else self.folder.iterdir())
                            if p.is_file() and p.suffix.lower() in SUPPORTED
                            and not any(part.startswith('PrintPrep_') for part in p.relative_to(self.folder).parts)),
                           key=lambda p: str(p).casefold())
            for i, path in enumerate(paths):
                if self.cancelled:
                    return
                try:
                    photos.append(inspect(path))
                except Exception as e:
                    errors.append((path, str(e)))
                if i % 10 == 0:
                    self.progress(i + 1, len(paths))
        except Exception as e:
            errors.append((self.folder, str(e)))
        self.callback(photos, errors)


class ResponsiveBar(QFrame):
    """Calls back with its width so the toolbar can switch to icons when the window is narrow."""

    def __init__(self, on_width):
        super().__init__()
        self.on_width = on_width

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.on_width(self.width())


class MainWindow(QMainWindow):
    scanned = Signal(object, object)
    scanProgress = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'Print Prep {__version__}')
        self.setWindowIcon(QIcon(str(ROOT / 'assets' / 'printprep.png')))
        self.setAcceptDrops(True)
        self.setMinimumSize(1100, 680)
        self.store = prefs()
        data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        self.data_dir = Path(data or Path.home() / '.printprep')
        self.library = PresetLibrary(self.data_dir)
        self.library.migrate_qsettings(prefs('PrintPrep'))
        self.cache = AnalysisCache()
        self.neural = NeuralWorker(self)
        self.service = RenderService(self.cache, self.neural, self)
        self.thumbs = ThumbnailLoader(self)
        self.folder = None
        self.photos = []
        self.edits = {}
        self.current = -1
        self.settings = BUILTIN_PRESETS['original']['settings']
        self.active_id = 'builtin:original'
        self.scope = 'batch'
        self.crop_mode = False
        self.view_mode = 'split'
        self.neural_progress = {}
        self.gen = 0
        self.fit_key = None
        self.fit_done_key = None
        self.roi_key = None
        self.export_job = None
        self.scan_worker = None
        self.analyses = {}
        self.undo_stack, self.redo_stack = [], []
        self.committed = None
        self.last_result = None
        self.last_request = None
        self._build()
        self._restore()
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self._request_fit)
        self.badge_timer = QTimer(self)
        self.badge_timer.setSingleShot(True)
        self.badge_timer.setInterval(150)
        self.badge_timer.timeout.connect(self._refresh_badges)
        self.session_timer = QTimer(self)
        self.session_timer.setSingleShot(True)
        self.session_timer.setInterval(800)
        self.session_timer.timeout.connect(self._save_session)
        self.service.status.connect(self._on_status)
        self.service.ready.connect(self._on_ready)
        self.service.failed.connect(self._on_failed)
        self.service.analyzed.connect(self._on_analyzed)
        self.neural.progress.connect(self._neural_progress)
        self.neural.done.connect(self._neural_done)
        self.neural.failed.connect(self._neural_failed)
        self.thumbs.ready.connect(lambda gen, path, img: self.strip.set_thumb(path, img))
        self.scanned.connect(self._on_scanned)
        self.scanProgress.connect(lambda i, n: self.viewer.set_status(tr('Читаем папку… {i} из {n}', i=i, n=n), i / max(1, n)))
        self._shortcuts()
        self._refresh_presets()
        self._sync_all()

    # ================================================================= layout
    def _build(self):
        root = QWidget()
        root.setObjectName('Window')
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._top_bar())
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(1)
        self.presets = PresetPanel()
        self.presets.setMinimumWidth(240)
        self.presets.setMaximumWidth(360)
        self.presets.applyRequested.connect(self.apply_preset)
        self.presets.saveRequested.connect(self.save_preset)
        self.presets.saveAsRequested.connect(self.save_preset_as)
        self.presets.revertRequested.connect(self.revert_preset)
        self.presets.renameRequested.connect(self.rename_preset)
        self.presets.deleteRequested.connect(self.delete_preset)
        self.presets.duplicateRequested.connect(self.duplicate_preset)
        self.presets.exportRequested.connect(self.export_preset_file)
        self.presets.importRequested.connect(self.import_preset_file)
        self.presets.manageRequested.connect(self.manage_presets)
        self.split.addWidget(self.presets)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._viewer_bar())
        self.viewer = Viewer()
        self.viewer.empty.openRequested.connect(self.choose_folder)
        self.viewer.empty.recentRequested.connect(lambda p: self.load_folder(Path(p)))
        self.viewer.roiRequested.connect(self._request_roi)
        self.viewer.zoomChanged.connect(self._zoom_changed)
        self.viewer.cropEdited.connect(self._crop_edited)
        cl.addWidget(self.viewer, 1)
        cl.addWidget(self._info_bar())
        strip_box = QWidget()
        strip_box.setObjectName('Strip')
        self.strip_box = strip_box
        sl = QVBoxLayout(strip_box)
        sl.setContentsMargins(8, 4, 8, 2)
        sl.setSpacing(0)
        self.strip = Filmstrip()
        self.strip.currentPhotoChanged.connect(self.select_photo)
        sl.addWidget(self.strip)
        cl.addWidget(strip_box)
        self.split.addWidget(center)
        self.inspector = Inspector()
        self.inspector.settingsEdited.connect(self._settings_edited)
        self.inspector.editEdited.connect(self._edit_edited)
        self.inspector.action.connect(self._inspector_action)
        self.inspector.scopeChanged.connect(self._scope_changed)
        self.inspector.presetAction.connect(self._preset_action)
        self.split.addWidget(self.inspector)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([264, 900, 372])
        outer.addWidget(self.split, 1)
        outer.addWidget(self._status_bar())
        self.toast = Toast(root)

    def _top_bar(self):
        bar = QFrame()
        bar.setObjectName('TopBar')
        bar.setFixedHeight(56)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 8, 14, 8)
        row.setSpacing(10)
        mark = QLabel()
        logo = QPixmap(str(ROOT / 'assets' / 'printprep.png'))
        dpr = self.devicePixelRatioF()
        logo = logo.scaled(round(26 * dpr), round(26 * dpr), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        logo.setDevicePixelRatio(dpr)
        mark.setPixmap(logo)
        row.addWidget(mark)
        row.addWidget(label('Print Prep', 'Brand'))
        row.addSpacing(14)
        self.folder_btn = QToolButton()
        self.folder_btn.setText(tr('  Открыть папку'))
        self.folder_btn.setIcon(icons.icon('folder', T['text2'], T['text']))
        self.folder_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.folder_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_btn.setStyleSheet(f'QToolButton {{ border: 1px solid {T["border_strong"]}; background: {T["raised"]}; padding: 5px 10px; color: {T["text"]}; }}'
                                      f'QToolButton::menu-button {{ border: none; width: 18px; }}')
        self.folder_btn.clicked.connect(self.choose_folder)
        self.folder_menu = QMenu(self.folder_btn)
        self.folder_menu.aboutToShow.connect(self._fill_folder_menu)
        self.folder_btn.setMenu(self.folder_menu)
        self.folder_btn.setToolTip(tr('Открыть папку со снимками (Ctrl+O)'))
        row.addWidget(self.folder_btn)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.folder_title = label(tr('Папка не выбрана'), None)
        self.folder_title.setStyleSheet('font-weight: 600;')
        self.folder_sub = label(tr('Перетащите папку в окно'), 'Hint')
        texts.addWidget(self.folder_title)
        texts.addWidget(self.folder_sub)
        row.addLayout(texts, 1)
        self.summary_chip = QToolButton()
        self.summary_chip.setIcon(icons.icon('warning', T['warning'], T['warning']))
        self.summary_chip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.summary_chip.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.summary_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self.summary_chip.setStyleSheet(f'QToolButton {{ background: rgba(242,177,74,0.12); color: {T["chip_warning"]}; border: 1px solid rgba(242,177,74,0.35);'
                                        ' border-radius: 14px; padding: 4px 10px; font-size: 12px; }'
                                        'QToolButton:hover { background: rgba(242,177,74,0.2); }')
        self.summary_menu = QMenu(self.summary_chip)
        self.summary_chip.setMenu(self.summary_menu)
        self.summary_chip.hide()
        row.addWidget(self.summary_chip)
        self.undo_btn = tool('undo', tr('Отменить (Ctrl+Z)'), self.undo)
        self.redo_btn = tool('redo', tr('Повторить (Ctrl+Y)'), self.redo)
        row.addWidget(self.undo_btn)
        row.addWidget(self.redo_btn)
        row.addWidget(tool('help', tr('Справка и горячие клавиши (F1)'), self.show_help))
        row.addWidget(tool('sliders', tr('Настройки приложения: тема, язык, обучение'), self.open_app_settings))
        row.addSpacing(6)
        self.progress_box = QWidget()
        pl = QHBoxLayout(self.progress_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        self.export_spinner = Spinner(16)
        pl.addWidget(self.export_spinner)
        pv = QVBoxLayout()
        pv.setSpacing(3)
        self.progress_text = label(tr('Готовим…'), None)
        self.progress_text.setStyleSheet('font-size: 12px;')
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(200)
        pv.addWidget(self.progress_text)
        pv.addWidget(self.progress_bar)
        pl.addLayout(pv)
        self.stop_btn = button(tr('Стоп'), self.cancel_export, None, 'stop')
        pl.addWidget(self.stop_btn)
        self.progress_box.hide()
        row.addWidget(self.progress_box)
        self.export_btn = button(tr('Подготовить'), self.export, 'Primary', 'arrow_right')
        self.export_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.export_btn.setMinimumHeight(36)
        self.export_btn.setToolTip(tr('Обработать все снимки папки выбранным пресетом (Ctrl+E)'))
        row.addWidget(self.export_btn)
        return bar

    def _viewer_bar(self):
        bar = ResponsiveBar(self._fit_viewer_bar)
        bar.setObjectName('ViewerBar')
        self.bar_compact = False
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 6)
        row.setSpacing(6)
        self.view_seg = Segmented([(tr('Результат'), 'result', tr('Только обработанный снимок')),
                                   (tr('До / после'), 'split', tr('Шторка: слева исходник, справа результат. Тяните шторку мышью (\\)')),
                                   (tr('Исходник'), 'original', tr('Снимок без обработки в том же кадре'))], compact=True)
        self.view_seg.changed.connect(self.set_view_mode)
        row.addWidget(self.view_seg)
        row.addSpacing(4)
        self.zoom_seg = Segmented([(tr('По окну'), 'fit', tr('Весь кадр в окне (Пробел)')),
                                   ('1:1', 1.0, tr('Масштаб 1:1 — один пиксель файла на один пиксель экрана.\n'
                                                'Так видны реальная резкость, шум и работа нейросети.')),
                                   ('2:1', 2.0, tr('Увеличение вдвое — для проверки мелких деталей'))], compact=True)
        self.zoom_seg.setValue('fit')
        self.zoom_seg.changed.connect(lambda z: self.viewer.set_zoom(z))
        row.addWidget(self.zoom_seg)
        row.addSpacing(6)
        self.crop_tool = tool('crop', tr('Кадрирование этого снимка (C)'), lambda on: self.set_crop_mode(on), checkable=True)
        self.rot_l = tool('rotate_left', tr('Повернуть против часовой (Ctrl+[)'), lambda: self.rotate(-90))
        self.rot_r = tool('rotate_right', tr('Повернуть по часовой (Ctrl+])'), lambda: self.rotate(90))
        self.safe_btn = tool('safe', tr('Безопасная зона печати: 3 мм от края'), self._toggle_safe, checkable=True)
        self.proof_btn = tool('eye', tr('Экранная проба ICC-профиля'), self._toggle_proof, checkable=True)
        self.gamut_btn = tool('warning', tr('Показать цвета вне охвата принтера'), self._toggle_proof, checkable=True)
        for w in (self.crop_tool, self.rot_l, self.rot_r, self.safe_btn, self.proof_btn, self.gamut_btn):
            row.addWidget(w)
        self.crop_done = button(tr('Готово'), lambda: self.set_crop_mode(False), 'Primary', 'check')
        self.crop_done.hide()
        row.addWidget(self.crop_done)
        row.addStretch()
        self.nav_label = label('', 'Hint')
        row.addWidget(self.nav_label)
        self.nav_prev = tool('chevron_left', tr('Предыдущий снимок (←)'), lambda: self.step(-1))
        self.nav_next = tool('chevron_right', tr('Следующий снимок (→)'), lambda: self.step(1))
        row.addWidget(self.nav_prev)
        row.addWidget(self.nav_next)
        row.addSpacing(6)
        self.bg_seg = Segmented([('', 'dark', tr('Тёмный фон')), ('', 'gray', tr('Средне-серый фон (ISO 12646)')), ('', 'light', tr('Светлый фон'))], compact=True)
        for key, swatch in (('dark', T['viewer_dark']), ('gray', T['viewer_gray']), ('light', T['viewer_light'])):
            b = self.bg_seg.buttons[key]
            b.setFixedWidth(26)
            b.setStyleSheet(f'QPushButton {{ background: {swatch}; border: 2px solid transparent; border-radius: 5px; min-height: 14px; }}'
                            f'QPushButton:checked {{ border-color: {T["accent"]}; }}')
        self.bg_seg.setFixedWidth(100)
        self.bg_seg.changed.connect(self._set_background)
        row.addWidget(self.bg_seg)
        return bar

    def _fit_viewer_bar(self, width):
        compact = width < 800 if not self.bar_compact else width < 860
        if compact == self.bar_compact or not hasattr(self, 'bg_seg'):
            return
        self.bar_compact = compact
        glyphs = {'result': 'sparkles', 'split': 'compare', 'original': 'image', 'fit': 'fit'}
        for seg in (self.view_seg, self.zoom_seg):
            for value, b in seg.buttons.items():
                if value not in glyphs:
                    continue
                if not b.property('full_text'):
                    b.setProperty('full_text', b.text())
                b.setText('' if compact else b.property('full_text'))
                b.setIcon(icons.icon(glyphs[value]) if compact else QIcon())
                b.setIconSize(QSize(16, 16))
        for w in (self.nav_label, self.nav_prev, self.nav_next):
            w.setVisible(not compact)      # the filmstrip and the arrow keys still navigate

    def _status_bar(self):
        bar = QFrame()
        bar.setObjectName('StatusBar')
        bar.setFixedHeight(26)
        bar.setStyleSheet(f'#StatusBar {{ background: {T["panel"]}; border-top: 1px solid {T["border"]}; }}'
                          f'#StatusBar QLabel {{ color: {T["text3"]}; font-size: 11px; }}')
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 14, 0)
        row.setSpacing(18)
        self.status_file = QLabel('')
        self.status_render = QLabel('')
        self.status_neural = QLabel('')
        self.status_cpu = QLabel(tr('Процессор: {v} потоков · работа локально, без интернета', v=os.cpu_count() or 1))
        row.addWidget(self.status_file, 1)
        row.addWidget(self.status_neural)
        row.addWidget(self.status_render)
        row.addWidget(self.status_cpu)
        return bar

    def _info_bar(self):
        bar = QFrame()
        bar.setObjectName('ViewerBar')
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 4, 14, 6)
        row.setSpacing(6)
        self.info_flow = FlowRow()
        row.addWidget(self.info_flow, 1)
        self.time_label = label('', 'Hint')
        row.addWidget(self.time_label)
        return bar

    def _shortcuts(self):
        def sc(keys, fn):
            for key in ([keys] if isinstance(keys, (str, QKeySequence.StandardKey)) else keys):
                s = QShortcut(QKeySequence(key), self)
                s.setContext(Qt.ShortcutContext.WindowShortcut)
                s.activated.connect(fn)
        sc('Ctrl+O', self.choose_folder)
        sc(QKeySequence.StandardKey.Undo, self.undo)
        sc(['Ctrl+Y', 'Ctrl+Shift+Z'], self.redo)
        sc('Ctrl+E', self.export)
        sc('Ctrl+S', self.save_preset)
        sc('Right', lambda: self._nav_key(1))
        sc('Left', lambda: self._nav_key(-1))
        sc('Space', self._toggle_zoom)
        sc('Z', self._toggle_zoom)
        sc('\\', lambda: self.set_view_mode('result' if self.view_mode == 'split' else 'split'))
        sc('C', lambda: self.crop_tool.toggle())
        sc('Ctrl+[', lambda: self.rotate(-90))
        sc('Ctrl+]', lambda: self.rotate(90))
        sc('Ctrl+Shift+V', self.copy_edits_to_selected)
        sc('Escape', lambda: self.set_crop_mode(False) if self.crop_mode else None)
        sc('Return', lambda: self.set_crop_mode(False) if self.crop_mode else None)
        sc('F1', self.show_help)

    def _nav_key(self, delta):
        focus = self.focusWidget()
        from .controls import ParamSlider
        if isinstance(focus, ParamSlider) or focus.__class__.__name__ in ('QLineEdit', 'QSpinBox', 'QDoubleSpinBox'):
            return
        self.step(delta)

    # ================================================================= persistence
    def _restore(self):
        geometry = self.store.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        else:
            screen = self.screen().availableGeometry()
            self.resize(min(1600, screen.width() - 40), min(980, screen.height() - 60))
        sizes = self.store.value('splitter')
        if sizes:
            try:
                self.split.setSizes([int(v) for v in sizes])
            except (TypeError, ValueError):
                pass
        bg = self.store.value('viewer_bg', 'gray' if T['name'] == 'light' else 'dark')
        self.bg_seg.setValue(bg)
        self.viewer.set_background(bg)
        self.view_mode = self.store.value('view_mode', 'split') or 'split'
        self.view_seg.setValue(self.view_mode)
        self.viewer.set_view_mode(self.view_mode)
        try:
            saved = self.store.value('settings')
            if saved:
                self.settings = Settings.from_dict(json.loads(saved))
                self.settings.validate(check_icc=False)
            self.active_id = self.store.value('active_preset', 'builtin:original') or None
        except Exception:
            self.settings = copy_settings(BUILTIN_PRESETS['original']['settings'])
            self.active_id = 'builtin:original'
        if self.active_id and self.library.get(self.active_id) is None:
            self.active_id = None
        self.committed = self._snapshot()
        self.viewer.set_empty(self._recent())

    def _recent(self):
        try:
            items = json.loads(self.store.value('recent', '[]'))
        except Exception:
            items = []
        return [p for p in items if isinstance(p, str) and Path(p).is_dir()][:6]

    def _remember_folder(self, folder):
        items = [str(folder)] + [p for p in self._recent() if p != str(folder)]
        self.store.setValue('recent', json.dumps(items[:8], ensure_ascii=False))

    def _save_session(self):
        if self.folder:
            try:
                save_session(self.data_dir, self.folder, self.edits)
            except OSError:
                pass

    def closeEvent(self, e):
        if self.export_job and self.export_job.running():
            if QMessageBox.question(self, 'Print Prep', tr('Идёт подготовка фотографий. Остановить и закрыть?')) != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.export_job.cancel()
            self.export_job.thread.join(timeout=30)
        self._save_session()
        self.store.setValue('geometry', self.saveGeometry())
        self.store.setValue('splitter', self.split.sizes())
        self.store.setValue('settings', json.dumps(self.settings.to_dict(), ensure_ascii=False))
        self.store.setValue('active_preset', self.active_id or '')
        if self.scan_worker:
            self.scan_worker.cancelled = True
        self.thumbs.stop()
        self.neural.stop()
        self.service.stop()
        e.accept()

    # ================================================================= folder
    def _fill_folder_menu(self):
        m = self.folder_menu
        m.clear()
        m.addAction(icons.icon('folder'), tr('Открыть папку…'), self.choose_folder)
        sub = m.addAction(tr('Искать и во вложенных папках'))
        sub.setCheckable(True)
        sub.setChecked(self.store.value('recursive', False, type=bool))
        sub.toggled.connect(self._toggle_recursive)
        act = m.addAction(icons.icon('reset'), tr('Перечитать папку'), lambda: self.load_folder(self.folder))
        act.setEnabled(self.folder is not None)
        recent = self._recent()
        if recent:
            m.addSeparator()
            for path in recent:
                m.addAction(path, lambda p=path: self.load_folder(Path(p)))
        m.addSeparator()
        m.addAction(icons.icon('upload'), tr('Импортировать рецепт (пресет + правки)…'), self.import_preset_file)
        rec = m.addAction(icons.icon('download'), tr('Экспортировать рецепт…'), self.export_recipe_file)
        rec.setEnabled(self.folder is not None)

    def _toggle_recursive(self, on):
        self.store.setValue('recursive', on)
        if self.folder:
            self.load_folder(self.folder)

    def choose_folder(self):
        start = str(self.folder or (self._recent() or [str(Path.home())])[0])
        folder = QFileDialog.getExistingDirectory(self, tr('Папка с фотографиями'), start)
        if folder:
            self.load_folder(Path(folder))

    def load_folder(self, folder, select=0):
        if folder is None or not Path(folder).is_dir():
            return
        self.pending_select = select or 0
        if self.scan_worker:
            self.scan_worker.cancelled = True
        self._save_session()
        self.folder = Path(folder).resolve()
        self._remember_folder(self.folder)
        self.photos, self.current = [], -1
        self.edits = load_session(self.data_dir, self.folder)
        self.analyses = {}
        self.service.drop_source()
        self.strip.set_photos([])
        self.folder_title.setText(self.folder.name or str(self.folder))
        self.folder_sub.setText(tr('Читаем папку…'))
        self.folder_title.setToolTip(str(self.folder))
        self.viewer.set_loading(1.5)
        self.viewer.set_status(tr('Читаем папку…'))
        self.scan_worker = ScanWorker(self.folder, self.store.value('recursive', False, type=bool),
                                      lambda p, e: self.scanned.emit(p, e), lambda i, n: self.scanProgress.emit(i, n))
        self.scan_worker.start()

    def _on_scanned(self, photos, errors):
        self.viewer.clear_status()
        self.photos = photos
        self.edits = {k: v for k, v in self.edits.items() if any(str(p.path) == k for p in photos)}
        self.strip.set_photos(photos)
        self.thumbs.load([p.path for p in photos])
        if not photos:
            self.viewer.set_empty(self._recent())
            self.folder_sub.setText(tr('Нет поддерживаемых снимков'))
            self.toast.show_message(tr('В папке нет поддерживаемых фотографий'), tr('Выберите другую папку или включите поиск во вложенных папках.'), 'warning')
        else:
            self.strip.select_row(min(max(0, getattr(self, 'pending_select', 0)), len(photos) - 1))
            if self.edits:
                self.toast.show_message(tr('Восстановлены правки: {n}', n=len(self.edits)), tr('Правки снимков этой папки сохраняются автоматически.'), 'info', timeout=4000)
        if errors:
            box = QMessageBox(self)
            box.setWindowTitle(tr('Некоторые файлы не прочитаны'))
            box.setText(tr('Пропущено файлов: {n}. Остальные доступны.', n=len(errors)))
            box.setDetailedText('\n'.join(f'{p.name}: {e}' for p, e in errors))
            box.exec()
        self._sync_all()

    # ================================================================= selection
    def select_photo(self, row):
        if not (0 <= row < len(self.photos)) or row == self.current:
            return
        self.current = row
        photo = self.photos[row]
        self.viewer.set_canvas(assess(photo.size, self.settings, self.edits.get(str(photo.path)))['pixels'], reset=True)
        self.viewer.set_loading(photo.size[0] / max(1, photo.size[1]), self.strip.model_.thumbs.get(str(photo.path)))
        self.fit_done_key = None
        if self.crop_mode:
            self.set_crop_mode(False)
        self.viewer.set_neural_badge(None)
        self.status_file.setText(tr('{name} · {v} × {v2} px · {megapixels:.1f} Мп · {bits} бит · {profile}', name=photo.path.name, v=photo.size[0], v2=photo.size[1], megapixels=photo.megapixels, bits=photo.bits, profile=photo.profile))
        self._sync_inspector()
        self._update_info()
        self._schedule(0)

    def step(self, delta):
        if self.photos:
            self.strip.select_row(max(0, min(len(self.photos) - 1, self.current + delta)))

    def photo(self):
        return self.photos[self.current] if 0 <= self.current < len(self.photos) else None

    def edit(self):
        p = self.photo()
        return self.edits.get(str(p.path)) if p else None

    # ================================================================= state & undo
    def _snapshot(self):
        return copy_settings(self.settings), {k: copy_edit(v) for k, v in self.edits.items()}, self.active_id

    def _commit(self):
        snap = self._snapshot()
        if self.committed is not None and (self.committed[0] != snap[0] or self.committed[1] != snap[1]):
            self.undo_stack.append(self.committed)
            self.undo_stack = self.undo_stack[-100:]
            self.redo_stack.clear()
        self.committed = snap
        self._update_undo()
        self.session_timer.start()

    def _restore_snapshot(self, snap):
        self.settings, edits, self.active_id = copy_settings(snap[0]), {k: copy_edit(v) for k, v in snap[1].items()}, snap[2]
        self.edits = edits
        self.committed = self._snapshot()
        self._sync_all()
        self._schedule(0)
        self.session_timer.start()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._snapshot())
            self._restore_snapshot(self.undo_stack.pop())
            self._update_undo()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._snapshot())
            self._restore_snapshot(self.redo_stack.pop())
            self._update_undo()

    def _update_undo(self):
        self.undo_btn.setEnabled(bool(self.undo_stack))
        self.redo_btn.setEnabled(bool(self.redo_stack))

    def _dirty(self):
        preset = self.library.get(self.active_id)
        return preset is None or preset.settings != self.settings

    def _settings_edited(self, settings, commit):
        self.settings = settings
        self._after_change(commit, interactive=not commit)

    def _edit_edited(self, edit, commit):
        p = self.photo()
        if not p:
            return
        if edit.is_default():
            self.edits.pop(str(p.path), None)
        else:
            self.edits[str(p.path)] = edit
        self._after_change(commit, interactive=not commit)

    def _after_change(self, commit, interactive=False):
        self._update_preset_card()
        if commit:
            self._commit()
        p = self.photo()
        if p:
            self.viewer.set_canvas(assess(p.size, self.settings, self.edit())['pixels'])
        self._update_info()
        self.badge_timer.start()
        self._update_export_button()
        if self.crop_mode:
            self._request_crop_image()
        self._schedule(40 if interactive else 0, interactive)

    def _sync_inspector(self):
        p = self.photo()
        analysis = self.analyses.get(str(p.path)) if p else None
        offsets = None
        if analysis is not None and p is not None:
            offsets, _ = auto_values(analysis, self.settings.adjust, assess(p.size, self.settings, self.edit())['scale'])
        self.inspector.set_state(self.settings, self.edit(), p, analysis, offsets)

    def _update_preset_card(self):
        preset = self.library.get(self.active_id)
        dirty = self._dirty()
        own = bool(preset and not preset.builtin)
        name = preset.name if preset else tr('Свои настройки')
        self.inspector.set_preset_info(name, dirty, own, preset_summary(self.settings))
        self.inspector.set_context(name, len(self.photos))
        self.presets.set_state(self.active_id, dirty)

    def _sync_all(self):
        self._sync_inspector()
        self._update_preset_card()
        n = len(self.photos)
        if self.folder:
            self.folder_sub.setText(tr('{n} фото · {folder}', n=n, folder=self.folder) if n else str(self.folder))
        self._update_export_button()
        self._update_undo()
        self._update_info()
        self.badge_timer.start()
        has = self.photo() is not None
        self.strip_box.setVisible(bool(self.photos))
        for w in (self.zoom_seg, self.view_seg, self.crop_tool, self.rot_l, self.rot_r, self.safe_btn):
            w.setEnabled(has)
        icc = self.settings.output_space == 'ICC'
        self.proof_btn.setVisible(icc)
        self.gamut_btn.setVisible(icc)
        self.safe_btn.setVisible(self.settings.size_mode == 'print')

    def _update_export_button(self):
        n = len(self.photos)
        running = bool(self.export_job and self.export_job.running())
        self.export_btn.setText(tr('Подготовить {n} фото', n=n) if n else tr('Подготовить'))
        self.export_btn.setEnabled(n > 0 and not running)
        self.export_btn.setVisible(not running)

    def _refresh_badges(self):
        if not self.photos:
            self.summary_chip.hide()
            return
        badges = {}
        self.summary_menu.clear()
        problems = 0
        for row, photo in enumerate(self.photos):
            edit = self.edits.get(str(photo.path))
            info = assess(photo.size, self.settings, edit)
            warning = info['warnings'][0] if info['warnings'] else ''
            if info['upscale'] and not self.settings.allow_upscale:
                warning = tr('Будет пропущен: увеличение запрещено')
            badges[str(photo.path)] = dict(edited=bool(edit and not edit.is_default()), warning=warning)
            if warning and problems < 40:
                problems += 1
                self.summary_menu.addAction(icons.icon('warning', T['warning']), f'{photo.path.name} — {warning}',
                                            lambda r=row: self.strip.select_row(r))
        self.strip.set_badges(badges)
        s = batch_summary(self.photos, self.settings, self.edits)
        parts, tips = [], []
        if s['low']:
            parts.append(tr('{low} ниже 240 PPI', low=s["low"]))
            tips.append(tr('Детализации может не хватить для выбранного размера печати.'))
        if s['up'] and not self.settings.allow_upscale:
            parts.append(tr('{up} будут пропущены', up=s["up"]))
            tips.append(tr('Увеличение запрещено, а эти снимки меньше нужного размера.'))
        if s['crop']:
            parts.append(tr('{crop} с обрезкой ≥15%', crop=s["crop"]))
            tips.append(tr('Проверьте кадр или выберите «Вписать».'))
        self.summary_chip.setVisible(bool(parts))
        self.summary_chip.setText(' · '.join(parts))
        self.summary_chip.setToolTip('\n'.join(tips))
        n = len(self.photos)
        self.nav_label.setText(f'{self.current + 1} / {n}' + (tr(' · с правками: {edited}', edited=s["edited"]) if s['edited'] else '') if n else '')

    def _update_info(self, notes=None):
        self.info_flow.clear()
        p = self.photo()
        if not p:
            return
        info = assess(p.size, self.settings, self.edit())
        w, h = info['pixels']
        self.info_flow.add(Chip(f'{w} × {h} px', 'neutral'))
        if info['ppi'] is not None:
            kind = 'success' if info['ppi'] >= 240 else 'warning'
            self.info_flow.add(Chip(f'≈ {info["ppi"]} PPI', kind))
        if info['downscale']:
            self.info_flow.add(Chip(tr('уменьшение ×{v:.1f}', v=1 / info["scale"]), 'neutral'))
        for text in info['warnings']:
            if 'PPI' not in text:
                self.info_flow.add(Chip(text, 'warning'))
        from ..model import NEURAL_MIN_SCALE
        from ..pipeline import neural_wanted
        if info['scale'] >= NEURAL_MIN_SCALE and not neural_wanted(self.settings, self.edit()) and p.megapixels <= 4:
            self.info_flow.add(Chip(tr('Мало разрешения — поможет нейросеть'), 'neural'))
        for text in notes or []:
            if tr('Нейросеть применена') in text:
                self.info_flow.add(Chip(tr('Нейросеть ✓'), 'neural'))
            elif not text.startswith(tr('Нейросеть')):
                self.info_flow.add(Chip(text, 'neutral'))
        e = self.edit()
        if e and not e.is_default():
            self.info_flow.add(Chip(tr('есть правки снимка'), 'accent'))

    # ================================================================= preview
    def _key(self):
        p = self.photo()
        if not p:
            return None
        e = self.edit() or Edit()
        return (str(p.path), json.dumps(self.settings.to_dict(), sort_keys=True), json.dumps(e.to_dict(), sort_keys=True),
                self.view_mode != 'result', self.proof_btn.isChecked(), self.gamut_btn.isChecked())

    def _schedule(self, delay=0, interactive=False):
        if not self.photo():
            return
        self._interactive = interactive
        self.preview_timer.start(delay)

    def _request_fit(self):
        p = self.photo()
        if not p:
            return
        if self.crop_mode:
            self._request_crop_image()
            return
        key = self._key()
        dpr = self.devicePixelRatioF() or 1
        target = int(max(self.viewer.width(), self.viewer.height()) * dpr)
        target = max(600, min(2600, int(target * (.5 if getattr(self, '_interactive', False) else 1))))
        self.gen += 1
        self.fit_key = key
        req = PreviewRequest(self.gen, p, copy_settings(self.settings), copy_edit(self.edit() or Edit()), 'fit',
                             target, None, self.view_mode != 'result', self.proof_btn.isChecked(), self.gamut_btn.isChecked())
        if not getattr(self, '_interactive', False):
            self.last_request = req
        self.service.request(req)
        if getattr(self, '_interactive', False):
            self._interactive = False
            self.preview_timer.start(260)

    def _request_roi(self, region):
        p = self.photo()
        if not p or self.crop_mode:
            return
        self.gen += 1
        self.roi_key = (self._key(), region)
        self.service.request(PreviewRequest(self.gen, p, copy_settings(self.settings), copy_edit(self.edit() or Edit()), 'roi',
                                            0, region, self.view_mode != 'result', self.proof_btn.isChecked(), self.gamut_btn.isChecked()))

    def _request_crop_image(self):
        p = self.photo()
        if not p:
            return
        self.gen += 1
        dpr = self.devicePixelRatioF() or 1
        self.service.request(PreviewRequest(self.gen, p, copy_settings(self.settings), copy_edit(self.edit() or Edit()), 'crop',
                                            int(max(self.viewer.width(), self.viewer.height()) * dpr)))

    def _on_status(self, gen, text, progress):
        if gen == self.gen:
            self.viewer.set_status(text, progress)

    def _on_failed(self, gen, text):
        if gen == self.gen:
            self.viewer.clear_status()
            self.toast.show_message(tr('Не удалось построить просмотр'), text, 'danger')

    def _on_analyzed(self, path, analysis):
        first = path not in self.analyses
        self.analyses[path] = analysis
        p = self.photo()
        if p and str(p.path) == path and first:
            offsets, _ = auto_values(analysis, self.settings.adjust, assess(p.size, self.settings, self.edit())['scale'])
            self.inspector.set_auto_notes(analysis, offsets)

    def _on_ready(self, result):
        p = self.photo()
        if not p or result.path != str(p.path):
            return
        if result.gen == self.gen:
            self.viewer.clear_status()
        if result.mode == 'crop':
            if self.crop_mode:
                ratio = self._crop_ratio(result.geometry)
                if self.viewer.crop is None or self.viewer.mode != 'crop':
                    self.viewer.enter_crop(result.image, result.k, result.geometry.crop, ratio)
                else:
                    self.viewer.update_crop_image(result.image, result.k, result.geometry.crop, ratio)
            return
        if result.mode == 'fit':
            self.viewer.set_canvas(result.canvas)
            self.viewer.set_fit(result.image, result.before)
            self.fit_done_key = self.fit_key
            if result.hist:
                self.inspector.set_histogram(result.hist)
            self._prefetch_neighbours()
        else:
            self.viewer.set_roi(result.image, result.region, result.before)
            if self.fit_done_key != self._key():
                self._schedule(0)
        self.last_result = result
        self._show_neural_state(result.neural, result.neural_reason)
        self._update_info(result.notes)
        self.time_label.setText(tr('{v:.0f} мс', v=result.seconds * 1000))
        self.status_render.setText(tr('Просмотр: {v:.0f} мс', v=result.seconds * 1000))

    def _prefetch_neighbours(self):
        """Decode, analyse and render the next and previous photos while the user looks at this one."""
        if not self.last_request:
            return
        jobs = []
        for row in (self.current + 1, self.current - 1, self.current + 2):
            if 0 <= row < len(self.photos) and row != self.current:
                photo = self.photos[row]
                jobs.append(replace(self.last_request, gen=0, info=photo,
                                    edit=copy_edit(self.edits.get(str(photo.path)) or Edit())))
        self.service.prefetch(jobs)

    # ================================================================= neural
    def _enhance_key(self):
        p = self.photo()
        if not p:
            return None
        e = self.edit() or Edit()
        from ..neural import denoise_level
        return p.key + (e.rotation % 360, round(e.angle, 3), denoise_level(self.settings.neural_detail))

    def _show_neural_state(self, state, reason=''):
        key = self._enhance_key()
        if state == 'pending' and key in self.neural_progress:
            f, eta = self.neural_progress[key]
            self.inspector.set_neural_state('running', progress=f, eta=eta)
            self.viewer.set_neural_badge(self._neural_text(f, eta), f)
            return
        self.inspector.set_neural_state(state, reason)
        if state == 'pending':
            self.viewer.set_neural_badge(tr('Нейросеть: готовим улучшение снимка…'), 0.)
        else:
            self.viewer.set_neural_badge(None)

    @staticmethod
    def _neural_text(f, eta):
        return tr('Нейросеть улучшает снимок · {v:.0f}%', v=f * 100) + (tr(' · ещё ≈ {eta:.0f} с', eta=eta) if eta >= 1 else '')

    def _neural_progress(self, key, fraction, eta):
        self.neural_progress[key] = (fraction, eta)
        self.status_neural.setText(tr('Нейросеть: {v:.0f}%', v=fraction * 100))
        if key == self._enhance_key():
            self.inspector.set_neural_state('running', progress=fraction, eta=eta)
            self.viewer.set_neural_badge(self._neural_text(fraction, eta), fraction)

    def _neural_done(self, key):
        self.neural_progress.pop(key, None)
        self.status_neural.setText(tr('Нейросеть: готово'))
        if key == self._enhance_key():
            self.viewer.set_neural_badge(None)
            self.viewer.clear_roi()
            self._schedule(0)

    def _neural_failed(self, key, text):
        self.neural_progress.pop(key, None)
        self.viewer.set_neural_badge(None)
        self.status_neural.setText(tr('Нейросеть: ошибка'))
        self.toast.show_message(tr('Нейросеть не смогла обработать снимок'), text, 'danger')

    def _zoom_changed(self, zoom):
        self.zoom_seg.setValue(zoom)

    def _toggle_zoom(self):
        if self.photo() and not self.crop_mode:
            self.viewer.set_zoom(1.0 if self.viewer.zoom == 'fit' else 'fit')

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.view_seg.setValue(mode)
        self.viewer.set_view_mode(mode)
        self.store.setValue('view_mode', mode)
        self._schedule(0)

    def _toggle_safe(self, on):
        s = self.settings
        self.viewer.set_safe_zone(s.dpi / 25.4 if on and s.size_mode == 'print' else None, 3)

    def _toggle_proof(self, _=None):
        if self.gamut_btn.isChecked() and not self.proof_btn.isChecked():
            self.proof_btn.setChecked(True)
            return
        self._schedule(0)

    def _set_background(self, name):
        self.viewer.set_background(name)
        self.store.setValue('viewer_bg', name)

    # ================================================================= crop & rotate
    def _crop_ratio(self, geom):
        e = self.edit() or Edit()
        if self.settings.size_mode in ('print', 'pixels'):
            return geom.image[0] / geom.image[1]
        if e.aspect:
            return e.aspect
        w, h = geom.source
        return w / h

    def set_crop_mode(self, on):
        if on and not self.photo():
            on = False
        self.crop_mode = on
        for w, value in ((self.crop_tool, on), ):
            w.blockSignals(True)
            w.setChecked(value)
            w.blockSignals(False)
        self.inspector.set_crop_mode(on)
        self.crop_done.setVisible(on)
        self.zoom_seg.setEnabled(not on)
        self.view_seg.setEnabled(not on)
        if on:
            self.viewer.set_zoom('fit')
            self.viewer.set_status(tr('Подготавливаем кадрирование…'))
            self._request_crop_image()
            if self.scope != 'photo':
                self.inspector.set_scope('photo')
        else:
            self.viewer.exit_crop()
            self._schedule(0)

    def _crop_edited(self, cx, cy, zoom):
        p = self.photo()
        if not p:
            return
        e = copy_edit(self.edit() or Edit())
        e.center_x, e.center_y, e.zoom, e.manual_crop = cx, cy, zoom, True
        if self.settings.size_mode in ('print', 'pixels') and (e.fit or self.settings.fit) == 'contain':
            e.fit = 'cover'
        self.edits[str(p.path)] = e
        self._sync_inspector()
        self._after_change(True)

    def rotate(self, degrees):
        p = self.photo()
        if not p:
            return
        e = copy_edit(self.edit() or Edit())
        e.rotation = (e.rotation + degrees) % 360
        e.center_x = e.center_y = .5
        self.edits[str(p.path)] = e
        if e.is_default():
            self.edits.pop(str(p.path))
        self._sync_inspector()
        self.viewer.set_canvas(assess(p.size, self.settings, e)['pixels'], reset=True)
        self._after_change(True)

    # ================================================================= inspector actions
    def _scope_changed(self, scope):
        self.scope = scope

    def _inspector_action(self, name):
        p = self.photo()
        if name == 'view100':
            if p:
                self.set_crop_mode(False)
                self.viewer.set_zoom(1.0)
        elif name == 'crop':
            self.set_crop_mode(not self.crop_mode)
        elif name == 'rotate_left':
            self.rotate(-90)
        elif name == 'rotate_right':
            self.rotate(90)
        elif name == 'reset_photo' and p:
            self.edits.pop(str(p.path), None)
            self._sync_inspector()
            self.viewer.set_canvas(assess(p.size, self.settings, None)['pixels'], reset=True)
            self._after_change(True)
        elif name == 'reset_frame' and p:
            e = copy_edit(self.edit() or Edit())
            e.rotation, e.angle, e.fit, e.aspect, e.center_x, e.center_y, e.zoom, e.manual_crop = 0, 0., None, None, .5, .5, 1., False
            if e.is_default():
                self.edits.pop(str(p.path), None)
            else:
                self.edits[str(p.path)] = e
            self._sync_inspector()
            self.viewer.set_canvas(assess(p.size, self.settings, e)['pixels'], reset=True)
            self._after_change(True)
        elif name == 'to_preset' and p:
            e = self.edit()
            if e and e.offsets:
                from ..model import combined_adjust
                self.settings = replace(self.settings, adjust=combined_adjust(self.settings, e))
                e = copy_edit(e)
                e.offsets = {}
                if e.is_default():
                    self.edits.pop(str(p.path), None)
                else:
                    self.edits[str(p.path)] = e
                self._sync_inspector()
                self._after_change(True)
                self.toast.show_message(tr('Правки перенесены в пресет'), tr('Теперь они применяются ко всем фото. Сохраните пресет, чтобы не потерять.'), 'info')
        elif name == 'copy_edits':
            self.copy_edits_to_selected()

    def copy_edits_to_selected(self):
        p = self.photo()
        if not p:
            return
        source = self.edit() or Edit()
        rows = [r for r in self.strip.selected_rows() if r != self.current]
        if not rows:
            self.toast.show_message(tr('Выделите снимки в ленте'), tr('Ctrl или Shift + щелчок — затем повторите. Правки цвета и нейросети скопируются.'), 'info')
            return
        for r in rows:
            target = self.photos[r]
            e = copy_edit(self.edits.get(str(target.path)) or Edit())
            e.offsets = dict(source.offsets)
            e.neural = source.neural
            if e.is_default():
                self.edits.pop(str(target.path), None)
            else:
                self.edits[str(target.path)] = e
        self._after_change(True)
        self.toast.show_message(tr('Правки скопированы: {n}', n=len(rows)), tr('Кадр и поворот у каждого снимка свои.'), 'success', timeout=3500)

    # ================================================================= presets
    def _refresh_presets(self):
        self.presets.set_presets(self.library.all(), self.active_id, self._dirty())
        self._update_preset_card()

    def _preset_action(self, name):
        pid = self.active_id
        actions = {
            'save': self.save_preset, 'save_as': self.save_preset_as, 'revert': self.revert_preset,
            'rename': lambda: self.rename_preset(pid), 'delete': lambda: self.delete_preset(pid),
            'duplicate': lambda: self.duplicate_preset(pid) if pid else self.save_preset_as(),
            'export': lambda: self.export_preset_file(pid or ''), 'import': self.import_preset_file,
            'manage': self.manage_presets,
        }
        actions[name]()

    def manage_presets(self):
        dialog = PresetManager(self.library, self.active_id, self)
        dialog.exec()
        if self.active_id and self.library.get(self.active_id) is None:
            self.active_id = None
        self._refresh_presets()
        if dialog.apply_id:
            self.apply_preset(dialog.apply_id)

    def apply_preset(self, pid):
        preset = self.library.get(pid)
        if not preset:
            return
        self.active_id = pid
        self.settings = copy_settings(preset.settings)
        self._sync_all()
        self._after_change(True)

    def revert_preset(self):
        if self.active_id:
            self.apply_preset(self.active_id)

    def save_preset(self):
        if not (self.active_id and self.active_id.startswith('user:')):
            return self.save_preset_as()
        try:
            name = self.active_id.split(':', 1)[1]
            self.library.put(name, copy_settings(self.settings), describe(self.settings))
            self._refresh_presets()
            self.toast.show_message(tr('Пресет «{name}» сохранён', name=name), '', 'success', timeout=2500)
        except Exception as e:
            self.error(str(e))

    def save_preset_as(self):
        base = self.library.get(self.active_id)
        suggestion = self.library.unique_name((base.name if base else tr('Мой пресет')) + (tr(' — копия') if base and base.builtin else ''))
        name, ok = QInputDialog.getText(self, tr('Новый пресет'), tr('Название пресета:'), text=suggestion)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.library.user and QMessageBox.question(self, tr('Заменить?'), tr('Пресет «{name}» уже есть. Заменить?', name=name)) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.active_id = self.library.put(name, copy_settings(self.settings), describe(self.settings))
            self._refresh_presets()
            self._commit()
            self.toast.show_message(tr('Пресет «{name}» сохранён и выбран', name=name), tr('Он появился в разделе «Мои» слева.'), 'success', timeout=3000)
        except Exception as e:
            self.error(str(e))

    def duplicate_preset(self, pid):
        preset = self.library.get(pid)
        if not preset:
            return
        name = self.library.unique_name(preset.name + tr(' — копия'))
        self.active_id = self.library.put(name, copy_settings(preset.settings), preset.note)
        self.settings = copy_settings(preset.settings)
        self._refresh_presets()
        self._sync_all()
        self._after_change(True)

    def rename_preset(self, pid):
        preset = self.library.get(pid)
        if not preset or preset.builtin:
            return
        name, ok = QInputDialog.getText(self, tr('Переименовать пресет'), tr('Новое название:'), text=preset.name)
        if not ok or not name.strip() or name.strip() == preset.name:
            return
        try:
            new_id = self.library.rename(pid, name)
            if self.active_id == pid:
                self.active_id = new_id
            self._refresh_presets()
        except Exception as e:
            self.error(str(e))

    def delete_preset(self, pid):
        preset = self.library.get(pid)
        if not preset or preset.builtin:
            return
        if QMessageBox.question(self, tr('Удалить пресет?'), tr('Удалить «{name}»? Это нельзя отменить.', name=preset.name)) != QMessageBox.StandardButton.Yes:
            return
        self.library.delete(pid)
        if self.active_id == pid:
            self.active_id = None
        self._refresh_presets()

    def export_preset_file(self, pid):
        preset = self.library.get(pid) if pid else None
        name = preset.name if preset else tr('Свои настройки')
        settings = preset.settings if preset and pid != self.active_id else self.settings
        path, _ = QFileDialog.getSaveFileName(self, tr('Экспорт пресета'), f'{name}.printprep.json', tr('Пресет Print Prep (*.json)'))
        if path:
            try:
                export_preset(Path(path), name, settings, preset.note if preset else '')
                self.toast.show_message(tr('Пресет сохранён в файл'), tr('Передайте файл коллегам: «Импортировать пресет».'), 'success', timeout=3000)
            except Exception as e:
                self.error(str(e))

    def import_preset_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Импорт пресета или рецепта'), '', 'Print Prep (*.json)')
        if not path:
            return
        try:
            name, settings, edits = read_preset_file(Path(path))
            name = self.library.unique_name(name) if name in self.library.user else name
            self.active_id = self.library.put(name, settings, describe(settings))
            self.settings = copy_settings(settings)
            matched = 0
            if edits and self.folder:
                for photo in self.photos:
                    rel = str(photo.path.relative_to(self.folder))
                    if rel in edits:
                        self.edits[str(photo.path)] = edits[rel]
                        matched += 1
            self._refresh_presets()
            self._sync_all()
            self._after_change(True)
            self.toast.show_message(tr('Импортирован «{name}»', name=name), tr('Правок снимков сопоставлено: {matched}.', matched=matched) if edits else '', 'success')
        except Exception as e:
            self.error(tr('Не удалось импортировать: {e}', e=e))

    def export_recipe_file(self):
        if not self.folder:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr('Экспорт рецепта'), 'recipe.printprep.json', tr('Рецепт Print Prep (*.json)'))
        if path:
            edits = {str(Path(k).relative_to(self.folder)): v for k, v in self.edits.items() if Path(k).is_relative_to(self.folder)}
            preset = self.library.get(self.active_id)
            export_recipe(Path(path), preset.name if preset else tr('Рецепт'), self.settings, edits)

    # ================================================================= export
    def export(self):
        if not self.photos or (self.export_job and self.export_job.running()):
            return
        try:
            self.settings.validate()
        except Exception as e:
            self.error(str(e))
            return
        preset = self.library.get(self.active_id)
        name = preset.name + (tr(' (изменён)') if self._dirty() and preset else '') if preset else tr('Свои настройки')
        self.export_job = ExportJob(self.folder, self.photos, self.settings, self.edits, name, self.cache, self)
        self.export_job.progress.connect(self._export_progress)
        self.export_job.file_progress.connect(self._export_file_progress)
        self.export_job.finished.connect(self._export_done)
        self.export_job.failed.connect(self._export_failed)
        self.progress_bar.setRange(0, len(self.photos))
        self.progress_bar.setValue(0)
        self.progress_text.setText(tr('Готовим 0 из {n}…', n=len(self.photos)))
        self.progress_box.show()
        self.stop_btn.setEnabled(True)
        self._update_export_button()
        self.export_job.start()
        self._update_export_button()
        self.store.setValue('settings', json.dumps(self.settings.to_dict(), ensure_ascii=False))

    def _export_progress(self, done, total, row):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(done)
        self.progress_text.setText(tr('Готово {done} из {total} · {name}', done=done, total=total, name=Path(row["source"]).name))

    def _export_file_progress(self, path, fraction):
        if self.settings.neural:
            self.progress_text.setText(tr('Нейросеть: {name} · {v:.0f}%', name=Path(path).name, v=fraction * 100))

    def cancel_export(self):
        if self.export_job:
            self.export_job.cancel()
            self.stop_btn.setEnabled(False)
            self.progress_text.setText(tr('Останавливаем после текущих файлов…'))

    def _export_done(self, output, report):
        self.progress_box.hide()
        self._update_export_button()
        rows = report['results']
        ok = sum(r['status'] == 'ok' for r in rows)
        bad = sum(r['status'] == 'error' for r in rows)
        skipped = sum(r['status'] == 'skipped' for r in rows)
        title = (tr('Остановлено: ') if report['cancelled'] else tr('Готово: ')) + tr('{ok} из {n} фото', ok=ok, n=len(rows))
        detail = output.name + (tr(' · ошибок {bad}', bad=bad) if bad else '') + (tr(' · пропущено {skipped}', skipped=skipped) if skipped else '')
        self.last_output = output
        self.toast.show_message(title, detail, 'success' if not bad else 'warning',
                                actions=[(tr('Открыть папку'), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(output))), 'Primary'),
                                         (tr('Отчёт'), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(output / 'report.csv'))), None)],
                                timeout=0)

    def _export_failed(self, text):
        self.progress_box.hide()
        self._update_export_button()
        self.error(tr('Экспорт не выполнен: {text}', text=text))

    # ================================================================= app settings, tour
    def open_app_settings(self):
        from .app_settings import AppSettingsDialog
        dialog = AppSettingsDialog(self)
        if dialog.exec() != AppSettingsDialog.DialogCode.Accepted:
            return
        changed = dialog.save()
        if dialog.tutorial_requested:
            self.store.setValue('tutorial_done', False)
        if 'language' in changed:
            # Some labels are built once at import; a quick restart switches every one of them.
            from .app import restart
            QTimer.singleShot(0, lambda: restart(self))
        elif changed:
            from .app import rebuild as rebuild_window
            QTimer.singleShot(0, lambda: rebuild_window(self).maybe_show_tutorial())
        elif dialog.tutorial_requested:
            self.show_tutorial()

    def maybe_show_tutorial(self):
        if not self.store.value('tutorial_done', False, type=bool):
            QTimer.singleShot(250, self.show_tutorial)

    def show_tutorial(self):
        if getattr(self, 'tour', None) is not None:
            return
        from .tutorial import Tour

        def done():
            self.tour = None
            self.store.setValue('tutorial_done', True)
        self.tour = Tour(self, done)
        self.tour.start()

    # ================================================================= misc
    def error(self, text):
        QMessageBox.warning(self, 'Print Prep', text)

    def show_help(self):
        QMessageBox.information(self, tr('Print Prep · Справка'), (
            tr('КАК РАБОТАТЬ\n'
            '1. Откройте или перетащите папку со снимками.\n'
            '2. Выберите пресет слева — он сразу применяется ко всем фото.\n'
            '3. Нажмите «Подготовить». Результат — в подпапке PrintPrep_… Оригиналы не меняются.\n\n'
            'ПРИ НЕОБХОДИМОСТИ\n'
            '• Справа «Все фото» — настройки пресета, «Этот снимок» — правки одного фото поверх пресета.\n'
            '• Любое изменение сразу видно. «Сохранить» обновляет ваш пресет, «+» создаёт новый.\n'
            '• Умная авто-коррекция анализирует каждый снимок отдельно; силу и состав можно настроить.\n'
            '• Нейросеть видна в масштабе 100%: там показывается прогресс и результат.\n\n'
            'ГОРЯЧИЕ КЛАВИШИ\n'
            '←/→ — снимки · Пробел/Z — вписать/100% · \\ — до/после · C — кадр · Ctrl+[ ] — поворот\n'
            'Ctrl+Z/Ctrl+Y — отмена/повтор · Ctrl+S — сохранить пресет · Ctrl+E — подготовить · Ctrl+O — папка\n'
            'Двойной щелчок по ползунку — сброс; по снимку — 100% в этой точке.\n\n'
            'ПЕЧАТЬ\n'
            'Для лабораторий оставляйте sRGB и 300 PPI. ICC принтера — только если его требует печатник; '
            'не включайте управление цветом повторно в драйвере. Отпечаток темнее экрана — подберите '
            '«Яркость отпечатка» по пробе и сохраните в пресет для своей бумаги.')))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(Path(u.toLocalFile()).is_dir() for u in e.mimeData().urls()):
            e.acceptProposedAction()
            self.viewer.empty.set_drag_active(True)

    def dragLeaveEvent(self, e):
        self.viewer.empty.set_drag_active(False)

    def dropEvent(self, e):
        self.viewer.empty.set_drag_active(False)
        for url in e.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                self.load_folder(path)
                break

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, 'toast'):
            self.toast.reposition()
        if hasattr(self, 'preview_timer') and self.photo() and self.viewer.zoom == 'fit':
            self._schedule(200)
