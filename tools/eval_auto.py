"""Objective check of the automatic correction on well-processed reference photos.

Each reference is degraded with known faults (colour casts, wrong exposure, flat
contrast, haze); the auto correction is applied at 100 % and the colour difference to
the reference is measured (mean ΔE in Oklab ×100, ≈ ΔE00 scale). A good auto shrinks
the error a lot and barely touches the references themselves ("do no harm").

Usage: python tools/eval_auto.py [--only=wb,light,color] <folder with good JPEGs> [more folders...]
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from PIL import Image

from printprep.color import decode, encode
from printprep.imageio import inspect
from printprep.model import Adjust, Edit, Settings
from printprep.pipeline import Source, render

DEGRADATIONS = {
    'тёплый оттенок': lambda lin: lin * np.array([1.18, 1.0, .78], np.float32),
    'холодный оттенок': lambda lin: lin * np.array([.84, 1.0, 1.22], np.float32),
    'зелёный оттенок': lambda lin: lin * np.array([.92, 1.08, .9], np.float32),
    'недодержка −1 EV': lambda lin: lin * .5,
    'передержка +0.5 EV': lambda lin: np.minimum(lin * 1.41, 1),
    'плоский контраст': lambda lin: decode(encode(np.clip(lin, 0, 1)) * .7 + .15),
    'дымка': lambda lin: lin * .7 + .12,
    'тёплый + тёмный': lambda lin: lin * np.array([1.15, 1.0, .82], np.float32) * .6,
}


def delta_e(a, b):
    """Mean CIELAB ΔE76 between two sRGB-encoded float images."""
    import cv2
    la = cv2.cvtColor(np.ascontiguousarray(a, np.float32), cv2.COLOR_RGB2Lab)
    lb = cv2.cvtColor(np.ascontiguousarray(b, np.float32), cv2.COLOR_RGB2Lab)
    return float(np.linalg.norm(la - lb, axis=2).mean())


GROUPS = dict(wb=True, light=True, color=True)


def auto_render(path, strength=100):
    src = Source.open(inspect(path))
    s = Settings(adjust=Adjust(auto=True, auto_strength=strength, auto_noise=False, auto_wb=GROUPS['wb'],
                               auto_light=GROUPS['light'], auto_color=GROUPS['color']))
    return render(src, s, Edit()).image


def evaluate(ref, groups=None):
    """Harm on the reference and (ΔE before, ΔE after) for every degradation of it."""
    GROUPS.update(groups or {})
    out = {'name': f'{ref.parent.name}/{ref.name}'}
    with tempfile.TemporaryDirectory() as temp:
        img = Image.open(ref).convert('RGB')
        img.thumbnail((1200, 1200))
        ref_enc = np.asarray(img).astype(np.float32) / 255
        path = Path(temp) / 'ref.png'
        img.save(path)
        out['harm'] = delta_e(auto_render(path), ref_enc)
        for name, fault in DEGRADATIONS.items():
            bad = np.clip(encode(np.clip(fault(decode(ref_enc)), 0, 1)), 0, 1)
            bad_path = Path(temp) / 'bad.png'
            Image.fromarray(np.round(bad * 255).astype(np.uint8)).save(bad_path)
            out[name] = (delta_e(bad, ref_enc), delta_e(auto_render(bad_path), ref_enc))
    return out


def main(folders):
    from concurrent.futures import ProcessPoolExecutor
    refs = [p for f in folders for p in sorted(Path(f).glob('*.jpg'))]
    if not refs:
        raise SystemExit('Нет JPEG-эталонов')
    with ProcessPoolExecutor(min(8, len(refs))) as pool:
        rows = list(pool.map(evaluate, refs, [dict(GROUPS)] * len(refs)))
    print(f'Эталонов: {len(refs)}')
    print(f'{"Дефект":24s} {"ΔE до":>8s} {"ΔE после":>9s} {"улучшение":>10s}')
    total_before = total_after = 0
    for name in DEGRADATIONS:
        before = np.mean([r[name][0] for r in rows])
        after = np.mean([r[name][1] for r in rows])
        total_before += before
        total_after += after
        print(f'{name:24s} {before:8.2f} {after:9.2f} {100 * (1 - after / before):9.0f}%')
    print(f'{"ИТОГО":24s} {total_before / len(DEGRADATIONS):8.2f} {total_after / len(DEGRADATIONS):9.2f} '
          f'{100 * (1 - total_after / total_before):9.0f}%')
    harm = [r['harm'] for r in rows]
    print(f'Изменение хороших снимков (ΔE, меньше — лучше): {np.mean(harm):.2f} (макс {np.max(harm):.2f})')


if __name__ == '__main__':
    args = sys.argv[1:]
    if args and args[0].startswith('--only='):
        keep = args.pop(0).split('=', 1)[1].split(',')
        GROUPS.update({k: k in keep for k in GROUPS})
    main(args)
