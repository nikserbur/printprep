"""Create a source-only archive without caches, Git metadata or user photos."""
from pathlib import Path
import zipfile
root = Path(__file__).resolve().parents[1]
files = [root / name for name in ('.gitignore', 'README.md', 'README.txt', 'THIRD_PARTY.md',
    'requirements.txt', 'requirements-dev.txt', 'build_exe.bat', 'print_prep.py')]
for directory in ('.github', 'assets', 'docs', 'licenses', 'printprep', 'tests', 'tools'):
    files.extend(p for p in (root / directory).rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and p.suffix != '.pyc')
out = root / 'dist' / 'PrintPrep-source.zip'
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, str(Path('PrintPrep') / path.relative_to(root)))
print(f'{out}: {len(files)} files, {out.stat().st_size} bytes')
