"""Package an already tested Windows executable with notices and checksums."""
from importlib.metadata import distribution
from pathlib import Path
import hashlib
import shutil
import zipfile


def package(root):
    dist = root / 'dist'
    exe = dist / 'PrintPrep.exe'
    if exe.read_bytes()[:2] != b'MZ':
        raise ValueError('Expected a Windows executable, not a renamed non-Windows binary')
    licenses = dist / 'licenses'
    shutil.copytree(root / 'licenses', licenses, dirs_exist_ok=True)
    # Some Qt wheels contain no license files, so the pinned project's license
    # texts are also retained in the source tree rather than silently omitted.
    for name in ('Pillow', 'PySide6_Essentials', 'shiboken6', 'numpy', 'opencv-contrib-python-headless', 'PyInstaller'):
        metadata = distribution(name)
        for file in metadata.files or []:
            if any('license' in part.lower() or 'copying' in part.lower() for part in file.parts) and str(file).lower().endswith(('.txt', '.md', '.rst', 'copying', 'license', '.html')):
                source = Path(metadata.locate_file(file))
                if source.is_file():
                    dest = licenses / name / str(file).replace('..', '_')
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(source.read_bytes())
    (dist / 'SHA256SUMS.txt').write_text(hashlib.sha256(exe.read_bytes()).hexdigest() + '  PrintPrep.exe\n', encoding='ascii')
    with zipfile.ZipFile(dist / 'PrintPrep-Windows-x64.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for filename in ('PrintPrep.exe', 'README.txt', 'THIRD_PARTY.md', 'SHA256SUMS.txt'):
            archive.write(dist / filename, filename)
        for path in sorted(licenses.rglob('*')):
            if path.is_file():
                archive.write(path, str(path.relative_to(dist)))
    print('Packaged PrintPrep-Windows-x64.zip')


if __name__ == '__main__':
    package(Path(__file__).resolve().parents[1])
