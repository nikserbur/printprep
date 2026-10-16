import json

import pytest
from PySide6.QtCore import QSettings

from printprep.model import Adjust, Edit, Settings
from printprep.presets import (PresetLibrary, export_preset, export_recipe, load_session, read_preset_file,
                               save_session)


def test_library_put_rename_delete_persist(tmp_path):
    lib = PresetLibrary(tmp_path)
    pid = lib.put('Саша · глянец', Settings(size_mode='print', adjust=Adjust(auto=True, auto_strength=40)))
    assert pid == 'user:Саша · глянец'
    again = PresetLibrary(tmp_path)
    assert again.get(pid).settings.adjust.auto_strength == 40
    new = again.rename(pid, 'Глянец 10×15')
    assert again.get(new) and again.get(pid) is None
    with pytest.raises(ValueError):
        again.put('  ', Settings())
    again.delete(new)
    assert PresetLibrary(tmp_path).user == {}
    assert all(p.builtin for p in PresetLibrary(tmp_path).all())


def test_broken_library_is_kept_aside(tmp_path):
    (tmp_path / 'presets.json').write_text('{oops', encoding='utf-8')
    lib = PresetLibrary(tmp_path)
    assert lib.user == {} and (tmp_path / 'presets.broken.json').exists()


def test_migrates_v1_library_from_qsettings(tmp_path):
    store = QSettings(str(tmp_path / 'old.ini'), QSettings.Format.IniFormat)
    store.setValue('preset_library', json.dumps({'Мой старый': dict(size_mode='print', width_mm=100, height_mm=150,
                                                                    sharpen=True, upscaler='lanczos', shadows=.3)}))
    lib = PresetLibrary(tmp_path / 'data')
    assert lib.migrate_qsettings(store) == 1
    assert lib.get('user:Мой старый').settings.sharpen == 'glossy'
    assert lib.migrate_qsettings(store) == 0


def test_preset_and_recipe_files_roundtrip(tmp_path):
    s = Settings(size_mode='pixels', pixel_width=3840, pixel_height=2160, adjust=Adjust(vibrance=12))
    export_preset(tmp_path / 'p.json', 'Экран', s, 'заметка')
    name, settings, edits = read_preset_file(tmp_path / 'p.json')
    assert name == 'Экран' and settings == s and edits == {}
    export_recipe(tmp_path / 'r.json', 'Рецепт', s, {'sub/a.jpg': Edit(rotation=90, offsets={'exposure': .4})})
    _, _, edits = read_preset_file(tmp_path / 'r.json')
    assert edits['sub/a.jpg'].rotation == 90 and edits['sub/a.jpg'].offsets == {'exposure': .4}
    (tmp_path / 'bad.json').write_text('{"version": 9, "settings": {}}', encoding='utf-8')
    with pytest.raises(ValueError):
        read_preset_file(tmp_path / 'bad.json')


def test_reads_v1_recipe(tmp_path):
    (tmp_path / 'old.json').write_text(json.dumps({'version': 1, 'settings': dict(size_mode='original', upscaler='lanczos'),
                                                   'edits': {'a.jpg': dict(rotation=90, exposure=.2, contrast=1, saturation=1)}}),
                                       encoding='utf-8')
    _, settings, edits = read_preset_file(tmp_path / 'old.json')
    assert settings.size_mode == 'original' and edits['a.jpg'].offsets == {'exposure': .2}


def test_sessions_restore_edits_per_folder(tmp_path):
    folder = tmp_path / 'photos'
    folder.mkdir()
    edits = {str(folder / 'a.jpg'): Edit(angle=2.5), str(folder / 'b.jpg'): Edit()}
    save_session(tmp_path / 'data', folder, edits)
    restored = load_session(tmp_path / 'data', folder)
    assert list(restored) == [str(folder / 'a.jpg')] and restored[str(folder / 'a.jpg')].angle == 2.5
    save_session(tmp_path / 'data', folder, {})
    assert load_session(tmp_path / 'data', folder) == {}
