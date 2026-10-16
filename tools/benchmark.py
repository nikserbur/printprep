"""Reproducible local throughput benchmark; does not compare with other software."""
import sys
import json
import platform
import tempfile
import time
from dataclasses import replace
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from printprep.engine import Settings, scan, export_batch, SRGB_BYTES
from printprep.enhance import PRESETS

# Standardized deterministic 24 MP fixture, no copyrighted dataset.
w, h = 6000, 4000
image = Image.new('RGB', (w, h))
x = np.linspace(0, 1, w, dtype=np.float32)
for top in range(0, h, 128):
    y = np.arange(top, min(h, top + 128), dtype=np.float32)[:, None] / h
    tile = np.stack(np.broadcast_arrays(.12 + .7 * x[None, :], .08 + .7 * y, .15 + .4 * (1-x[None, :]) + .1 * y), axis=2)
    image.paste(Image.fromarray(np.round(np.clip(tile, 0, 1) * 255).astype(np.uint8)), (0, top))
results = []
with tempfile.TemporaryDirectory(prefix='printprep-benchmark-') as temp:
    folder = Path(temp)
    image.save(folder / '24mp.jpg', quality=95, icc_profile=SRGB_BYTES)
    image.close()
    photos, errors = scan(folder)
    assert not errors
    for name in ['none', 'balanced', 'lowlight']:
        settings = Settings(enhancement_preset=name, **PRESETS[name][1])
        timings = []
        for repeat in range(3):
            start = time.perf_counter()
            out, report = export_batch(folder, photos, settings, {})
            elapsed = time.perf_counter() - start
            assert report['results'][0]['status'] == 'ok'
            with Image.open(report['results'][0]['output']) as im:
                assert im.size == (1772, 1181)
            timings.append(round(elapsed, 3))
        results.append({'preset': name, 'seconds': timings, 'median_seconds': float(np.median(timings))})
report = {'python': platform.python_version(), 'platform': platform.platform(),
          'input': [w, h], 'output': [1772, 1181], 'repeats': 3,
          'scope': 'local JPEG decode + ICC + downsample + correction + JPEG encode + reports; warm OS cache; synthetic fixture; no Photoshop comparison',
          'results': results}
print(json.dumps(report, ensure_ascii=False, indent=2))
