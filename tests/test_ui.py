import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
from PIL import Image
from PySide6.QtWidgets import QApplication
from printprep.engine import Edit, Settings, SRGB_BYTES
from printprep.ui import MainWindow, CropDialog, STYLE


def settle(app, window, timeout=15):
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        app.processEvents()
        busy = window.busy or any(w is not None and w.isRunning() for w in (window.worker, window.preview_worker))
        if not busy and not window.timer.isActive() and not window.summary_timer.isActive() and not window.preview_pending:
            return
        time.sleep(.01)
    raise AssertionError('UI background work did not complete')


def test_folder_preview_rotation_and_ui(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    Image.new('RGB', (1200, 800), '#ae806a').save(tmp_path / 'портрет.jpg', icc_profile=SRGB_BYTES)
    window = MainWindow()
    window.apply_settings(Settings())
    window.show()
    window.load_folder(tmp_path)
    settle(app, window)
    assert len(window.photos) == 1
    assert window.mode == 'batch'
    assert window.preview.picture is None
    window.show_review()
    settle(app, window)
    assert window.preview.picture is not None
    assert window.export_btn.isEnabled()
    assert '1772' in window.info.text()
    window.fit.setCurrentIndex(1)
    window.edits[str(window.photos[0].path)] = Edit(rotation=90, zoom=1.5, manual_crop=True)
    window.schedule_preview()
    settle(app, window)
    assert '1181' in window.info.text()
    im = Image.new('RGB', (900, 600), '#ae806a')
    dialog = CropDialog(im, Settings(), Edit(), window)
    dialog.show()
    app.processEvents()
    assert dialog.canvas.rect.width() > 0
    dialog.rotate(90)
    assert dialog.canvas.im.size == (600, 900)
    dialog.set_zoom(200)
    assert dialog.edit.zoom == 2
    dialog.reset()
    assert dialog.edit == Edit()
    dialog.close()
    window.close()
    app.processEvents()


def test_export_from_interface(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: QMessageBox.StandardButton.Ok)
    app = QApplication.instance() or QApplication([])
    Image.new('RGB', (1000, 1600), '#8bdbbd').save(tmp_path / 'test.jpg', icc_profile=SRGB_BYTES)
    window = MainWindow()
    window.apply_settings(Settings())
    window.show()
    window.load_folder(tmp_path)
    settle(app, window)
    assert window.preset.currentText() == '10 × 15 см'
    window.width.setValue(123)
    assert window.preset.currentText() == 'Свой размер'
    window.preflight()
    window.export()
    settle(app, window)
    assert window.last_output.is_dir()
    assert (window.last_output / 'report.json').exists()
    with Image.open(window.last_output / 'test.jpg.jpg') as im:
        assert im.size == (1453, 1772)
    assert window.output_btn.isEnabled() and window.export_btn.isEnabled()
    assert window.mode == 'done'
    assert 'Готово: 1' in window.done_summary.text()
    window.close()


def test_algorithm_and_named_preset_library(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QInputDialog
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.store = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    window.refresh_library()
    window.apply_settings(Settings())
    window.enhancement_preset.setCurrentIndex(window.enhancement_preset.findData('portrait'))
    assert window.settings().highlights == .3
    assert window.settings().enhancement_preset == 'portrait'
    window.algorithm_controls['clarity'].setValue(25)
    assert window.settings().enhancement_preset == 'custom'
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a: ('Моя бумага', True))
    window.save_library()
    saved = window.settings()
    window.apply_settings(Settings())
    assert window.settings().clarity == 0
    index = window.recipe_library.findData('Моя бумага')
    assert index > 0
    window.load_library(index)
    assert window.settings() == saved
    window.timer.stop()
    window.close()


def test_advanced_panels_are_collapsed_and_reveal_on_demand():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.apply_settings(Settings())
    window.show()
    app.processEvents()
    assert window.advanced_correction.body.isHidden()
    assert window.geometry_disclosure.body.isHidden()
    assert window.ai_disclosure.body.isHidden()
    assert window.icc_button.isHidden()
    window.advanced_correction.toggle.click()
    assert not window.advanced_correction.body.isHidden()
    window.preset.setCurrentIndex(window.preset.count() - 1)
    assert not window.geometry_disclosure.body.isHidden()
    window.space.setCurrentIndex(1)
    assert not window.icc_button.isHidden()
    window.ai_disclosure.toggle.click()
    window.upscaler.setCurrentIndex(1)
    assert window.settings().upscaler == 'fsrcnn'
    assert 'включено' in window.ai_disclosure.toggle.text()
    window.timer.stop()
    window.close()


def test_batch_preset_exports_whole_folder_without_preview(tmp_path, monkeypatch):
    import json
    import printprep.ui as ui
    app = QApplication.instance() or QApplication([])
    for name in ('first.jpg', 'second.jpg', 'third.jpg'):
        Image.new('RGB', (500, 700), '#c0a68a').save(tmp_path / name, icc_profile=SRGB_BYTES)
    window = MainWindow()
    window.apply_settings(Settings())
    window.show()
    preview_loads = []
    monkeypatch.setattr(ui, 'load_rgb', lambda *args, **kwargs: preview_loads.append(args))
    window.load_folder(tmp_path)
    settle(app, window)
    assert window.mode == 'batch'
    assert preview_loads == []
    assert window.list.currentRow() == -1
    window.batch_cards['photo_13x18'].click()
    settle(app, window)
    assert window.settings().width_mm == 130 and window.settings().height_mm == 180
    assert '13 × 18' in window.batch_summary.text()
    assert '3 фото' in window.export_btn.text()
    assert preview_loads == []
    window.export_btn.click()
    settle(app, window)
    assert window.mode == 'done'
    report = json.loads((window.last_output / 'report.json').read_text())
    assert len(report['results']) == 3
    assert all(r['status'] == 'ok' for r in report['results'])
    assert report['settings']['width_mm'] == 130
    assert preview_loads == []
    assert len(list(tmp_path.glob('*.jpg'))) == 3
    window.show_batch()
    assert window.mode == 'batch'
    window.close()


def test_settings_cancel_rolls_back_whole_batch(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.apply_settings(Settings())
    before = window.settings()
    def reject():
        window.width.setValue(250)
        window.upscaler.setCurrentIndex(1)
        return 0
    monkeypatch.setattr(window.settings_dialog, 'exec', reject)
    window.open_settings()
    assert window.settings() == before
    window.close()


def test_empty_folder_has_actionable_message(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    window.load_folder(tmp_path)
    settle(app, window)
    assert window.mode == 'welcome'
    assert not window.export_btn.isEnabled()
    assert 'нет поддерживаемых фотографий' in window.welcome_feedback.text()
    window.close()


def test_small_window_scrolls_presets_without_overlapping(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.apply_settings(Settings())
    window.resize(1080, 760)
    window.show()
    Image.new('RGB', (800, 1200)).save(tmp_path / 'test.jpg')
    window.load_folder(tmp_path)
    settle(app, window)
    first = window.batch_cards['photo_10x15'].geometry()
    second_row = window.batch_cards['photo_20x30'].geometry()
    assert first.bottom() < second_row.top()
    assert window.batch_scroll.verticalScrollBar().maximum() > 0
    assert window.export_btn.isVisible() and window.action_bar.isVisible()
    window.close()
