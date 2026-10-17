"""Background work for the UI: preview rendering, neural enhancement, thumbnails, export.

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
from ..pipeline import (AnalysisCache, Source, assess, enhance_key, enhanced, needs_analysis, neural_status, plan,
                        render_fast, soft_proof)


def to_qimage(array):
    """uint8 or float [0, 1] RGB array → QImage (deep copy)."""
    if array.dtype != np.uint8:
        array = np.round(np.clip(array, 0, 1) * 255).astype(np.uint8)
    array = np.ascontiguousarray(array)
    h, w = array.shape[:2]
    return QImage(array.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def histogram(u8):
    """RGB + luminance histograms (256 bins, normalised) and clipping fractions."""
    small = u8[::2, ::2].reshape(-1, 3)
    hists = [np.bincount(small[:, c], minlength=256).astype(np.float32) for c in range(3)]
    lum = np.round(small @ np.array([.2126, .7152, .0722])).astype(np.int32)
    hists.append(np.bincount(np.clip(lum, 0, 255), minlength=256).astype(np.float32))
    n = max(1, small.shape[0])
    clip_low = float((small.max(axis=1) <= 1).mean())
    clip_high = float((small.max(axis=1) >= 254).mean())
    return {'channels': [h / n for h in hists], 'low': clip_low, 'high': clip_high}


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
    neural: str = 'off'               # off | not_needed | pending | ready
    neural_reason: str = ''
    hist: dict | None = None


class NeuralWorker(QObject):
    """Runs Real-ESRGAN for one photo at a time. Colour edits never restart it; a different
    photo or orientation replaces the job."""
    progress = Signal(object, float, float)     # key, fraction, eta seconds
    done = Signal(object)                       # key
    failed = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cond = threading.Condition()
        self.job = None
        self.current = None
        self.running = True
        self.thread = threading.Thread(target=self._loop, name='printprep-neural', daemon=True)
        self.thread.start()

    def ensure(self, source, settings, edit):
        key = enhance_key(source, edit, settings)
        with self.cond:
            if self.current == key or (self.job and self.job[0] == key):
                return key
            self.job = (key, source, replace(settings, adjust=replace(settings.adjust)), replace(edit or Edit()))
            if self.current is not None:
                self.current = None          # the running photo is no longer wanted: let it stop
            self.cond.notify()
        return key

    def cancel(self):
        with self.cond:
            self.job = None
            self.current = None

    def busy_key(self):
        with self.cond:
            return self.current or (self.job[0] if self.job else None)

    def stop(self):
        with self.cond:
            self.running = False
            self.job = None
            self.current = None
            self.cond.notify()
        self.thread.join(timeout=5)

    def _loop(self):
        from ..neural import release
        while True:
            with self.cond:
                while self.running and self.job is None:
                    self.cond.wait()
                if not self.running:
                    break
                key, source, settings, edit = self.job
                self.job = None
                self.current = key
            try:
                stale = lambda: self.current != key or not self.running
                enhanced(source, settings, edit, progress=lambda f, eta: self.progress.emit(key, f, eta), cancel=stale)
                if not stale():
                    self.done.emit(key)
            except Cancelled:
                pass
            except Exception as e:
                traceback.print_exc()
                self.failed.emit(key, str(e) or e.__class__.__name__)
            finally:
                with self.cond:
                    if self.current == key:
                        self.current = None
        release()


class RenderService(QObject):
    status = Signal(int, str, object)     # generation, text, progress fraction or None
    ready = Signal(object)
    failed = Signal(int, str)
    analyzed = Signal(str, object)        # path, analysis dict

    def __init__(self, analysis_cache: AnalysisCache, neural_worker: NeuralWorker, parent=None):
        super().__init__(parent)
        self.cache = analysis_cache
        self.neural = neural_worker
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
        if source.analysis is None and needs_analysis(settings, edit):
            self.status.emit(req.gen, 'Анализ снимка: свет, цвет, лица…', None)
            source.ensure_analysis(self.cache)
        if source.analysis is not None:
            self.analyzed.emit(str(req.info.path), source.analysis)
        if self._stale(req):
            return
        geom = plan(source, settings, edit, self.cache)
        if req.mode == 'crop':
            import cv2
            base = source.base(replace(edit, manual_crop=False), False)
            h, w = base.shape[:2]
            k = min(1, req.target / max(h, w))
            small = cv2.resize(base, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
            image = to_qimage((small >> 8).astype(np.uint8) if small.dtype == np.uint16 else small)
            self.ready.emit(PreviewResult(req.gen, 'crop', image, None, geom.canvas, k, None, geom, [],
                                          source.analysis, time.perf_counter() - started, str(req.info.path)))
            return
        applies, reason = neural_status(source, settings, edit, geom)
        entry = enhanced(source, settings, edit, compute=False) if applies else None
        state = 'ready' if entry is not None else 'pending' if applies else ('not_needed' if reason else 'off')
        if state == 'pending':
            self.neural.ensure(source, settings, edit)
        cw, ch = geom.canvas
        if req.mode == 'roi':
            k, use_full, region = 1.0, True, req.region
            self.status.emit(req.gen, 'Рендер 1:1 в полном разрешении…', None)
        else:
            k, use_full, region = min(1., req.target / max(cw, ch)), False, None
        result = render_fast(source, settings, edit, k=k, region=region, use_full=use_full,
                             enhanced_source=entry, analysis_cache=self.cache)
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
        notes = list(dict.fromkeys(source.notes + result.notes + ([reason] if reason else [])))
        self.ready.emit(PreviewResult(req.gen, req.mode, to_qimage(display), before, geom.canvas, k, region, geom,
                                      notes, source.analysis, time.perf_counter() - started, str(req.info.path),
                                      state, reason, histogram(display) if req.mode == 'fit' else None))


class ThumbnailLoader(QObject):
    ready = Signal(int, str, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='printprep-thumb')
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
