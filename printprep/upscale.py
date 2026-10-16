"""Optional, offline pretrained FSRCNN ×2 via OpenCV DNN on overlapping tiles."""
from __future__ import annotations
import hashlib
import os
import threading
from pathlib import Path
import numpy as np
from PIL import Image

MODEL = Path(__file__).resolve().parents[1] / 'assets' / 'models' / 'FSRCNN_x2.pb'
# Set from the upstream asset retained in this repository; never download at runtime.
MODEL_SHA256 = '366b33f0084c7b3f2bf6724f0a2c77bca94fcec9d7b6d72389d330073b380d5c'
_STATE = threading.local()


def _network():
    if not hasattr(_STATE, 'network'):
        import cv2
        if hashlib.sha256(MODEL.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError('Контрольная сумма FSRCNN не совпала. Восстановите модель из проекта.')
        cv2.setNumThreads(min(4, os.cpu_count() or 1))
        network = cv2.dnn_superres.DnnSuperResImpl_create()
        network.readModel(str(MODEL))
        network.setModel('fsrcnn', 2)
        network.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        network.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        _STATE.network = network
    return _STATE.network


def upscale2x(im: Image.Image, strength=.6, tile_size=192, cancel=None):
    import cv2
    if im.width * im.height > 8_000_000:
        raise ValueError('Нейро ×2 ограничено исходным кадром 8 Мп.')
    if not 0 <= strength <= 1:
        raise ValueError('Сила нейроувеличения: от 0 до 1.')
    baseline = im.resize((im.width * 2, im.height * 2), Image.Resampling.LANCZOS)
    if strength == 0:
        return baseline
    network = _network()
    output = Image.new('RGB', baseline.size)
    overlap = 24
    for y in range(0, im.height, tile_size):
        for x in range(0, im.width, tile_size):
            if cancel and cancel.is_set():
                raise InterruptedError('Нейроувеличение отменено.')
            right, bottom = min(im.width, x + tile_size), min(im.height, y + tile_size)
            left, top = max(0, x - overlap), max(0, y - overlap)
            r, b = min(im.width, right + overlap), min(im.height, bottom + overlap)
            rgb = np.asarray(im.crop((left, top, r, b)))
            # Very small fixtures need at least a few convolution samples.
            pad_y, pad_x = max(0, 16 - rgb.shape[0]), max(0, 16 - rgb.shape[1])
            if pad_y or pad_x:
                rgb = np.pad(rgb, ((0, pad_y), (0, pad_x), (0, 0)), mode='edge')
            result = network.upsample(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            result = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
            crop = result[(y - top) * 2:(bottom - top) * 2, (x - left) * 2:(right - left) * 2]
            output.paste(Image.fromarray(crop), (x * 2, y * 2))
    return Image.blend(baseline, output, strength)


def release_network():
    """Release the calling thread's cached DNN before GUI/runtime teardown."""
    _STATE.__dict__.clear()
