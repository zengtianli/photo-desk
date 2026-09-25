"""End-to-end check of the automatic-refresh gate in the real app (ViewModel + engine).

    python3 tests/e2e_gate.py <PhotoDesk.app> [--library <x.photoslibrary>] [--work <dir>] [--keep]

Makes an isolated COPY of a Photos database (read-only backup of the source library; the source
is never written), launches the given app passively (open -n -g -j, no activation, no input) with
PHOTODESK_LIBRARY / PHOTODESK_DATA_ROOT / PHOTODESK_PREFERENCES_SUITE pointing at the copy and
refreshSeconds = 30, then commits real SQLite writes to the copy and watches which writes make
the app start its engine and whether the new data reaches the app's output files.

Phases (engine runs counted from the app's own child processes):
  P0 first build              exactly one run at launch
  P1 untouched library        no run for two intervals
  P2 system-style writes      analysis scores, view counts, search/background tables: no run
  P3 photo retitled           one run; the new title reaches the timeline plan
  P4 write during a rebuild   the next check rebuilds again; the later title wins
  P5 burst of edits (import)  one run after the burst settles; the last edit wins
  P6 untouched again          no run
  P7 related column, same UI  one run; engine answers "unchanged": output files are not rewritten
  P8 edit after that          the stretched interval (2x) still delivers the edit within 2 intervals + slack
Exit status 1 if any phase fails. The copy, data root and preference suite are removed afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

REFRESH = 30
PREFS = dict(automatic=True, includeShared=True, recognizeContent=False, refreshSeconds=REFRESH, batchSize=12,
             eventHours=3, eventKilometers=8, meetingMinutes=90, petNames='', preselectDuplicates=True,
             thumbnailWidth=180.0, appearance='light', initialTrack='全部')


def system_library():
    default = Path.home() / 'Pictures/Photos Library.photoslibrary'
    return default if default.is_dir() else None


class Run:
    def __init__(self, app: Path, work: Path, source: Path):
        self.app, self.work, self.t0 = app, work, time.time()
        self.library = work / 'E2E.photoslibrary'
        self.db = self.library / 'database/Photos.sqlite'
        self.data = work / 'data'
        self.suite = f'PhotoDesk.Test.e2e.{os.getpid()}'
        self.log = open(work / 'e2e.log', 'w')
        self.runs: dict[int, list[float]] = {}
        self.pid = None
        self.stop = False
        self.copy_library(source)

    def say(self, *parts):
        line = f'{time.time() - self.t0:7.1f}s ' + ' '.join(str(p) for p in parts)
        print(line, flush=True); self.log.write(line + '\n'); self.log.flush()

    def now(self):
        return time.time() - self.t0

    def copy_library(self, source: Path):
        (self.library / 'database').mkdir(parents=True)
        for name in ('DataModelVersion.plist', 'photos.db', 'metaSchema.db'):
            if (source / 'database' / name).is_file():
                shutil.copy2(source / 'database' / name, self.library / 'database' / name)
        src = sqlite3.connect(f'file:{source / "database/Photos.sqlite"}?mode=ro', uri=True, timeout=30)
        dst = sqlite3.connect(self.db)
        src.backup(dst)  # one step: a consistent snapshot, read-only on the source
        src.close()
        dst.execute('PRAGMA journal_mode=WAL')
        dst.close()
        self.say('isolated copy', self.db, f'{self.db.stat().st_size / 1e6:.0f} MB')
        self.asset, self.attr, self.title0 = self.sql_one(
            """SELECT a.Z_PK, x.Z_PK, x.ZTITLE FROM ZASSET a JOIN ZADDITIONALASSETATTRIBUTES x ON x.ZASSET = a.Z_PK
               WHERE a.ZTRASHEDSTATE = 0 AND a.ZVISIBILITYSTATE = 0 AND a.ZHIDDEN = 0 ORDER BY a.ZDATECREATED DESC LIMIT 1""")

    def sql_one(self, query):
        with sqlite3.connect(self.db, timeout=30) as c:
            return c.execute(query).fetchone()

    def write(self, label, *statements):
        before = self.stamp()
        with sqlite3.connect(self.db, timeout=30) as c:
            for s in statements:
                c.execute(s)
        self.say('WRITE', label, 'stamp moved' if self.stamp() != before else 'STAMP DID NOT MOVE')

    def stamp(self):
        out = []
        for p in (self.db, Path(str(self.db) + '-wal')):
            try:
                s = p.stat(); out.append((s.st_mtime_ns, s.st_size))
            except FileNotFoundError:
                out.append(None)
        return out

    def launch(self):
        data = json.dumps(PREFS).encode().hex()
        subprocess.run(['defaults', 'write', self.suite, 'product.preferences.v1', '-data', data], check=True)
        self.data.mkdir()
        exe = str(self.app / 'Contents/MacOS/PhotoDesk')
        before = set(self.pids(exe))
        subprocess.run(['open', '-n', '-g', '-j', '--env', f'PHOTODESK_LIBRARY={self.library}',
                        '--env', f'PHOTODESK_DATA_ROOT={self.data}', '--env', f'PHOTODESK_PREFERENCES_SUITE={self.suite}',
                        str(self.app)], check=True)
        for _ in range(120):
            new = [p for p in self.pids(exe) if p not in before]
            if new:
                self.pid = new[0]; break
            time.sleep(0.25)
        if not self.pid:
            raise SystemExit('app did not start')
        env = subprocess.run(['ps', '-wwE', '-p', str(self.pid), '-o', 'command='], capture_output=True, text=True).stdout
        if str(self.data) not in env:
            raise SystemExit('launched process is not the isolated instance')
        self.say('pid', self.pid)
        threading.Thread(target=self.watch, daemon=True).start()

    @staticmethod
    def pids(exe):
        out = subprocess.run(['pgrep', '-f', f'^{exe}$'], capture_output=True, text=True).stdout.split()
        return [int(p) for p in out]

    def watch(self):
        while not self.stop:
            ps = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True, text=True).stdout
            now = self.now()
            for line in ps.splitlines():
                f = line.split(None, 2)
                if len(f) == 3 and f[1] == str(self.pid) and 'photo-engine' in f[2]:
                    pid = int(f[0])
                    if pid not in self.runs:
                        self.runs[pid] = [now, now]; self.say('ENGINE start', pid)
                    self.runs[pid][1] = now
            time.sleep(0.3)

    def count(self, a, b):
        return sum(1 for s, _ in self.runs.values() if a <= s < b)

    def running(self):
        return any(self.now() - last < 0.8 for _, last in self.runs.values())

    def wait_until(self, t):
        while self.now() < t:
            time.sleep(0.2)

    def wait_idle(self, limit=60):
        end = self.now() + limit
        while self.running() and self.now() < end:
            time.sleep(0.3)

    def plan_text(self):
        plans = list((self.data / 'plans').glob('*.json'))
        return '\n'.join(p.read_text(errors='replace') for p in plans if 'journey' in p.read_text(errors='replace')[:400])

    def outputs(self):
        return {str(p.relative_to(self.data)): p.stat().st_mtime_ns
                for p in list((self.data / 'plans').glob('*.json')) + list((self.data / 'journey').glob('*/latest.json'))}

    def wait_for_title(self, title, limit):
        end = self.now() + limit
        while self.now() < end:
            if f'"original_title": "{title}"' in self.plan_text():
                return round(self.now(), 1)
            time.sleep(0.5)
        return None

    def retitle(self, title):
        return f"UPDATE ZADDITIONALASSETATTRIBUTES SET ZTITLE = '{title}' WHERE Z_PK = {self.attr}"

    def close(self):
        self.stop = True
        if self.pid:
            for child in subprocess.run(['pgrep', '-P', str(self.pid)], capture_output=True, text=True).stdout.split():
                os.kill(int(child), signal.SIGTERM)
            os.kill(self.pid, signal.SIGTERM)
            for _ in range(20):
                if subprocess.run(['kill', '-0', str(self.pid)], capture_output=True).returncode:
                    break
                time.sleep(0.25)
            else:
                os.kill(self.pid, signal.SIGKILL)
        subprocess.run(['defaults', 'delete', self.suite], capture_output=True)
        plist = Path.home() / f'Library/Preferences/{self.suite}.plist'
        if plist.exists():
            plist.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('app', type=Path)
    ap.add_argument('--library', type=Path, default=None)
    ap.add_argument('--work', type=Path, default=None, help='scratch directory (default: a new temporary one)')
    ap.add_argument('--keep', action='store_true', help='keep the copy and data root for inspection')
    a = ap.parse_args()
    source = a.library or system_library()
    if not source or not (source / 'database/Photos.sqlite').is_file():
        raise SystemExit('no source library; pass --library')
    work = Path(tempfile.mkdtemp(prefix='photodesk-e2e-', dir=a.work))
    r = Run(a.app.resolve(), work, source)
    results, ok = {}, True

    def check(name, passed, **detail):
        nonlocal ok
        ok &= bool(passed)
        results[name] = dict(passed=bool(passed), **detail)
        r.say('PASS' if passed else 'FAIL', name, json.dumps(detail, ensure_ascii=False))

    try:
        r.launch()
        # P0: exactly one build at launch.
        r.wait_until(45); r.wait_idle()
        check('P0_first_build', r.count(0, r.now()) == 1, runs=r.count(0, r.now()))
        # P1: untouched for two intervals plus slack.
        a0 = r.now(); r.wait_until(a0 + 2 * REFRESH + 15)
        check('P1_untouched', r.count(a0, r.now()) == 0, runs=r.count(a0, r.now()))
        # P2: writes like photoanalysisd / the search indexer make: columns and tables the timeline does not use.
        a0 = r.now()
        for i in range(4):
            r.write(f'system-{i}',
                    f'UPDATE ZASSET SET ZCURATIONSCORE = COALESCE(ZCURATIONSCORE, 0) + 0.001 WHERE Z_PK = {r.asset}',
                    f'UPDATE ZADDITIONALASSETATTRIBUTES SET ZVIEWCOUNT = COALESCE(ZVIEWCOUNT, 0) + 1 WHERE Z_PK = {r.attr}',
                    'UPDATE ZGLOBALKEYVALUE SET Z_OPT = COALESCE(Z_OPT, 0) + 1 WHERE Z_PK = (SELECT MIN(Z_PK) FROM ZGLOBALKEYVALUE)')
            r.wait_until(a0 + (i + 1) * 20)
        r.wait_until(a0 + 2 * REFRESH + 25)
        check('P2_system_writes_ignored', r.count(a0, r.now()) == 0, runs=r.count(a0, r.now()))
        # P3: a real edit reaches the app.
        a0 = r.now(); r.write('retitle-1', r.retitle('PhotoDesk-e2e-1'))
        seen = r.wait_for_title('PhotoDesk-e2e-1', 2 * REFRESH + 45)
        r.wait_idle(); r.wait_until(max(r.now(), a0 + REFRESH + 20))
        check('P3_edit_rebuilds_once', r.count(a0, r.now()) == 1 and seen is not None,
              runs=r.count(a0, r.now()), visible_after_s=seen and round(seen - a0, 1))
        # P4: a write while the engine runs must not be lost.
        a0 = r.now(); r.write('retitle-2', r.retitle('PhotoDesk-e2e-2'))
        while not r.running() and r.now() < a0 + 2 * REFRESH + 30:
            time.sleep(0.1)
        r.say('engine running:', r.running()); time.sleep(1.0)
        r.write('retitle-3-during-rebuild', r.retitle('PhotoDesk-e2e-3'))
        seen = r.wait_for_title('PhotoDesk-e2e-3', 2 * REFRESH + 60)
        r.wait_idle(); r.wait_until(max(r.now(), a0 + 3 * REFRESH))
        check('P4_write_during_rebuild', r.count(a0, r.now()) == 2 and seen is not None
              and 'PhotoDesk-e2e-2"' not in r.plan_text(), runs=r.count(a0, r.now()), visible_after_s=seen and round(seen - a0, 1))
        # P5: a burst of edits (like an import) becomes one rebuild after it settles.
        r.wait_until(r.now() + 5)
        a0 = r.now()
        for i in range(6):
            r.write(f'burst-{i}', r.retitle(f'PhotoDesk-e2e-burst-{i}'))
            time.sleep(4)
        seen = r.wait_for_title('PhotoDesk-e2e-burst-5', 2 * REFRESH + 60)
        r.wait_idle(); r.wait_until(max(r.now(), a0 + 2 * REFRESH + 10))
        check('P5_burst_coalesced', r.count(a0, r.now()) == 1 and seen is not None,
              runs=r.count(a0, r.now()), visible_after_s=seen and round(seen - a0, 1))
        # P6: quiet again.
        a0 = r.now(); r.wait_until(a0 + 2 * REFRESH + 10)
        check('P6_untouched_again', r.count(a0, r.now()) == 0, runs=r.count(a0, r.now()))
        # P7: a column the fingerprint covers but that does not change the timeline.
        files = r.outputs(); a0 = r.now()
        r.write('imported-by-name', f"UPDATE ZADDITIONALASSETATTRIBUTES SET ZIMPORTEDBYDISPLAYNAME = COALESCE(ZIMPORTEDBYDISPLAYNAME, '') || 'x' WHERE Z_PK = {r.attr}")
        r.wait_until(a0 + 2 * REFRESH + 20); r.wait_idle()
        check('P7_same_result_not_rewritten', r.count(a0, r.now()) == 1 and r.outputs() == files,
              runs=r.count(a0, r.now()), files_rewritten=r.outputs() != files)
        # P8: after a same-result rebuild the interval stretches (2x), but a real edit still arrives.
        a0 = r.now(); r.write('retitle-after-same', r.retitle('PhotoDesk-e2e-after-same'))
        seen = r.wait_for_title('PhotoDesk-e2e-after-same', 3 * REFRESH + 45)
        r.wait_idle()
        check('P8_edit_after_same_result', r.count(a0, r.now()) == 1 and seen is not None
              and seen - a0 <= 2 * REFRESH + 45, runs=r.count(a0, r.now()), visible_after_s=seen and round(seen - a0, 1))
    finally:
        r.close()
        results['engine_runs'] = {str(k): [round(v[0], 1), round(v[1], 1)] for k, v in sorted(r.runs.items(), key=lambda kv: kv[1][0])}
        (work / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1))
        r.say('RESULTS', json.dumps({k: v['passed'] for k, v in results.items() if isinstance(v, dict) and 'passed' in v}))
        print('results:', work / 'results.json')
        if not a.keep:
            for p in [r.library, r.data]:
                shutil.rmtree(p, ignore_errors=True)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
