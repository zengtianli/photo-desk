"""Explicitly refresh a source snapshot; normal builds do not import another app."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('/Users/tianli/Apps/apple-data/engine/photo/photocli/photocli')
DEST = ROOT / 'vendor/photocli'

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--sync', action='store_true')
    a = p.parse_args()
    manifest_path = ROOT / 'vendor/manifest.json'
    if a.sync:
        DEST.mkdir(parents=True, exist_ok=True)
        for f in SOURCE.glob('*.py'):
            shutil.copy2(f, DEST / f.name)
        hashes = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in DEST.glob('*.py')}
        manifest_path.write_text(json.dumps({'source': str(SOURCE), 'sha256': hashes}, indent=2) + '\n')
    manifest = json.loads(manifest_path.read_text())
    for name, digest in manifest['sha256'].items():
        assert hashlib.sha256((DEST / name).read_bytes()).hexdigest() == digest, name
    print('Vendored engine verified:', len(manifest['sha256']), 'files')

if __name__ == '__main__':
    main()
