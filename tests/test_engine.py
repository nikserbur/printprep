import hashlib
import json
import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageCms
from printprep.engine import (Settings, Edit, inspect_photo, load_rgb, render, assess, crop_box,
    scan, export_batch, output_color, proof, SRGB_BYTES)


@pytest.fixture
def photo_dir(tmp_path):
    Image.new('RGB', (900, 600), '#bc7560').save(tmp_path / 'фото.jpg', icc_profile=SRGB_BYTES)
    return tmp_path


def test_mm_ppi_and_orientation():
    s = Settings()
    assert s.pixels == (1181, 1772)
    assert assess((6000, 4000), s, Edit())['pixels'] == (1772, 1181)
    assert assess((4000, 6000), s, Edit())['pixels'] == (1181, 1772)
    assert assess((6000, 4000), replace(s, auto_orientation=False), Edit())['pixels'] == (1181, 1772)


@pytest.mark.parametrize('kwargs', [dict(width_mm=0), dict(border_mm=51), dict(dpi=0),
    dict(width_mm=float('nan')), dict(output_space='CMYK'), dict(output_space='ICC'),
    dict(width_mm=1500, height_mm=1500, dpi=720), dict(quality=100)])
def test_reject_invalid_settings(kwargs):
    with pytest.raises((ValueError, OSError)):
        replace(Settings(), **kwargs).validate()


def test_fit_cover_and_border_pixels():
    im = Image.new('RGB', (600, 300), 'red')
    s = Settings(width_mm=25.4, height_mm=25.4, dpi=100, auto_orientation=False)
    contain = render(im, s, Edit())
    assert contain.size == (100, 100)
    assert contain.getpixel((50, 0)) == (255, 255, 255)
    assert contain.getpixel((50, 50)) == (255, 0, 0)
    cover = render(im, replace(s, fit='cover', border_mm=2.54), Edit())
    assert cover.getpixel((9, 50)) == (255, 255, 255)
    assert cover.getpixel((10, 50)) == (255, 0, 0)
    assert cover.getpixel((89, 50)) == (255, 0, 0)
    assert cover.getpixel((90, 50)) == (255, 255, 255)


def test_crop_preserves_selected_subject():
    im = Image.new('RGB', (300, 100), 'red')
    im.paste('blue', (200, 0, 300, 100))
    s = Settings(width_mm=25.4, height_mm=25.4, dpi=100, fit='cover', auto_orientation=False)
    right = render(im, s, Edit(center_x=1, manual_crop=True))
    assert right.getpixel((50, 50)) == (0, 0, 255)
    b = crop_box((300, 100), 1, Edit(center_x=1, zoom=2))
    assert b == (250, 25, 300, 75)
    assert assess((300, 100), s, Edit(zoom=2))['crop_percent'] == 92


def test_exif_rotation_and_stripped_gps(tmp_path):
    p = tmp_path / 'rotated.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (100, 50), 'green').save(p, exif=exif)
    assert inspect_photo(p).size == (50, 100)
    im, _ = load_rgb(p)
    assert im.size == (50, 100)
    assert assess((50, 100), Settings(), Edit(rotation=90))['pixels'] == (1772, 1181)


def test_alpha_is_flattened_white(tmp_path):
    p = tmp_path / 'alpha.png'
    Image.new('RGBA', (10, 10), (255, 0, 0, 0)).save(p)
    im, notes = load_rgb(p)
    assert im.getpixel((0, 0)) == (255, 255, 255)
    assert notes


def test_missing_cmyk_profile_is_not_guessed(tmp_path):
    p = tmp_path / 'cmyk.tif'
    Image.new('CMYK', (10, 10), (0, 20, 20, 0)).save(p)
    with pytest.raises(ValueError, match='без ICC'):
        load_rgb(p)


def test_reject_high_bit_and_multiframe(tmp_path):
    p = tmp_path / '16bit.tif'
    Image.new('I;16', (10, 10)).save(p)
    with pytest.raises(ValueError, match='16/32'):
        inspect_photo(p)
    p = tmp_path / 'multi.tif'
    Image.new('RGB', (10, 10)).save(p, save_all=True, append_images=[Image.new('RGB', (10, 10))])
    with pytest.raises(ValueError, match='Многостраничный'):
        inspect_photo(p)


@pytest.mark.parametrize('fmt', ['JPEG', 'TIFF'])
def test_export_roundtrip_non_destructive(photo_dir, fmt):
    source = photo_dir / 'фото.jpg'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    photos, errors = scan(photo_dir)
    assert not errors
    output, report = export_batch(photo_dir, photos, replace(Settings(), format=fmt), {})
    row = report['results'][0]
    assert row['status'] == 'ok'
    with Image.open(row['output']) as im:
        assert im.mode == 'RGB'
        assert im.size == (1772, 1181)
        assert im.info['icc_profile'] == SRGB_BYTES
        assert abs(im.info['dpi'][0] - 300) < 1
        assert not im.getexif().get(274)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert json.loads((output / 'report.json').read_text(encoding='utf8'))['results'][0]['status'] == 'ok'
    assert (output / 'report.csv').read_bytes().startswith(b'\xef\xbb\xbf')
    # Repeated runs never rescan exported images and never overwrite output.
    again, _ = scan(photo_dir, True)
    assert len(again) == 1
    second, _ = export_batch(photo_dir, photos, Settings(), {})
    assert second != output


def test_recursive_names_and_corrupt_files(photo_dir):
    sub = photo_dir / 'вложенная'
    sub.mkdir()
    Image.new('RGB', (40, 40)).save(sub / 'фото.jpg')
    Image.new('RGB', (40, 40)).save(sub / 'фото.png')
    (sub / 'broken.jpg').write_bytes(b'not an image')
    photos, errors = scan(photo_dir, True)
    assert len(photos) == 3 and len(errors) == 1
    out, report = export_batch(photo_dir, photos, Settings(dpi=72), {})
    assert len(list(out.rglob('*.jpg'))) == 3
    assert all(r['status'] == 'ok' for r in report['results'])


def test_skip_upscale_and_cancel(photo_dir):
    photos, _ = scan(photo_dir)
    _, report = export_batch(photo_dir, photos, Settings(allow_upscale=False), {})
    assert report['results'][0]['status'] == 'skipped'
    event = threading.Event()
    event.set()
    out, report = export_batch(photo_dir, photos, Settings(), {}, event)
    assert report['cancelled'] and not report['results']
    assert (out / 'report.csv').exists()


def test_file_failure_does_not_stop_batch(photo_dir):
    Image.new('RGB', (100, 100)).save(photo_dir / 'second.png')
    photos, _ = scan(photo_dir)
    photos[0].path.unlink()
    _, report = export_batch(photo_dir, photos, Settings(dpi=72), {})
    assert [r['status'] for r in report['results']] == ['error', 'ok']


def test_rgb_icc_transform_and_proof(tmp_path):
    profile = tmp_path / 'sRGB.icc'
    profile.write_bytes(SRGB_BYTES)
    s = Settings(output_space='ICC', icc_path=str(profile))
    s.validate()
    im = Image.new('RGB', (32, 24), (120, 140, 170))
    out, icc = output_color(im, s)
    assert out.mode == 'RGB' and icc == SRGB_BYTES
    assert out.getpixel((0, 0)) == (120, 140, 170)
    assert proof(im, s).size == im.size


def test_auto_enhance_and_smart_crop_are_deterministic():
    im = Image.new('RGB', (400, 200), (80, 80, 80))
    for x in range(280, 395, 5):
        im.paste('white', (x, 30, x + 2, 170))
    s = Settings(width_mm=25.4, height_mm=25.4, dpi=100, fit='cover', smart_crop=True, auto_enhance=True)
    a = render(im, s, Edit())
    b = render(im, s, Edit())
    assert a.tobytes() == b.tobytes()
    # Explicit user framing overrides saliency selection.
    a = render(im, s, Edit(center_x=0, manual_crop=True))
    b = render(im, replace(s, smart_crop=False), Edit(center_x=0, manual_crop=True))
    assert a.tobytes() == b.tobytes()


def test_cmyk_real_profile_roundtrip(tmp_path):
    profile = os.environ.get('PRINTPREP_TEST_CMYK_ICC')
    if not profile:
        pytest.skip('External licensed CMYK ICC not provided')
    s = Settings(output_space='ICC', icc_path=profile, format='TIFF')
    s.validate()
    im, icc = output_color(Image.new('RGB', (100, 80), '#ad6951'), s)
    assert im.mode == 'CMYK'
    p = tmp_path / 'cmyk.tif'
    im.save(p, icc_profile=icc)
    loaded, _ = load_rgb(p)
    assert loaded.mode == 'RGB'
    assert max(abs(a-b) for a,b in zip(loaded.getpixel((0,0)), (173,105,81))) < 25
