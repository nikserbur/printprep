"""Per-photo smart analysis: what an experienced operator would correct first.

Runs on the deterministic analysis proxy (the same in preview and export), so the
automatic corrections shown on screen are exactly what gets written. All results
are *suggestions in slider units*; Adjust.auto_strength scales them.
"""
from __future__ import annotations

import math

import numpy as np

from .color import LUMA, decode, encode, to_oklab

ANALYSIS_EDGE = 1024


def _proxy_float(proxy):
    import cv2
    h, w = proxy.shape[:2]
    k = min(1, ANALYSIS_EDGE / max(h, w))
    small = cv2.resize(proxy, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else proxy
    depth = 255 if small.dtype == np.uint8 else 65535
    return small.astype(np.float32) / depth


def _gray_pixel_gains(lin):
    top = lin.max(axis=2)
    low = lin.min(axis=2)
    sat = (top - low) / np.maximum(top, 1e-3)
    y = lin @ LUMA
    mask = (sat < .3) & (y > .03) & (y < .8)
    fraction = float(mask.mean())
    if mask.sum() < 64 or fraction < .01:
        return None, fraction
    med = np.exp(np.median(np.log(np.maximum(lin[mask], 1e-4)), axis=0))
    return float(np.exp(np.log(med).mean())) / med, fraction


def _learned_gains(enc):
    """OpenCV xphoto LearningBasedWB (gradient-boosted illuminant model) as channel gains."""
    import cv2
    u8 = np.round(np.clip(enc, 0, 1) * 255).astype(np.uint8)
    wb = cv2.xphoto.createLearningBasedWB()
    wb.setSaturationThreshold(.98)
    balanced = wb.balanceWhite(cv2.cvtColor(u8, cv2.COLOR_RGB2BGR))[..., ::-1]
    src = decode(u8.astype(np.float32) / 255)
    dst = decode(balanced.astype(np.float32) / 255)
    y = src @ LUMA
    mask = (y > .02) & (src.max(axis=2) < .95) & (dst.max(axis=2) < .98)
    if mask.sum() < 64:
        return None
    gains = dst[mask].mean(axis=0) / np.maximum(src[mask].mean(axis=0), 1e-4)
    return gains / np.exp(np.log(gains).mean())


def _normalise(gains):
    gains = np.clip(gains, .8, 1.25)
    return (gains / float(gains @ LUMA)).astype(np.float32)


def estimate_noise(full):
    """Immerkær (1996) fast noise sigma on a native-resolution centre crop, in 8-bit units.

    Restricted to flat areas (low gradient) so texture is not mistaken for noise.
    """
    import cv2
    h, w = full.shape[:2]
    cy, cx, r = h // 2, w // 2, 640
    crop = full[max(0, cy - r):cy + r, max(0, cx - r):cx + r]
    depth = 255 if crop.dtype == np.uint8 else 65535
    gray = (crop.astype(np.float32) @ LUMA) * (255 / depth)
    if min(gray.shape) < 16:
        return 0.
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
    response = np.abs(cv2.filter2D(gray, -1, kernel))[1:-1, 1:-1]
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)[1:-1, 1:-1]
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)[1:-1, 1:-1]
    grad = np.hypot(gx, gy)
    flat = grad < np.percentile(grad, 40)
    valid = flat & (gray[1:-1, 1:-1] > 12) & (gray[1:-1, 1:-1] < 243)
    if valid.sum() < 500:
        valid = flat
    if valid.sum() < 100:
        return 0.
    return float(math.sqrt(math.pi / 2) * response[valid].mean() / 6)


def saliency_map(enc):
    import cv2
    u8 = np.round(np.clip(enc, 0, 1) * 255).astype(np.uint8)
    small = cv2.resize(u8, (128, max(1, round(128 * u8.shape[0] / u8.shape[1])))) if u8.shape[1] >= u8.shape[0] \
        else cv2.resize(u8, (max(1, round(128 * u8.shape[1] / u8.shape[0])), 128))
    try:
        detector = cv2.saliency.StaticSaliencySpectralResidual_create()
        ok, sal = detector.computeSaliency(cv2.cvtColor(small, cv2.COLOR_RGB2BGR))
        sal = sal.astype(np.float32) if ok else None
    except Exception:
        sal = None
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)
    edges = np.hypot(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
    edges[:2] = edges[-2:] = 0
    edges[:, :2] = edges[:, -2:] = 0
    edges /= max(1e-6, float(edges.max()))
    combined = edges if sal is None else .5 * edges + .5 * sal / max(1e-6, float(sal.max()))
    return cv2.GaussianBlur(combined, (0, 0), 3)


def analyze(proxy, full=None):
    """Return a dict of automatic suggestions for this photo (JSON-safe except 'saliency')."""
    from .neural import detect_faces
    enc = _proxy_float(proxy)
    lin = decode(enc)
    notes = []

    # White balance: learned illuminant estimate cross-checked with near-neutral pixels.
    learned = _learned_gains(enc)
    gray, fraction = _gray_pixel_gains(lin)
    if learned is not None and gray is not None:
        agreement = float(np.abs(np.log(learned) - np.log(gray)).max())
        weight = .5 if agreement < .08 else .7
        gains = np.exp(weight * np.log(learned) + (1 - weight) * np.log(gray))
        confidence = 1 if agreement < .12 else .6
    elif learned is not None:
        gains, confidence = learned, .6
    elif gray is not None:
        gains, confidence = gray, .7
    else:
        gains, confidence = np.ones(3, np.float32), 0
    gains = np.exp(np.log(np.asarray(gains, np.float64)) * .8 * confidence)
    wb = _normalise(gains)
    shift = float(np.log(wb[0] / wb[2]))
    if abs(shift) > .03:
        notes.append('ББ: теплее' if shift > 0 else 'ББ: холоднее')

    balanced = lin * wb
    y = balanced @ LUMA
    u8 = np.round(np.clip(enc, 0, 1) * 255).astype(np.uint8)
    try:
        faces = detect_faces(u8)
    except Exception:
        faces = []

    # Exposure: log-average key toward middle grey, with faces as a second opinion.
    valid = (y > .002) & (y < .97)
    sample = y[valid] if valid.sum() > 100 else y.ravel()
    key = float(np.exp(np.log(np.maximum(sample, 1e-4)).mean()))
    ev_global = float(np.clip(math.log2(.18 / max(key, 1e-4)) * .55, -1.2, 1.2))
    if ev_global < 0:
        # Bright scenes (snow, white backgrounds, high key) are usually intended: darken only
        # as far as needed to bring genuinely clipping highlights back.
        clipped = float((y > .9).mean())
        ev_global = max(ev_global, -.6) * min(1., clipped * 8)
    ev = ev_global
    if faces:
        h, w = y.shape
        face_lum = []
        for fx, fy, fw, fh, _ in faces[:4]:
            x0, y0 = int((fx + fw * .25) * w), int((fy + fh * .3) * h)
            x1, y1 = int((fx + fw * .75) * w), int((fy + fh * .8) * h)
            region = y[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
            if region.size:
                face_lum.append(float(np.median(region)))
        if face_lum:
            yf = float(np.median(face_lum))
            target = min(.42, max(.16, yf))  # respect any natural skin tone inside a broad range
            ev_face = float(np.clip(math.log2(target / max(yf, 1e-4)), -.6, 1.0))
            ev = .45 * ev_global + .55 * ev_face
            notes.append(f'Лица: {len(faces)}')
    p995 = float(np.percentile(y, 99.5))
    ev = min(ev, math.log2(1.15 / max(p995, 1e-4)))  # keep highlights within the soft shoulder
    ev = float(np.clip(ev, -1.2, 1.2))
    if abs(ev) >= .1:
        notes.append(f'Экспозиция {ev:+.1f} EV')

    exposed = np.clip(y * 2 ** ev, 0, 4)
    p = encode(np.minimum(exposed, 1))
    low, high = (float(v) for v in np.percentile(p, (.3, 99.7)))
    median = float(np.median(p))
    suggestions = dict(exposure=ev)
    shadows = float((p < .14).mean())
    lights = float((p > .93).mean())
    suggestions['shadows'] = float(np.clip(shadows * 160, 0, 45) * (.5 if median < .2 else 1))
    suggestions['highlights'] = -float(np.clip(lights * 450, 0, 55))
    suggestions['blacks'] = -float(np.clip((low - .025) * 380, 0, 35)) if low > .03 else 0.
    suggestions['whites'] = float(np.clip((.955 - high) * 260, 0, 35)) if high < .94 else 0.
    spread = float(np.std(p))
    suggestions['contrast'] = float(np.clip((.215 - spread) * 220, -20, 25))

    lab = to_oklab(np.clip(balanced * 2 ** ev, 0, 1))
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    mid = (lab[..., 0] > .25) & (lab[..., 0] < .9)
    mean_chroma = float(chroma[mid].mean()) if mid.any() else 0.
    if mean_chroma < .012:
        suggestions['vibrance'] = 0.
        notes.append('Монохромный снимок')
    else:
        suggestions['vibrance'] = float(np.clip((.075 - mean_chroma) * 520, -10, 32))

    # Haze: bright dark channel over most of the frame with compressed tonal range.
    dark = np.clip(balanced * 2 ** ev, 0, 1).min(axis=2)
    haze = float(np.median(dark))
    suggestions['dehaze'] = float(np.clip((haze - .2) * 140, 0, 30)) if spread < .2 else 0.
    if suggestions['dehaze'] >= 5:
        notes.append('Убрать дымку')

    sigma = estimate_noise(full) if full is not None else 0.
    if sigma > 1.6:
        notes.append('Шум: заметный' if sigma > 3.2 else 'Шум: небольшой')
    return {
        'wb_gains': [float(v) for v in wb], 'suggestions': {k: round(v, 3) for k, v in suggestions.items()},
        'noise_sigma': round(sigma, 3), 'faces': [list(map(float, f)) for f in faces],
        'saliency': saliency_map(enc), 'notes': notes, 'mean_chroma': mean_chroma,
    }


def auto_values(analysis, adjust, out_scale=1.0):
    """Translate an analysis + Adjust auto switches into slider offsets and WB gains."""
    if not adjust.auto or not analysis:
        return {}, np.ones(3, np.float32)
    k = adjust.auto_strength / 100
    s = analysis['suggestions']
    offsets = {}
    if adjust.auto_light:
        for key in ('exposure', 'shadows', 'highlights', 'blacks', 'whites', 'contrast', 'dehaze'):
            offsets[key] = s.get(key, 0) * k
    if adjust.auto_color:
        offsets['vibrance'] = s.get('vibrance', 0) * k
    if adjust.auto_noise:
        # Downsampling averages noise away: sigma scales roughly with the resize factor.
        sigma = analysis.get('noise_sigma', 0) * min(1.0, max(out_scale, .05))
        offsets['denoise'] = float(np.clip((sigma - 1.2) * 14, 0, 55)) * k
        offsets['color_denoise'] = float(np.clip((sigma - .8) * 20, 0, 70)) * k
    gains = np.ones(3, np.float32)
    if adjust.auto_wb:
        gains = np.exp(np.log(np.asarray(analysis['wb_gains'], np.float32)) * k).astype(np.float32)
        gains = gains / float(gains @ LUMA)
    return offsets, gains
