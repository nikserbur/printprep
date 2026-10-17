"""Package an already tested Windows build folder with notices and checksums."""
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
import hashlib
import shutil
import zipfile

LICENSED = ('Pillow', 'PySide6_Essentials', 'shiboken6', 'numpy', 'opencv-python-headless', 'PyInstaller')


def package(root):
    dist = root / 'dist'
    app = dist / 'PrintPrep'
    exe = app / 'PrintPrep.exe'
    if exe.read_bytes()[:2] != b'MZ':
        raise ValueError('Expected a Windows executable, not a renamed non-Windows binary')
    licenses = app / 'licenses'
    shutil.copytree(root / 'licenses', licenses, dirs_exist_ok=True)
    # Some Qt wheels contain no license files, so the pinned project's license
    # texts are also retained in the source tree rather than silently omitted.
    for name in LICENSED:
        try:
            metadata = distribution(name)
        except PackageNotFoundError:
            continue
        for file in metadata.files or []:
            if any('license' in part.lower() or 'copying' in part.lower() for part in file.parts) and str(file).lower().endswith(('.txt', '.md', '.rst', 'copying', 'license', '.html')):
                source = Path(metadata.locate_file(file))
                if source.is_file():
                    dest = licenses / name / str(file).replace('..', '_')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(source.read_bytes())
    for name in ('README.txt', 'README_EN.txt', 'THIRD_PARTY.md'):
        if (dist / name).exists():
            shutil.copy(dist / name, app / name)
    sums = []
    for path in sorted(app.rglob('*')):
        if path.is_file() and path.suffix.lower() in ('.exe', '.dll', '.pyd', '.onnx', '.npz'):
            sums.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(app).as_posix()}')
    (app / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='ascii')
    archive_path = dist / 'PrintPrep-Windows-x64.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file():
                archive.write(path, str(Path('PrintPrep') / path.relative_to(app)))
    print(f'Packaged {archive_path.name}: {archive_path.stat().st_size / 1e6:.1f} MB')


if __name__ == '__main__':
    package(Path(__file__).resolve().parents[1])
