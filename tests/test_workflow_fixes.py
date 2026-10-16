from dataclasses import replace
import json
import time
import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication, QInputDialog, QDialog
from PySide6.QtCore import Qt
from printprep.engine import Settings, Edit, render, scan, export_batch, assess, SRGB_BYTES
from printprep.ui import MainWindow, CropDialog


def settle_editor(app, dialog, timeout=20):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        app.processEvents()
        running = dialog.live_worker is not None and dialog.live_worker.isRunning()
        if not running and not dialog.live_timer.isActive() and not dialog.live_pending:
            assert dialog.last_result is not None, dialog.live_status.text()
            return
        time.sleep(.01)
    raise AssertionError('Live editor did not settle: ' + dialog.live_status.text())


def color_image(w=180, h=120):
    yy, xx = np.mgrid[:h, :w]
    rgb = np.stack((40 + xx % 170, 30 + yy % 150, 180 - xx % 110), axis=2).astype('uint8')
    return Image.fromarray(rgb)


def test_new_preset_is_selected_dirty_update_and_survives_restart(tmp_path, monkeypatch):
    app = QApplication.instance()
    w = MainWindow()
    w.apply_settings(Settings(size_mode='long_edge', long_edge=2048))
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args: ('Сашин пресет', True))
    assert w.save_library()
    assert w.recipe_library.currentData() == 'Сашин пресет'
    assert 'Сашин пресет' in w.batch_summary.text()
    assert not w.update_preset_btn.isEnabled()
    w.long_edge.setValue(4096)
    w.refresh_batch_summary()
    assert w.recipe_library.currentData() == 'Сашин пресет'
    assert 'изменён' in w.recipe_library.currentText()
    assert w.update_preset_btn.isEnabled()
    assert w.update_library()
    assert not w.update_preset_btn.isEnabled()
    assert w.library()['Сашин пресет']['long_edge'] == 4096
    w.close()
    reopened = MainWindow()
    index = reopened.recipe_library.findData('Сашин пресет')
    reopened.load_library(index)
    assert reopened.settings().long_edge == 4096
    assert reopened.recipe_library.currentData() == 'Сашин пресет'
    reopened.close()


def test_builtin_can_be_edited_and_saved_as_named_copy(monkeypatch):
    w = MainWindow()
    w.choose_batch_preset('photo_10x15')
    w.width.setValue(120)
    w.refresh_batch_summary()
    assert w.update_preset_btn.isEnabled()
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args: ('12 × 15', True))
    assert w.update_library()
    assert w.active_preset_key == '12 × 15'
    assert w.settings().width_mm == 120
    w.choose_batch_preset('photo_10x15')
    assert w.settings().width_mm == 100
    w.load_library(w.recipe_library.findData('12 × 15'))
    assert w.settings().width_mm == 120
    w.close()


def test_editor_exposure_saturation_live_before_accept_and_cancel():
    app = QApplication.instance()
    im = color_image()
    initial = Edit()
    settings = Settings(size_mode='original')
    d = CropDialog(im, settings, initial)
    d.show()
    settle_editor(app, d)
    before = d.last_result.tobytes()
    d.sliders['exposure'].setValue(80)
    settle_editor(app, d)
    assert d.last_result.tobytes() != before
    exposed = d.last_result.tobytes()
    d.sliders['saturation'].setValue(0)
    settle_editor(app, d)
    assert d.last_result.tobytes() != exposed
    result = np.asarray(d.last_result)
    assert np.abs(result[..., 0].astype(int) - result[..., 1]).max() <= 1
    d.before_check.setChecked(True)
    assert d.result_view.image.tobytes() == d.last_before.tobytes()
    d.before_check.setChecked(False)
    assert d.result_view.image.tobytes() == d.last_result.tobytes()
    d.undo()
    settle_editor(app, d)
    assert d.edit.saturation == 1
    assert initial == Edit()  # Transactional: caller not changed until accept.
    d.reject()
    assert d.result() == QDialog.DialogCode.Rejected


def test_editor_crop_applies_even_when_batch_is_contain_and_matches_export(tmp_path):
    app = QApplication.instance()
    im = color_image(240, 160)
    im.save(tmp_path / 'source.png', icc_profile=SRGB_BYTES)
    settings = Settings(size_mode='original', fit='contain', format='TIFF')
    d = CropDialog(im, settings, Edit())
    d.show()
    d.zoom.setValue(200)
    settle_editor(app, d)
    assert d.edit.fit == 'cover'
    assert d.last_result.size == (120, 80)
    assert assess(im.size, settings, d.edit)['pixels'] == d.last_result.size
    photos, _ = scan(tmp_path)
    _, report = export_batch(tmp_path, photos, settings, {str(photos[0].path): d.edit})
    with Image.open(report['results'][0]['output']) as exported:
        assert exported.size == d.last_result.size
        assert exported.tobytes() == d.last_result.tobytes()
    d.reject()


def test_neural_live_preview_toggle_undo_and_export_match(tmp_path):
    app = QApplication.instance()
    im = color_image(80, 60)
    im.save(tmp_path / 'source.png', icc_profile=SRGB_BYTES)
    settings = Settings(size_mode='long_edge', long_edge=160, upscaler='fsrcnn', format='TIFF')
    d = CropDialog(im, settings, Edit())
    d.show()
    settle_editor(app, d)
    neural = d.last_result.tobytes()
    assert 'FSRCNN' in d.live_status.text()
    d.neural_check.setChecked(False)
    settle_editor(app, d)
    assert d.edit.use_neural is False
    assert d.last_result.tobytes() != neural
    d.undo()
    settle_editor(app, d)
    assert d.last_result.tobytes() == neural
    photos, _ = scan(tmp_path)
    _, report = export_batch(tmp_path, photos, settings, {str(photos[0].path): d.edit})
    with Image.open(report['results'][0]['output']) as exported:
        assert exported.tobytes() == d.last_result.tobytes()
    d.reject()


def test_original_tiff_preserves_all_pixels_and_pixel_modes(tmp_path):
    im = color_image(180, 120)
    im.save(tmp_path / 'source.png', icc_profile=SRGB_BYTES)
    photos, _ = scan(tmp_path)
    _, report = export_batch(tmp_path, photos, Settings(size_mode='original', format='TIFF'), {})
    with Image.open(report['results'][0]['output']) as exported:
        assert exported.size == im.size
        assert exported.tobytes() == im.tobytes()
    exact = Settings(size_mode='pixels', pixel_width=3840, pixel_height=2160, auto_orientation=False)
    assert render(im, exact, Edit()).size == (3840, 2160)
    edge = Settings(size_mode='long_edge', long_edge=3840)
    assert render(im, edge, Edit()).size == (3840, 2560)
    assert render(im.rotate(90, expand=True), edge, Edit()).size == (2560, 3840)


def test_main_preview_is_exact_at_100_percent_and_navigation(tmp_path):
    from test_ui import settle
    app = QApplication.instance()
    im = color_image()
    im.save(tmp_path / 'source.png', icc_profile=SRGB_BYTES)
    w = MainWindow()
    w.apply_settings(Settings(size_mode='long_edge', long_edge=360, upscaler='fsrcnn'))
    w.show()
    w.load_folder(tmp_path)
    settle(app, w)
    w.show_review()
    settle(app, w)
    expected = render(im, w.settings(), Edit())
    assert w.preview.image.tobytes() == expected.tobytes()
    w.preview_zoom.setCurrentIndex(1)
    assert w.preview.zoom_mode == 1.
    w.step_labels[1].click()
    assert w.mode == 'batch'
    w.step_labels[0].click()
    assert w.mode == 'welcome'
    w.step_labels[1].click()
    assert w.mode == 'batch'
    assert len(w.photos) == 1
    w.close()


def test_settings_live_preview_and_visible_numeric_controls(tmp_path):
    from test_ui import settle
    app = QApplication.instance()
    im = color_image()
    im.save(tmp_path / 'source.png', icc_profile=SRGB_BYTES)
    w = MainWindow()
    w.apply_settings(Settings(size_mode='original'))
    w.show()
    w.load_folder(tmp_path)
    settle(app, w)
    w.settings_dialog.resize(1080, 740)
    w.settings_dialog.show()
    w.schedule_preview()
    settle(app, w)
    assert w.dpi.lineEdit().geometry().width() > 20
    assert w.settings_preview.image.size == im.size
    w.size_mode.setCurrentIndex(w.size_mode.findData('pixels'))
    w.pixel_width.setValue(360)
    w.pixel_height.setValue(200)
    w.auto_orientation.setChecked(False)
    settle(app, w)
    assert w.pixel_width.lineEdit().geometry().width() > 20
    assert w.settings_preview.image.size == (360, 200)
    w.settings_dialog.reject()
    w.close()


def test_original_jpeg_keeps_dimensions_and_reasonable_fidelity(tmp_path):
    im = color_image(600, 400)
    im.save(tmp_path / 'source.png', icc_profile=SRGB_BYTES)
    photos, _ = scan(tmp_path)
    _, report = export_batch(tmp_path, photos, Settings(size_mode='original'), {})
    with Image.open(report['results'][0]['output']) as out:
        assert out.size == im.size
        error = np.mean((np.asarray(out, dtype=float) - np.asarray(im, dtype=float)) ** 2)
        psnr = 10 * np.log10(255**2 / error)
        assert psnr > 38


def test_pixel_modes_do_not_depend_on_ppi_and_huge_output_is_rejected():
    import pytest
    im = color_image()
    for mode in ('pixels', 'long_edge', 'original'):
        s = Settings(size_mode=mode, pixel_width=360, pixel_height=200, long_edge=360)
        assert render(im, s, Edit()).size == render(im, replace(s, dpi=720), Edit()).size
    with pytest.raises(ValueError, match='80 мегапикселей'):
        render(im, Settings(size_mode='long_edge', long_edge=32768), Edit())


def test_rename_and_recipe_roundtrip_preserve_pixel_settings(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    w = MainWindow()
    s = Settings(size_mode='pixels', pixel_width=2560, pixel_height=1440, auto_orientation=False)
    w.apply_settings(s)
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args: ('Мой размер', True))
    w.save_library()
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args: ('Новый размер', True))
    w.rename_library()
    assert w.recipe_library.currentData() == 'Новый размер'
    assert 'Мой размер' not in w.library()
    recipe = tmp_path / 'recipe.json'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(recipe), ''))
    w.save_recipe()
    w.choose_batch_preset('original')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(recipe), ''))
    w.load_recipe()
    assert w.settings() == s
    w.close()
