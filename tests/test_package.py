from pathlib import Path
import shutil
import zipfile

from tools.package_release import package


def test_archive_has_notices_and_checksums(tmp_path):
    source = Path(__file__).resolve().parents[1]
    shutil.copytree(source / 'licenses', tmp_path / 'licenses')
    app = tmp_path / 'dist' / 'PrintPrep'
    (app / '_internal').mkdir(parents=True)
    # Packaging fixture only; never execute or distribute it as an application.
    (app / 'PrintPrep.exe').write_bytes(b'MZ packaging test fixture')
    (app / '_internal' / 'x.dll').write_bytes(b'fixture')
    for name in ('README.txt', 'THIRD_PARTY.md'):
        shutil.copy(source / name, tmp_path / 'dist' / name)
    package(tmp_path)
    with zipfile.ZipFile(tmp_path / 'dist' / 'PrintPrep-Windows-x64.zip') as archive:
        names = archive.namelist()
        assert 'PrintPrep/PrintPrep.exe' in names and 'PrintPrep/SHA256SUMS.txt' in names
        assert 'PrintPrep/README.txt' in names and 'PrintPrep/_internal/x.dll' in names
        assert 'PrintPrep/licenses/Real-ESRGAN-BSD-3-Clause.txt' in names
        assert 'PrintPrep/licenses/LGPL-3.0-only.txt' in names
        assert any('numpy' in name and 'LICENSE' in name for name in names)
        sums = archive.read('PrintPrep/SHA256SUMS.txt').decode()
        assert 'PrintPrep.exe' in sums and '_internal/x.dll' in sums
