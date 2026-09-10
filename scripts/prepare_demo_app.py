"""Prepare an isolated app copy for CUA background capture; never launch it."""
import json
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'build/DerivedData/Build/Products/Release/PhotoDesk.app'
TARGET = ROOT / 'build/demo-app/PhotoDesk Demo.app'


def main():
    if TARGET.exists():
        raise SystemExit('A demo app copy already exists. Preserve a running capture; choose a new copy explicitly.')
    env = json.loads((ROOT / 'build/demo-input/environment.json').read_text())
    assert env['PHOTODESK_BACKGROUND'] == '1'
    assert Path(env['PHOTODESK_DATA_ROOT']).is_relative_to(Path(env['PHOTODESK_DEMO_ROOT']))
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ditto', str(SOURCE), str(TARGET)], check=True)
    path = TARGET / 'Contents/Info.plist'
    info = plistlib.loads(path.read_bytes())
    info['CFBundleIdentifier'] = 'cyou.tianli.PhotoDesk.ProductDemo'
    info['CFBundleName'] = 'PhotoDesk Demo'
    info['CFBundleDisplayName'] = 'PhotoDesk Demo'
    info['LSUIElement'] = True
    info['LSEnvironment'] = env
    path.write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign', '--force', '--deep', '-s', '-', str(TARGET)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(TARGET)], check=True)
    print(TARGET)
    print(f'v{info["CFBundleShortVersionString"]} build {info["CFBundleVersion"]}; prepared only, not launched.')


if __name__ == '__main__':
    main()
