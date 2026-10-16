import csv
import hashlib
import threading
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from printprep import neural
from printprep.export import destinations, export_batch, worker_count
from printprep.imageio import SRGB_BYTES, inspect
from printprep.model import Adjust, Edit, Settings
from printprep.pipeline import AnalysisCache, Source, render

from conftest import gradient_image


def test_bundled_models_match_checksums():
    for name, digest in neural.CHECKSUMS.items():
        assert hashlib.sha256((neural.MODELS / name).read_bytes()).hexdigest() == digest
    assert neural.available('fsrcnn') and neural.available('esrgan')


@pytest.mark.parametrize('kind, factor', [('fsrcnn', 2), ('esrgan', 4)])
def test_upscale_shape_progress_and_tiling(kind, factor):
    rng = np.random.default_rng(0)
    img = np.clip(gradient_image(150, 110).astype(np.float32) / 255 + rng.normal(0, .01, (110, 150, 3)), 0, 1).astype(np.float32)
    seen = []
    out = neural.upscale(img, kind, progress=seen.append)
    assert out.shape == (110 * factor, 150 * factor, 3) and seen[-1] == 1
    # Tiled result must match an untiled run closely (no visible seams).
    spec = dict(neural.UPSCALERS[kind])
    try:
        neural.UPSCALERS[kind]['tile'] = 64
        tiled = neural.upscale(img, kind)
    finally:
        neural.UPSCALERS[kind].update(spec)
    assert np.abs(tiled - out).max() < .03


def test_upscale_can_be_cancelled():
    img = np.zeros((600, 600, 3), np.float32)
    with pytest.raises(neural.Cancelled):
        neural.upscale(img, 'esrgan', cancel=lambda: True)


def test_neural_render_only_when_enlarging(tmp_path):
    Image.fromarray(gradient_image(200, 150)).save(tmp_path / 's.png')
    src = Source.open(inspect(tmp_path / 's.png'))
    s = Settings(size_mode='long_edge', long_edge=400, upscaler='fsrcnn')
    r = render(src, s, Edit())
    assert r.neural and r.image.shape[:2] == (300, 400)
    r = render(src, Settings(size_mode='long_edge', long_edge=100, upscaler='fsrcnn'), Edit())
    assert not r.neural and any('не нужна' in n for n in r.notes)
    r = render(src, Settings(size_mode='long_edge', long_edge=400, upscaler='fsrcnn'), Edit(neural=False))
    assert not r.neural


def test_face_detector_runs_offline():
    assert neural.detect_faces(np.zeros((240, 320, 3), np.uint8)) == []


def test_export_formats_icc_dpi_and_names(photo_folder):
    photos = [inspect(p) for p in sorted(photo_folder.iterdir())]
    (photo_folder / 'a_landscape.png').write_bytes((photo_folder / 'b_portrait.png').read_bytes())
    photos.append(inspect(photo_folder / 'a_landscape.png'))
    s = Settings(size_mode='print', width_mm=102, height_mm=152, sharpen='glossy', adjust=Adjust(auto=True))
    out, report = export_batch(photo_folder, photos, s, {}, preset_name='Лаборатория 10×15')
    assert out.name.startswith('PrintPrep_Лаборатория_10_15_')
    ok = [r for r in report['results'] if r['status'] == 'ok']
    assert len(ok) == len(photos)
    names = sorted(Path(r['output']).name for r in ok)
    assert names == ['a_landscape.jpg', 'a_landscape_png.jpg', 'b_portrait.jpg', 'c_small.jpg']
    with Image.open(out / 'a_landscape.jpg') as im:
        assert im.size == (1795, 1205) and im.info['dpi'] == (300, 300) and im.info['icc_profile'] == SRGB_BYTES
    with Image.open(out / 'b_portrait.jpg') as im:
        assert im.size == (1205, 1795)
    rows = list(csv.DictReader((out / 'report.csv').open(encoding='utf-8-sig'), delimiter=';'))
    assert len(rows) == len(photos) and (out / 'report.json').exists()


def test_export_16bit_tiff_matches_source(photo_folder):
    import cv2
    photos = [inspect(photo_folder / 'b_portrait.png')]
    out, report = export_batch(photo_folder, photos, Settings(format='TIFF', bit_depth=16), {})
    data = cv2.imdecode(np.fromfile(str(out / 'b_portrait.tif'), np.uint8), cv2.IMREAD_UNCHANGED)[..., ::-1]
    source = np.asarray(Image.open(photo_folder / 'b_portrait.png').convert('RGB'))
    assert data.dtype == np.uint16 and np.array_equal((data // 257).astype(np.uint8), source)


def test_export_keeps_exif_without_gps_and_never_touches_originals(photo_folder):
    img = Image.open(photo_folder / 'a_landscape.jpg')
    exif = img.getexif()
    exif[0x0132] = '2026:10:16 12:00:00'
    exif[0x8825] = {1: 'N'}
    img.save(photo_folder / 'exif.jpg', exif=exif, quality=95)
    before = {p.name: p.read_bytes() for p in photo_folder.iterdir() if p.is_file()}
    out, _ = export_batch(photo_folder, [inspect(photo_folder / 'exif.jpg')], Settings(), {})
    written = Image.open(out / 'exif.jpg').getexif()
    assert written.get(0x0132) == '2026:10:16 12:00:00' and 0x8825 not in written
    after = {p.name: p.read_bytes() for p in photo_folder.iterdir() if p.is_file()}
    assert before == after


def test_export_skips_disallowed_upscale_and_respects_edits(photo_folder):
    photos = [inspect(photo_folder / 'c_small.jpg'), inspect(photo_folder / 'a_landscape.jpg')]
    s = Settings(size_mode='long_edge', long_edge=1000, allow_upscale=False)
    edits = {str(photo_folder / 'a_landscape.jpg'): Edit(rotation=90)}
    out, report = export_batch(photo_folder, photos, s, edits)
    status = {Path(r['source']).name: r['status'] for r in report['results']}
    assert status == {'c_small.jpg': 'skipped', 'a_landscape.jpg': 'ok'}
    with Image.open(out / 'a_landscape.jpg') as im:
        assert im.size[1] > im.size[0]                # rotated photo got a portrait sheet


def test_parallel_and_serial_exports_are_identical(photo_folder):
    photos = [inspect(p) for p in sorted(photo_folder.iterdir())]
    s = Settings(size_mode='long_edge', long_edge=640, format='PNG', adjust=Adjust(auto=True, clarity=20))
    cache = AnalysisCache()
    a, _ = export_batch(photo_folder, photos, s, {}, workers=1, analysis_cache=cache)
    b, _ = export_batch(photo_folder, photos, s, {}, workers=3)
    for name in ('a_landscape.png', 'b_portrait.png', 'c_small.png'):
        assert np.array_equal(np.asarray(Image.open(a / name)), np.asarray(Image.open(b / name)))


def test_export_cancel_keeps_report(photo_folder):
    photos = [inspect(p) for p in sorted(photo_folder.iterdir())]
    stop = threading.Event()
    stop.set()
    out, report = export_batch(photo_folder, photos, Settings(), {}, cancel=stop)
    assert report['cancelled'] and all(r['status'] == 'cancelled' for r in report['results'])
    assert (out / 'report.csv').exists() and not list(out.glob('*.jpg'))


def test_worker_count_is_bounded(photo_folder):
    photos = [inspect(p) for p in photo_folder.iterdir()]
    assert worker_count(Settings(upscaler='esrgan'), photos) == 1
    assert 1 <= worker_count(Settings(), photos) <= len(photos)


def test_cmyk_icc_output_if_profile_available(photo_folder):
    candidates = [Path(r'C:\Windows\System32\spool\drivers\color') / n for n in ('USWebCoatedSWOP.icc', 'CoatedFOGRA39.icc')]
    profile = next((p for p in candidates if p.exists()), None)
    if profile is None:
        pytest.skip('no CMYK profile installed')
    s = Settings(output_space='ICC', icc_path=str(profile), format='TIFF')
    out, report = export_batch(photo_folder, [inspect(photo_folder / 'b_portrait.png')], s, {})
    with Image.open(out / 'b_portrait.tif') as im:
        assert im.mode == 'CMYK'
