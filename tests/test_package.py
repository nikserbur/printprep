from pathlib import Path
import shutil
import zipfile
from tools.package_release import package


def test_archive_has_notices_and_checksum(tmp_path):
    source = Path(__file__).resolve().parents[1]
    shutil.copytree(source / 'licenses', tmp_path / 'licenses')
    dist = tmp_path / 'dist'
    dist.mkdir()
    # Packaging fixture only; never execute or distribute it as an application.
    (dist / 'PrintPrep.exe').write_bytes(b'MZ packaging test fixture')
    for name in ('README.txt', 'THIRD_PARTY.md'):
        shutil.copy(source / name, dist / name)
    package(tmp_path)
    with zipfile.ZipFile(dist / 'PrintPrep-Windows-x64.zip') as archive:
        names = archive.namelist()
        assert 'PrintPrep.exe' in names and 'SHA256SUMS.txt' in names
        assert 'licenses/FSRCNN-Apache-2.0.txt' in names
        assert 'licenses/LGPL-3.0-only.txt' in names
        assert any('numpy' in name and 'LICENSE' in name for name in names)
