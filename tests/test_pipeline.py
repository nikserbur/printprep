from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from printprep.imageio import inspect
from printprep.model import Adjust, Edit, Settings
from printprep.pipeline import (AnalysisCache, Source, assess, geometry, render, render_fast, smart_center,
                                straightened_size)
from printprep import analysis as auto

from conftest import gradient_image


def source_from(array, tmp_path, name='s.png'):
    path = tmp_path / name
    Image.fromarray(array).save(path)
    return Source.open(inspect(path))


def to_u8(enc):
    return np.round(np.clip(enc, 0, 1) * 255).astype(np.uint8)


def test_identity_render_is_pixel_exact(tmp_path):
    arr = gradient_image(320, 200)
    src = source_from(arr, tmp_path)
    r = render(src, Settings(), Edit())
    assert np.array_equal(to_u8(r.image), arr)


def test_print_geometry_cover_contain_and_border(tmp_path):
    s = Settings(size_mode='print', width_mm=102, height_mm=152, dpi=300)
    g = geometry((3000, 2000), s, Edit())
    assert g.canvas == (1795, 1205) and g.image == (1795, 1205)   # auto orientation follows the landscape photo
    g = geometry((3000, 2000), replace(s, fit='contain', border_mm=5), Edit())
    assert g.border == 59 and g.image[0] <= 1795 - 118 and g.offset[0] >= 59
    src = source_from(gradient_image(300, 300), tmp_path)
    out = render(src, replace(s, fit='contain', background='#000000', dpi=72), Edit())
    assert out.image.shape[:2] == (431, 289)          # square photo keeps the portrait sheet as entered
    assert to_u8(out.image)[0, 0].tolist() == [0, 0, 0]


def test_original_long_edge_and_pixels_modes(tmp_path):
    assert geometry((4000, 3000), Settings(size_mode='long_edge', long_edge=2048), Edit()).canvas == (2048, 1536)
    assert geometry((4000, 3000), Settings(), Edit()).canvas == (4000, 3000)
    g = geometry((4000, 3000), Settings(size_mode='pixels', pixel_width=3840, pixel_height=2160, auto_orientation=False), Edit())
    assert g.canvas == (3840, 2160)
    g = geometry((4000, 3000), Settings(), Edit(manual_crop=True, aspect=1.0, zoom=2))
    assert g.canvas == (1500, 1500)


def test_rotation_and_straighten_change_frame(tmp_path):
    src = source_from(gradient_image(400, 200), tmp_path)
    r = render(src, Settings(), Edit(rotation=90))
    assert r.image.shape[:2] == (400, 200)
    w, h = straightened_size((400, 200), 10)
    r = render(src, Settings(), Edit(angle=10))
    assert r.image.shape[:2] == (h, w) and w < 400 and h < 200


def test_regions_and_strips_match_whole_render(tmp_path):
    rng = np.random.default_rng(3)
    arr = np.clip(gradient_image(900, 600) + rng.normal(0, 4, (600, 900, 3)), 0, 255).astype(np.uint8)
    src = source_from(arr, tmp_path)
    s = Settings(size_mode='pixels', pixel_width=700, pixel_height=500, sharpen='screen',
                 adjust=Adjust(shadows=30, clarity=25, vibrance=20, denoise=20, color_denoise=30, exposure=.3))
    whole = render(src, s, Edit()).image
    part = render(src, s, Edit(), region=(150, 120, 300, 200)).image
    assert np.abs(part - whole[120:320, 150:450]).max() < 2.5 / 255
    strips = render_fast(src, s, Edit(), strips=4).image
    assert np.abs(strips - whole).max() < 2.5 / 255


def test_preview_proxy_resembles_export(tmp_path):
    src = source_from(gradient_image(3200, 2100), tmp_path)
    s = Settings(adjust=Adjust(auto=True, shadows=20, contrast=15))
    full = render(src, s, Edit()).image
    k = 800 / 3200
    preview = render(src, s, Edit(), k=k, use_full=False).image
    import cv2
    small = cv2.resize(full, (preview.shape[1], preview.shape[0]), interpolation=cv2.INTER_AREA)
    assert np.abs(small - preview).mean() < 1.5 / 255


def test_neutral_stays_neutral_and_controls_are_monotonic(tmp_path):
    ramp = np.repeat(np.linspace(10, 245, 256, dtype=np.uint8)[None, :, None], 16, axis=0).repeat(3, axis=2)
    src = source_from(ramp, tmp_path)
    for adjust in (Adjust(exposure=.7), Adjust(contrast=60), Adjust(shadows=80, highlights=-80), Adjust(whites=40, blacks=-40),
                   Adjust(vibrance=80, saturation=50), Adjust(clarity=60), Adjust(look='film')):
        out = render(src, Settings(adjust=adjust), Edit()).image[8]
        if adjust.look == 'none':
            assert np.abs(out[:, 0] - out[:, 2]).max() < 1.5 / 255, adjust
        lum = out.mean(axis=1)
        assert np.all(np.diff(lum) >= -1.5 / 255), adjust
    bright = render(src, Settings(adjust=Adjust(exposure=1.5)), Edit()).image[8].mean(axis=1)
    assert bright.max() <= 1 and np.diff(bright)[-40:].min() >= -1e-6   # soft shoulder, no reversal at white
    assert bright[-1] > .99                                              # paper white is reached


def test_shadows_lift_darks_more_than_lights(tmp_path):
    ramp = np.repeat(np.linspace(5, 250, 256, dtype=np.uint8)[None, :, None], 32, axis=0).repeat(3, axis=2)
    src = source_from(ramp, tmp_path)
    base = render(src, Settings(), Edit()).image[16].mean(axis=1)
    lifted = render(src, Settings(adjust=Adjust(shadows=80)), Edit()).image[16].mean(axis=1)
    delta = lifted - base
    assert delta[40] > .05 and delta[40] > 3 * abs(delta[230])


def test_saturation_mono_and_white_balance(tmp_path):
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
    src = source_from(arr, tmp_path)
    gray = render(src, Settings(adjust=Adjust(saturation=-100)), Edit()).image
    assert np.abs(gray[..., 0] - gray[..., 1]).max() < 2 / 255
    mono = render(src, Settings(adjust=Adjust(look='bw')), Edit()).image
    assert np.abs(mono[..., 0] - mono[..., 2]).max() < 2 / 255
    warm = render(src, Settings(adjust=Adjust(temperature=60)), Edit()).image
    plain = render(src, Settings(), Edit()).image
    assert warm[..., 0].mean() > plain[..., 0].mean() and warm[..., 2].mean() < plain[..., 2].mean()


def test_output_sharpening_scales_with_paper_and_ppi(tmp_path):
    arr = np.zeros((200, 200, 3), np.uint8)
    arr[:, 100:] = 200
    arr = np.asarray(Image.fromarray(arr).resize((200, 200)))
    src = source_from(arr, tmp_path)
    plain = render(src, Settings(), Edit()).image[100, 90:110, 1]
    glossy = render(src, Settings(sharpen='glossy'), Edit()).image[100, 90:110, 1]
    matte = render(src, Settings(sharpen='matte', sharpen_amount='high'), Edit()).image[100, 90:110, 1]
    contrast = lambda row: row.max() - row.min()
    assert contrast(plain) <= contrast(glossy) <= contrast(matte)


def test_denoise_and_dehaze_do_their_job(tmp_path):
    rng = np.random.default_rng(2)
    flat = np.clip(np.full((240, 240, 3), 120.) + rng.normal(0, 10, (240, 240, 3)), 0, 255).astype(np.uint8)
    src = source_from(flat, tmp_path)
    noisy = render(src, Settings(), Edit()).image.std()
    clean = render(src, Settings(adjust=Adjust(denoise=70, color_denoise=70)), Edit()).image.std()
    assert clean < noisy * .6
    hazy = (gradient_image(400, 300).astype(np.float32) * .45 + 120).astype(np.uint8)
    src = source_from(hazy, tmp_path, 'hazy.png')
    before = render(src, Settings(), Edit()).image
    after = render(src, Settings(adjust=Adjust(dehaze=70)), Edit()).image
    assert after.std() > before.std() * 1.15


def test_auto_analysis_corrects_cast_exposure_and_estimates_noise(tmp_path):
    rng = np.random.default_rng(5)
    scene = gradient_image(800, 600).astype(np.float32)
    scene[100:500, 100:300] = 128                     # a neutral grey card
    cast = np.clip(scene * np.array([1.15, 1.0, .8]) * .5, 0, 255).astype(np.uint8)
    src = source_from(cast, tmp_path)
    a = src.ensure_analysis()
    gains = np.array(a['wb_gains'])
    assert gains[2] > gains[0], 'should cool down a warm cast'
    assert a['suggestions']['exposure'] > .2, 'should brighten a dark frame'
    noisy = np.clip(scene + rng.normal(0, 8, scene.shape), 0, 255).astype(np.uint8)
    quiet = auto.estimate_noise(scene.astype(np.uint8))
    loud = auto.estimate_noise(noisy)
    assert loud > quiet + 3
    snow = np.full((400, 600, 3), 235, np.uint8)
    snow[300:] = 200
    s = source_from(snow, tmp_path, 'snow.png').ensure_analysis()
    assert s['suggestions']['exposure'] > -.15, 'bright scenes must not be darkened'


def test_auto_strength_scales_and_switches(tmp_path):
    src = source_from(gradient_image(400, 300), tmp_path)
    a = src.ensure_analysis()
    full, _ = auto.auto_values(a, Adjust(auto=True, auto_strength=100))
    half, _ = auto.auto_values(a, Adjust(auto=True, auto_strength=50))
    for key, value in full.items():
        if key == 'levels':
            assert abs(half[key][0] - value[0] / 2) < 1e-6 and abs((1 - half[key][1]) - (1 - value[1]) / 2) < 1e-6
        else:
            assert abs(half[key] - value / 2) < 1e-6
    none, gains = auto.auto_values(a, Adjust(auto=True, auto_light=False, auto_color=False, auto_noise=False, auto_wb=False))
    assert none == {} and np.allclose(gains, 1)


def test_smart_crop_follows_salient_detail():
    sal = np.zeros((40, 120), np.float32)
    sal[10:30, 95:115] = 1                       # detail on the right
    x, y = smart_center((3000, 1000), .667, Edit(), {'faces': [], 'saliency': sal})
    assert x > .6 and y == .5
    face = {'faces': [(.08, .3, .1, .3, .9)], 'saliency': np.zeros((40, 120), np.float32)}
    x, _ = smart_center((3000, 1000), .667, Edit(), face)
    assert x < .35


def test_assess_reports_ppi_and_upscale():
    s = Settings(size_mode='print', width_mm=203, height_mm=305)
    info = assess((900, 600), s)
    assert info['upscale'] and info['ppi'] < 100 and any('PPI' in w for w in info['warnings'])
    assert assess((6000, 4000), Settings())['scale'] == 1
