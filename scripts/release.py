"""Build and stage a private-source, directly downloadable PhotoDesk release."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reuse-build', action='store_true', help='Validate and package the existing bundle; do not compile.')
    args = parser.parse_args()
    if not args.reuse_build:
        subprocess.run(['bash', 'build.sh', '--no-install'], cwd=ROOT, check=True)
    app = ROOT / 'build/DerivedData/Build/Products/Release/PhotoDesk.app'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    version, build = info['CFBundleShortVersionString'], info['CFBundleVersion']
    arch = subprocess.check_output(['lipo', '-archs', str(app / 'Contents/MacOS/PhotoDesk')], text=True).strip()
    if arch != 'arm64':
        raise SystemExit(f'This distribution is Apple Silicon only; got {arch}.')
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    stage = dist / f'PhotoDesk-{version}-{build}-arm64'
    if stage.exists():
        raise SystemExit(f'Release staging already exists: {stage}. Preserve the existing release; use its manifest.')
    stage.mkdir()
    relocated = stage / 'PhotoDesk.app'
    subprocess.run(['ditto', str(app), str(relocated)], check=True)
    shutil.copyfile(ROOT / 'docs/INSTALL.txt', stage / '安装与使用.txt')
    shutil.copyfile(app / 'Contents/Resources/THIRD_PARTY_NOTICES.txt', stage / 'THIRD_PARTY_NOTICES.txt')
    subprocess.run([sys.executable, str(ROOT / 'scripts/check_distribution.py'), str(relocated),
                    '--report', str(dist / 'distribution-check.json')], check=True)
    filename = f'PhotoDesk-{version}-{build}-arm64.zip'
    archive = dist / filename
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(stage), str(archive)], check=True)
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / f'{filename}.sha256').write_text(f'{sha}  {filename}\n')
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT, text=True).strip())
    manifest = {'product': 'PhotoDesk', 'version': version, 'build': build, 'architecture': arch,
                'minimum_macos': info['LSMinimumSystemVersion'], 'filename': filename,
                'sha256': sha, 'bytes': archive.stat().st_size, 'signing': 'ad-hoc', 'notarized': False,
                'source_commit': source, 'source_dirty': dirty, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'homepage': 'https://app-mac-photodesk.tianli.cyou/',
                'privacy': 'Local photo analysis; no photo upload or external model calls.',
                'photos_mutated_during_distribution_check': False}
    (dist / 'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Release: {archive}\nSHA-256: {sha}')


if __name__ == '__main__':
    main()
