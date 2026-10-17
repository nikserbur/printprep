"""The one-click installer unpacks cleanly, upgrades in place and never touches a foreign folder."""
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'installer'))
import printprep_setup as setup  # noqa: E402


@pytest.fixture
def payload(tmp_path, monkeypatch):
    archive = tmp_path / 'PrintPrep-Windows-x64.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('PrintPrep/PrintPrep.exe', b'MZ fixture')
        z.writestr('PrintPrep/_internal/new.dll', b'new')
        z.writestr('PrintPrep/README.txt', 'readme')
    monkeypatch.setattr(setup, 'bundled', lambda name: archive)
    return archive


def test_install_unpacks_and_marks_the_folder(tmp_path, payload):
    target = tmp_path / 'Programs' / 'Print Prep'
    exe = setup.install(target, shortcuts=False, registry=False)
    assert exe == target / 'PrintPrep.exe' and exe.read_bytes() == b'MZ fixture'
    assert (target / '_internal' / 'new.dll').exists()
    info = json.loads((target / setup.MARKER).read_text(encoding='utf-8'))
    assert info['registered'] is False and info['shortcuts'] == []
    assert setup.installed_version(target) == info['version']


def test_upgrade_removes_stale_libraries(tmp_path, payload):
    target = tmp_path / 'Print Prep'
    setup.install(target, shortcuts=False, registry=False)
    stale = target / '_internal' / 'old.dll'
    stale.write_bytes(b'old')
    setup.install(target, shortcuts=False, registry=False)
    assert not stale.exists() and (target / '_internal' / 'new.dll').exists()


def test_foreign_folder_gets_its_own_subfolder(tmp_path):
    docs = tmp_path / 'Documents'
    docs.mkdir()
    (docs / 'thesis.docx').write_text('keep me')
    assert setup.resolve_target(docs) == docs / 'Print Prep'
    empty = tmp_path / 'Empty'
    empty.mkdir()
    assert setup.resolve_target(empty) == empty


def test_archive_cannot_escape_the_target(tmp_path, monkeypatch):
    evil = tmp_path / 'evil.zip'
    with zipfile.ZipFile(evil, 'w') as z:
        z.writestr('PrintPrep/../../outside.txt', 'x')
    monkeypatch.setattr(setup, 'bundled', lambda name: evil)
    with pytest.raises(ValueError):
        setup.install(tmp_path / 'inst', shortcuts=False, registry=False)
    assert not (tmp_path / 'outside.txt').exists()
