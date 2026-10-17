"""Every Russian interface string has an English translation with the same {fields}."""
import ast
import re
import string
from pathlib import Path

import pytest

from printprep import i18n
from printprep.i18n_en import EN

ROOT = Path(__file__).resolve().parents[1] / 'printprep'
CYR = re.compile('[А-Яа-яЁё]')


def tr_keys():
    keys = {}
    for path in ROOT.rglob('*.py'):
        if path.name == 'i18n_en.py':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr' and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                keys.setdefault(node.args[0].value, f'{path.name}:{node.lineno}')
    return keys


def table_keys():
    """Module-level tables are translated where they are shown."""
    from printprep import model
    from printprep.ui import app_settings, inspector, splash, tutorial
    keys = [v[0] for v in model.ADJUST_RANGES.values()] + [v[0] for v in model.LOOKS.values()]
    keys += [n for n, *_ in model.PAPER_SIZES] + [n for n, _ in inspector.PIXEL_PRESETS + inspector.ASPECTS]
    keys += [p[f] for p in model.BUILTIN_PRESETS.values() for f in ('name', 'note', 'group')]
    keys += list(splash.LINES) + [t for step in tutorial.STEPS for t in step[2:]] + [n for _, n in app_settings.THEMES]
    return [k for k in keys if CYR.search(k)]


def fields(text):
    return sorted({f for _, f, _, _ in string.Formatter().parse(text) if f} - {'s'})


def test_every_string_is_translated():
    missing = {k: where for k, where in tr_keys().items() if CYR.search(k) and k not in EN}
    missing.update({k: 'table' for k in table_keys() if k not in EN})
    assert not missing, '\n'.join(f'{where}: {k!r}' for k, where in missing.items())


def test_translations_keep_fields_and_have_no_cyrillic():
    for key, value in EN.items():
        assert fields(key) == fields(value), key
        if key != 'Русский':
            assert not CYR.search(value), value


@pytest.fixture
def english():
    i18n.set_language('en')
    yield
    i18n.set_language('ru')


def test_english_plurals_and_fallback(english):
    assert i18n.tr('Подготовить {n} фото', n=1) == 'Prepare 1 photo'
    assert i18n.tr('Подготовить {n} фото', n=4) == 'Prepare 4 photos'
    assert i18n.tr('{ok} из {n} фото', ok=2, n=1) == '2 of 1 photo'
    assert i18n.tr('Моя свадьба') == 'Моя свадьба'          # user text passes through


def test_builtin_presets_and_window_in_english(desktop_runtime, english, photo_folder):
    from printprep.presets import PresetLibrary
    names = {p.name for p in PresetLibrary(photo_folder).all()}
    assert 'Photo lab 4×6 in' in names and not any(CYR.search(n) for n in names)
    from printprep.ui.main_window import MainWindow
    from conftest import wait_idle
    w = MainWindow()
    w.show()
    w.load_folder(photo_folder)
    wait_idle(desktop_runtime, w)
    assert w.export_btn.text().startswith('Prepare') and w.folder_btn.text().strip() == 'Open folder'
    w.close()
