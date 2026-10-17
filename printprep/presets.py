"""Preset library (built-in + user JSON file), recipe files and per-folder sessions."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path

from .model import BUILTIN_PRESETS, Edit, Settings

LIBRARY_VERSION = 2
MAX_FILE = 5_000_000


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.pp-', dir=path.parent)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def _read_json(path: Path):
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Файл слишком большой.')
    return json.loads(path.read_text(encoding='utf-8'))


class Preset:
    def __init__(self, pid, name, settings: Settings, note='', group='Мои', builtin=False):
        self.id, self.name, self.settings, self.note, self.group, self.builtin = pid, name, settings, note, group, builtin

    def __repr__(self):
        return f'Preset({self.id!r})'


class PresetLibrary:
    """Built-ins are immutable; user presets live in <data>/presets.json."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.path = self.folder / 'presets.json'
        self.user = {}
        self.load()

    def load(self):
        self.user = {}
        if not self.path.exists():
            return
        try:
            data = _read_json(self.path)
            for item in data.get('presets', []):
                name = str(item['name'])[:80]
                self.user[name] = dict(note=str(item.get('note', ''))[:200], settings=Settings.from_dict(item['settings']).to_dict())
        except Exception:
            # Keep a broken file for inspection instead of silently overwriting it.
            backup = self.path.with_suffix('.broken.json')
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            self.user = {}

    def save(self):
        presets = [dict(name=n, note=v['note'], settings=v['settings']) for n, v in sorted(self.user.items(), key=lambda i: i[0].casefold())]
        _atomic_write(self.path, json.dumps({'version': LIBRARY_VERSION, 'presets': presets}, ensure_ascii=False, indent=2))

    def all(self):
        items = [Preset('builtin:' + key, p['name'], replace(p['settings'], adjust=replace(p['settings'].adjust)),
                        p['note'], p['group'], True) for key, p in BUILTIN_PRESETS.items()]
        for name in sorted(self.user, key=str.casefold):
            entry = self.user[name]
            items.append(Preset('user:' + name, name, Settings.from_dict(entry['settings']), entry['note'] or describe(Settings.from_dict(entry['settings'])), 'Мои'))
        return items

    def get(self, pid):
        if not pid:
            return None
        return next((p for p in self.all() if p.id == pid), None)

    def put(self, name, settings: Settings, note=''):
        name = name.strip()[:80]
        if not name:
            raise ValueError('Введите название пресета.')
        settings.validate(check_icc=False)
        self.user[name] = dict(note=note, settings=settings.to_dict())
        self.save()
        return 'user:' + name

    def rename(self, pid, new):
        old = pid.split(':', 1)[1]
        new = new.strip()[:80]
        if not new:
            raise ValueError('Введите название.')
        if new != old and new in self.user:
            raise ValueError('Пресет с таким названием уже есть.')
        self.user[new] = self.user.pop(old)
        self.save()
        return 'user:' + new

    def delete(self, pid):
        self.user.pop(pid.split(':', 1)[1], None)
        self.save()

    def unique_name(self, base):
        name, n = base, 2
        while name in self.user:
            name = f'{base} {n}'
            n += 1
        return name

    def migrate_qsettings(self, store):
        """Import Print Prep 1.x presets kept in QSettings('preset_library') once."""
        if store.value('migrated_v2', False, type=bool):
            return 0
        count = 0
        try:
            old = json.loads(store.value('preset_library', '{}') or '{}')
            for name, values in (old.items() if isinstance(old, dict) else []):
                try:
                    settings = Settings.from_dict(values)
                    self.user[self.unique_name(str(name)[:80])] = dict(note='Перенесён из версии 1.x', settings=settings.to_dict())
                    count += 1
                except Exception:
                    continue
            if count:
                self.save()
        except Exception:
            pass
        store.setValue('migrated_v2', True)
        return count


def describe(s: Settings):
    if s.size_mode == 'original':
        size = 'исходный размер'
    elif s.size_mode == 'long_edge':
        size = f'{s.long_edge} px по длинной стороне'
    elif s.size_mode == 'pixels':
        size = f'{s.pixel_width}×{s.pixel_height} px'
    else:
        size = f'{s.width_mm:g}×{s.height_mm:g} мм · {s.dpi} PPI'
    parts = [size, s.format + (' 16 бит' if s.bit_depth == 16 else '')]
    if s.adjust.auto:
        parts.append(f'авто {s.adjust.auto_strength:.0f}%')
    if s.neural:
        parts.append('нейросеть')
    return ' · '.join(parts)


# ---------------------------------------------------------------- preset & recipe files
def export_preset(path: Path, name, settings: Settings, note=''):
    _atomic_write(Path(path), json.dumps({'kind': 'printprep-preset', 'version': LIBRARY_VERSION, 'name': name,
                                          'note': note, 'settings': settings.to_dict()}, ensure_ascii=False, indent=2))


def read_preset_file(path: Path):
    """Returns (name, settings, edits_by_relative_path). Accepts presets and 1.x/2.x recipes."""
    data = _read_json(Path(path))
    if not isinstance(data, dict) or 'settings' not in data:
        raise ValueError('Это не файл пресета Print Prep.')
    if data.get('version') not in (1, 2):
        raise ValueError('Неизвестная версия файла.')
    settings = Settings.from_dict(data['settings'])
    settings.validate(check_icc=False)
    edits = {}
    for relative, values in (data.get('edits') or {}).items():
        edits[str(relative)] = Edit.from_dict(values).validate()
    return str(data.get('name') or Path(path).stem)[:80], settings, edits


def export_recipe(path: Path, name, settings: Settings, edits_by_relative: dict):
    _atomic_write(Path(path), json.dumps({'kind': 'printprep-recipe', 'version': LIBRARY_VERSION, 'name': name,
                                          'settings': settings.to_dict(),
                                          'edits': {k: v.to_dict() for k, v in edits_by_relative.items()}},
                                         ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- per-folder sessions
def session_path(data_folder: Path, folder: Path):
    digest = hashlib.sha1(str(Path(folder).resolve()).casefold().encode('utf-8')).hexdigest()[:16]
    return Path(data_folder) / 'sessions' / f'{digest}.json'


def save_session(data_folder: Path, folder: Path, edits: dict):
    path = session_path(data_folder, folder)
    payload = {str(Path(k).relative_to(folder)): v.to_dict() for k, v in edits.items()
               if v is not None and not v.is_default() and Path(k).is_relative_to(folder)}
    if not payload:
        if path.exists():
            path.unlink()
        return
    _atomic_write(path, json.dumps({'version': LIBRARY_VERSION, 'folder': str(folder), 'edits': payload}, ensure_ascii=False))


def load_session(data_folder: Path, folder: Path):
    path = session_path(data_folder, folder)
    if not path.exists():
        return {}
    try:
        data = _read_json(path)
        return {str(Path(folder) / k): Edit.from_dict(v).validate() for k, v in data.get('edits', {}).items()}
    except Exception:
        return {}
