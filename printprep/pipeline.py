"""The print pipeline: geometry, smart framing, tone maps and the develop step.

One code path renders the exported file, the fit-to-window preview (on a proxy)
and the 100% view (a region of the full-resolution result). Low-frequency maps
and automatic suggestions come from the same deterministic proxy everywhere, so
what you see is what gets written.

Order: oriented sRGB-encoded source → user rotation / straighten → crop →
[neural SR] → resize → denoise → linear → white balance → exposure → dehaze →
local tone (shadows, highlights, clarity) → tone curve → colour (Oklab) → look →
encode → output sharpening → borders → output colour space.
"""
from __future__ import annotations

import math
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np

from . import analysis as auto
from .color import LUMA, decode, decode_unit, encode, from_oklab, gamut_clip, luminance, to_oklab
from .model import ADJUST_RANGES, LOOKS, NUMERIC_ADJUST, Edit, Settings, combined_adjust

PROXY_EDGE = 2560
MAP_EDGE = 640
SKIN = np.array([math.cos(math.radians(58)), math.sin(math.radians(58))], dtype=np.float32)


# ---------------------------------------------------------------- source & caches
class Source:
    """A decoded photo with its proxy, analysis and small per-geometry caches."""

    def __init__(self, info, full, notes=(), analysis=None):
        self.info = info
        self.full = full
        self.notes = list(notes)
        self.proxy = make_proxy(full)
        self.analysis = analysis
        self._bases = OrderedDict()
        self._maps = OrderedDict()
        self._lock = threading.Lock()

    @classmethod
    def open(cls, info, analysis_cache=None):
        from .imageio import load
        full, notes = load(info.path)
        cached = analysis_cache.get(info.key) if analysis_cache is not None else None
        source = cls(info, full, notes, cached)
        return source

    def ensure_analysis(self, analysis_cache=None):
        if self.analysis is None:
            self.analysis = auto.analyze(self.proxy, self.full)
            if analysis_cache is not None:
                analysis_cache.put(self.info.key, self.analysis)
        return self.analysis

    def base(self, edit, use_full):
        key = (use_full, edit.rotation % 360, round(edit.angle, 3))
        with self._lock:
            if key in self._bases:
                self._bases.move_to_end(key)
                return self._bases[key]
        array = transform(self.full if use_full else self.proxy, edit)
        with self._lock:
            self._bases[key] = array
            while len(self._bases) > 3:
                self._bases.popitem(last=False)
        return array

    def oriented_size(self, edit):
        h, w = self.full.shape[:2]
        return straightened_size((h, w) if edit.rotation % 180 else (w, h), edit.angle)


class AnalysisCache:
    def __init__(self, limit=2000):
        self.data = OrderedDict()
        self.limit = limit
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            value = self.data.get(key)
            if value is not None:
                self.data.move_to_end(key)
            return value

    def put(self, key, value):
        with self.lock:
            self.data[key] = value
            while len(self.data) > self.limit:
                self.data.popitem(last=False)


def make_proxy(full):
    import cv2
    h, w = full.shape[:2]
    k = min(1, PROXY_EDGE / max(h, w))
    src = full.astype(np.uint16) * 257 if full.dtype == np.uint8 else full
    if k >= 1:
        return np.ascontiguousarray(src)
    return cv2.resize(src, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)


def straightened_size(size, angle):
    if not angle:
        return size
    w, h = size
    a = math.radians(abs(angle))
    s = min(w / (w * math.cos(a) + h * math.sin(a)), h / (w * math.sin(a) + h * math.cos(a)))
    return max(1, int(w * s)), max(1, int(h * s))


def transform(array, edit):
    """User 90° rotation (clockwise) and straighten (positive = clockwise) with inscribed crop."""
    import cv2
    rotation = edit.rotation % 360
    if rotation:
        array = cv2.rotate(array, {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                                   270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rotation])
    if edit.angle:
        h, w = array.shape[:2]
        nw, nh = straightened_size((w, h), edit.angle)
        m = cv2.getRotationMatrix2D((w / 2, h / 2), -edit.angle, 1.0)
        m[0, 2] += (nw - w) / 2
        m[1, 2] += (nh - h) / 2
        array = cv2.warpAffine(array, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    return np.ascontiguousarray(array)


# ---------------------------------------------------------------- geometry
@dataclass
class Geometry:
    canvas: tuple[int, int]
    image: tuple[int, int]
    offset: tuple[int, int]
    crop: tuple[float, float, float, float]   # normalised to the transformed source
    source: tuple[int, int]                   # transformed full-resolution source size
    fit: str
    border: int = 0
    notes: list = field(default_factory=list)

    @property
    def crop_px(self):
        w, h = self.source
        return self.crop[0] * w, self.crop[1] * h, self.crop[2] * w, self.crop[3] * h

    @property
    def scale(self):
        x0, _, x1, _ = self.crop_px
        return self.image[0] / max(1e-6, x1 - x0)

    @property
    def crop_fraction(self):
        x0, y0, x1, y1 = self.crop
        return (x1 - x0) * (y1 - y0)


def crop_box(size, ratio, cx=.5, cy=.5, zoom=1.0):
    w, h = size
    cw = min(w, h * ratio) / zoom
    ch = cw / ratio
    left = max(0., min(w - cw, cx * w - cw / 2))
    top = max(0., min(h - ch, cy * h - ch / 2))
    return left, top, left + cw, top + ch


def _rotate_points(faces, rotation):
    out = []
    for x, y, w, h, s in faces:
        if rotation == 90:
            x, y, w, h = 1 - y - h, x, h, w
        elif rotation == 180:
            x, y = 1 - x - w, 1 - y - h
        elif rotation == 270:
            x, y, w, h = y, 1 - x - w, h, w
        out.append((x, y, w, h, s))
    return out


def smart_center(size, ratio, edit, analysis):
    """Choose the free crop axis position: keep faces (with headroom), else salient detail."""
    w, h = size
    cw = min(w, h * ratio)
    ch = cw / ratio
    horizontal = cw < w - 1
    if not horizontal and ch >= h - 1:
        return .5, .5
    faces = _rotate_points(analysis.get('faces', []), edit.rotation % 360) if analysis else []
    sal = analysis.get('saliency') if analysis else None
    if sal is not None and edit.rotation % 360:
        sal = np.rot90(sal, k={90: -1, 180: 2, 270: 1}[edit.rotation % 360])
    best, best_score = .5, -1e9
    span = (w - cw) / w if horizontal else (h - ch) / h
    half = (cw / w if horizontal else ch / h) / 2
    for i in range(41):
        c = half + span * i / 40
        box = crop_box(size, ratio, c if horizontal else .5, .5 if horizontal else c)
        nx0, ny0, nx1, ny1 = box[0] / w, box[1] / h, box[2] / w, box[3] / h
        score = 0.
        if sal is not None:
            sh, sw = sal.shape
            region = sal[int(ny0 * sh):max(int(ny0 * sh) + 1, int(ny1 * sh)), int(nx0 * sw):max(int(nx0 * sw) + 1, int(nx1 * sw))]
            score += float(region.sum()) / max(1e-6, float(sal.sum()))
        for fx, fy, fw, fh, conf in faces:
            area = max(0., min(nx1, fx + fw) - max(nx0, fx)) * max(0., min(ny1, fy + fh) - max(ny0, fy))
            inside = area / max(1e-9, fw * fh)
            weight = 2 + 6 * min(1, fw * fh * 40) * conf
            score += weight * inside
            if not horizontal and inside > .9:
                eye = (fy + fh * .4 - ny0) / max(1e-6, ny1 - ny0)
                score -= weight * .5 * abs(eye - .36)
            if horizontal and inside > .9:
                centre = (fx + fw / 2 - nx0) / max(1e-6, nx1 - nx0)
                score -= weight * .15 * abs(centre - .5)
        score -= .08 * abs(c - .5)
        if score > best_score:
            best, best_score = c, score
    return (best, .5) if horizontal else (.5, best)


def geometry(size, settings: Settings, edit: Edit, analysis=None) -> Geometry:
    """`size` is the transformed (rotated/straightened) full-resolution source size."""
    w, h = size
    fit = edit.fit or settings.fit
    notes = []
    if settings.size_mode in ('original', 'long_edge'):
        if edit.manual_crop or edit.aspect:
            ratio = edit.aspect or w / h
            box = crop_box(size, ratio, edit.center_x, edit.center_y, edit.zoom)
        else:
            box = (0., 0., float(w), float(h))
        cw, ch = box[2] - box[0], box[3] - box[1]
        if settings.size_mode == 'original':
            image = (max(1, round(cw)), max(1, round(ch)))
        else:
            k = settings.long_edge / max(cw, ch)
            image = (max(1, round(cw * k)), max(1, round(ch * k)))
        crop = (box[0] / w, box[1] / h, box[2] / w, box[3] / h)
        return Geometry(image, image, (0, 0), crop, size, 'cover', 0, notes)
    tw, th = settings.target_pixels()
    if settings.auto_orientation and w != h and (w > h) != (tw > th):
        tw, th = th, tw
    border = settings.border_px()
    inner = (max(1, tw - 2 * border), max(1, th - 2 * border))
    if fit == 'cover':
        ratio = inner[0] / inner[1]
        cx, cy = edit.center_x, edit.center_y
        if settings.smart_crop and not edit.manual_crop and analysis is not None:
            cx, cy = smart_center(size, ratio, edit, analysis)
        box = crop_box(size, ratio, cx, cy, edit.zoom)
        image, offset = inner, (border, border)
    else:
        box = (0., 0., float(w), float(h))
        k = min(inner[0] / w, inner[1] / h)
        image = (max(1, min(inner[0], round(w * k))), max(1, min(inner[1], round(h * k))))
        offset = ((tw - image[0]) // 2, (th - image[1]) // 2)
    crop = (box[0] / w, box[1] / h, box[2] / w, box[3] / h)
    return Geometry((tw, th), image, offset, crop, size, fit, border, notes)


def assess(info_size, settings: Settings, edit: Edit | None = None):
    """Quick metadata-only check used for the batch summary and photo chips."""
    edit = edit or Edit()
    size = info_size[::-1] if edit.rotation % 180 else info_size
    size = straightened_size(size, edit.angle)
    g = geometry(size, settings, edit)
    scale = g.scale
    ppi = settings.dpi / scale if settings.size_mode == 'print' else None
    warnings = []
    if ppi is not None and ppi < 150:
        warnings.append(f'Мало деталей: ≈{ppi:.0f} PPI')
    elif ppi is not None and ppi < 240:
        warnings.append(f'≈{ppi:.0f} PPI — проверьте пробу')
    if scale > 1.02:
        warnings.append(f'Увеличение ×{scale:.1f}')
    crop = round(100 * (1 - g.crop_fraction))
    if crop >= 15:
        warnings.append(f'Обрезка {crop}%')
    return {'pixels': g.canvas, 'ppi': None if ppi is None else round(ppi), 'scale': scale,
            'crop_percent': crop, 'upscale': scale > 1.0001, 'downscale': scale < .9999, 'warnings': warnings}


# ---------------------------------------------------------------- adjustment values
def effective_values(settings: Settings, edit: Edit | None, analysis, out_scale=1.0):
    """Final slider values (preset + photo offsets + auto + look) and channel gains."""
    adjust = combined_adjust(settings, edit)
    values = {k: float(getattr(adjust, k)) for k in NUMERIC_ADJUST}
    auto_offsets, gains = auto.auto_values(analysis, adjust, out_scale)
    extras = {'fade': 0., 'split': 0., 'mono': 0., 'levels': auto_offsets.pop('levels', None)}
    for key, delta in auto_offsets.items():
        values[key] += delta
    look = LOOKS.get(adjust.look, LOOKS['none'])[1]
    strength = adjust.look_strength / 100
    for key, delta in look.items():
        if key in values:
            values[key] += delta * strength
        else:
            extras[key] = delta * strength
    for key in NUMERIC_ADJUST:
        _, low, high, _, _ = ADJUST_RANGES[key]
        values[key] = min(high, max(low, values[key]))
    t, n = values['temperature'] / 100, values['tint'] / 100
    wb = np.array([2 ** (.24 * t), 2 ** (-.2 * n), 2 ** (-.3 * t)], dtype=np.float32)
    gains = gains * wb
    gains = (gains / float(gains @ LUMA)).astype(np.float32)
    return values, gains, extras


def _needs_develop(values, gains, extras, settings):
    return (any(abs(values[k]) > 1e-6 for k in NUMERIC_ADJUST) or np.abs(gains - 1).max() > 1e-6
            or any(extras.values()) or settings.print_brightness)


# ---------------------------------------------------------------- tone maps
def _guided(guide, src, radius, eps):
    """Gray-guide guided filter (He et al.) with O(1) box means; src may have channels."""
    import cv2
    k = (2 * radius + 1, 2 * radius + 1)
    g = np.ascontiguousarray(guide, np.float32)
    p = np.ascontiguousarray(src, np.float32)
    mean_i = cv2.boxFilter(g, -1, k)
    var = cv2.boxFilter(g * g, -1, k) - mean_i * mean_i
    if p.ndim == 3:
        g3, mi3, var3 = g[..., None], mean_i[..., None], var[..., None]
    else:
        g3, mi3, var3 = g, mean_i, var
    mean_p = cv2.boxFilter(p, -1, k)
    cov = cv2.boxFilter(np.ascontiguousarray(g3 * p), -1, k) - mi3 * mean_p
    a = cov / (var3 + eps)
    b = mean_p - a * mi3
    return cv2.boxFilter(np.ascontiguousarray(a, np.float32), -1, k) * g3 + cv2.boxFilter(np.ascontiguousarray(b, np.float32), -1, k)


def compute_maps(proxy_base, geom: Geometry, values, gains):
    """Low-frequency base lightness and haze maps for the whole image area."""
    import cv2
    ph, pw = proxy_base.shape[:2]
    x0, y0, x1, y1 = geom.crop
    crop = proxy_base[int(round(y0 * ph)):max(int(round(y0 * ph)) + 1, int(round(y1 * ph))),
                      int(round(x0 * pw)):max(int(round(x0 * pw)) + 1, int(round(x1 * pw)))]
    iw, ih = geom.image
    k = MAP_EDGE / max(iw, ih)
    mw, mh = max(4, round(iw * k)), max(4, round(ih * k))
    small = cv2.resize(crop, (mw, mh), interpolation=cv2.INTER_AREA).astype(np.float32) / 65535
    lin = decode(small) * gains * (2 ** values['exposure'])
    maps = {}
    if values['dehaze']:
        dark = np.clip(lin, 0, None).min(axis=2)
        dark = cv2.erode(dark, np.ones((7, 7), np.uint8))
        flat = dark.ravel()
        top = flat >= np.percentile(flat, 99.7)
        atmosphere = np.clip(lin.reshape(-1, 3)[top].mean(axis=0), .35, 1.0).astype(np.float32)
        a_lum = max(1e-3, float(atmosphere @ LUMA))
        t = 1 - .95 * dark / a_lum
        gray = np.clip(lin @ LUMA, 0, 1).astype(np.float32)
        t = _guided(gray, t.astype(np.float32), 12, 1e-3)
        maps['haze_t'] = np.clip(t, 0, 1).astype(np.float32)
        maps['atmosphere'] = atmosphere
        lin = _dehaze(lin, values['dehaze'], maps['haze_t'], atmosphere)
    p = encode(np.clip(lin @ LUMA, 0, 4)).astype(np.float32)
    maps['base'] = _guided(p, p, max(2, round(MAP_EDGE / 32)), .012).astype(np.float32)
    return maps


def sample_map(m, full_size, region):
    """Resample a low-res map over a (x, y, w, h) region of an image of `full_size`."""
    import cv2
    fw, fh = full_size
    x, y, w, h = region
    sx, sy = m.shape[1] / fw, m.shape[0] / fh
    matrix = np.array([[sx, 0, (x + .5) * sx - .5], [0, sy, (y + .5) * sy - .5]], dtype=np.float64)
    return cv2.warpAffine(m, matrix, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def _dehaze(lin, amount, t, atmosphere):
    d = amount / 100
    if d > 0:
        tt = np.maximum(1 - d * (1 - t), .3)[..., None]
        return (lin - atmosphere) / tt + atmosphere
    mix = (-d * .45) * (1 - t * .5)[..., None]
    return lin + mix * (atmosphere - lin)


# ---------------------------------------------------------------- develop
def _tone_lut(values, extras, settings):
    """Global curve on perceptual lightness: shoulder → auto levels → contrast → whites/blacks → fade → print."""
    ev = values['exposure']
    pmax = max(1., float(encode(np.float32(2 ** max(0., ev)))))
    pmax *= 1 + .3 * max(0., values['highlights']) / 100 + .12 * max(0., values['clarity']) / 100
    xs = np.linspace(0, pmax, 4097, dtype=np.float32)
    y = xs.copy()
    if pmax > 1:
        knee = .8
        a = (pmax - knee) / (1 - knee)
        t = np.clip((xs - knee) / (pmax - knee), 0, 1)
        y = np.where(xs > knee, knee + (1 - knee) * (t * a / (1 + (a - 1) * t)), xs)
    if extras.get('levels'):
        lb, lw = extras['levels']
        y = np.maximum(0, (y - lb) / max(.3, lw - lb))
    c = values['contrast'] / 100
    if c:
        m = .46
        g = 1 + 1.1 * c if c > 0 else 1 / (1 + 1.1 * -c)
        yc = np.clip(y, 0, 1)
        y = np.where(yc < m, m * np.power(yc / m, g), 1 - (1 - m) * np.power((1 - yc) / (1 - m), g))
    b, w = values['blacks'] / 100, values['whites'] / 100
    if b > 0:
        y = y + b * .12 * np.power(np.clip(1 - y, 0, 1), 3)
    elif b < 0:
        d = -b * .1
        y = np.maximum(0, (y - d) / (1 - d))
    if w > 0:
        y = y / (1 - w * .18)                          # lower white point: brightest tones clip, like Lightroom
    elif w < 0:
        y = y * (1 + w * .15)
    if extras.get('fade'):
        y = y + extras['fade'] / 100 * .12 * np.power(np.clip(1 - y, 0, 1), 2)
    if settings.print_brightness:
        y = np.power(np.clip(y, 0, 1), 1 / (1 + settings.print_brightness / 100 * 1.2))
    return np.clip(y, 0, 1).astype(np.float32), pmax


def _denoise(enc, luma, chroma, k):
    import cv2
    y = luminance(enc)
    cdiff = enc - y[..., None]
    if luma > 0:
        y8 = np.round(np.clip(y, 0, 1) * 255).astype(np.uint8)
        h = 1.5 + luma / 100 * 11
        clean = cv2.fastNlMeansDenoising(y8, None, h * min(1, .4 + .6 * k), 5, 13)
        y = y + (clean.astype(np.float32) - y8) * (min(1, .3 + luma / 70) / 255)
    if chroma > 0:
        radius = max(1, round((1 + chroma / 100 * 7) * k))
        smooth = _guided(np.clip(y, 0, 1).astype(np.float32), np.ascontiguousarray(cdiff, np.float32), radius, 2e-3)
        cdiff = cdiff + (smooth - cdiff) * min(1, chroma / 45)
    return (y[..., None] + cdiff).astype(np.float32)


_TEAL = np.array([math.cos(math.radians(205)), math.sin(math.radians(205))], dtype=np.float32)
_AMBER = np.array([math.cos(math.radians(70)), math.sin(math.radians(70))], dtype=np.float32)
_MONO = np.array([.3, .59, .11], dtype=np.float32)


def develop(enc, values, gains, extras, settings, get_maps, map_region, image_size, k, preview):
    """Colour/tone processing of an sRGB-encoded float region; returns encoded float.

    `get_maps()` lazily supplies the low-frequency maps; `map_region` locates this
    region inside the image of `image_size` (both at the current render scale).
    """
    import cv2
    if values['denoise'] or values['color_denoise']:
        if not preview or k >= .5:
            enc = _denoise(enc, values['denoise'], values['color_denoise'], k)
    if not _needs_develop(values, gains, extras, settings):
        return np.clip(enc, 0, 1)
    lin = decode_unit(np.clip(enc, 0, 1)) * (gains * np.float32(2 ** values['exposure']))
    if values['dehaze']:
        maps = get_maps()
        if 'haze_t' in maps:
            t = sample_map(maps['haze_t'], image_size, map_region)
            lin = _dehaze(lin, values['dehaze'], t, maps['atmosphere'])
    y = np.maximum(luminance(lin), 0)
    p = encode(y)
    sh, hl, cl = values['shadows'] / 100, values['highlights'] / 100, values['clarity'] / 100
    if sh or hl or cl:
        bc = np.clip(sample_map(get_maps()['base'], image_size, map_region), 0, 1)
        dp = np.zeros_like(p)
        if sh:
            inv = 1 - bc
            dp += np.float32(sh * 1.05) * cv2.sqrt(bc) * inv * inv * inv
        if hl:
            dp += np.float32(hl * .82) * bc * bc * bc * cv2.pow(1 - np.minimum(bc, .999), .35)
        if cl:
            # Band relative to the image, so the effect looks the same in preview and export.
            sigma = max(.5, max(image_size) / 1600)
            band = cv2.GaussianBlur(p, (0, 0), sigma) - bc
            weight = cv2.sqrt(np.clip(4 * p * (1 - p), 0, 1))
            dp += np.float32(cl * .9) * np.clip(band, -.25, .25) * weight
        p = p + dp
    lut, pmax = _tone_lut(values, extras, settings)
    idx = (np.clip(p, 0, pmax) * ((len(lut) - 1) / pmax) + .5).astype(np.int32)
    p2 = np.take(lut, idx)
    y2 = decode_unit(p2)
    w = np.clip(y * 500, 0, 1)
    ratio = np.minimum(y2 / np.maximum(y, 1e-6), 32)
    lin = lin * (w * ratio)[..., None] + ((1 - w) * y2)[..., None]
    sat, vib = values['saturation'] / 100, values['vibrance'] / 100
    mono, split = extras.get('mono', 0), extras.get('split', 0)
    if sat or vib or split:
        lab = to_oklab(np.maximum(lin, 0))
        a, b = lab[..., 1], lab[..., 2]
        chroma = cv2.magnitude(np.ascontiguousarray(a), np.ascontiguousarray(b))
        gain = np.full(chroma.shape, 1 + sat, dtype=np.float32)
        if vib:
            skin = np.clip(((a * SKIN[0] + b * SKIN[1]) / np.maximum(chroma, 1e-6) - .82) * (1 / .18), 0, 1) \
                * np.clip(chroma * (1 / .03), 0, 1)
            if vib > 0:
                gain *= 1 + np.float32(vib) * np.clip(1 - chroma * 5, 0, 1) * (1 - .65 * skin)
            else:
                gain *= 1 + np.float32(vib) * (.5 + .5 * np.clip(1 - chroma * 4, 0, 1))
        gain = np.maximum(gain, 0)
        lab[..., 1] = a * gain
        lab[..., 2] = b * gain
        if split:
            L = lab[..., 0]
            shadow, light = (1 - L) ** 2 * (.022 * split), L ** 2 * (.016 * split)
            lab[..., 1] += shadow * _TEAL[0] + light * _AMBER[0]
            lab[..., 2] += shadow * _TEAL[1] + light * _AMBER[1]
        lin = from_oklab(lab)
    if mono:
        gray = cv2.transform(np.ascontiguousarray(np.maximum(lin, 0)), _MONO.reshape(1, 3))[..., None]
        lin = lin + np.float32(mono) * (gray - lin)
    return np.clip(encode(gamut_clip(lin)), 0, 1)


def sharpen_params(settings: Settings):
    mode = settings.sharpen
    if mode == 'off':
        return None
    amount = {'low': .45, 'standard': .8, 'high': 1.25}[settings.sharpen_amount]
    if mode == 'screen':
        return .55, amount
    sigma = (.62 if mode == 'glossy' else .85) * settings.dpi / 300
    return sigma, amount * (1.2 if mode == 'matte' else 1)


def output_sharpen(enc, settings, k):
    import cv2
    params = sharpen_params(settings)
    if not params:
        return enc
    sigma, amount = params
    sigma *= k
    if sigma < .3:
        return enc
    y = luminance(enc)
    detail = y - cv2.GaussianBlur(y, (0, 0), sigma)
    detail = np.sign(detail) * np.maximum(np.abs(detail) - .004, 0)
    return np.clip(enc + np.clip(detail * np.float32(amount * 1.6), -.1, .1)[..., None], 0, 1)


# ---------------------------------------------------------------- render
@dataclass
class Rendered:
    image: np.ndarray            # sRGB-encoded float32 canvas (or region of it)
    geometry: Geometry
    notes: list
    neural: bool = False


def _to_float(block):
    return block.astype(np.float32) / (255 if block.dtype == np.uint8 else 65535)


def neural_wanted(settings: Settings, edit: Edit | None):
    edit = edit or Edit()
    return edit.neural if edit.neural is not None else settings.neural


def neural_status(source: Source, settings: Settings, edit: Edit | None, geom: Geometry):
    """(applies, reason). The network runs only where it visibly helps a print."""
    from .model import NEURAL_MAX_MP, NEURAL_MIN_SCALE
    if not neural_wanted(settings, edit):
        return False, ''
    w, h = geom.source
    if geom.scale < NEURAL_MIN_SCALE:
        return False, 'Нейросеть не нужна: снимку хватает собственного разрешения.'
    if w * h > NEURAL_MAX_MP * 1e6:
        return False, f'Нейросеть пропущена: исходник больше {NEURAL_MAX_MP:g} Мп — он и так детальный.'
    return True, ''


def enhance_key(source: Source, edit: Edit | None, settings: Settings):
    edit = edit or Edit()
    return source.info.key + (edit.rotation % 360, round(edit.angle, 3))


def enhanced(source: Source, settings: Settings, edit: Edit | None, progress=None, cancel=None, compute=True):
    """Cached Real-ESRGAN version of the oriented source, computing it if asked."""
    from . import neural
    key = enhance_key(source, edit, settings)
    entry = neural.CACHE.get(key)
    if entry is None and compute:
        entry = neural.enhance(source.base(edit or Edit(), True), 1.0, progress, cancel)
        neural.CACHE.put(key, entry)
    return entry


def needs_analysis(settings: Settings, edit: Edit | None):
    edit = edit or Edit()
    framing = (settings.smart_crop and settings.size_mode in ('print', 'pixels')
               and (edit.fit or settings.fit) == 'cover' and not edit.manual_crop)
    return settings.adjust.auto or framing


def plan(source: Source, settings: Settings, edit: Edit | None = None, analysis_cache=None, analysis=None):
    """Final geometry for this photo (smart framing needs the analysis)."""
    edit = edit or Edit()
    if analysis is None and needs_analysis(settings, edit):
        analysis = source.ensure_analysis(analysis_cache)
    return geometry(source.oriented_size(edit), settings, edit, analysis)


def resample(block, d, origin, size):
    """Exact affine resampling: output pixel u maps to block pixel origin + d·u.

    Downscaling (d > 1) pre-filters with a Gaussian matched to the ratio, so any
    region of the image — a preview, a 100% tile or an export strip — samples the
    same continuous image without seams or phase shifts.
    """
    import cv2
    if d > 1.01:
        block = cv2.GaussianBlur(block, (0, 0), .42 * math.sqrt(d * d - 1))
    matrix = np.array([[d, 0, origin[0]], [0, d, origin[1]]], dtype=np.float64)
    flags = (cv2.INTER_LANCZOS4 if d < 1 else cv2.INTER_CUBIC) | cv2.WARP_INVERSE_MAP
    out = cv2.warpAffine(block, matrix, size, flags=flags, borderMode=cv2.BORDER_REFLECT_101)
    return np.clip(out, 0, 1)


def _sample(base, geom, iw, window):
    """Resample the crop of `base` so that the image is `iw` px wide; return `window` (x0, y0, x1, y1)."""
    bh, bw = base.shape[:2]
    x0, y0, x1, y1 = geom.crop
    cx0, cy0, cx1 = x0 * bw, y0 * bh, x1 * bw
    s = iw / max(1e-6, cx1 - cx0)                               # render px per base px
    mx0, my0, mx1, my1 = window
    sx0 = max(0, int(math.floor(cx0 + mx0 / s)) - 4)
    sy0 = max(0, int(math.floor(cy0 + my0 / s)) - 4)
    sx1 = min(bw, int(math.ceil(cx0 + mx1 / s)) + 4)
    sy1 = min(bh, int(math.ceil(cy0 + my1 / s)) + 4)
    d = 1 / s
    origin = ((cx0 - sx0) + (mx0 + .5) * d - .5, (cy0 - sy0) + (my0 + .5) * d - .5)
    return resample(_to_float(base[sy0:sy1, sx0:sx1]), d, origin, (mx1 - mx0, my1 - my0))


def render(source: Source, settings: Settings, edit: Edit | None = None, *, k=1.0, region=None,
           use_full=True, before=False, enhanced_source=None, analysis_cache=None, **_):
    """Render the canvas at scale `k` (render px per output px), or only a canvas `region`
    (x, y, w, h) in render pixels. `use_full=False` renders from the proxy (fit preview);
    `before=True` gives the same framing without any processing (for comparison).
    `enhanced_source` is a neural cache entry used in place of the plain source.
    """
    edit = edit or Edit()
    analysis = source.ensure_analysis(analysis_cache) if needs_analysis(settings, edit) else None
    geom = plan(source, settings, edit, analysis_cache, analysis)
    notes = []
    cw, ch = geom.canvas
    region = region or (0, 0, max(1, round(cw * k)), max(1, round(ch * k)))
    rx, ry, rwid, rhei = region
    canvas = np.empty((rhei, rwid, 3), dtype=np.float32)
    canvas[:] = np.array(_rgb(settings.background), dtype=np.float32) / 255
    iw, ih = max(1, round(geom.image[0] * k)), max(1, round(geom.image[1] * k))
    ox, oy = round(geom.offset[0] * k), round(geom.offset[1] * k)
    ix0, iy0 = max(rx, ox), max(ry, oy)
    ix1, iy1 = min(rx + rwid, ox + iw), min(ry + rhei, oy + ih)
    used_neural = enhanced_source is not None and not before
    if ix1 <= ix0 or iy1 <= iy0:
        return Rendered(canvas, geom, notes, used_neural)
    want = (ix0 - ox, iy0 - oy, ix1 - ix0, iy1 - iy0)        # wanted part, image coords
    values, gains, extras = effective_values(settings, edit, analysis, geom.scale)
    preview = not use_full or k < 1
    margin = 0 if before else int(math.ceil(3 * max(1., max(iw, ih) / 1600, 2.5 * k))) + 6
    mx0, my0 = max(0, want[0] - margin), max(0, want[1] - margin)
    mx1, my1 = min(iw, want[0] + want[2] + margin), min(ih, want[1] + want[3] + margin)
    plain = source.base(edit, use_full)
    if used_neural:
        window = _sample(enhanced_source['full'] if use_full else enhanced_source['proxy'], geom, iw, (mx0, my0, mx1, my1))
        strength = settings.neural_strength / 100
        if strength < 1:
            window = window * strength + _sample(plain, geom, iw, (mx0, my0, mx1, my1)) * (1 - strength)
    else:
        window = _sample(plain, geom, iw, (mx0, my0, mx1, my1))
    if not before:
        def get_maps():
            return source_maps(source, edit, geom, values, gains)
        window = develop(window, values, gains, extras, settings, get_maps,
                         (mx0, my0, mx1 - mx0, my1 - my0), (iw, ih), k, preview)
        if not preview or k >= .5:
            window = output_sharpen(window, settings, k)
        if used_neural:
            notes.append('Нейросеть применена.')
    part = window[want[1] - my0:want[1] - my0 + want[3], want[0] - mx0:want[0] - mx0 + want[2]]
    canvas[iy0 - ry:iy1 - ry, ix0 - rx:ix1 - rx] = part
    return Rendered(canvas, geom, notes, used_neural)


_POOL = None
_POOL_LOCK = threading.Lock()


def _pool():
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            from concurrent.futures import ThreadPoolExecutor
            import os
            _POOL = ThreadPoolExecutor(max_workers=max(2, min(8, (os.cpu_count() or 4))), thread_name_prefix='printprep-strip')
        return _POOL


def render_fast(source: Source, settings: Settings, edit: Edit | None = None, *, k=1.0, region=None,
                use_full=True, before=False, enhanced_source=None, analysis_cache=None, strips=None, **_):
    """`render` split into horizontal strips rendered in parallel (NumPy/OpenCV release the GIL).

    Caches (analysis, transformed base, tone maps) are warmed first so strips share them.
    """
    edit = edit or Edit()
    analysis = source.ensure_analysis(analysis_cache) if needs_analysis(settings, edit) else None
    geom = plan(source, settings, edit, analysis_cache, analysis)
    cw, ch = geom.canvas
    region = region or (0, 0, max(1, round(cw * k)), max(1, round(ch * k)))
    rx, ry, rw, rh = region
    n = strips or max(1, min(8, rw * rh // 300_000))
    kwargs = dict(k=k, use_full=use_full, before=before, enhanced_source=enhanced_source, analysis_cache=analysis_cache)
    if n == 1 or rh < 128:
        return render(source, settings, edit, region=region, **kwargs)
    if enhanced_source is None:
        source.base(edit, use_full)
    if not before:
        values, gains, _ = effective_values(settings, edit, analysis, geom.scale)
        if any(values[key] for key in ('shadows', 'highlights', 'clarity', 'dehaze')):
            source_maps(source, edit, geom, values, gains)
    step = (rh + n - 1) // n
    parts = [(rx, ry + top, rw, min(step, rh - top)) for top in range(0, rh, step)]
    futures = [_pool().submit(render, source, settings, edit, region=part, **kwargs) for part in parts]
    results = [f.result() for f in futures]
    image = np.concatenate([r.image for r in results], axis=0)
    notes = []
    for r in results:
        notes.extend(x for x in r.notes if x not in notes)
    return Rendered(image, results[0].geometry, notes, any(r.neural for r in results))


def source_maps(source: Source, edit, geom, values, gains):
    key = (edit.rotation % 360, round(edit.angle, 3), tuple(round(v, 5) for v in geom.crop), geom.image,
           tuple(np.round(gains, 5)), round(values['exposure'], 4), round(values['dehaze'], 3))
    with source._lock:
        if key in source._maps:
            source._maps.move_to_end(key)
            return source._maps[key]
    maps = compute_maps(source.base(edit, False), geom, values, gains)
    with source._lock:
        source._maps[key] = maps
        while len(source._maps) > 6:
            source._maps.popitem(last=False)
    return maps


def _rgb(text):
    from PIL import ImageColor
    return ImageColor.getrgb(text)[:3]


# ---------------------------------------------------------------- output
_DITHER = None


def quantize8(enc, seed=0):
    """Float → uint8 with a fixed triangular dither tile (smooth print gradients)."""
    global _DITHER
    if _DITHER is None:
        rng = np.random.default_rng(20261016)
        _DITHER = ((rng.random((128, 128, 3)) + rng.random((128, 128, 3)) - 1) * .5).astype(np.float32)
    h, w = enc.shape[:2]
    out = np.empty(enc.shape, dtype=np.uint8)
    for top in range(0, h, 256):
        block = enc[top:top + 256] * 255
        bh = block.shape[0]
        tile = np.tile(_DITHER, ((bh + 127) // 128 + 1, (w + 127) // 128, 1))
        oy = (top + seed) % 128
        out[top:top + bh] = np.clip(np.round(block + tile[oy:oy + bh, :w]), 0, 255).astype(np.uint8)
    return out


def to_output(enc, settings: Settings, seed=0):
    """Encoded float canvas → (array, PIL mode, ICC bytes) in the requested output space."""
    from PIL import Image, ImageCms
    from .imageio import SRGB_BYTES, SRGB_PROFILE
    if settings.output_space == 'sRGB':
        if settings.bit_depth == 16:
            return np.round(np.clip(enc, 0, 1) * 65535).astype(np.uint16), 'RGB', SRGB_BYTES
        return quantize8(enc, seed), 'RGB', SRGB_BYTES
    profile = ImageCms.getOpenProfile(settings.icc_path)
    mode = profile.profile.xcolor_space.strip()
    im = ImageCms.profileToProfile(Image.fromarray(quantize8(enc, seed)), SRGB_PROFILE, profile, outputMode=mode,
                                   renderingIntent=settings.intent, flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
    return np.asarray(im), mode, profile.tobytes()


def soft_proof(rgb_u8, settings: Settings, gamut_warning=False):
    """Screen simulation of the output ICC (sRGB display assumed) and optional gamut mask."""
    from PIL import Image, ImageCms
    from .imageio import SRGB_PROFILE
    profile = ImageCms.getOpenProfile(settings.icc_path)
    im = Image.fromarray(rgb_u8)
    transform = ImageCms.buildProofTransform(SRGB_PROFILE, SRGB_PROFILE, profile, 'RGB', 'RGB',
                                             renderingIntent=1, proofRenderingIntent=settings.intent,
                                             flags=ImageCms.Flags.SOFTPROOFING | ImageCms.Flags.BLACKPOINTCOMPENSATION)
    proofed = np.asarray(ImageCms.applyTransform(im, transform))
    if not gamut_warning:
        return proofed
    mode = profile.profile.xcolor_space.strip()
    there = ImageCms.profileToProfile(im, SRGB_PROFILE, profile, outputMode=mode, renderingIntent=1)
    back = np.asarray(ImageCms.profileToProfile(there, profile, SRGB_PROFILE, outputMode='RGB', renderingIntent=1))
    a = to_oklab(decode(rgb_u8.astype(np.float32) / 255))
    b = to_oklab(decode(back.astype(np.float32) / 255))
    out = np.linalg.norm(a - b, axis=2) > .035
    proofed = proofed.copy()
    proofed[out] = (proofed[out] * .25 + np.array([255, 0, 200]) * .75).astype(np.uint8)
    return proofed
