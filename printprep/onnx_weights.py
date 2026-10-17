"""Read and patch the weight initializers of an ONNX model without the onnx package.

Only the protobuf wire format is needed: ModelProto.graph (7) → GraphProto.initializer (5)
→ TensorProto {dims 1, data_type 2, float_data 4, name 8, raw_data 9}. Patching replaces
tensor bytes in place (same size), so the rest of the model stays byte-identical.
"""
from __future__ import annotations

import numpy as np

DTYPES = {1: np.float32, 6: np.int32, 7: np.int64, 10: np.float16, 11: np.float64}


def _varint(data, pos):
    shift = result = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def _fields(data, start, end):
    """Yield (field, wire_type, value_start, value_end, int_value) for one message."""
    pos = start
    while pos < end:
        tag, pos = _varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if wire == 0:
            value, new = _varint(data, pos)
            yield field, wire, pos, new, value
            pos = new
        elif wire == 1:
            yield field, wire, pos, pos + 8, None
            pos += 8
        elif wire == 2:
            length, pos = _varint(data, pos)
            yield field, wire, pos, pos + length, None
            pos += length
        elif wire == 5:
            yield field, wire, pos, pos + 4, None
            pos += 4
        else:
            raise ValueError(f'unsupported wire type {wire}')


def _tensor(data, start, end):
    dims, dtype, name, span = [], 1, '', None
    for field, wire, a, b, value in _fields(data, start, end):
        if field == 1:
            if wire == 0:
                dims.append(value)
            else:
                pos = a
                while pos < b:
                    v, pos = _varint(data, pos)
                    dims.append(v)
        elif field == 2:
            dtype = value
        elif field == 8:
            name = bytes(data[a:b]).decode('utf-8')
        elif field in (9, 4) and wire == 2:
            span = (a, b)
    return name, tuple(dims), dtype, span


def initializer_spans(data):
    for field, wire, a, b, _ in _fields(data, 0, len(data)):
        if field == 7 and wire == 2:
            for gfield, gwire, ga, gb, _ in _fields(data, a, b):
                if gfield == 5 and gwire == 2:
                    yield _tensor(data, ga, gb)


def read_initializers(data):
    """[(name, ndarray)] for every initializer with inline data."""
    out = []
    for name, dims, dtype, span in initializer_spans(data):
        if span is None or dtype not in DTYPES:
            continue
        arr = np.frombuffer(bytes(data[span[0]:span[1]]), dtype=np.dtype(DTYPES[dtype]).newbyteorder('<'))
        out.append((name, arr.reshape(dims) if dims else arr))
    return out


def patch(data, replacements):
    """Return a copy of the model bytes with the named float32 initializers replaced."""
    buf = bytearray(data)
    done = set()
    for name, dims, dtype, span in initializer_spans(data):
        if name in replacements and span is not None:
            raw = np.ascontiguousarray(replacements[name], dtype='<f4').tobytes()
            if len(raw) != span[1] - span[0]:
                raise ValueError(f'size mismatch for {name}')
            buf[span[0]:span[1]] = raw
            done.add(name)
    missing = set(replacements) - done
    if missing:
        raise ValueError(f'initializers not found: {sorted(missing)[:3]}')
    return bytes(buf)
