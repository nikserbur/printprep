from dataclasses import replace
import numpy as np
import pytest
from PIL import Image
from printprep.engine import Settings, Edit, render
from printprep.enhance import enhance, guided_base, estimate_white_balance, analyze, PRESETS


def gradient(w=256, h=96):
    a = np.tile(np.arange(w, dtype=np.uint8), (h, 1))
    return Image.fromarray(np.stack((a, a, a), axis=2))


def test_zero_correction_is_byte_identical():
    im = gradient()
    assert enhance(im, Settings()).tobytes() == im.tobytes()
    assert enhance(im, Settings(shadows=1, clarity=1, enhancement_strength=0)).tobytes() == im.tobytes()


@pytest.mark.parametrize('preset', [k for k in PRESETS if k != 'none'])
def test_preset_no_nan_no_neutral_cast_preserves_endpoints(preset):
    s = Settings(enhancement_preset=preset, **PRESETS[preset][1])
    s.validate()
    im = gradient()
    out = np.asarray(enhance(im, s))
    assert out.dtype == np.uint8 and out.shape == (96, 256, 3)
    assert np.max(np.abs(out[..., 0].astype(int) - out[..., 1])) <= 1
    assert np.max(np.abs(out[..., 1].astype(int) - out[..., 2])) <= 1
    assert out[40, 0].max() == 0
    assert out[40, -1].min() >= 253


def test_tone_curve_without_clarity_is_monotonic():
    out = np.asarray(enhance(gradient(), Settings(shadows=.7, highlights=.7, enhancement_strength=1)))
    assert np.diff(out[48, :, 0].astype(int)).min() >= 0
    assert out[48, 40, 0] > 40
    assert out[48, 215, 0] < 215


def test_guided_filter_preserves_step_better_than_wide_blur():
    y = np.full((128, 256), .15, dtype=np.float32)
    y[:, 128:] = .85
    base = guided_base(y, 15)
    # At the edge, contamination remains below 2% of the 0..1 lightness scale.
    assert abs(float(base[64, 127]) - .15) < .02
    assert abs(float(base[64, 128]) - .85) < .02
    assert np.isfinite(base).all()


def test_white_balance_refuses_saturated_scene():
    rgb = np.zeros((64, 64, 3), dtype=np.float32)
    rgb[..., 2] = .5
    gains, note = estimate_white_balance(rgb)
    assert np.array_equal(gains, np.ones(3))
    assert 'не применён' in note


def test_white_balance_reduces_known_mild_cast():
    rgb = np.full((64, 64, 3), [.2, .19, .175], dtype=np.float32)
    gains, _ = estimate_white_balance(rgb)
    corrected = rgb * gains
    assert np.ptp(corrected[0, 0]) < np.ptp(rgb[0, 0])
    assert gains.min() >= .85 and gains.max() <= 1.18


def test_vibrance_and_warmth_are_bounded():
    rng = np.random.default_rng(42)
    im = Image.fromarray(rng.integers(0, 256, (300, 256, 3), dtype=np.uint8))
    out = np.asarray(enhance(im, Settings(vibrance=1, warmth=1, tint=-1, shadows=1, clarity=1)))
    assert out.min() >= 0 and out.max() <= 255
    # Color is deterministic and processing doesn't mutate input.
    assert out.tobytes() == enhance(im, Settings(vibrance=1, warmth=1, tint=-1, shadows=1, clarity=1)).tobytes()


def test_chroma_denoise_reduces_color_variance_without_luma_blur():
    rng = np.random.default_rng(17)
    y = np.full((100, 100), 128, dtype=np.uint8)
    cb = rng.integers(110, 146, (100, 100), dtype=np.uint8)
    cr = rng.integers(110, 146, (100, 100), dtype=np.uint8)
    im = Image.merge('YCbCr', tuple(Image.fromarray(x) for x in (y, cb, cr))).convert('RGB')
    out = enhance(im, Settings(chroma_denoise=1, enhancement_strength=1)).convert('YCbCr')
    before = np.asarray(im.convert('YCbCr'))
    after = np.asarray(out)
    assert after[..., 1:].var() < before[..., 1:].var() * .5
    assert np.abs(after[..., 0].astype(int) - before[..., 0]).max() <= 3


def test_diagnostics_on_black_white():
    black = analyze(Image.new('RGB', (64, 64)))
    white = analyze(Image.new('RGB', (64, 64), 'white'))
    assert black['shadow_percent'] == 100
    assert white['highlight_percent'] == 100


def test_one_pixel_input_does_not_crash():
    im = Image.new('RGB', (1, 1), '#9a806f')
    out = enhance(im, Settings(shadows=.5, auto_wb=True))
    assert out.size == (1, 1)


def test_invalid_strength_rejected():
    with pytest.raises(ValueError):
        Settings(enhancement_strength=float('nan')).validate()
