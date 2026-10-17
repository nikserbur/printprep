"""Convert Real-ESRGAN realesr-general-wdn-x4v3.pth into assets/models/realesr-general-wdn-x4v3.npz.

The .pth is read without PyTorch through a restricted unpickler that only allows the
handful of torch tensor-rebuild helpers (no arbitrary code). Weights are matched to the
initializers of the bundled ONNX export of realesr-general-x4v3 (same architecture) by
order and shape, and stored under the ONNX initializer names, so printprep.neural can
interpolate the two networks (deep network interpolation, as `--denoise_strength` in
the official Real-ESRGAN inference script).

Usage: python -I tools/convert_wdn.py <realesr-general-wdn-x4v3.pth> [<realesr-general-x4v3.pth>]
The optional base .pth verifies the mapping against the ONNX weights.
"""
import pickle
import sys
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from printprep.onnx_weights import read_initializers  # noqa: E402

DTYPES = {'FloatStorage': np.float32, 'HalfStorage': np.float16, 'DoubleStorage': np.float64,
          'LongStorage': np.int64, 'IntStorage': np.int32}


class _Storage:
    def __init__(self, name):
        self.name = name


def load_pth(path):
    archive = zipfile.ZipFile(path)
    root = archive.namelist()[0].split('/')[0]

    def rebuild(storage, offset, size, stride, *_):
        dtype, key = storage
        data = np.frombuffer(archive.read(f'{root}/data/{key}'), dtype=dtype)
        count = int(np.prod(size)) if size else 1
        flat = data[offset:offset + max(count, 1) + (sum((s - 1) * st for s, st in zip(size, stride)) if size else 0)]
        if not size:
            return flat[:1].reshape(())
        return np.lib.stride_tricks.as_strided(flat, shape=size, strides=[s * flat.itemsize for s in stride]).copy()

    class Restricted(pickle.Unpickler):
        def find_class(self, module, name):
            if module == 'collections' and name == 'OrderedDict':
                import collections
                return collections.OrderedDict
            if module == 'torch._utils' and name == '_rebuild_tensor_v2':
                return rebuild
            if module == 'torch' and name in DTYPES:
                return _Storage(name)
            raise pickle.UnpicklingError(f'blocked {module}.{name}')

        def persistent_load(self, pid):
            _, storage, key, _, _ = pid
            return DTYPES[storage.name], key

    data = Restricted(archive.open(f'{root}/data.pkl')).load()
    return data.get('params', data.get('params_ema', data))


def main(wdn_path, base_path=None):
    onnx_path = ROOT / 'assets' / 'models' / 'realesr-general-x4v3.onnx'
    initializers = dict(read_initializers(onnx_path.read_bytes()))

    def mapping(state):
        """ONNX name → pth key: convolutions keep their names; PReLU slopes were renamed
        'onnx::PRelu_N' by the exporter and keep the module order."""
        conv = {k: k for k in state if k in initializers}
        prelu_keys = [k for k in state if k not in initializers]
        prelu_names = [n for n in initializers if n.startswith('onnx::PRelu')]
        if len(prelu_keys) != len(prelu_names):
            raise SystemExit(f'PReLU count mismatch: {len(prelu_keys)} vs {len(prelu_names)}')
        conv.update(zip(prelu_names, prelu_keys))
        return conv

    state = load_pth(wdn_path)
    names = mapping(state)
    mapped = {}
    for name, key in names.items():
        arr, w = initializers[name], state[key].astype(np.float32)
        if w.size != arr.size:
            raise SystemExit(f'shape mismatch {name} {arr.shape} vs {key} {w.shape}')
        mapped[name] = w.reshape(arr.shape)
    if base_path:
        base = load_pth(base_path)
        worst = max(float(np.abs(initializers[n] - base[k].astype(np.float32).reshape(initializers[n].shape)).max())
                    for n, k in mapping(base).items())
        print(f'base .pth vs ONNX max |diff| = {worst:.2e}')
        if worst > 1e-5:
            raise SystemExit('mapping check failed')
    out = ROOT / 'assets' / 'models' / 'realesr-general-wdn-x4v3.npz'
    np.savez_compressed(out, **mapped)
    print(f'saved {out.name}: {len(mapped)} tensors, {out.stat().st_size} bytes')


if __name__ == '__main__':
    main(*sys.argv[1:])
