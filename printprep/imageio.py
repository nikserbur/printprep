"""Reading and writing photos.

Sources are normalised once to *sRGB-encoded* integer arrays (uint8 for plain 8-bit
sRGB, uint16 for 16-bit or converted sources), oriented by EXIF. Writers embed ICC,
resolution and (optionally) EXIF without GPS.
"""
from __future__ import annotations

import io
import os
import struct
import tempfile
import warnings
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

from .color import IccSource
from .model import MAX_PIXELS
from .i18n import tr

SUPPORTED = {'.jpg', '.jpeg', '.jpe', '.png', '.tif', '.tiff', '.webp', '.bmp'}
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
SRGB_BYTES = SRGB_PROFILE.tobytes()
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass
class PhotoInfo:
    path: Path
    size: tuple[int, int]          # after EXIF orientation
    bits: int
    profile: str
    file_size: int
    mtime_ns: int
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self):
        return str(self.path), self.mtime_ns, self.file_size

    @property
    def megapixels(self):
        return self.size[0] * self.size[1] / 1e6


def _png_bits(path):
    with open(path, 'rb') as f:
        head = f.read(26)
    return head[24] if head[:8] == b'\x89PNG\r\n\x1a\n' else 8


def inspect(path: Path) -> PhotoInfo:
    stat = path.stat()
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as im:
            if im.width * im.height > MAX_PIXELS:
                raise ValueError(tr('Снимок больше 100 мегапикселей.'))
            if getattr(im, 'n_frames', 1) > 1 and im.format not in ('TIFF', 'JPEG', 'MPO'):
                raise ValueError(tr('Анимированный файл: сохраните отдельный кадр.'))
            bits = 8
            if im.format == 'TIFF':
                value = im.tag_v2.get(258, (8,))
                bits = max(value) if isinstance(value, tuple) else int(value)
            elif im.format == 'PNG':
                bits = _png_bits(path)
            if im.mode in ('I;16', 'I;16B', 'I;16L', 'I'):
                bits = 16
            if bits > 16 or im.mode == 'F':
                raise ValueError(tr('32-битные файлы не поддерживаются: сохраните 16- или 8-битную копию.'))
            size = im.size
            if im.getexif().get(274, 1) in (5, 6, 7, 8):
                size = size[::-1]
            notes = []
            icc = im.info.get('icc_profile')
            if icc:
                parsed = IccSource(icc)
                profile = parsed.description or ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
            elif im.mode in ('CMYK', 'LAB'):
                raise ValueError(tr('CMYK/Lab без ICC-профиля: цвет нельзя преобразовать корректно.'))
            else:
                profile = tr('Без профиля → sRGB')
                notes.append(tr('Нет ICC-профиля: считаем, что это sRGB.'))
    return PhotoInfo(path, size, bits, profile, stat.st_size, stat.st_mtime_ns, notes)


def _orient(array, orientation):
    import cv2
    ops = {2: lambda a: a[:, ::-1], 3: lambda a: a[::-1, ::-1], 4: lambda a: a[::-1],
           5: lambda a: np.swapaxes(a, 0, 1), 6: lambda a: cv2.rotate(a, cv2.ROTATE_90_CLOCKWISE),
           7: lambda a: np.swapaxes(a, 0, 1)[::-1, ::-1], 8: lambda a: cv2.rotate(a, cv2.ROTATE_90_COUNTERCLOCKWISE)}
    op = ops.get(orientation)
    return np.ascontiguousarray(op(array)) if op else array


def _flatten_alpha(rgb, alpha, depth):
    a = alpha.astype(np.float32)[..., None] / depth
    out = rgb.astype(np.float32) * a + depth * (1 - a)
    return np.round(out).astype(rgb.dtype)


def load(path: Path, max_edge=None):
    """sRGB-encoded array (uint8 or uint16, HxWx3) and notes.

    With `max_edge`, JPEGs are decoded at a reduced DCT scale that is still at least that
    large (several times faster than a full decode); the caller resizes the rest.
    """
    import cv2
    notes = []
    with Image.open(path) as im:
        icc = im.info.get('icc_profile')
        orientation = im.getexif().get(274, 1)
        mode = im.mode
        high = mode in ('I;16', 'I;16B', 'I;16L', 'I') or (im.format == 'TIFF' and max(_tuple(im.tag_v2.get(258, (8,)))) > 8) \
            or (im.format == 'PNG' and _png_bits(path) > 8)
        if not high:
            if max_edge and im.format == 'JPEG' and max(im.size) > max_edge:
                k = max_edge / max(im.size)
                im.draft(im.mode, (max(1, int(im.size[0] * k)), max(1, int(im.size[1] * k))))
            im.load()
            if im.mode == 'P':
                im = im.convert('RGBA')
            alpha = np.asarray(im.getchannel('A')) if im.mode in ('RGBA', 'LA', 'PA') else None
            if im.mode in ('RGBA', 'PA'):
                im = im.convert('RGB')
            elif im.mode == 'LA':
                im = im.convert('L')
            if icc and (im.mode in ('CMYK', 'LAB') or IccSource(icc).matrix is None):
                src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                space = src.profile.xcolor_space.strip()
                base = im.convert('RGB') if space == 'RGB' and im.mode != 'RGB' else im
                im = ImageCms.profileToProfile(base, src, SRGB_PROFILE, outputMode='RGB', renderingIntent=1,
                                               flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
                icc = None
                notes.append(tr('Цвет преобразован из встроенного профиля (LittleCMS).'))
            array = np.asarray(im.convert('RGB'))
            if alpha is not None:
                array = _flatten_alpha(array, alpha, 255)
        else:
            raw = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            if raw is None:
                raise ValueError(tr('OpenCV не смог прочитать 16-битный файл.'))
            if raw.dtype != np.uint16:
                raw = raw.astype(np.uint16) * 257 if raw.dtype == np.uint8 else np.clip(raw, 0, 65535).astype(np.uint16)
            if raw.ndim == 2:
                array = np.repeat(raw[..., None], 3, axis=2)
            elif raw.shape[2] == 4:
                array = _flatten_alpha(raw[..., 2::-1], raw[..., 3], 65535)
            else:
                array = raw[..., 2::-1]
            array = np.ascontiguousarray(array)
    array = _orient(array, orientation)
    if icc:
        parsed = IccSource(icc)
        if parsed.matrix is not None and not parsed.is_srgb:
            array = parsed.to_srgb_encoded(array)
            notes.append(tr('Цвет преобразован: {v} → sRGB.', v=parsed.description or tr('профиль')))
        elif parsed.matrix is None and high:
            notes.append(tr('Профиль 16-битного файла не поддерживается: цвет считается sRGB.'))
    if array.shape[0] * array.shape[1] > MAX_PIXELS:
        raise ValueError(tr('Снимок больше 100 мегапикселей.'))
    return np.ascontiguousarray(array), notes


def _tuple(value):
    return value if isinstance(value, tuple) else (int(value),)


def thumbnail(path: Path, size=320):
    """Fast oriented RGB uint8 thumbnail (JPEG DCT scaling where possible)."""
    try:
        with Image.open(path) as im:
            if im.format == 'JPEG':
                im.draft('RGB', (size * 2, size * 2))
            im = ImageOps.exif_transpose(im)
            if im.mode not in ('RGB', 'L', 'RGBA', 'P', 'LA', 'CMYK'):
                raise ValueError
            icc = im.info.get('icc_profile')
            if im.mode == 'CMYK' and icc:
                im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(io.BytesIO(icc)), SRGB_PROFILE, outputMode='RGB')
            im = im.convert('RGB')
            im.thumbnail((size, size), Image.Resampling.BILINEAR)
            return np.asarray(im)
    except Exception:
        import cv2
        array, _ = load(path)
        h, w = array.shape[:2]
        k = size / max(h, w)
        small = cv2.resize(array, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
        return (small >> 8).astype(np.uint8) if small.dtype == np.uint16 else small


def read_exif(path: Path):
    try:
        with Image.open(path) as im:
            exif = im.getexif()
    except Exception:
        return None
    if not exif:
        return None
    exif[274] = 1
    exif.pop(0x8825, None)  # GPS IFD
    for tag in (0x0201, 0x0202):  # stale embedded thumbnail pointers
        exif.pop(tag, None)
    return exif


# ---------------------------------------------------------------- writers
def save(path: Path, array, fmt, *, quality=95, dpi=300, icc=SRGB_BYTES, exif=None, mode='RGB'):
    """Atomically write `array` (uint8/uint16 HxWxC) to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.printprep-', suffix=path.suffix, dir=path.parent)
    os.close(fd)
    try:
        if array.dtype == np.uint16:
            data = _tiff16(array, dpi, icc) if fmt == 'TIFF' else _png16(array, dpi, icc)
            Path(temporary).write_bytes(data)
        else:
            im = Image.fromarray(array, mode)
            options = {'dpi': (dpi, dpi)}
            if icc:
                options['icc_profile'] = icc
            if exif is not None and fmt in ('JPEG', 'TIFF', 'PNG'):
                try:
                    options['exif'] = exif.tobytes()
                except Exception:
                    pass
            if fmt == 'JPEG':
                options.update(quality=quality, subsampling=0 if quality >= 85 else 2, optimize=True)
            elif fmt == 'TIFF':
                options.update(compression='tiff_lzw')
            else:
                options.update(compress_level=6)
            im.save(temporary, format=fmt, **options)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def _png16(array, dpi, icc):
    import cv2
    ok, encoded = cv2.imencode('.png', np.ascontiguousarray(array[..., ::-1]), [cv2.IMWRITE_PNG_COMPRESSION, 6])
    if not ok:
        raise ValueError(tr('Не удалось закодировать PNG.'))
    data = encoded.tobytes()
    ihdr_end = 8 + 25
    extra = _chunk(b'pHYs', struct.pack('>IIB', round(dpi / .0254), round(dpi / .0254), 1))
    if icc:
        extra = _chunk(b'iCCP', b'ICC Profile\0\0' + zlib.compress(icc)) + extra
    return data[:ihdr_end] + extra + data[ihdr_end:]


def _tiff16(array, dpi, icc):
    """Baseline little-endian RGB TIFF, 16 bit, Deflate + horizontal predictor."""
    h, w, c = array.shape
    rows = max(1, 65536 // (w * c * 2))
    strips = []
    for top in range(0, h, rows):
        block = array[top:top + rows].astype(np.uint16)
        diff = block.copy()
        diff[:, 1:] = block[:, 1:] - block[:, :-1]  # uint16 wraps, as the predictor expects
        strips.append(zlib.compress(diff.astype('<u2').tobytes(), 6))
    SHORT, LONG, RATIONAL, ASCII, UNDEF = 3, 4, 5, 2, 7
    unit = {SHORT: 2, LONG: 4, RATIONAL: 8, ASCII: 1, UNDEF: 1}
    tags = [(256, LONG, [w]), (257, LONG, [h]), (258, SHORT, [16] * c), (259, SHORT, [8]), (262, SHORT, [2]),
            (273, LONG, [0] * len(strips)), (277, SHORT, [c]), (278, LONG, [rows]),
            (279, LONG, [len(s) for s in strips]), (282, RATIONAL, [(dpi, 1)]), (283, RATIONAL, [(dpi, 1)]),
            (284, SHORT, [1]), (296, SHORT, [2]), (305, ASCII, list(b'Print Prep\0')), (317, SHORT, [2])]
    if icc:
        tags.append((34675, UNDEF, list(icc)))

    def pack(kind, values):
        if kind == RATIONAL:
            return b''.join(struct.pack('<II', *v) for v in values)
        if kind in (ASCII, UNDEF):
            return bytes(values)
        return struct.pack('<' + ('H' if kind == SHORT else 'I') * len(values), *values)

    header = 8 + 2 + 12 * len(tags) + 4
    # Out-of-line payload sizes do not depend on offsets, so positions are fixed in one pass.
    cursor = header
    positions = {}
    for code, kind, values in tags:
        size = unit[kind] * len(values)
        if size > 4:
            positions[code] = cursor
            cursor += size + size % 2
    strip_offsets = []
    for s in strips:
        strip_offsets.append(cursor)
        cursor += len(s)
    tags = [(code, kind, strip_offsets if code == 273 else values) for code, kind, values in tags]
    out = bytearray(b'II*\0' + struct.pack('<I', 8) + struct.pack('<H', len(tags)))
    blobs = bytearray()
    for code, kind, values in tags:
        payload = pack(kind, values)
        if code in positions:
            out += struct.pack('<HHII', code, kind, len(values), positions[code])
            blobs += payload + (b'\0' if len(payload) % 2 else b'')
        else:
            out += struct.pack('<HHI', code, kind, len(values)) + payload.ljust(4, b'\0')
    out += b'\0\0\0\0' + blobs
    for s in strips:
        out += s
    return bytes(out)
