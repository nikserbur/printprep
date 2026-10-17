"""Per-photo smart analysis: what an experienced operator would correct first.

Runs on the deterministic analysis proxy (the same in preview and export), so the
automatic corrections shown on screen are exactly what gets written. Results are
suggestions in slider units; Adjust.auto_strength scales them.

White balance votes in log-chroma space (near-neutral surfaces cluster at the
illuminant), weighting textured surfaces above smooth sky or backdrops. A cast shifts
shadows and highlights alike, while warm scene light (sunset, lamps) leaves shadows
neutral: only the first is corrected almost fully. Detected skin must stay in the
natural hue range and must not turn grey. Black/white points follow the Lightroom
habit of letting about 0.1 % of pixels clip, at full strength only when both ends of
the histogram are empty; shadows are lifted only where they hold detail; strong veils go to the
dark-channel dehaze. Exposure aims the log-average at middle grey, also lifts frames
whose highlights stop far short of white, takes faces as a second opinion and never
darkens bright scenes unless highlights really clip. Measured with tools/eval_auto.py.
"""
from __future__ import annotations

import math

import numpy as np

from .color import LUMA, decode, encode, to_oklab
from .i18n import tr

ANALYSIS_EDGE = 768
VEIL_GAIN = 450


def _proxy_float(proxy):
    import cv2
    h, w = proxy.shape[:2]
    k = min(1, ANALYSIS_EDGE / max(h, w))
    small = cv2.resize(proxy, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else proxy
    depth = 255 if small.dtype == np.uint8 else 65535
    return small.astype(np.float32) / depth


def _angle(a, b):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    cos = float(a @ b / max(1e-12, np.linalg.norm(a) * np.linalg.norm(b)))
    return math.degrees(math.acos(min(1., max(-1., cos))))


def _minkowski(values, p=6):
    v = np.maximum(values.astype(np.float64), 0)
    return np.power(np.mean(np.power(v, p), axis=0), 1 / p)


def illuminant_estimates(lin):
    """Named illuminant estimates (unit-sum RGB) from several classical colour-constancy methods."""
    import cv2
    top = lin.max(axis=2)
    y = lin @ LUMA
    valid = (top < .96) & (y > .006)
    if valid.sum() < 400:
        return {}
    est = {'shades_of_gray': _minkowski(lin[valid])}
    smooth = cv2.GaussianBlur(lin, (0, 0), 2)
    est['general_gray_world'] = _minkowski(smooth[valid])
    g = cv2.GaussianBlur(lin, (0, 0), 1)
    mag = np.sqrt(cv2.Sobel(g, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(g, cv2.CV_32F, 0, 1) ** 2)
    edge_valid = cv2.erode(valid.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    edge_valid &= mag.max(axis=2) > 1e-3
    if edge_valid.sum() > 200:
        est['gray_edge'] = _minkowski(mag[edge_valid])
    low = lin.min(axis=2)
    sat = (top - low) / np.maximum(top, 1e-3)
    neutral = valid & (sat < .25) & (y > .03) & (y < .85)
    if neutral.sum() > 200 and neutral.mean() > .01:
        est['gray_pixels'] = np.exp(np.median(np.log(np.maximum(lin[neutral], 1e-4)), axis=0))
    bright = valid & (y >= np.percentile(y[valid], 97))
    if bright.sum() > 50:
        patch = lin[bright].mean(axis=0)
        if (patch.max() - patch.min()) / max(patch.max(), 1e-6) < .35:   # only near-white highlights count
            est['white_patch'] = patch
    return {k: v / v.sum() for k, v in est.items() if np.all(v > 0)}


def grey_pixels(lin):
    """Illuminant from grey pixels (Yang, Gao, Li, CVPR 2015).

    Achromatic surfaces have identical local contrast in the log of every channel under
    any illuminant colour, while coloured content (sky, foliage, skin) does not. So the
    estimate is not pulled by dominant scene colours the way Gray-World methods are.
    Returns (unit-sum illuminant, mean grey index of the selected pixels) or (None, 1).
    """
    import cv2
    eps = 1e-3
    y = lin @ LUMA
    valid = (lin.max(axis=2) < .95) & (y > .01)
    logs = np.log(np.maximum(cv2.GaussianBlur(lin, (0, 0), 1.0), 0) + eps)
    contrast = np.abs(cv2.Laplacian(logs, cv2.CV_32F, ksize=3))
    mean = contrast.mean(axis=2)
    gi = contrast.std(axis=2) / np.maximum(mean, 1e-6)
    gi = cv2.blur(gi.astype(np.float32), (7, 7))
    candidates = valid & (mean > .02)
    if candidates.sum() < 300:
        return None, 1.
    values = gi[candidates]
    count = max(200, int(values.size * .01))
    threshold = np.partition(values, count - 1)[count - 1]
    pick = candidates & (gi <= threshold)
    illum = lin[pick].mean(axis=0)
    if np.any(illum <= 0):
        return None, 1.
    return illum / illum.sum(), float(gi[pick].mean())


CHROMA_RANGE = .8
CHROMA_BINS = 80


def texture_weight(lin):
    """0.35..1 per pixel: textured surfaces vote more than smooth sky or studio backdrops,
    whose colour is usually the subject's choice rather than the light's."""
    import cv2
    g = cv2.GaussianBlur(np.log(np.maximum(lin @ LUMA, 1e-3)).astype(np.float32), (0, 0), 1.2)
    mag = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    mag = cv2.blur(mag, (9, 9))
    return .35 + .65 * np.clip(mag / .25, 0, 1)


def chroma_vote(lin, region=None, texture=None):
    """Illuminant by voting in log-chroma space (fixed-filter Convolutional Color Constancy).

    A white-balance error shifts every pixel by the same (log R/G, log B/G) vector, so the
    near-neutral surfaces of a scene form a dense cluster around the illuminant point. The
    histogram is smoothed, weighted by a prior that prefers casts along the warm–cool
    (daylight) axis, and searched near the origin. `region` limits the voters (a tonal
    band). Returns (u, v, confidence) or None.
    """
    import cv2
    y = lin @ LUMA
    valid = (lin.max(axis=2) < .95) & (y > .03) & (lin.min(axis=2) > 2e-3)
    if region is not None:
        valid &= region
    if valid.sum() < 500:
        return None
    px = lin[valid].astype(np.float64)
    u = np.log(px[:, 0] / px[:, 1])
    v = np.log(px[:, 2] / px[:, 1])
    # Mid-tones vote most: deep shadows carry noisy, often tinted chroma.
    weight = np.clip((y[valid] - .03) / .2, 0, 1)
    if texture is not None:
        weight = weight * texture[valid]
    hist, _, _ = np.histogram2d(u, v, bins=CHROMA_BINS, range=[[-CHROMA_RANGE, CHROMA_RANGE]] * 2, weights=weight)
    density = cv2.GaussianBlur(hist.astype(np.float32), (0, 0), 1.5)
    step = 2 * CHROMA_RANGE / CHROMA_BINS
    centres = -CHROMA_RANGE + step * (np.arange(CHROMA_BINS) + .5)
    uu, vv = np.meshgrid(centres, centres, indexing='ij')
    warm_cool = (uu - vv) / math.sqrt(2)        # along the daylight locus
    green_magenta = (uu + vv) / math.sqrt(2)
    prior = np.exp(-(warm_cool / .28) ** 2 / 2 - (green_magenta / .12) ** 2 / 2)
    prior[np.hypot(uu, vv) > .45] = 0
    score = density * prior
    i, j = np.unravel_index(int(np.argmax(score)), score.shape)
    origin = density[CHROMA_BINS // 2 - 1:CHROMA_BINS // 2 + 1, CHROMA_BINS // 2 - 1:CHROMA_BINS // 2 + 1].mean()
    peak = density[i, j]
    total = float(hist.sum())
    if peak < .002 * total:
        return None                             # no real near-neutral cluster: colourful scene, leave it
    confidence = float(np.clip((peak / max(origin, 1e-6) - 1.3) / 2.5, 0, 1))
    return float(uu[i, j]), float(vv[i, j]), confidence


def white_balance(lin):
    """Channel gains (luminance-preserving), confidence 0..1 and a short note."""
    texture = texture_weight(lin)
    vote = chroma_vote(lin, texture=texture)
    if vote is None:
        return np.ones(3, np.float32), 0., ''
    u, v, confidence = vote
    consensus = np.array([math.exp(u), 1., math.exp(v)])
    consensus /= consensus.sum()
    cast = _angle(consensus, np.ones(3))
    if cast < 2 or confidence <= 0:
        return np.ones(3, np.float32), confidence, ''
    l0 = -np.log(consensus)
    l0 -= l0.mean()
    temp = (l0[0] - l0[2]) / 2                  # > 0: light was bluish, warm it up
    tint = l0[1] - (l0[0] + l0[2]) / 2          # > 0: light was magenta, add green
    # A cast (wrong camera WB) shifts shadows and highlights alike. Warm scene light — sunset,
    # tungsten lamps — warms the lit parts while shadows stay neutral or bluish from the sky.
    y = lin @ LUMA
    lit = chroma_vote(lin, y > np.percentile(y, 60), texture)
    shade = chroma_vote(lin, y < np.percentile(y, 40), texture)
    global_cast = lit is not None and shade is not None and math.hypot(lit[0] - shade[0], lit[1] - shade[1]) < .07
    if global_cast:
        keep_mood = .9
    else:
        keep_mood = .5 if temp < -.25 else .7   # cool warm scenes only partly: sunsets, candles, interiors
    temp *= (keep_mood if temp < 0 else .9) * confidence
    tint *= .9 * confidence
    temp, tint = float(np.clip(temp, -.3, .3)), float(np.clip(tint, -.15, .15))
    l = np.array([temp - tint / 3, 2 * tint / 3, -temp - tint / 3])
    gains = np.exp(l)
    gains /= float(gains @ LUMA)
    note = ''
    if abs(temp) > .02 or abs(tint) > .02:
        note = tr('ББ: теплее') if temp > .02 else tr('ББ: холоднее') if temp < -.02 else tr('ББ: убран оттенок')
    return gains.astype(np.float32), confidence, note


SKIN_HUE = (25., 95.)     # Oklab hue of natural skin of any tone under neutral light, degrees
SKIN_CHROMA = .015        # natural skin is never greyer: half the Oklab chroma of very pale skin (≈ .03)
GREY_SKIN_MISS = 30.      # a face drained to grey is as wrong as one pushed this far out of the hue range


def skin_tone(lin, faces):
    """Median Oklab (hue in degrees, chroma) of the central face areas, or None without usable faces."""
    if not faces:
        return None
    h, w = lin.shape[:2]
    patches = []
    for fx, fy, fw, fh, _ in faces[:4]:
        x0, y0 = int((fx + fw * .3) * w), int((fy + fh * .35) * h)
        x1, y1 = int((fx + fw * .7) * w), int((fy + fh * .75) * h)
        patch = lin[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)].reshape(-1, 3)
        if len(patch) >= 16:
            patches.append(patch)
    if not patches:
        return None
    lab = to_oklab(np.clip(np.median(np.concatenate(patches), axis=0), 0, 1)[None, None, :].astype(np.float32))[0, 0]
    if lab[0] < .2:
        return None                         # too dark (heavy shadow): no opinion
    return math.degrees(math.atan2(lab[2], lab[1])), math.hypot(lab[1], lab[2])


def skin_hue(lin, faces):
    """Median Oklab hue of the central face areas, or None without usable faces or for grey ones."""
    tone = skin_tone(lin, faces)
    return None if tone is None or tone[1] < .01 else tone[0]


def skin_guard(lin, gains, faces):
    """Skin is a memory colour: people forgive a cast on a wall, not on a face. If the white
    balance would push detected skin out of the natural hue range (green or purple faces) or
    drain it to grey (a pink backdrop read as neutral cools a face that was cool already),
    pull the correction back toward neutral. Returns (gains, acted)."""
    before, after = skin_tone(lin, faces), skin_tone(lin * gains, faces)
    if before is None or after is None:
        return gains, False
    lo, hi = SKIN_HUE

    def miss(tone):
        if tone is None:
            return 0.
        hue, chroma = tone
        off = 0. if lo <= hue <= hi else min((lo - hue) % 360, (hue - hi) % 360)
        grey = max(0., 1 - chroma / SKIN_CHROMA)     # near grey the hue is noise and greyness is the fault
        return (1 - grey) * off + grey * GREY_SKIN_MISS
    limit = miss(before) + 3
    if miss(after) <= limit:
        return gains, False
    for k in (.6, .3):
        g = np.exp(np.log(gains) * k)
        g = (g / float(g @ LUMA)).astype(np.float32)
        if miss(skin_tone(lin * g, faces)) <= limit:
            return g, True
    return np.ones(3, np.float32), True


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
    grad = np.hypot(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))[1:-1, 1:-1]
    flat = grad < np.percentile(grad, 40)
    valid = flat & (gray[1:-1, 1:-1] > 12) & (gray[1:-1, 1:-1] < 243)
    if valid.sum() < 500:
        valid = flat
    if valid.sum() < 100:
        return 0.
    return float(math.sqrt(math.pi / 2) * response[valid].mean() / 6)


def shadow_detail(tone, mask):
    """0..1: how much real texture the deep shadows carry (local contrast above the noise floor)."""
    import cv2
    if mask.mean() < .02:
        return 0.
    t = tone.astype(np.float32)
    mean = cv2.blur(t, (5, 5))
    std = np.sqrt(np.maximum(cv2.blur(t * t, (5, 5)) - mean * mean, 0))
    level = float(np.median(std[mask]))
    return float(np.clip((level - .006) / .014, 0, 1))


def saliency_map(enc):
    """Spectral-residual saliency (Hou & Zhang 2007) blended with edge energy, ~128 px."""
    import cv2
    gray = cv2.cvtColor(np.ascontiguousarray(np.clip(enc, 0, 1), np.float32), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    k = 128 / max(h, w)
    small = cv2.resize(gray, (max(8, round(w * k)), max(8, round(h * k))), interpolation=cv2.INTER_AREA)
    spectrum = np.fft.fft2(small)
    log_amp = np.log(np.abs(spectrum) + 1e-6)
    residual = log_amp - cv2.blur(log_amp.astype(np.float32), (3, 3))
    sal = np.abs(np.fft.ifft2(np.exp(residual + 1j * np.angle(spectrum)))) ** 2
    sal = cv2.GaussianBlur(sal.astype(np.float32), (0, 0), 2.5)
    edges = np.hypot(cv2.Sobel(small, cv2.CV_32F, 1, 0), cv2.Sobel(small, cv2.CV_32F, 0, 1))
    edges[:2] = edges[-2:] = 0
    edges[:, :2] = edges[:, -2:] = 0
    combined = .5 * sal / max(1e-6, float(sal.max())) + .5 * edges / max(1e-6, float(edges.max()))
    return cv2.GaussianBlur(combined, (0, 0), 2)


def analyze(proxy, source_long=None):
    """Return a dict of automatic suggestions for this photo (JSON-safe except 'saliency').

    `source_long` is the long edge of the original; noise measured on the proxy is scaled
    back to it (averaging during the reduction lowers noise roughly with the scale).
    """
    from .neural import detect_faces
    enc = _proxy_float(proxy)
    lin = decode(enc)
    notes = []
    try:
        faces = detect_faces(np.round(np.clip(enc, 0, 1) * 255).astype(np.uint8))
    except Exception:
        faces = []
    wb, wb_confidence, wb_note = white_balance(lin)
    wb, guarded = skin_guard(lin, wb, faces)
    if guarded:
        wb_note = tr('ББ: бережно к коже')
    if wb_note:
        notes.append(wb_note)
    balanced = lin * wb
    y = balanced @ LUMA

    # Exposure: log-average key toward middle grey, faces as a second opinion.
    valid = (y > .002) & (y < .97)
    sample = y[valid] if valid.sum() > 100 else y.ravel()
    key = float(np.exp(np.log(np.maximum(sample, 1e-4)).mean()))
    deviation = math.log2(.18 / max(key, 1e-4))
    clipped = float((y > .97).mean())
    # Underexposure shows as a low key *and* highlights that stop well short of white; a dark
    # frame with bright highlights is low-key on purpose and is left alone.
    headroom = max(0., math.log2(.92 / max(float(np.percentile(y, 99.9)), 1e-4)))
    if deviation > -.3:
        key_ev = min(deviation - .35, headroom, 1.5) if deviation > .45 else 0.
        # A frame of normal key whose brightest pixels stop far short of white is underexposed
        # too (a bright scene shot dark); bright pastel frames are excluded by their high key.
        head_ev = min(max(0., headroom - .2) * float(np.clip((deviation + .5) / .8, 0, 1)), 1.2)
        ev = max(key_ev, head_ev)
        ev = ev if ev >= .15 else 0.
    else:
        # Darken only a clearly bright frame that really loses highlights; high-key stays high-key.
        ev = max(deviation * .6, -.8) * float(np.clip((clipped - .01) * 12, 0, 1))
    if faces:
        h, w = y.shape
        lums = []
        for fx, fy, fw, fh, _ in faces[:4]:
            x0, y0 = int((fx + fw * .25) * w), int((fy + fh * .3) * h)
            x1, y1 = int((fx + fw * .75) * w), int((fy + fh * .8) * h)
            region = y[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
            if region.size:
                lums.append(float(np.median(region)))
        if lums:
            yf = float(np.median(lums))
            target = min(.42, max(.16, yf))      # respect any natural skin tone inside a broad range
            ev = .45 * ev + .55 * float(np.clip(math.log2(target / max(yf, 1e-4)), -.6, 1.0))
            notes.append(tr('Лица: {n}', n=len(faces)))
    ev = float(np.clip(ev, -1.2, 1.5))
    if abs(ev) >= .1:
        notes.append(tr('Экспозиция {ev:+.1f} EV', ev=ev).replace('-', '−'))

    p = encode(np.minimum(y * 2 ** ev, 1))
    low, high = (float(v) for v in np.percentile(p, (.1, 99.9)))
    median = float(np.median(p))
    s = {'exposure': ev}
    # Auto levels (as Photoshop's luminance auto-contrast): stretch so that ~0.1 % of pixels reach
    # black and white, only when the histogram clearly stops short — a flat, hazy or faded frame.
    # A histogram short at both ends is a flat, faded or hazy frame. Short at one end only is far
    # more often a choice — pastel high-key, a matte look, a moody low-key — so it gets a nudge.
    black_gap, white_gap = low > .05, high < .92
    both = 1. if black_gap and white_gap else .35
    level_black = min(.12, (low - .01) * .8) * both if black_gap else 0.
    level_white = 1 - min(.12, (1 - high - .015) * .8) * both if white_gap else 1.
    s['level_black'], s['level_white'] = level_black, level_white
    stretched = np.clip((p - level_black) / max(.3, level_white - level_black), 0, 1)
    spread = float(np.std(stretched))
    s['contrast'] = float(np.clip((.17 - spread) * 220, 0, 20)) * both
    # Lift shadows only where they hold detail: a flat black backdrop or night sky stays black.
    deep_mask = stretched < .12
    deep = float((stretched < .06).mean())
    texture = shadow_detail(stretched, deep_mask)
    s['shadows'] = float(np.clip((deep - .2) * 120, 0, 35)) * texture if median < .3 else 0.
    s['highlights'] = -float(np.clip((float((stretched > .97).mean()) - .02) * 500, 0, 45))

    lab = to_oklab(np.clip(balanced * 2 ** ev, 0, 1))
    chroma = np.hypot(lab[..., 1], lab[..., 2])
    mid = (lab[..., 0] > .25) & (lab[..., 0] < .9)
    mean_chroma = float(chroma[mid].mean()) if mid.any() else 0.
    if mean_chroma < .012:
        s['vibrance'] = 0.
        notes.append(tr('Монохромный снимок'))
    else:
        s['vibrance'] = float(np.clip((.04 - mean_chroma) * 500, 0, 15))

    # Nothing darker than a third of the scale is a veil — fog, glare through glass, a faded print
    # scan — not a style. A luminance curve cannot bring its colour back, so the dark-channel
    # dehaze removes it per channel; milder lifted blacks are left to auto levels.
    # A veil also washes colour out; a bright, saturated graphic without darks is not hazy.
    lit = np.clip(balanced * 2 ** ev, 0, 1)
    dark_channel = lit.min(axis=2)
    veil = float(np.percentile(dark_channel, 5))
    saturation = float(np.median((lit.max(axis=2) - dark_channel) / np.maximum(lit.max(axis=2), 1e-3)))
    s['dehaze'] = float(np.clip((veil - .05) * VEIL_GAIN, 0, 60) * np.clip((low - .25) / .1, 0, 1)
                        * np.clip((.6 - saturation) / .25, 0, 1))
    if s['dehaze'] >= 5:
        notes.append(tr('Убрана дымка'))

    ratio = max(proxy.shape[:2]) / max(1, source_long or max(proxy.shape[:2]))
    sigma = estimate_noise(proxy) / max(ratio, .05) ** .8
    if sigma > 1.6:
        notes.append(tr('Шум: заметный') if sigma > 3.2 else tr('Шум: небольшой'))
    return {
        'wb_gains': [float(v) for v in wb], 'wb_confidence': wb_confidence,
        'suggestions': {k: round(v, 3) for k, v in s.items()},
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
        for key in ('exposure', 'shadows', 'highlights', 'contrast', 'dehaze'):
            offsets[key] = s.get(key, 0) * k
        lb, lw = s.get('level_black', 0.), s.get('level_white', 1.)
        if lb > 0 or lw < 1:
            offsets['levels'] = (lb * k, 1 - (1 - lw) * k)
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
