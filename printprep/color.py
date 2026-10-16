"""Colour math in float32: sRGB transfer, Oklab, gamut mapping, matrix/TRC ICC sources.

Everything operates on HxWx3 float32 arrays. Linear values are scene-referred
sRGB primaries (D65); encoded values use the sRGB transfer curve.
"""
from __future__ import annotations

import struct

import numpy as np

LUMA = np.array([.2126, .7152, .0722], dtype=np.float32)

# Oklab (Björn Ottosson, 2020), linear sRGB in.
_M1 = np.array([[.4122214708, .5363325363, .0514459929],
                [.2119034982, .6806995451, .1073969566],
                [.0883024619, .2817188376, .6299787005]], dtype=np.float32)
_M2 = np.array([[.2104542553, .7936177850, -.0040720468],
                [1.9779984951, -2.4285922050, .4505937099],
                [.0259040371, .7827717662, -.8086757660]], dtype=np.float32)
_M1I = np.linalg.inv(_M1.astype(np.float64)).astype(np.float32)
_M2I = np.linalg.inv(_M2.astype(np.float64)).astype(np.float32)

# Linear sRGB <-> XYZ, D50-adapted (Bradford), which is how ICC v2/v4 PCS stores colorants.
SRGB_TO_XYZ_D50 = np.array([[.4360747, .3850649, .1430804],
                            [.2225045, .7168786, .0606169],
                            [.0139322, .0971045, .7141733]], dtype=np.float64)
XYZ_D50_TO_SRGB = np.linalg.inv(SRGB_TO_XYZ_D50)


def _mat(m):
    return np.ascontiguousarray(m, dtype=np.float32)


def _c(x):
    return x if x.flags.c_contiguous and x.dtype == np.float32 else np.ascontiguousarray(x, dtype=np.float32)


def _pow(a, exponent):
    """Non-negative power; OpenCV's SIMD path for images, NumPy for tiny arrays/scalars."""
    if a.ndim >= 2 and a.size >= 1024:
        import cv2
        return cv2.pow(_c(a), exponent)
    return np.power(a, exponent, dtype=np.float32)


def decode(x):
    """sRGB-encoded -> linear (exact; odd extension outside [0, 1])."""
    x = np.asarray(x, dtype=np.float32)
    a = np.abs(x)
    curve = _pow((a + .055) * (1 / 1.055), 2.4)
    out = np.where(a <= .04045, a * (1 / 12.92), curve)
    return np.copysign(out, x).astype(np.float32, copy=False)


def encode(x):
    """Linear -> sRGB-encoded (exact; odd extension for negatives)."""
    x = np.asarray(x, dtype=np.float32)
    a = np.abs(x)
    curve = _pow(a, 1 / 2.4) * 1.055 - .055
    out = np.where(a <= .0031308, a * 12.92, curve)
    return np.copysign(out, x).astype(np.float32, copy=False)


_DECODE_LUT = None


def decode_unit(x):
    """Fast sRGB decode for values already in [0, 1] (65536-entry table)."""
    global _DECODE_LUT
    if _DECODE_LUT is None:
        _DECODE_LUT = decode(np.linspace(0, 1, 65536, dtype=np.float32))
    idx = np.clip(x * 65535 + .5, 0, 65535).astype(np.uint16)
    return np.take(_DECODE_LUT, idx)


def luminance(rgb):
    import cv2
    return cv2.transform(_c(rgb), LUMA.reshape(1, 3))


def transform(rgb, matrix):
    """Per-pixel 3×3 matrix (multithreaded OpenCV)."""
    import cv2
    return cv2.transform(_c(rgb), _mat(matrix))


def to_oklab(rgb):
    import cv2
    lms = transform(rgb, _M1)
    return transform(cv2.pow(np.maximum(lms, 0), 1 / 3), _M2)


def from_oklab(lab):
    lms = transform(lab, _M2I)
    return transform(lms * lms * lms, _M1I)


def channel_extremes(rgb):
    import cv2
    rgb = _c(rgb)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return cv2.min(cv2.min(r, g), b), cv2.max(cv2.max(r, g), b)


def gamut_clip(rgb, white=1.0):
    """Bring linear RGB into [0, white] by desaturating toward the pixel's own luminance.

    Unlike per-channel clipping this keeps hue and avoids the orange/yellow shifts
    of clipped skies and skin; luminance itself is limited to [0, white]. Only the
    offending pixels are processed.
    """
    rgb = _c(rgb)
    low, high = channel_extremes(rgb)
    bad = (low < 0) | (high > white)
    if not bad.any():
        return rgb
    out = rgb.copy()
    px = out[bad]
    y = np.clip(px @ LUMA, 0, white)[:, None]
    d = px - y
    with np.errstate(divide='ignore', invalid='ignore'):
        up = np.where(d > 1e-7, (white - y) / d, np.inf)
        down = np.where(d < -1e-7, -y / d, np.inf)
    t = np.minimum(1, np.minimum(up, down).min(axis=1, keepdims=True))
    out[bad] = y + d * t
    return out


# ---------------------------------------------------------------- ICC (matrix/TRC sources)
class IccSource:
    """Minimal parser for matrix/TRC RGB display profiles (sRGB, Display P3, Adobe RGB,
    ProPhoto...). LUT-based or non-RGB profiles report `matrix is None` and are
    converted through LittleCMS instead."""

    def __init__(self, data: bytes):
        self.data = data
        self.matrix = None
        self.curves = None
        self.description = ''
        self.is_srgb = False
        try:
            self._parse()
        except Exception:
            self.matrix = None

    def _parse(self):
        d = self.data
        if len(d) < 132 or d[36:40] != b'acsp':
            return
        colorspace, pcs = d[16:20], d[20:24]
        count = struct.unpack('>I', d[128:132])[0]
        tags = {}
        for i in range(min(count, 200)):
            sig, off, size = struct.unpack('>4sII', d[132 + 12 * i:144 + 12 * i])
            tags[sig] = d[off:off + size]
        self.description = _description(tags.get(b'desc', b''))
        if colorspace != b'RGB ' or pcs != b'XYZ ':
            return
        if any(k in tags for k in (b'A2B0', b'A2B1')) and not self.description.lower().startswith(('srgb', 'display p3', 'adobe rgb')):
            return
        cols = [_xyz(tags[k]) for k in (b'rXYZ', b'gXYZ', b'bXYZ')]
        curves = [_curve(tags[k]) for k in (b'rTRC', b'gTRC', b'bTRC')]
        if any(c is None for c in curves):
            return
        self.matrix = (XYZ_D50_TO_SRGB @ np.array(cols, dtype=np.float64).T).astype(np.float32)
        self.curves = curves
        grid = np.linspace(0, 1, 1024, dtype=np.float32)
        srgb = decode(grid)
        same_curve = all(np.abs(c(grid) - srgb).max() < 2.5e-3 for c in curves)
        self.is_srgb = same_curve and np.abs(self.matrix - np.eye(3)).max() < 4e-3

    def to_srgb_encoded(self, array):
        """uint8/uint16 RGB in this profile -> sRGB-encoded uint16, gamut-mapped softly."""
        depth = 255 if array.dtype == np.uint8 else 65535
        grid = np.arange(depth + 1, dtype=np.float32) / depth
        out = np.empty(array.shape, dtype=np.uint16)
        luts = [c(grid).astype(np.float32) for c in self.curves]
        for top in range(0, array.shape[0], 512):
            block = array[top:top + 512]
            lin = np.stack([luts[i][block[..., i]] for i in range(3)], axis=-1)
            lin = gamut_clip(transform(lin, self.matrix))
            out[top:top + 512] = np.round(np.clip(encode(lin), 0, 1) * 65535).astype(np.uint16)
        return out


def _description(tag):
    if not tag:
        return ''
    kind = tag[:4]
    try:
        if kind == b'desc':
            n = struct.unpack('>I', tag[8:12])[0]
            return tag[12:12 + n].split(b'\0')[0].decode('latin-1').strip()
        if kind == b'mluc':
            count, size = struct.unpack('>II', tag[8:16])
            if count:
                length, offset = struct.unpack('>II', tag[20:28])
                return tag[offset:offset + length].decode('utf-16-be').strip('\0 ')
    except Exception:
        pass
    return ''


def _s15(b):
    return struct.unpack('>i', b)[0] / 65536


def _xyz(tag):
    return [_s15(tag[8 + 4 * i:12 + 4 * i]) for i in range(3)]


def _curve(tag):
    kind = tag[:4]
    if kind == b'curv':
        n = struct.unpack('>I', tag[8:12])[0]
        if n == 0:
            return lambda x: x
        if n == 1:
            gamma = struct.unpack('>H', tag[12:14])[0] / 256
            return lambda x, g=gamma: np.power(x, g, dtype=np.float32)
        table = np.frombuffer(tag[12:12 + 2 * n], dtype='>u2').astype(np.float32) / 65535
        xs = np.linspace(0, 1, n, dtype=np.float32)
        return lambda x, t=table, s=xs: np.interp(x, s, t).astype(np.float32)
    if kind == b'para':
        ftype = struct.unpack('>H', tag[8:10])[0]
        count = {0: 1, 1: 3, 2: 4, 3: 5, 4: 7}.get(ftype)
        if count is None:
            return None
        p = [_s15(tag[12 + 4 * i:16 + 4 * i]) for i in range(count)]
        g, a, b, c, d, e, f = (p + [0] * 7)[:7] if ftype else (p[0], 1, 0, 0, 0, 0, 0)

        def para(x, ftype=ftype, g=g, a=a, b=b, c=c, d=d, e=e, f=f):
            x = np.asarray(x, dtype=np.float32)
            if ftype == 0:
                return np.power(x, g, dtype=np.float32)
            if ftype == 1:
                return np.where(x >= -b / a, np.power(np.maximum(a * x + b, 0), g), 0).astype(np.float32)
            if ftype == 2:
                return np.where(x >= -b / a, np.power(np.maximum(a * x + b, 0), g) + c, c).astype(np.float32)
            if ftype == 3:
                return np.where(x >= d, np.power(np.maximum(a * x + b, 0), g), c * x).astype(np.float32)
            return np.where(x >= d, np.power(np.maximum(a * x + b, 0), g) + e, c * x + f).astype(np.float32)
        return para
    return None
