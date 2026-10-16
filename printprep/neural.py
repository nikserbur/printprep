"""Bundled offline networks run by OpenCV DNN on CPU. Nothing is downloaded at runtime.

* FSRCNN ×2 (Apache-2.0) — tiny, fast enlargement.
* Real-ESRGAN general x4v3 (BSD-3) — enlargement with detail restoration and
  JPEG/noise cleanup; noticeably heavier.
* YuNet 2023mar (MIT) — face detection for framing and skin-aware colour; falls
  back to the Haar cascade shipped with OpenCV.
"""
from __future__ import annotations

import hashlib
import os
import sys
import threading
from pathlib import Path

import numpy as np

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
MODELS = ROOT / 'assets' / 'models'
CHECKSUMS = {
    'FSRCNN_x2.pb': '366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c',
    'realesr-general-x4v3.onnx': '924ebad6532777303582d4ce7811849b88869231a3ae7093e0f21200249df8d5',
    'face_detection_yunet_2023mar.onnx': '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
}
UPSCALERS = {
    'fsrcnn': dict(title='FSRCNN ×2 · быстро', factor=2, limit_mp=12, file='FSRCNN_x2.pb', tile=256, overlap=16),
    'esrgan': dict(title='Real-ESRGAN ×4 · качество', factor=4, limit_mp=6, file='realesr-general-x4v3.onnx', tile=224, overlap=20),
}
_local = threading.local()
_verified = {}
_verify_lock = threading.Lock()


class Cancelled(Exception):
    pass


def _model_path(name):
    path = MODELS / name
    with _verify_lock:
        if name not in _verified:
            if not path.exists():
                raise FileNotFoundError(f'Нет файла модели {name}. Переустановите Print Prep.')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != CHECKSUMS[name]:
                raise ValueError(f'Контрольная сумма модели {name} не совпала. Переустановите Print Prep.')
            _verified[name] = path
    return _verified[name]


def available(kind):
    try:
        _model_path(UPSCALERS[kind]['file'] if kind in UPSCALERS else kind)
        return True
    except Exception:
        return False


def _threads():
    import cv2
    cv2.setNumThreads(max(1, (os.cpu_count() or 2) - 1))


def _net(kind):
    nets = _local.__dict__.setdefault('nets', {})
    if kind not in nets:
        import cv2
        _threads()
        spec = UPSCALERS[kind]
        path = str(_model_path(spec['file']))
        if kind == 'fsrcnn':
            net = cv2.dnn_superres.DnnSuperResImpl_create()
            net.readModel(path)
            net.setModel('fsrcnn', 2)
        else:
            net = cv2.dnn.readNetFromONNX(path)
        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        nets[kind] = net
    return nets[kind]


def _infer(kind, tile):
    """tile: float32 HxWx3 sRGB-encoded in [0, 1] -> float32 (H*f)x(W*f)x3."""
    net = _net(kind)
    if kind == 'fsrcnn':
        import cv2
        u8 = np.round(np.clip(tile, 0, 1) * 255).astype(np.uint8)
        out = net.upsample(cv2.cvtColor(u8, cv2.COLOR_RGB2BGR))
        return cv2.cvtColor(out, cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    blob = np.ascontiguousarray(np.clip(tile, 0, 1).transpose(2, 0, 1)[None], dtype=np.float32)
    net.setInput(blob)
    return np.ascontiguousarray(net.forward()[0].transpose(1, 2, 0), dtype=np.float32)


def upscale(image, kind, progress=None, cancel=None):
    """Tile-wise super-resolution of an sRGB-encoded float image with overlap blending.

    `progress(fraction)` is called after each tile; `cancel()` returning True aborts.
    """
    spec = UPSCALERS[kind]
    factor, tile, overlap = spec['factor'], spec['tile'], spec['overlap']
    h, w = image.shape[:2]
    if h * w > spec['limit_mp'] * 1e6:
        raise ValueError(f'{spec["title"]}: кадр больше {spec["limit_mp"]} Мп.')
    out = np.empty((h * factor, w * factor, 3), dtype=np.float32)
    ys = list(range(0, h, tile))
    xs = list(range(0, w, tile))
    total = len(ys) * len(xs)
    done = 0
    for y in ys:
        for x in xs:
            if cancel and cancel():
                raise Cancelled()
            bottom, right = min(h, y + tile), min(w, x + tile)
            top, left = max(0, y - overlap), max(0, x - overlap)
            b2, r2 = min(h, bottom + overlap), min(w, right + overlap)
            piece = image[top:b2, left:r2]
            ph, pw = piece.shape[:2]
            pad_y, pad_x = max(0, 16 - ph), max(0, 16 - pw)
            if pad_y or pad_x:
                piece = np.pad(piece, ((0, pad_y), (0, pad_x), (0, 0)), mode='edge')
            result = _infer(kind, piece)
            oy, ox = (y - top) * factor, (x - left) * factor
            out[y * factor:bottom * factor, x * factor:right * factor] = \
                result[oy:oy + (bottom - y) * factor, ox:ox + (right - x) * factor]
            done += 1
            if progress:
                progress(done / total)
    return np.clip(out, 0, 1)


# ---------------------------------------------------------------- faces
def detect_faces(rgb_u8):
    """Faces as [(x, y, w, h, score)] normalised to the image, most confident first."""
    import cv2
    h, w = rgb_u8.shape[:2]
    bgr = cv2.cvtColor(rgb_u8, cv2.COLOR_RGB2BGR)
    faces = []
    try:
        detector = _local.__dict__.get('yunet')
        if detector is None:
            _threads()
            detector = cv2.FaceDetectorYN.create(str(_model_path('face_detection_yunet_2023mar.onnx')), '', (w, h), .75, .3, 50)
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
