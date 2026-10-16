"""Batch export: parallel, strip-wise (bounded memory), atomic writes, CSV/JSON report."""
from __future__ import annotations

import csv
import ctypes
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import numpy as np

from . import __version__
from .imageio import inspect, read_exif, save
from .model import Edit, Settings
from .pipeline import AnalysisCache, Source, assess, plan, render, to_output

EXTENSIONS = {'JPEG': '.jpg', 'TIFF': '.tif', 'PNG': '.png'}
STRIP_PIXELS = 6_000_000


def available_memory():
    try:
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                        ('avail', ctypes.c_ulonglong), ('total_page', ctypes.c_ulonglong),
                        ('avail_page', ctypes.c_ulonglong), ('total_virtual', ctypes.c_ulonglong),
                        ('avail_virtual', ctypes.c_ulonglong), ('extended', ctypes.c_ulonglong)]
        status = Status()
        status.length = ctypes.sizeof(Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.avail
    except Exception:
        pass
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except Exception:
        return 8 << 30


def worker_count(settings: Settings, photos):
    if settings.upscaler != 'off':
        return 1  # the network already uses every core
    biggest = max((p.size[0] * p.size[1] for p in photos), default=1)
    per_job = biggest * 3 * 2 + STRIP_PIXELS * 3 * 4 * 7 + 300e6
    by_memory = int(available_memory() * .6 // per_job)
    return max(1, min(6, (os.cpu_count() or 2) // 2, by_memory, len(photos)))


def slug(text):
    text = re.sub(r'[^\w\-]+', '_', text.strip(), flags=re.UNICODE).strip('_')
    return text[:40] or 'preset'


def destinations(folder: Path, output: Path, photos, settings: Settings):
    ext = EXTENSIONS[settings.format]
    taken, result = set(), {}
    for photo in photos:
        relative = photo.path.relative_to(folder)
        stem = relative.stem
        candidate = relative.parent / (stem + ext)
        if str(candidate).casefold() in taken:
            candidate = relative.parent / f'{stem}_{relative.suffix.lstrip(".").lower()}{ext}'
            n = 2
            while str(candidate).casefold() in taken:
                candidate = relative.parent / f'{stem}_{n}{ext}'
                n += 1
        taken.add(str(candidate).casefold())
        result[str(photo.path)] = output / candidate
    return result


def render_file(source: Source, settings: Settings, edit: Edit, cancel=None, progress=None, analysis_cache=None):
    """Full-resolution render in horizontal strips; returns (array, mode, icc, notes, neural)."""
    w, h = plan(source, settings, edit, analysis_cache).canvas
    rows = max(64, STRIP_PIXELS // max(1, w))
    strips, notes, neural_used = [], [], False
    total = (h + rows - 1) // rows
    for index, top in enumerate(range(0, h, rows)):
        if cancel and cancel():
            raise InterruptedError('Остановлено.')
        part_progress = (lambda f, i=index: progress((i + f) / total)) if progress else None
        r = render(source, settings, edit, k=1, region=(0, top, w, min(rows, h - top)),
                   progress=part_progress, cancel=cancel, analysis_cache=analysis_cache)
        strips.append((top, r.image))
        notes.extend(n for n in r.notes if n not in notes)
        neural_used |= r.neural
        if progress:
            progress((index + 1) / total)
    if settings.output_space == 'sRGB':
        dtype = np.uint16 if settings.bit_depth == 16 else np.uint8
        out = np.empty((h, w, 3), dtype=dtype)
        for top, image in strips:
            part, mode, icc = to_output(image, settings, seed=top)
            out[top:top + part.shape[0]] = part
        return out, mode, icc, notes, neural_used
    canvas = np.concatenate([image for _, image in strips], axis=0)
    out, mode, icc = to_output(canvas, settings)
    return out, mode, icc, notes, neural_used


def export_batch(folder: Path, photos, settings: Settings, edits: dict, *, preset_name='', cancel: threading.Event | None = None,
                 progress=None, analysis_cache: AnalysisCache | None = None, workers=None, file_progress=None):
    """Write every photo into a new PrintPrep_* subfolder. Originals are never touched.

    progress(done, total, row) fires after each file; file_progress(path, fraction) during
    long single files (neural). Errors in one photo never stop the others.
    """
    settings.validate()
    stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    output = folder / f'PrintPrep_{slug(preset_name or "export")}_{stamp}'
    n = 2
    while output.exists():
        output = folder / f'PrintPrep_{slug(preset_name or "export")}_{stamp}_{n}'
        n += 1
    output.mkdir()
    targets = destinations(folder, output, photos, settings)
    cancel = cancel or threading.Event()
    analysis_cache = analysis_cache or AnalysisCache()
    lock = threading.Lock()
    rows, done = [], [0]

    def job(photo):
        row = {'source': str(photo.path), 'output': '', 'status': 'error', 'size': '', 'ppi': '', 'notes': '', 'error': ''}
        if cancel.is_set():
            row.update(status='cancelled', error='Остановлено до начала.')
            return row
        try:
            edit = edits.get(str(photo.path)) or Edit()
            edit.validate()
            info = inspect(photo.path)
            check = assess(info.size, settings, edit)
            row['ppi'] = check['ppi'] or ''
            if check['upscale'] and not settings.allow_upscale:
                row.update(status='skipped', error='Увеличение запрещено настройками: снимок меньше нужного размера.')
                return row
            source = Source.open(info, analysis_cache)
            fp = (lambda f: file_progress(photo.path, f)) if file_progress else None
            array, mode, icc, notes, _ = render_file(source, settings, edit, cancel.is_set, fp, analysis_cache)
            dest = targets[str(photo.path)]
            exif = read_exif(photo.path) if settings.keep_exif else None
            save(dest, array, settings.format, quality=settings.quality, dpi=settings.dpi, icc=icc, exif=exif, mode=mode)
            auto_notes = list(source.analysis.get('notes', [])) if settings.adjust.auto and source.analysis else []
            row.update(output=str(dest), status='ok', size=f'{array.shape[1]}×{array.shape[0]}',
                       notes=' | '.join(info.warnings + source.notes + check['warnings'] + auto_notes + notes))
        except InterruptedError:
            row.update(status='cancelled', error='Остановлено.')
        except Exception as e:
            from .neural import Cancelled
            if isinstance(e, Cancelled):
                row.update(status='cancelled', error='Остановлено.')
            else:
                row['error'] = str(e) or e.__class__.__name__
        return row

    count = workers or worker_count(settings, photos)
    with ThreadPoolExecutor(max_workers=count, thread_name_prefix='printprep-export') as pool:
        futures = [pool.submit(job, p) for p in photos]
        for future in as_completed(futures):
            row = future.result()
            with lock:
                rows.append(row)
                done[0] += 1
                current = done[0]
            if progress:
                progress(current, len(photos), row)
    order = {str(p.path): i for i, p in enumerate(photos)}
    rows.sort(key=lambda r: order.get(r['source'], 0))
    report = {'app': 'Print Prep', 'version': __version__, 'preset': preset_name, 'settings': settings.to_dict(),
              'edits': {str(Path(k).relative_to(folder)) if Path(k).is_relative_to(folder) else k: v.to_dict()
                        for k, v in edits.items() if v is not None},
              'results': rows, 'total': len(photos), 'workers': count,
              'cancelled': any(r['status'] == 'cancelled' for r in rows)}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output / 'report.csv').open('w', encoding='utf-8-sig', newline='') as f:
        names = ['source', 'output', 'status', 'size', 'ppi', 'notes', 'error']
        writer = csv.DictWriter(f, fieldnames=names, delimiter=';')
        writer.writeheader()
        # Neutralise spreadsheet formulas coming from file names or messages.
        writer.writerows({k: ("'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else v) for k, v in r.items()} for r in rows)
    return output, report
