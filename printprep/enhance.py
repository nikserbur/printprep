"""Bounded non-neural corrections. Small analysis maps, full-resolution tiled color.

Original implementation of standard guided-filter and luminance/chroma operations;
no third-party application code or machine-learning models are embedded.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

PRESETS = {
    'none': ('Без коррекции', {}),
    'balanced': ('Естественная печать', dict(shadows=.25, highlights=.25, clarity=.18, vibrance=.15, auto_tone=True)),
    'portrait': ('Портрет · мягкий', dict(shadows=.22, highlights=.3, clarity=.04, vibrance=.08, chroma_denoise=.15)),
    'landscape': ('Пейзаж · детали', dict(shadows=.25, highlights=.32, clarity=.38, vibrance=.28)),
    'lowlight': ('Слабый свет · бережно', dict(shadows=.45, highlights=.15, clarity=.08, vibrance=.08, chroma_denoise=.5, auto_tone=True)),
    'product': ('Предметная · чисто', dict(shadows=.1, highlights=.25, clarity=.16, vibrance=.04, chroma_denoise=.12)),
}
DEFAULTS = dict(shadows=0., highlights=0., clarity=0., vibrance=0., warmth=0., tint=0.,
                chroma_denoise=0., auto_wb=False, auto_tone=False)
_LUT = np.where(np.arange(256, dtype=np.float32) / 255 <= .04045,
                np.arange(256, dtype=np.float32) / 255 / 12.92,
                ((np.arange(256, dtype=np.float32) / 255 + .055) / 1.055) ** 2.4)
_WEIGHTS = np.array([.2126, .7152, .0722], dtype=np.float32)


def box_mean(array, radius):
    """O(N) reflected-window mean; float64 sums avoid cancellation."""
    radius = max(1, min(radius, max(1, min(array.shape) // 3)))
    p = np.pad(array, radius, mode='reflect')
    integral = np.pad(p, ((1, 0), (1, 0))).cumsum(0, dtype=np.float64).cumsum(1)
    k = 2 * radius + 1
    return ((integral[k:, k:] - integral[:-k, k:] - integral[k:, :-k] + integral[:-k, :-k]) / (k * k)).astype(np.float32)


def guided_base(lightness, radius=16, epsilon=.0015):
    mean = box_mean(lightness, radius)
    variance = np.maximum(box_mean(lightness * lightness, radius) - mean * mean, 0)
    a = variance / (variance + epsilon)
    b = mean * (1 - a)
    return box_mean(a, radius) * lightness + box_mean(b, radius)


def _lightness(y):
    return np.where(y > .008856, 1.16 * np.cbrt(y) - .16, 9.03296 * y)


def _inverse_lightness(l):
    return np.where(l > .08, ((l + .16) / 1.16) ** 3, l / 9.03296)


def _sample(im):
    small = im.copy()
    small.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    return _LUT[np.asarray(small)]


def estimate_white_balance(rgb):
    """Robust gray-pixel estimate; refuse weak evidence, cap gains ±18%."""
    top = rgb.max(axis=2)
    bottom = rgb.min(axis=2)
    saturation = (top - bottom) / np.maximum(top, .001)
    y = rgb @ _WEIGHTS
    neutral = (saturation < .32) & (y > .035) & (y < .75)
    count = int(neutral.sum())
    fraction = count / neutral.size
    if count < 64 or fraction < .015:
        return np.ones(3, dtype=np.float32), 'Недостаточно нейтральных участков: авто-ББ не применён.'
    values = rgb[neutral]
    channels = np.exp(np.median(np.log(np.maximum(values, .001)), axis=0))
    geometric = float(np.exp(np.log(channels).mean()))
    gains = np.clip(geometric / channels, .85, 1.18)
    # Even a plausible neutral area is not evidence of the intended lighting.
    gains = 1 + (gains - 1) * min(.65, fraction * 3)
    return gains.astype(np.float32), f'Авто-ББ: нейтральные кандидаты {fraction:.0%}; коррекция ограничена.'


def analyze(im):
    rgb = _sample(im)
    y = rgb @ _WEIGHTS
    encoded = np.round(_encode(np.clip(rgb, 0, 1)) * 255)
    _, wb_note = estimate_white_balance(rgb)
    return {'shadow_percent': round(float((y < .01).mean()) * 100, 1),
            'highlight_percent': round(float((encoded.min(axis=2) >= 250).mean()) * 100, 1),
            'median_linear_luminance': round(float(np.median(y)), 4), 'white_balance': wb_note}


def _soft_gamut(rgb):
    # Scale over-range pixels toward black instead of clipping individual channels.
    rgb = np.maximum(rgb, 0)
    return rgb / np.maximum(1, rgb.max(axis=2, keepdims=True))


def _encode(rgb):
    return np.where(rgb <= .0031308, rgb * 12.92, 1.055 * np.power(np.maximum(rgb, 0), 1 / 2.4) - .055)


def _vibrance(rgb, amount):
    high = rgb.max(axis=2)
    low = rgb.min(axis=2)
    sat = (high - low) / np.maximum(high, .001)
    skin_like = (rgb[..., 0] > rgb[..., 1]) & (rgb[..., 1] > rgb[..., 2]) & ((rgb[..., 0] - rgb[..., 2]) > .05)
    gain = 1 + amount * .55 * (1 - sat) * np.where(skin_like, .3, 1)
    y = (rgb @ _WEIGHTS)[..., None]
    chroma = rgb - y
    positive = np.where(chroma > .00001, (1 - y) / np.maximum(chroma, .00001), 100)
    negative = np.where(chroma < -.00001, y / np.maximum(-chroma, .00001), 100)
    gain = np.minimum(gain, np.minimum(positive.min(axis=2), negative.min(axis=2)))
    return np.clip(y + chroma * gain[..., None], 0, 1)


def enhance(im: Image.Image, settings, return_notes=False):
    """Apply controls at requested strength. Zero controls is byte-identical."""
    active = any(getattr(settings, k) for k in DEFAULTS)
    if not active or settings.enhancement_strength == 0:
        return (im, []) if return_notes else im
    strength = settings.enhancement_strength
    rgb = _sample(im)
    notes = []
    gains = np.ones(3, dtype=np.float32)
    if settings.auto_wb:
        wb, note = estimate_white_balance(rgb)
        gains *= 1 + (wb - 1) * strength
        notes.append(note)
    gains *= np.exp2(np.array([settings.warmth * .2, -settings.tint * .15, -settings.warmth * .2], dtype=np.float32) * strength)
    rgb *= gains
    y = rgb @ _WEIGHTS
    exposure = 1.
    if settings.auto_tone:
        median = float(np.median(y))
        if median > .005 and median < .65:
            ev = float(np.clip(np.log2(.18 / median), -.35, .35)) * strength
            exposure = 2 ** ev
            notes.append(f'Автотон: {ev:+.2f} EV (ограничен ±0,35).')
        else:
            notes.append('Автотон не применён: экстремальная яркость сцены.')
    l = _lightness(np.clip(y, 0, 1))
    base = guided_base(l, radius=max(2, round(max(l.shape) / 50)))
    envelope = 4 * base * (1 - base)
    delta = (settings.shadows * .25 * (1 - base) ** 2 - settings.highlights * .23 * base ** 2) * envelope
    delta += settings.clarity * .65 * (l - base) * (1 - .5 * l)
    target = _inverse_lightness(np.clip(l + strength * delta, 0, 1))
    gain_map = np.clip(target / np.maximum(y, .0001), .55, 1.8).astype(np.float32)
    # Anchor black and paper-white: autotone acts mainly on mid-tones.
    gain_map *= np.power(exposure, np.clip(4 * l * (1 - l), 0, 1)).astype(np.float32)
    # Keep exact black black, not a raised gray floor.
    gain_map[y < .0001] = 1
    map_image = Image.fromarray(gain_map).resize(im.size, Image.Resampling.BILINEAR)
    result = Image.new('RGB', im.size)
    # Full-resolution color only in small tiles: memory doesn't scale as N×RGB×float.
    for top in range(0, im.height, 256):
        rect = (0, top, im.width, min(im.height, top + 256))
        tile = _LUT[np.asarray(im.crop(rect))]
        local_gain = np.asarray(map_image.crop(rect))[..., None]
        tile = _soft_gamut(tile * gains * local_gain)
        encoded = _encode(tile)
        if settings.vibrance:
            encoded = _vibrance(encoded, settings.vibrance * strength)
        result.paste(Image.fromarray(np.round(np.clip(encoded, 0, 1) * 255).astype(np.uint8)), rect)
    if settings.chroma_denoise:
        y, cb, cr = result.convert('YCbCr').split()
        mix = settings.chroma_denoise * strength
        cb = Image.blend(cb, cb.filter(ImageFilter.MedianFilter(3)), mix)
        cr = Image.blend(cr, cr.filter(ImageFilter.MedianFilter(3)), mix)
        result = Image.merge('YCbCr', (y, cb, cr)).convert('RGB')
    return (result, notes) if return_notes else result
