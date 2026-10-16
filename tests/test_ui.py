"""End-to-end UI checks, including every complaint from the first user review."""
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from printprep.ui.main_window import MainWindow
from printprep.ui.services import to_qimage

from conftest import wait_idle


def image_mean(qimage):
    ptr = qimage.constBits()
    arr = np.frombuffer(ptr, np.uint8, qimage.sizeInBytes()).reshape(qimage.height(), qimage.bytesPerLine())
    return float(arr[:, :qimage.width() * 3].mean())


@pytest.fixture
def window(desktop_runtime, photo_folder):
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    w.load_folder(photo_folder)
    wait_idle(desktop_runtime, w)
    yield w
    w.close()


def test_folder_opens_and_first_photo_renders(desktop_runtime, window):
    assert len(window.photos) == 3 and window.current == 0
    assert window.viewer.fit_img is not None and window.viewer.mode == 'image'
    assert window.export_btn.text() == 'Подготовить 3 фото' and window.export_btn.isEnabled()
    assert window.strip.model_.rowCount() == 3


def test_batch_exposure_slider_updates_preview_live(desktop_runtime, window):
    before = image_mean(window.viewer.fit_img)
    slider = window.inspector.batch_controls['exposure']
    slider.setValue(1.5, emit=True)          # emits valueChanged like a drag
    slider.editingFinished.emit()
    wait_idle(desktop_runtime, window)
    assert window.settings.adjust.exposure == 1.5
    assert image_mean(window.viewer.fit_img) > before + 10


def test_photo_scope_saturation_affects_only_that_photo(desktop_runtime, window):
    window.inspector.set_scope('photo')
    sat = window.inspector.photo_controls['saturation']
    sat.setValue(-100, emit=True)
    sat.editingFinished.emit()
    wait_idle(desktop_runtime, window)
    path = str(window.photos[0].path)
    assert window.edits[path].offsets == {'saturation': -100}
    img = window.viewer.fit_img
    arr = np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3]
    rgb = arr.reshape(img.height(), img.width(), 3).astype(int)
    assert np.abs(rgb[..., 0] - rgb[..., 2]).max() <= 2           # grey on screen before any "apply"
    assert window.settings.adjust.saturation == 0                  # preset untouched
    window.strip.select_row(1)
    wait_idle(desktop_runtime, window)
    assert str(window.photos[1].path) not in window.edits
    assert window.strip.model_.badges[path]['edited']


def test_saved_preset_appears_selected_and_is_editable(desktop_runtime, window, monkeypatch):
    monkeypatch.setattr(QInputDialog, 'getText', staticmethod(lambda *a, **k: ('Саша · глянец', True)))
    window.apply_preset('builtin:lab_10x15')
    window.inspector.batch_controls['vibrance'].setValue(30, emit=True)
    window.inspector.batch_controls['vibrance'].editingFinished.emit()
    assert window.presets.dirty
    window.save_preset_as()
    assert window.active_id == 'user:Саша · глянец' and not window._dirty()
    names = [window.presets.list.item(i).text() for i in range(window.presets.list.count())]
    assert 'Саша · глянец' in names
    # Edit the saved preset and save in place.
    window.inspector.batch_controls['contrast'].setValue(15, emit=True)
    window.inspector.batch_controls['contrast'].editingFinished.emit()
    assert window._dirty() and window.presets.save_btn.isVisibleTo(window.presets)
    window.save_preset()
    assert not window._dirty()
    reloaded = window.library.__class__(window.library.folder).get('user:Саша · глянец')
    assert reloaded.settings.adjust.contrast == 15 and reloaded.settings.adjust.vibrance == 30
    # Switching away and back restores exactly the saved values.
    window.apply_preset('builtin:original')
    window.apply_preset('user:Саша · глянец')
    assert window.settings.adjust.contrast == 15 and window.inspector.batch_controls['contrast'].value() == 15


def test_undo_redo(desktop_runtime, window):
    window.apply_preset('builtin:web')
    window.apply_preset('builtin:archive_tiff')
    assert window.settings.format == 'TIFF'
    window.undo()
    assert window.settings.format == 'JPEG' and window.settings.long_edge == 2048
    window.redo()
    assert window.settings.format == 'TIFF'
    wait_idle(desktop_runtime, window)


def test_size_modes_and_4k(desktop_runtime, window):
    window.inspector.batch_controls['size_mode'].changed.emit('pixels')
    window.inspector.batch_controls['pixel_preset'].setCurrentIndex(1)
    window.inspector._pixel_preset_chosen(1)
    assert (window.settings.pixel_width, window.settings.pixel_height) == (3840, 2160)
    window.inspector.batch_controls['size_mode'].changed.emit('long_edge')
    window.inspector._set('long_edge', 3840, commit=True, refresh=True)
    wait_idle(desktop_runtime, window)
    assert window.viewer.canvas == (3840, 2560)


def test_crop_mode_and_rotation(desktop_runtime, window):
    window.apply_preset('builtin:lab_10x15')
    window.set_crop_mode(True)
    wait_idle(desktop_runtime, window)
    assert window.viewer.mode == 'crop' and window.viewer.crop is not None
    window.viewer.cropEdited.emit(.3, .5, 1.4)
    edit = window.edits[str(window.photos[0].path)]
    assert edit.manual_crop and edit.zoom == 1.4
    window.set_crop_mode(False)
    window.rotate(90)
    wait_idle(desktop_runtime, window)
    assert window.edits[str(window.photos[0].path)].rotation == 90
    assert window.viewer.canvas[1] > window.viewer.canvas[0]


def test_compare_shows_before_image(desktop_runtime, window):
    window.apply_preset('builtin:smart')
    window.compare_btn.setChecked(True)
    wait_idle(desktop_runtime, window)
    assert window.viewer.fit_before is not None and window.viewer.compare


def test_neural_shows_progress_and_result_at_100(desktop_runtime, window):
    window.strip.select_row(2)                    # 300×200 photo
    wait_idle(desktop_runtime, window)
    window.apply_preset('builtin:upscale_small')
    window.inspector.batch_controls['upscaler'].changed.emit('fsrcnn')
    statuses = []
    window.service.status.connect(lambda g, text, p: statuses.append(text))
    window.viewer.set_zoom(1.0)
    wait_idle(desktop_runtime, window, 120)
    deadline = time.monotonic() + 60
    while window.viewer.roi_img is None and time.monotonic() < deadline:
        desktop_runtime.processEvents()
        time.sleep(.02)
    assert window.viewer.roi_img is not None
    assert any('Нейросеть' in s for s in statuses)
    assert any('FSRCNN' in n for n in window.last_result.notes)


def test_export_from_ui(desktop_runtime, window):
    window.apply_preset('builtin:web')
    window.export()
    wait_idle(desktop_runtime, window, 120)
    assert window.toast.isVisible() and 'Готово: 3 из 3' in window.toast.title.text()
    out = window.last_output
    assert len(list(out.glob('*.jpg'))) == 3 and (out / 'report.csv').exists()


def test_session_edits_survive_restart(desktop_runtime, window, photo_folder):
    window.rotate(90)
    window._save_session()
    window.close()
    again = MainWindow()
    again.show()
    again.load_folder(photo_folder)
    wait_idle(desktop_runtime, again)
    assert again.edits[str(window.photos[0].path)].rotation == 90
    again.close()


def test_empty_folder_shows_message(desktop_runtime, tmp_path):
    w = MainWindow()
    w.show()
    w.load_folder(tmp_path)
    wait_idle(desktop_runtime, w)
    assert w.viewer.mode == 'empty' and w.toast.isVisible()
    assert not w.export_btn.isEnabled()
    w.close()


def test_to_qimage_handles_float_and_uint8():
    assert to_qimage(np.zeros((4, 5, 3), np.uint8)).size().width() == 5
    assert to_qimage(np.ones((4, 5, 3), np.float32)).pixelColor(0, 0).red() == 255
