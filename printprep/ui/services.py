"""Background work for the UI: preview rendering, thumbnails and batch export.

Signals are emitted from worker threads; Qt queues them to the GUI thread.
"""
from __future__ import annotations

import threading
import time
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from ..imageio import thumbnail
from ..model import Edit, Settings
from ..neural import Cancelled
from ..pipeline import AnalysisCache, Source, assess, plan, render_fast, soft_proof, transform


def to_qimage(array):
    """uint8 or float [0, 1] RGB array → QImage (deep copy)."""
    if array.dtype != np.uint8:
        array = np.round(np.clip(array, 0, 1) * 255).astype(np.uint8)
    array = np.ascontiguousarray(array)
    h, w = array.shape[:2]
    return QImage(array.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


@dataclass
class PreviewRequest:
    gen: int
    info: object
    settings: Settings
    edit: Edit
    mode: str = 'fit'                 # fit | roi | crop
    target: int = 1600                # long edge for fit / crop
    region: tuple | None = None       # roi in canvas pixels at 100%
    compare: bool = False
    proof: bool = False
    gamut: bool = False


@dataclass
class PreviewResult:
    gen: int
    mode: str
    image: QImage
    before: QImage | None
    canvas: tuple
    k: float
    region: tuple | None
    geometry: object
    notes: list = field(default_factory=list)
    analysis: dict | None = None
    seconds: float = 0
    path: str = ''


class RenderService(QObject):
    status = Signal(int, str, object)     # generation, text, progress fraction or None
    ready = Signal(object)
    failed = Signal(int, str)
    analyzed = Signal(str, object)        # path, analysis dict

    def __init__(self, analysis_cache: AnalysisCache, parent=None):
        super().__init__(parent)
        self.cache = analysis_cache
        self.sources = OrderedDict()
        self.cond = threading.Condition()
        self.pending = None
        self.latest = 0
        self.running = True
        self.busy = False
        self.thread = threading.Thread(target=self._loop, name='printprep-preview', daemon=True)
        self.thread.start()

    def request(self, req: PreviewRequest):
        with self.cond:
            self.pending = req
            self.latest = req.gen
            self.cond.notify()

    def cancel(self, gen):
        with self.cond:
            self.latest = max(self.latest, gen)
            self.pending = None

    def stop(self):
        with self.cond:
            self.running = False
            self.pending = None
            self.latest += 1
            self.cond.notify()
        self.thread.join(timeout=5)

    def is_idle(self):
        with self.cond:
            return self.pending is None and not self.busy

    def drop_source(self, path=None):
        with self.cond:
            if path is None:
                self.sources.clear()
            else:
                for key in [k for k in self.sources if k[0] == path]:
                    self.sources.pop(key, None)

    def _loop(self):
        from ..neural import release
        while True:
            with self.cond:
                while self.running and self.pending is None:
                    self.cond.wait()
                if not self.running:
                    break
                req, self.pending = self.pending, None
                self.busy = True
            try:
                self._process(req)
            except Cancelled:
                pass
            except Exception as e:
                traceback.print_exc()
                self.failed.emit(req.gen, str(e) or e.__class__.__name__)
            finally:
                with self.cond:
                    self.busy = False
        release()

    def _stale(self, req):
        return req.gen != self.latest or not self.running

    def _source(self, req):
        key = req.info.key
        with self.cond:
            source = self.sources.get(key)
            if source is not None:
                self.sources.move_to_end(key)
                return source
        self.status.emit(req.gen, 'Загружаем снимок…', None)
        source = Source.open(req.info, self.cache)
        with self.cond:
            self.sources[key] = source
            while len(self.sources) > 3:
                self.sources.popitem(last=False)
        return source

    def _process(self, req: PreviewRequest):
        started = time.perf_counter()
        if self._stale(req):
            return
        source = self._source(req)
        if self._stale(req):
            return
        settings, edit = req.settings, req.edit
        from ..pipeline import needs_analysis
        if source.analysis is None and needs_analysis(settings, edit):
            self.status.emit(req.gen, 'Анализ снимка: свет, цвет, лица…', None)
            source.ensure_analysis(self.cache)
        if source.analysis is not None:
            self.analyzed.emit(str(req.info.path), source.analysis)
        if self._stale(req):
            return
        cancel = lambda: self._stale(req)
        if req.mode == 'crop':
            base = source.base(replace(edit, manual_crop=False), False)
            h, w = base.shape[:2]
            k = min(1, req.target / max(h, w))
            import cv2
            small = cv2.resize(base, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
            image = to_qimage((small >> 8).astype(np.uint8) if small.dtype == np.uint16 else small)
            geom = plan(source, settings, edit, self.cache)
            self.ready.emit(PreviewResult(req.gen, 'crop', image, None, geom.canvas, k, None, geom, [],
                                          source.analysis, time.perf_counter() - started, str(req.info.path)))
            return
        geom = plan(source, settings, edit, self.cache)
        cw, ch = geom.canvas
        if req.mode == 'roi':
            k, use_full, region = 1.0, True, req.region
            kind = settings.upscaler if edit.neural is None else ('esrgan' if edit.neural else 'off')
            if kind != 'off' and geom.scale > 1.05 or (kind != 'off' and settings.neural_always):
                title = {'fsrcnn': 'FSRCNN ×2', 'esrgan': 'Real-ESRGAN ×4'}.get(kind, 'Нейросеть')
                self.status.emit(req.gen, f'Нейросеть {title} улучшает видимую область…', 0.)
            else:
                self.status.emit(req.gen, 'Рендер 100% · полное разрешение…', None)
        else:
            k = min(1., req.target / max(cw, ch))
            use_full = False
            region = None
            self.status.emit(req.gen, 'Обновляем просмотр…', None)

        def progress(f):
            self.status.emit(req.gen, f'Нейросеть улучшает видимую область · {f * 100:.0f}%', f)
        result = render_fast(source, settings, edit, k=k, region=region, use_full=use_full,
                             progress=progress, cancel=cancel, analysis_cache=self.cache)
        if self._stale(req):
            return
        display = np.round(np.clip(result.image, 0, 1) * 255).astype(np.uint8)
        if req.proof and settings.output_space == 'ICC' and settings.icc_path:
            try:
                display = soft_proof(display, settings, req.gamut)
            except Exception as e:
                result.notes.append(f'ICC-проба недоступна: {e}')
        before = None
        if req.compare:
            plain = render_fast(source, settings, edit, k=k, region=region, use_full=use_full, before=True,
                                analysis_cache=self.cache)
            before = to_qimage(plain.image)
        if self._stale(req):
            return
        notes = list(dict.fromkeys(source.notes + result.notes))
        self.ready.emit(PreviewResult(req.gen, req.mode, to_qimage(display), before, geom.canvas, k, region, geom,
                                      notes, source.analysis, time.perf_counter() - started, str(req.info.path)))


class ThumbnailLoader(QObject):
    ready = Signal(int, str, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='printprep-thumb')
        self.generation = 0

    def load(self, paths, size=240):
        self.generation += 1
        gen = self.generation
        for path in paths:
            self.pool.submit(self._one, gen, path, size)

    def _one(self, gen, path, size):
        if gen != self.generation:
            return
        try:
            image = to_qimage(thumbnail(path, size))
        except Exception:
            image = QImage()
        if gen == self.generation:
            self.ready.emit(gen, str(path), image)

    def stop(self):
        self.generation += 1
        self.pool.shutdown(wait=False, cancel_futures=True)


class ExportJob(QObject):
    progress = Signal(int, int, object)
    file_progress = Signal(str, float)
    finished = Signal(object, object)
    failed = Signal(str)

    def __init__(self, folder, photos, settings, edits, preset_name, cache, parent=None):
        super().__init__(parent)
        self.args = folder, list(photos), replace(settings, adjust=replace(settings.adjust)), \
            {k: replace(v, offsets=dict(v.offsets)) for k, v in edits.items()}, preset_name
        self.cache = cache
        self.cancel_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name='printprep-export', daemon=True)

    def start(self):
        self.thread.start()

    def cancel(self):
        self.cancel_event.set()

    def running(self):
        return self.thread.is_alive()

    def _run(self):
        from ..export import export_batch
        from ..neural import release
        folder, photos, settings, edits, name = self.args
        try:
            out, report = export_batch(folder, photos, settings, edits, preset_name=name, cancel=self.cancel_event,
                                       progress=lambda i, n, row: self.progress.emit(i, n, row),
                                       file_progress=lambda p, f: self.file_progress.emit(str(p), f),
                                       analysis_cache=self.cache)
            self.finished.emit(out, report)
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e) or e.__class__.__name__)
        finally:
            release()


def batch_summary(photos, settings, edits):
    low = crop = up = edited = 0
    for photo in photos:
        edit = edits.get(str(photo.path))
        info = assess(photo.size, settings, edit)
        low += info['ppi'] is not None and info['ppi'] < 240
        crop += info['crop_percent'] >= 15
        up += info['upscale']
        edited += bool(edit and not edit.is_default())
    return dict(low=low, crop=crop, up=up, edited=edited, total=len(photos))
