import hashlib
import numpy as np
import pytest
from PIL import Image
from printprep.upscale import upscale2x, MODEL, MODEL_SHA256
from printprep.engine import Settings, Edit, render, scan, export_batch, SRGB_BYTES


def fixture_image(w=100, h=80):
    rng = np.random.default_rng(7)
    return Image.fromarray(rng.integers(30, 220, (h, w, 3), dtype=np.uint8))


def test_bundled_model_integrity_and_real_inference():
    assert hashlib.sha256(MODEL.read_bytes()).hexdigest() == MODEL_SHA256
    im = fixture_image()
    out = upscale2x(im)
    assert out.size == (200, 160) and out.mode == 'RGB'
    ordinary = im.resize(out.size, Image.Resampling.LANCZOS)
    assert out.tobytes() != ordinary.tobytes()


def test_zero_strength_exactly_lanczos():
    im = fixture_image()
    assert upscale2x(im, 0).tobytes() == im.resize((200, 160), Image.Resampling.LANCZOS).tobytes()


def test_overlap_tiles_match_single_inference():
    im = fixture_image(130, 110)
    tiled = np.asarray(upscale2x(im, 1, tile_size=48)).astype(int)
    whole = np.asarray(upscale2x(im, 1, tile_size=256)).astype(int)
    # Chroma interpolation and convolution padding can round by one value.
    assert np.abs(tiled - whole).max() <= 2


def test_neural_only_for_actual_upscale_and_report(tmp_path):
    im = fixture_image(100, 80)
    settings = Settings(width_mm=50.8, height_mm=50.8, dpi=100, auto_orientation=False, upscaler='fsrcnn')
    notes = []
    out = render(im, settings, Edit(), notes=notes)
    assert out.size == (200, 200)
    assert any('FSRCNN' in n for n in notes)
    notes = []
    render(im, Settings(width_mm=25.4, height_mm=25.4, dpi=72, upscaler='fsrcnn'), Edit(), notes=notes)
    assert any('не применяется' in note for note in notes)  # Explain why the network is inactive.
    im.save(tmp_path / 'test.png', icc_profile=SRGB_BYTES)
    photos, _ = scan(tmp_path)
    _, report = export_batch(tmp_path, photos, settings, {})
    assert report['results'][0]['status'] == 'ok'
    assert 'FSRCNN' in report['results'][0]['warnings']
    assert report['results'][0]['ppi'] < 100  # Never pretend synthesized pixels are captured detail.


def test_tiny_input_and_bad_strength():
    assert upscale2x(Image.new('RGB', (1, 1), 'gray')).size == (2, 2)
    with pytest.raises(ValueError):
        upscale2x(fixture_image(), 2)
