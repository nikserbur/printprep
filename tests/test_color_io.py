import struct

import numpy as np
import pytest
from PIL import Image

from printprep.color import IccSource, decode, decode_unit, encode, from_oklab, gamut_clip, luminance, to_oklab
from printprep.imageio import SRGB_BYTES, inspect, load, read_exif, save, thumbnail

from conftest import gradient_image


def test_transfer_functions_invert():
    x = np.linspace(0, 1, 1001, dtype=np.float32).reshape(1, -1, 1).repeat(3, axis=2)
    assert np.abs(encode(decode(x)) - x).max() < 2e-5
    assert np.abs(decode_unit(x) - decode(x)).max() < 2e-5


def test_oklab_roundtrip_and_neutral_axis():
    rng = np.random.default_rng(0)
    rgb = rng.random((64, 64, 3)).astype(np.float32)
    assert np.abs(from_oklab(to_oklab(rgb)) - rgb).max() < 1e-4
    gray = np.full((8, 8, 3), .3, np.float32)
    assert np.abs(to_oklab(gray)[..., 1:]).max() < 1e-4


def test_gamut_clip_keeps_luminance_and_hue_direction():
    rgb = np.array([[[1.6, .4, .1], [-.05, .5, .6], [.2, .3, .4]]], np.float32)
    out = gamut_clip(rgb)
    assert out.min() >= -1e-6 and out.max() <= 1 + 1e-6
    assert np.allclose(luminance(out)[0, 2], luminance(rgb)[0, 2])
    assert out[0, 0, 0] > out[0, 0, 1] > out[0, 0, 2]   # still red-orange, not clipped to yellow
    assert np.allclose(out[0, 2], rgb[0, 2])


def _matrix_profile(gamma=2.2, primaries=None):
    """Minimal ICC v2 matrix/TRC display profile for tests (Adobe-RGB-like primaries)."""
    cols = primaries or [(.6097, .3111, .0195), (.2053, .6257, .0609), (.1492, .0632, .7446)]
    tags = []

    def xyz(v):
        return b'XYZ \0\0\0\0' + b''.join(struct.pack('>i', round(c * 65536)) for c in v)
    curve = b'curv\0\0\0\0' + struct.pack('>I', 1) + struct.pack('>H', round(gamma * 256)) + b'\0\0'
    desc_text = b'Test Wide RGB\0'
    desc = b'desc\0\0\0\0' + struct.pack('>I', len(desc_text)) + desc_text + b'\0' * 79
    for sig, data in ((b'desc', desc), (b'wtpt', xyz((.9642, 1., .8249))), (b'rXYZ', xyz(cols[0])), (b'gXYZ', xyz(cols[1])),
                      (b'bXYZ', xyz(cols[2])), (b'rTRC', curve), (b'gTRC', curve), (b'bTRC', curve)):
        tags.append((sig, data))
    offset = 128 + 4 + 12 * len(tags)
    table, blob = b'', b''
    for sig, data in tags:
        data += b'\0' * (-len(data) % 4)
        table += sig + struct.pack('>II', offset + len(blob), len(data))
        blob += data
    size = offset + len(blob)
    header = struct.pack('>I', size) + b'lcms' + bytes([2, 16, 0, 0]) + b'mntrRGB XYZ ' + b'\0' * 12 + b'acsp' + b'\0' * 24
    header += b'\0' * 16 + struct.pack('>iii', 63190, 65536, 54061) + b'\0' * 48
    header = header[:128].ljust(128, b'\0')
    return header + struct.pack('>I', len(tags)) + table + blob


def test_icc_parser_recognises_srgb_and_matrix_profiles():
    assert IccSource(SRGB_BYTES).is_srgb
    wide = IccSource(_matrix_profile())
    assert wide.matrix is not None and not wide.is_srgb
    assert wide.description == 'Test Wide RGB'
    # A saturated wide-gamut green maps outside sRGB and must be softly mapped, not wrapped.
    out = wide.to_srgb_encoded(np.array([[[0, 255, 0], [128, 128, 128]]], np.uint8))
    assert out.dtype == np.uint16
    assert int(out[0, 1].max()) - int(out[0, 1].min()) <= 8   # neutral stays neutral (16-bit units)
    assert out[0, 0, 1] > 60000 and out[0, 0, 0] < 20000


def test_wide_gamut_jpeg_is_converted_on_load(tmp_path):
    path = tmp_path / 'wide.jpg'
    Image.fromarray(gradient_image(64, 48)).save(path, quality=95, icc_profile=_matrix_profile())
    array, notes = load(path)
    assert array.dtype == np.uint16 and any('Test Wide RGB' in n for n in notes)
    assert 'Test Wide RGB' in inspect(path).profile


def test_reads_16bit_png_and_tiff(tmp_path):
    import cv2
    data = (np.linspace(0, 65535, 64 * 48 * 3) % 65536).astype(np.uint16).reshape(48, 64, 3)
    for name in ('deep.png', 'deep.tif'):
        cv2.imencode('.' + name.split('.')[1], data[..., ::-1])[1].tofile(str(tmp_path / name))
        info = inspect(tmp_path / name)
        assert info.bits == 16
        array, _ = load(tmp_path / name)
        assert array.dtype == np.uint16 and np.array_equal(array, data)


def test_exif_orientation_alpha_and_gray(tmp_path):
    img = Image.fromarray(gradient_image(60, 40))
    exif = img.getexif()
    exif[274] = 6
    exif[0x8825] = {1: 'N'}
    img.save(tmp_path / 'rot.jpg', exif=exif)
    assert inspect(tmp_path / 'rot.jpg').size == (40, 60)
    assert load(tmp_path / 'rot.jpg')[0].shape == (60, 40, 3)
    cleaned = read_exif(tmp_path / 'rot.jpg')
    assert cleaned[274] == 1 and 0x8825 not in cleaned
    rgba = np.zeros((10, 10, 4), np.uint8)
    rgba[..., 3] = 0
    Image.fromarray(rgba, 'RGBA').save(tmp_path / 'clear.png')
    assert (load(tmp_path / 'clear.png')[0] == 255).all()
    Image.new('L', (12, 8), 77).save(tmp_path / 'gray.png')
    assert load(tmp_path / 'gray.png')[0].shape == (8, 12, 3)
    assert thumbnail(tmp_path / 'rot.jpg', 32).shape[0] == 32


def test_cmyk_without_profile_is_rejected(tmp_path):
    Image.new('CMYK', (10, 10)).save(tmp_path / 'c.jpg')
    with pytest.raises(ValueError, match='CMYK'):
        inspect(tmp_path / 'c.jpg')


def test_writers_embed_icc_and_resolution(tmp_path):
    import cv2
    rng = np.random.default_rng(0)
    deep = rng.integers(0, 65535, (30, 40, 3), dtype=np.uint16)
    save(tmp_path / 'x.tif', deep, 'TIFF', dpi=360)
    back = cv2.imdecode(np.fromfile(str(tmp_path / 'x.tif'), np.uint8), cv2.IMREAD_UNCHANGED)[..., ::-1]
    assert np.array_equal(back, deep)
    with Image.open(tmp_path / 'x.tif') as im:
        assert im.info['icc_profile'] == SRGB_BYTES and round(float(im.info['dpi'][0])) == 360
    save(tmp_path / 'x.png', deep, 'PNG', dpi=300)
    back = cv2.imdecode(np.fromfile(str(tmp_path / 'x.png'), np.uint8), cv2.IMREAD_UNCHANGED)[..., ::-1]
    assert np.array_equal(back, deep)
    with Image.open(tmp_path / 'x.png') as im:
        assert im.info['icc_profile'] == SRGB_BYTES and round(im.info['dpi'][0]) == 300
    flat = rng.integers(0, 255, (30, 40, 3), dtype=np.uint8)
    save(tmp_path / 'x.jpg', flat, 'JPEG', quality=95, dpi=300)
    with Image.open(tmp_path / 'x.jpg') as im:
        assert im.info['icc_profile'] == SRGB_BYTES and im.info['dpi'] == (300, 300)
