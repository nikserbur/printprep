"""Bundled offline networks run by OpenCV DNN on the CPU. Nothing is downloaded at runtime.

* Real-ESRGAN general x4v3 (BSD-3) — the single enhancement network: enlargement with
  detail restoration and JPEG/noise cleanup. Its official weak-denoise twin (wdn-x4v3)
  is interpolated in for the 'details ↔ cleanliness' control, so texture is not smeared.
* YuNet 2023mar (MIT) — face detection for framing and face-aware exposure; falls back
  to the Haar cascade shipped with OpenCV.

Enhancement is computed once per photo and orientation and cached, so colour changes
never re-run the network.
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
from .i18n import tr

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
MODELS = ROOT / 'assets' / 'models'
SR_FILE = 'realesr-general-x4v3.onnx'
WDN_FILE = 'realesr-general-wdn-x4v3.npz'
FACE_FILE = 'face_detection_yunet_2023mar.onnx'
CHECKSUMS = {
    SR_FILE: '924ebad6532777303582d4ce7811849b88869231a3ae7093e0f21200249df8d5',
    FACE_FILE: '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
    WDN_FILE: '2786aa84e30e0b75b85bca3fc1f7ea7a70420033469ad60440bd109b4608c534',
}
FACTOR = 4
TILE = 192
OVERLAP = 24
PROXY_EDGE = 2560
_local = threading.local()
_verified = {}
_verify_lock = threading.Lock()
_speed = {'s_per_mp': None}


class Cancelled(Exception):
    pass


def _model_path(name):
    path = MODELS / name
    with _verify_lock:
        if name not in _verified:
            if not path.exists():
                raise FileNotFoundError(tr('Нет файла модели {name}. Переустановите Print Prep.', name=name))
            if hashlib.sha256(path.read_bytes()).hexdigest() != CHECKSUMS[name]:
                raise ValueError(tr('Контрольная сумма модели {name} не совпала. Переустановите Print Prep.', name=name))
            _verified[name] = path
    return _verified[name]


def available():
    try:
        _model_path(SR_FILE)
        return True
    except Exception:
        return False


def denoise_level(detail):
    """'Детали ↔ Чистота' slider (0 = cleanest, 100 = keep all texture) → Real-ESRGAN denoise
    strength, quantised so nearby slider values share a cached network and result."""
    return round((1 - min(100., max(0., detail)) / 100) * 20) / 20


def _net(level=1.0):
    """OpenCV network for a denoise strength. Like `--denoise_strength` in Real-ESRGAN, the
    weights are interpolated between realesr-general-x4v3 (1.0: strong cleanup) and
    realesr-general-wdn-x4v3 (0.0: keeps grain and fine texture)."""
    nets = _local.__dict__.setdefault('sr', {})
    net = nets.get(level)
    if net is None:
        import cv2
        from .onnx_weights import patch, read_initializers
        cv2.setNumThreads(max(1, os.cpu_count() or 2))
        data = _model_path(SR_FILE).read_bytes()
        if level < 1:
            wdn = np.load(_model_path(WDN_FILE))
            base = dict(read_initializers(data))
            data = patch(data, {k: level * base[k] + (1 - level) * wdn[k] for k in wdn.files})
        net = cv2.dnn.readNetFromONNX(np.frombuffer(data, np.uint8))
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        nets.clear()                     # one network per thread is enough; keep memory flat
        nets[level] = net
    return net


def estimate_seconds(width, height):
    """Expected run time on this PC (measured on the first tiles; rough before that)."""
    rate = _speed['s_per_mp'] or 10 * 8 / max(1, os.cpu_count() or 1) ** .5
    return width * height / 1e6 * rate


def upscale(image, progress=None, cancel=None, store_factor=FACTOR, level=1.0):
    """×4 super-resolution of an sRGB-encoded float image in overlapping tiles.

    With store_factor=2 each ×4 tile is box-averaged to ×2 before it is stored, which
    keeps memory at a quarter for larger sources. `progress(fraction, eta_seconds)` is
    called per tile; `cancel()` returning True raises Cancelled.
    """
    import cv2
    net = _net(level)
    h, w = image.shape[:2]
    k = store_factor
    out = np.empty((h * k, w * k, 3), dtype=np.float32)
    ys, xs = list(range(0, h, TILE)), list(range(0, w, TILE))
    total, done = len(ys) * len(xs), 0
    started = time.perf_counter()
    for y in ys:
        for x in xs:
            if cancel and cancel():
                raise Cancelled()
            bottom, right = min(h, y + TILE), min(w, x + TILE)
            top, left = max(0, y - OVERLAP), max(0, x - OVERLAP)
            b2, r2 = min(h, bottom + OVERLAP), min(w, right + OVERLAP)
            piece = image[top:b2, left:r2]
            ph, pw = piece.shape[:2]
            if ph < 16 or pw < 16:
                piece = np.pad(piece, ((0, max(0, 16 - ph)), (0, max(0, 16 - pw)), (0, 0)), mode='edge')
            net.setInput(np.ascontiguousarray(np.clip(piece, 0, 1).transpose(2, 0, 1)[None], dtype=np.float32))
            result = net.forward()[0].transpose(1, 2, 0)
            oy, ox = (y - top) * FACTOR, (x - left) * FACTOR
            tile = result[oy:oy + (bottom - y) * FACTOR, ox:ox + (right - x) * FACTOR]
            if k != FACTOR:
                tile = cv2.resize(np.ascontiguousarray(tile), ((right - x) * k, (bottom - y) * k), interpolation=cv2.INTER_AREA)
            out[y * k:bottom * k, x * k:right * k] = tile
            done += 1
            elapsed = time.perf_counter() - started
            if done >= 2 or total == 1:
                _speed['s_per_mp'] = elapsed / max(1e-6, (done / total) * h * w / 1e6)
            if progress:
                progress(done / total, elapsed / done * (total - done))
    return np.clip(out, 0, 1)


def enhance(base, strength=1.0, progress=None, cancel=None, level=1.0):
    """Enhance a whole oriented source (uint8/uint16) at a denoise level. Returns a cache entry.

    Small sources keep the full ×4 result; larger ones are stored at ×2 (enough for the
    enlargements that make sense in print, and four times less memory).
    """
    import cv2
    depth = 255 if base.dtype == np.uint8 else 65535
    src = base.astype(np.float32) / depth
    h, w = src.shape[:2]
    factor = FACTOR if h * w <= 1.2e6 else 2
    sr = upscale(src, progress, cancel, store_factor=factor, level=level)
    if strength < 1:
        plain = cv2.resize(src, (w * factor, h * factor), interpolation=cv2.INTER_LANCZOS4)
        sr = np.clip(plain + (sr - plain) * strength, 0, 1)
    full = np.round(sr * 65535).astype(np.uint16)
    k = min(1, PROXY_EDGE / max(full.shape[:2]))
    proxy = cv2.resize(full, (max(1, round(full.shape[1] * k)), max(1, round(full.shape[0] * k))),
                       interpolation=cv2.INTER_AREA) if k < 1 else full
    return {'full': full, 'proxy': proxy, 'factor': factor}


class EnhanceCache:
    """Process-wide LRU of enhanced sources with a memory budget, shared by preview and export."""

    def __init__(self, budget=450 << 20):
        self.budget = budget
        self.items = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            value = self.items.get(key)
            if value is not None:
                self.items.move_to_end(key)
            return value

    def put(self, key, value):
        size = value['full'].nbytes + value['proxy'].nbytes
        with self.lock:
            self.items[key] = value
            self.items.move_to_end(key)
            total = sum(v['full'].nbytes + v['proxy'].nbytes for v in self.items.values())
            while total > self.budget and len(self.items) > 1:
                _, old = self.items.popitem(last=False)
                total -= old['full'].nbytes + old['proxy'].nbytes

    def clear(self):
        with self.lock:
            self.items.clear()


CACHE = EnhanceCache()


# ---------------------------------------------------------------- faces
def detect_faces(rgb_u8):
    """Faces as [(x, y, w, h, score)] normalised to the image, most prominent first."""
    import cv2
    h, w = rgb_u8.shape[:2]
    bgr = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
    faces = []
    try:
        detector = _local.__dict__.get('yunet')
        if detector is None:
            detector = cv2.FaceDetectorYN.create(str(_model_path(FACE_FILE)), '', (w, h), .75, .3, 50)
            _local.yunet = detector
        detector.setInputSize((w, h))
        _, found = detector.detect(bgr)
        if found is not None:
            for row in found:
                x, y, fw, fh = (float(v) for v in row[:4])
                faces.append((x / w, y / h, fw / w, fh / h, float(row[-1])))
    except Exception:
        cascade = _local.__dict__.get('haar')
        if cascade is None:
            cascade = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml'))
            _local.haar = cascade
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        for (x, y, fw, fh) in cascade.detectMultiScale(gray, 1.1, 6, minSize=(max(16, w // 40),) * 2):
            faces.append((x / w, y / h, fw / w, fh / h, .6))
    faces = [f for f in faces if f[2] > .012 and f[3] > .012]
    faces.sort(key=lambda f: -f[4] * f[2] * f[3])
    return faces[:12]


def release():
    """Drop this thread's cached networks (called before interpreter teardown)."""
    _local.__dict__.clear()
