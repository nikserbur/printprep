"""Print pipeline. No GUI dependencies; all geometry is in oriented image space."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import tempfile
import threading
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image, ImageCms, ImageEnhance, ImageFilter, ImageOps, ImageStat
from .enhance import enhance, PRESETS, DEFAULTS
from . import __version__

SUPPORTED = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.bmp'}
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
SRGB_BYTES = SRGB.tobytes()
MAX_PIXELS = 80_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass
class Settings:
    width_mm: float = 100
    height_mm: float = 150
    size_mode: str = 'print'  # print, pixels, long_edge, original
    pixel_width: int = 3840
    pixel_height: int = 2160
    long_edge: int = 3840
    dpi: int = 300  # File PPI, not printer dot resolution.
    fit: str = 'contain'
    auto_orientation: bool = True
    border_mm: float = 0
    background: str = '#ffffff'
    format: str = 'JPEG'
    quality: int = 95
    output_space: str = 'sRGB'
    icc_path: str = ''
    intent: int = 1  # Relative colorimetric with black-point compensation.
    auto_enhance: bool = False
    sharpen: bool = False
    smart_crop: bool = False
    allow_upscale: bool = True
    enhancement_preset: str = 'none'
    enhancement_strength: float = .7
    shadows: float = 0
    highlights: float = 0
    clarity: float = 0
    vibrance: float = 0
    warmth: float = 0
    tint: float = 0
    chroma_denoise: float = 0
    auto_wb: bool = False
    auto_tone: bool = False
    upscaler: str = 'lanczos'
    neural_strength: float = .6

    def validate(self):
        if self.size_mode not in ('print', 'pixels', 'long_edge', 'original'):
            raise ValueError('Неизвестный режим размера.')
        for value in (self.pixel_width, self.pixel_height, self.long_edge):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 32768:
                raise ValueError('Размер в пикселях должен быть целым числом от 1 до 32768.')
        if self.size_mode != 'print' and self.border_mm:
            raise ValueError('Поля в миллиметрах доступны только в режиме печатного размера.')
        if not all(math.isfinite(v) for v in (self.width_mm, self.height_mm, self.border_mm)):
            raise ValueError('Размеры должны быть конечными числами.')
        if not (10 <= self.width_mm <= 1500 and 10 <= self.height_mm <= 1500):
            raise ValueError('Размер стороны: от 10 до 1500 мм.')
        if not 72 <= self.dpi <= 720:
            raise ValueError('PPI: от 72 до 720.')
        if self.border_mm < 0 or 2 * self.border_mm >= min(self.width_mm, self.height_mm):
            raise ValueError('Поля должны оставлять место для фотографии.')
        if self.fit not in ('cover', 'contain') or self.format not in ('JPEG', 'TIFF'):
            raise ValueError('Неизвестный режим или формат.')
        if self.output_space not in ('sRGB', 'ICC') or self.intent not in (0, 1, 2, 3):
            raise ValueError('Неизвестные настройки цвета.')
        if not 1 <= self.quality <= 95:
            raise ValueError('Качество JPEG: от 1 до 95.')
        if self.output_space == 'ICC':
            if not self.icc_path:
                raise ValueError('Выберите ICC-профиль машины, бумаги и чернил.')
            profile = ImageCms.getOpenProfile(self.icc_path)
            space = profile.profile.xcolor_space.strip()
            if space not in ('RGB', 'CMYK'):
                raise ValueError('Поддерживаются выходные ICC только RGB или CMYK.')
        for key in ('enhancement_strength', 'shadows', 'highlights', 'clarity', 'vibrance', 'chroma_denoise'):
            value = getattr(self, key)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f'Параметр {key} должен быть от 0 до 1.')
        if not all(math.isfinite(v) and -1 <= v <= 1 for v in (self.warmth, self.tint)):
            raise ValueError('Теплота и оттенок должны быть от −1 до 1.')
        if self.upscaler not in ('lanczos', 'fsrcnn') or not math.isfinite(self.neural_strength) or not 0 <= self.neural_strength <= 1:
            raise ValueError('Некорректный метод увеличения или его сила.')
        if self.enhancement_preset not in PRESETS and self.enhancement_preset != 'custom':
            raise ValueError('Неизвестный пресет обработки.')
        Image.new('RGB', (1, 1), self.background)
        if self.size_mode in ('print', 'pixels'):
            w, h = self.pixels
            if w * h > MAX_PIXELS:
                raise ValueError('Результат превышает лимит 80 мегапикселей. Уменьшите размер или PPI.')

    @property
    def pixels(self):
        if self.size_mode == 'pixels':
            return self.pixel_width, self.pixel_height
        if self.size_mode != 'print':
            raise ValueError('Размер зависит от исходника; используйте layout().')
        return tuple(max(1, round(v / 25.4 * self.dpi)) for v in (self.width_mm, self.height_mm))


@dataclass
class Edit:
    rotation: int = 0
    fit: str | None = None
    center_x: float = .5
    center_y: float = .5
    zoom: float = 1
    manual_crop: bool = False
    exposure: float = 0
    contrast: float = 1
    saturation: float = 1
    use_neural: bool | None = None
    neural_strength: float | None = None

    def validate(self):
        if self.fit not in (None, 'cover', 'contain'):
            raise ValueError('Некорректный индивидуальный режим кадрирования.')
        if self.use_neural is not None and type(self.use_neural) is not bool:
            raise ValueError('Некорректный переключатель нейроувеличения.')
        if self.neural_strength is not None and (not math.isfinite(self.neural_strength) or not 0 <= self.neural_strength <= 1):
            raise ValueError('Сила нейроувеличения должна быть от 0 до 1.')
        vals = (self.center_x, self.center_y, self.zoom, self.exposure, self.contrast, self.saturation)
        if not all(math.isfinite(v) for v in vals):
            raise ValueError('Некорректные индивидуальные настройки.')
        if self.rotation % 90 or not (0 <= self.center_x <= 1 and 0 <= self.center_y <= 1):
            raise ValueError('Некорректный поворот или центр кадра.')
        if not (1 <= self.zoom <= 5 and -2 <= self.exposure <= 2 and .5 <= self.contrast <= 1.5 and 0 <= self.saturation <= 1.5):
            raise ValueError('Индивидуальные настройки за допустимыми пределами.')


@dataclass
class Photo:
    path: Path
    size: tuple[int, int]
    mode: str
    profile: str
    warnings: list[str] = field(default_factory=list)


def inspect_photo(path: Path) -> Photo:
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as im:
            if im.width * im.height > MAX_PIXELS:
                raise ValueError('Исходник больше 80 мегапикселей.')
            # Pillow would silently reduce multichannel 16-bit TIFF to 8-bit.
            bits = getattr(im, 'tag_v2', {}).get(258, (8,))
            if isinstance(bits, int):
                bits = (bits,)
            if max(bits) > 8 or im.mode in ('I', 'F') or im.mode.startswith('I;16'):
                raise ValueError('16/32-битный исходник: сначала экспортируйте 8-битную RGB-копию в редакторе.')
            size = im.size
            if im.getexif().get(274, 1) in (5, 6, 7, 8):
                size = size[::-1]
            notes = []
            profile = 'Нет ICC → sRGB'
            if im.info.get('icc_profile'):
                p = ImageCms.ImageCmsProfile(io.BytesIO(im.info['icc_profile']))
                profile = ImageCms.getProfileDescription(p).strip()
            elif im.mode in ('CMYK', 'LAB'):
                raise ValueError('CMYK/Lab без ICC: корректное преобразование цвета невозможно.')
            else:
                notes.append('Нет ICC: предполагается sRGB; проверьте источник.')
            if getattr(im, 'n_frames', 1) > 1:
                raise ValueError('Многостраничный/анимированный файл: экспортируйте отдельные кадры.')
            return Photo(path, size, im.mode, profile, notes)


def load_rgb(path: Path, limit: int | None = None) -> tuple[Image.Image, list[str]]:
    photo = inspect_photo(path)
    with Image.open(path) as source:
        # JPEG reduced decoding keeps previews cheap, final export always full size.
        if limit:
            source.draft(source.mode, (limit, limit))
        icc = source.info.get('icc_profile')
        im = ImageOps.exif_transpose(source)
        im.load()
        if limit:
            im.thumbnail((limit, limit), Image.Resampling.LANCZOS)
        alpha = im.getchannel('A') if im.mode in ('RGBA', 'LA') else None
        if im.mode == 'P':
            rgba = im.convert('RGBA')
            alpha = rgba.getchannel('A')
            im = rgba.convert('RGB')
        elif im.mode in ('RGBA', 'LA'):
            im = im.convert('RGB')
        if icc:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            im = ImageCms.profileToProfile(im, src, SRGB, outputMode='RGB', renderingIntent=1,
                                          flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
        else:
            im = im.convert('RGB')
        if alpha is not None:
            white = Image.new('RGB', im.size, 'white')
            white.paste(im, mask=alpha)
            im = white
        return im.copy(), photo.warnings


def oriented(im: Image.Image, edit: Edit):
    return im.rotate(-edit.rotation, expand=True)


def layout(size: tuple[int, int], settings: Settings):
    if settings.size_mode == 'original':
        return size, size, 0
    if settings.size_mode == 'long_edge':
        factor = settings.long_edge / max(size)
        result = tuple(max(1, round(v * factor)) for v in size)
        return result, result, 0
    w, h = settings.pixels
    if settings.auto_orientation and (size[0] > size[1]) != (w > h) and size[0] != size[1]:
        w, h = h, w
    border = round(settings.border_mm / 25.4 * settings.dpi) if settings.size_mode == 'print' else 0
    return (w, h), (w - 2 * border, h - 2 * border), border


def crop_box(size, target_ratio, edit: Edit):
    w, h = size
    cw = min(w, h * target_ratio) / edit.zoom
    ch = cw / target_ratio
    left = max(0, min(w - cw, edit.center_x * w - cw / 2))
    top = max(0, min(h - ch, edit.center_y * h - ch / 2))
    return left, top, left + cw, top + ch


def smart_center(im: Image.Image, ratio: float):
    """Coarse edge saliency + center prior; no face recognition, always review."""
    small = im.copy()
    small.thumbnail((160, 160))
    edges = small.convert('L').filter(ImageFilter.FIND_EDGES)
    # Ignore image perimeter, which FIND_EDGES preserves.
    edges.paste(0, (0, 0, edges.width, min(2, edges.height)))
    edges.paste(0, (0, max(0, edges.height - 2), edges.width, edges.height))
    edges.paste(0, (0, 0, min(2, edges.width), edges.height))
    edges.paste(0, (max(0, edges.width - 2), 0, edges.width, edges.height))
    best = (-1, .5, .5)
    for x in (.25, .375, .5, .625, .75):
        for y in (.25, .375, .5, .625, .75):
            box = crop_box(small.size, ratio, Edit(center_x=x, center_y=y))
            score = ImageStat.Stat(edges.crop(box)).sum[0] * (1 - .25 * (abs(x - .5) + abs(y - .5)))
            if score > best[0]:
                best = score, x, y
    return best[1:]


def effective_edit(im: Image.Image, settings: Settings, edit: Edit):
    from dataclasses import replace
    if settings.fit == 'cover' and settings.smart_crop and not edit.manual_crop:
        _, inner, _ = layout(im.size, settings)
        x, y = smart_center(im, inner[0] / inner[1])
        return replace(edit, center_x=x, center_y=y)
    return edit


def assess(size, settings: Settings, edit: Edit):
    if edit.fit is not None:
        from dataclasses import replace
        settings = replace(settings, fit=edit.fit)
    if edit.rotation % 180:
        size = size[::-1]
    canvas, inner, _ = layout(size, settings)
    if settings.fit == 'cover':
        box = crop_box(size, inner[0] / inner[1], edit)
        used = box[2] - box[0], box[3] - box[1]
        fraction = used[0] * used[1] / (size[0] * size[1])
        scale = inner[0] / used[0]
    else:
        used = size
        fraction = 1
        scale = min(inner[0] / size[0], inner[1] / size[1])
    if settings.size_mode == 'original':
        if settings.fit == 'cover':
            integer_box = tuple(round(v) for v in box)
            canvas = (integer_box[2] - integer_box[0], integer_box[3] - integer_box[1])
        else:
            canvas = size
        scale = 1
    ppi = settings.dpi / scale
    notes = []
    if ppi < 150:
        notes.append('Низкая детализация: менее 150 PPI.')
    elif ppi < 240:
        notes.append('Разрешение ниже 240 PPI: проверьте пробный отпечаток.')
    if scale > 1.01:
        notes.append(f'Увеличение ×{scale:.2f}; новые детали не появятся.')
    if fraction < .85:
        notes.append(f'Будет обрезано {100 * (1 - fraction):.0f}% площади; проверьте кадр.')
    return {'pixels': canvas, 'ppi': round(ppi), 'crop_percent': round(100 * (1 - fraction)),
            'upscale': scale > 1.0001, 'downscale': scale < .9999, 'scale': scale, 'warnings': notes}


def adjust(im: Image.Image, settings: Settings, edit: Edit, notes=None):
    im, algorithm_notes = enhance(im, settings, return_notes=True)
    if notes is not None:
        notes.extend(algorithm_notes)
    if settings.auto_enhance:
        # Luminance-only, bounded 25% blend avoids independent RGB channel shifts.
        ycbcr = im.convert('YCbCr')
        y, cb, cr = ycbcr.split()
        stretched = ImageOps.autocontrast(y, cutoff=.3)
        y = Image.blend(y, stretched, .25)
        im = Image.merge('YCbCr', (y, cb, cr)).convert('RGB')
    if edit.exposure:
        im = ImageEnhance.Brightness(im).enhance(2 ** edit.exposure)
    if edit.contrast != 1:
        im = ImageEnhance.Contrast(im).enhance(edit.contrast)
    if edit.saturation != 1:
        im = ImageEnhance.Color(im).enhance(edit.saturation)
    return im


def without_enhancements(settings: Settings):
    """Same geometry, no automatic color/sharpening or learned enlargement."""
    from dataclasses import replace
    return replace(settings, **DEFAULTS, enhancement_preset='none', auto_enhance=False,
                   sharpen=False, upscaler='lanczos')


def render(im: Image.Image, settings: Settings, edit: Edit, preview_max: int | None = None, notes=None):
    from dataclasses import replace
    if edit.fit is not None:
        settings = replace(settings, fit=edit.fit)
    im = oriented(im, edit)
    edit = effective_edit(im, settings, edit)
    canvas_size, inner, border = layout(im.size, settings)
    # Crop once, on the source pixel grid, before either preview scaling or export.
    if settings.fit == 'cover':
        im = im.crop(crop_box(im.size, inner[0] / inner[1], edit))
    if settings.size_mode == 'original':
        canvas_size = inner = im.size
    if canvas_size[0] * canvas_size[1] > MAX_PIXELS:
        raise ValueError('Результат превышает 80 мегапикселей. Уменьшите размер.')
    requested_scale = (max if settings.fit == 'cover' else min)(inner[0] / im.width, inner[1] / im.height)
    neural = edit.use_neural if edit.use_neural is not None else settings.upscaler == 'fsrcnn'
    strength = edit.neural_strength if edit.neural_strength is not None else settings.neural_strength
    if neural:
        if requested_scale <= 1.05:
            if notes is not None:
                notes.append('Нейро ×2 не применяется: результат не требует увеличения. Для увеличения выберите больше пикселей.')
        elif im.width * im.height > 8_000_000:
            if notes is not None:
                notes.append('Нейро ×2 пропущено: кадр больше 8 Мп; использован Lanczos.')
        else:
            from .upscale import upscale2x
            im = upscale2x(im, strength)
            if notes is not None:
                notes.append('Применён FSRCNN ×2.' + (' Остаточное увеличение >×2 — Lanczos.' if requested_scale > 2 else ''))
    if settings.fit == 'cover':
        im = im.resize(inner, Image.Resampling.LANCZOS) if im.size != inner else im
    else:
        im = ImageOps.contain(im, inner, Image.Resampling.LANCZOS) if im.size != inner else im
    im = adjust(im, settings, edit, notes)
    if settings.sharpen:
        im = im.filter(ImageFilter.UnsharpMask(radius=.7, percent=70, threshold=3))
    canvas = Image.new('RGB', canvas_size, settings.background)
    canvas.paste(im, ((canvas.width - im.width) // 2, (canvas.height - im.height) // 2))
    if preview_max:
        # Exact processing first, then display scaling. Neural and numerical effects
        # are no longer silently dropped just because this is a preview.
        canvas.thumbnail((preview_max, preview_max), Image.Resampling.LANCZOS)
    return canvas


def output_color(im: Image.Image, settings: Settings):
    if settings.output_space == 'sRGB':
        return im, SRGB_BYTES
    profile = ImageCms.getOpenProfile(settings.icc_path)
    mode = profile.profile.xcolor_space.strip()
    result = ImageCms.profileToProfile(im, SRGB, profile, outputMode=mode, renderingIntent=settings.intent,
                                      flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
    return result, profile.tobytes()


def proof(im: Image.Image, settings: Settings):
    """ICC simulation in sRGB; assumes sRGB monitor, no paper-white simulation."""
    profile = ImageCms.getOpenProfile(settings.icc_path)
    transform = ImageCms.buildProofTransform(SRGB, SRGB, profile, 'RGB', 'RGB',
        renderingIntent=settings.intent, proofRenderingIntent=1,
        flags=ImageCms.Flags.SOFTPROOFING | ImageCms.Flags.BLACKPOINTCOMPENSATION)
    return ImageCms.applyTransform(im, transform)


def scan(folder: Path, recursive=False, cancel: threading.Event | None = None):
    photos, errors = [], []
    paths = folder.rglob('*') if recursive else folder.iterdir()
    for path in paths:
        if cancel and cancel.is_set():
            break
        if path.is_file() and path.suffix.lower() in SUPPORTED and not any(p.startswith('PrintPrep_') for p in path.relative_to(folder).parts):
            try:
                photos.append(inspect_photo(path))
            except Exception as e:
                errors.append({'file': str(path), 'error': str(e)})
    photos.sort(key=lambda p: str(p.path).casefold())
    return photos, errors


def export_batch(folder: Path, photos: list[Photo], settings: Settings, edits: dict[str, Edit],
                 cancel: threading.Event | None = None, progress: Callable | None = None):
    settings.validate()
    output = folder / ('PrintPrep_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    output.mkdir(exist_ok=False)
    rows = []
    for index, photo in enumerate(photos):
        if cancel and cancel.is_set():
            break
        row = {'source': str(photo.path), 'output': '', 'status': 'error', 'ppi': '', 'warnings': '', 'error': ''}
        try:
            edit = edits.get(str(photo.path), Edit())
            edit.validate()
            current = inspect_photo(photo.path)
            info = assess(current.size, settings, edit)
            row['ppi'] = info['ppi']
            row['warnings'] = ' | '.join(current.warnings + info['warnings'])
            if info['upscale'] and not settings.allow_upscale:
                row['status'] = 'skipped'
                row['error'] = 'Увеличение запрещено: исходного разрешения недостаточно.'
            else:
                im, _ = load_rgb(photo.path)
                algorithm_notes = []
                im = render(im, settings, edit, notes=algorithm_notes)
                row['warnings'] = ' | '.join(current.warnings + info['warnings'] + algorithm_notes)
                im, icc = output_color(im, settings)
                # Preserve hierarchy; foo.jpg and foo.png cannot overwrite each other.
                relative = photo.path.relative_to(folder)
                ext = '.jpg' if settings.format == 'JPEG' else '.tif'
                dest = output / relative.parent / (relative.name + ext)
                dest.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(prefix='.printprep-', dir=dest.parent)
                os.close(fd)
                try:
                    options = {'icc_profile': icc, 'dpi': (settings.dpi, settings.dpi)}
                    if settings.format == 'JPEG':
                        options.update(quality=settings.quality, subsampling=0, optimize=True, progressive=False)
                    else:
                        options.update(compression='tiff_lzw')
                    im.save(temporary, format=settings.format, **options)
                    os.replace(temporary, dest)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
                row.update(output=str(dest), status='ok')
        except Exception as e:
            row['error'] = str(e)
        rows.append(row)
        if progress:
            progress(index + 1, len(photos), row)
    report = {'app': 'Print Prep', 'version': __version__, 'settings': asdict(settings),
              'edits': {k: asdict(v) for k, v in edits.items()}, 'results': rows,
              'total': len(photos), 'cancelled': len(rows) < len(photos)}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    with (output / 'report.csv').open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['source', 'output', 'status', 'ppi', 'warnings', 'error']
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=';')
        writer.writeheader()
        # Prevent spreadsheet formula evaluation from user-supplied filenames/errors.
        writer.writerows({k: ("'" + str(v) if str(v).startswith(('=', '+', '-', '@')) else v) for k, v in r.items()} for r in rows)
    return output, report
