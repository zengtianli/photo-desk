"""Prepare an isolated app copy for CUA background capture; never launch it."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'build/DerivedData/Build/Products/Release/PhotoDesk.app'
TARGET = ROOT / 'build/demo-app/PhotoDesk Demo.app'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=TARGET, help='New app copy under build/demo-app; existing copies are preserved.')
    args = parser.parse_args()
    target = args.target.expanduser().resolve()
    if target.suffix != '.app' or not target.is_relative_to((ROOT / 'build/demo-app').resolve()):
        raise SystemExit('Demo target must be an .app inside build/demo-app.')
    if target.exists():
        raise SystemExit('A demo app copy already exists. Preserve a running capture; choose a new copy explicitly.')
    env = json.loads((ROOT / 'build/demo-input/environment.json').read_text())
    if env.get('PHOTODESK_BACKGROUND') != '1':
        raise SystemExit('Background capture must be explicitly enabled.')
    root = Path(env['PHOTODESK_DEMO_ROOT']).resolve(strict=True)
    data = Path(env['PHOTODESK_DATA_ROOT']).resolve()
    normal = (Path.home() / 'Library/Application Support/PhotoDesk').resolve()
    if root == normal or root.is_relative_to(normal) or data == normal or data.is_relative_to(normal):
        raise SystemExit('The normal PhotoDesk state cannot be used for a recording.')
    if not data.is_relative_to(root) or data == root:
        raise SystemExit('Recording state must live inside the synthetic library.')
    fixture = json.loads((root / 'demo-input.json').read_text())
    if fixture.get('format') != 'photodesk-synthetic-input-v1':
        raise SystemExit('Recording requires a synthetic input manifest.')
    if not env.get('PHOTODESK_PREFERENCES_SUITE', '').startswith('PhotoDesk.Test.'):
        raise SystemExit('Recording requires an isolated preferences suite.')
    info = plistlib.loads((SOURCE / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'cyou.tianli.PhotoDesk' or 'LSEnvironment' in info:
        raise SystemExit('Prepare recordings from the normal distribution bundle only.')
    release = json.loads((ROOT / 'dist/release.json').read_text())
    if (release['version'], release['build']) != (info['CFBundleShortVersionString'], info['CFBundleVersion']):
        raise SystemExit('The recording candidate does not match the current release manifest.')
    data.mkdir(parents=True, exist_ok=True)
    env = {'PHOTODESK_BACKGROUND': '1', 'PHOTODESK_DEMO_ROOT': str(root), 'PHOTODESK_DATA_ROOT': str(data),
           'PHOTODESK_PREFERENCES_SUITE': 'PhotoDesk.Test.ProductDemoBuild' + info['CFBundleVersion']}
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ditto', str(SOURCE), str(target)], check=True)
    path = target / 'Contents/Info.plist'
    info['CFBundleIdentifier'] = 'cyou.tianli.PhotoDesk.ProductDemo.Build' + info['CFBundleVersion']
    info['CFBundleName'] = 'PhotoDesk Demo'
    info['CFBundleDisplayName'] = 'PhotoDesk Demo'
    info['LSUIElement'] = True
    info['LSEnvironment'] = env
    path.write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign', '--force', '--deep', '-s', '-', str(target)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(target)], check=True)
    print(target)
    print(f'v{info["CFBundleShortVersionString"]} build {info["CFBundleVersion"]}; prepared only, not launched.')


if __name__ == '__main__':
    main()
