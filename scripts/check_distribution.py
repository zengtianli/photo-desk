"""Exercise a relocated frozen engine without reading or writing a Photos library."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile


def run(app: Path, report: Path) -> dict:
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    executable = app / 'Contents/Resources/Engine/photo-engine'
    assert executable.is_file(), 'Bundled engine missing'
    assert (app / 'Contents/Resources/THIRD_PARTY_NOTICES.txt').is_file(), 'Notices missing'
    with tempfile.TemporaryDirectory(prefix='PhotoDesk-isolated-data-') as scratch:
        root = Path(scratch)
        env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(root),
               'PHOTODESK_DATA_ROOT': str(root / 'PhotoDesk'), 'LANG': 'en_US.UTF-8'}
        results = []
        for label, request, expected in (
            ('bundled-runtime', {'command': 'ping'}, True),
            ('local-vision-ocr', {'command': 'ocr-probe'}, True),
            ('missing-library-error', {'command': 'audit', 'library': str(root / 'Missing.photoslibrary')}, False),
            ('unknown-command-error', {'command': 'invalid-distribution-check'}, False),
        ):
            result = subprocess.run([str(executable)], cwd='/', env=env, input=json.dumps(request),
                                    text=True, capture_output=True, timeout=120)
            data = json.loads(result.stdout)
            assert result.returncode == 0 and data['ok'] is expected, f'{label}: contract failed'
            if label == 'bundled-runtime':
                assert data['data']['data_root'] == str(root / 'PhotoDesk')
            if label == 'missing-library-error':
                assert '.photoslibrary' in data['error']
            results.append({'check': label, 'passed': True})
        result = {'version': info['CFBundleShortVersionString'], 'build': info['CFBundleVersion'],
                  'architecture': subprocess.check_output(['lipo', '-archs', str(app / 'Contents/MacOS/PhotoDesk')], text=True).strip(),
                  'checks': results, 'photos_library_accessed': False,
                  'gui_and_tcc_tested': False, 'notarized': False}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    run(args.app.resolve(), args.report)
