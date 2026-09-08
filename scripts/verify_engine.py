"""Read-only integration checks against the actual packaged executable."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build/engine/photo-engine/photo-engine'
QA = ROOT / 'qa'
QA.mkdir(exist_ok=True)

def run(name, command):
    result = subprocess.run([str(BINARY)], input=json.dumps(command), text=True, capture_output=True,
                            env={**os.environ, 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONPATH': ''}, timeout=240)
    data = json.loads(result.stdout)
    (QA / f'frozen-{name}.json').write_text(json.dumps(data, ensure_ascii=False))
    if not data['ok']:
        raise RuntimeError(f'{name}: {data.get("error")}')
    value = data['data']
    print(name, 'OK', f'{len(value["rows"])} rows' if 'rows' in value else '')
    return value

run('ping', {'command': 'ping'})
run('ocr-probe', {'command': 'ocr-probe'})
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    jobs = [pool.submit(run, 'audit', {'command': 'audit'})]
    jobs += [pool.submit(run, kind, {'command': 'plan', 'kind': kind}) for kind in ('classify', 'title', 'duplicates')]
    for job in jobs:
        job.result()
for kind in ('triage', 'sensitive'):
    run(kind, {'command': 'plan', 'kind': kind, 'limit': 3})
plan = json.loads((QA / 'frozen-classify.json').read_text())['data']
if plan['rows']:
    run('preflight', {'command': 'apply', 'plan_id': plan['id'], 'selected': [plan['rows'][0]['id']], 'confirmed': False})
print('All packaged checks passed; no Photos library writes performed.')
