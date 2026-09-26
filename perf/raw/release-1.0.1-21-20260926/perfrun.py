"""Passive idle measurement of PhotoDesk builds (round 2).

  perfrun.py single <tag> <App> [--settle 45] [--seconds 60]
  perfrun.py concurrent <minutes> <tag>=<App> [<tag>=<App> ...]

Each instance: own copy of the engine cache (sqlite backup of the user's journey index) as
PHOTODESK_DATA_ROOT, own empty preference suite (defaults: refresh 60 s, recognition on), real
system library read-only. Launch with open -n -g -j; no activation, no input. A 1 Hz sampler
records every photo-engine child: CPU time, peak RSS and peak phys_footprint. Photos.sqlite /
-wal stamps are logged each second. measure.py idle (main only, and --with-helpers) runs after
the settle period. Own processes are killed at the end.
"""
import json, os, signal, sqlite3, subprocess, sys, threading, time, datetime, glob, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = Path('<scratch>/runs')
MEASURE = '~/Apps/.claude/skills/app-lightweight/scripts/measure.py'
LIBDB = Path.home() / 'Pictures/Photos Library.photoslibrary/database/Photos.sqlite'
USERJOURNEY = Path.home() / 'Library/Application Support/PhotoDesk/journey'


def ts():
    return datetime.datetime.now().strftime('%H:%M:%S')


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout


def footprint_kb(pid):
    out = sh('footprint', '-p', str(pid))
    for line in out.splitlines():
        if 'phys_footprint:' in line:
            v = line.split('phys_footprint:')[1].split()
            n = float(v[0]); unit = v[1] if len(v) > 1 else 'KB'
            return n * {'KB': 1, 'MB': 1024, 'GB': 1024 * 1024, 'B': 1 / 1024}.get(unit, 1)
    return None


def cpu_s(t):
    t = t.strip()
    if '-' in t:
        d, t = t.split('-'); days = int(d)
    else:
        days = 0
    parts = [float(x) for x in t.split(':')]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return days * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


class Instance:
    def __init__(self, tag, app, out):
        self.tag, self.app, self.out = tag, Path(app).resolve(), out
        self.exe = str(self.app / 'Contents/MacOS/PhotoDesk')
        self.data = out / 'data'; self.suite = f'PhotoDesk.Test.perf.{tag}.{os.getpid()}'
        self.engines = {}  # pid -> dict(first, last, cpu, rss_kb, fp_kb)
        self.pid = None; self.stop = False
        (self.data / 'journey').mkdir(parents=True, exist_ok=True)
        for src in USERJOURNEY.glob('*/index.sqlite'):
            dst = self.data / 'journey' / src.parent.name / 'index.sqlite'; dst.parent.mkdir(parents=True, exist_ok=True)
            a = sqlite3.connect(f'file:{src}?mode=ro', uri=True); b = sqlite3.connect(dst); a.backup(b); a.close(); b.close()

    def launch(self):
        before = set(sh('pgrep', '-f', f'^{self.exe}$').split())
        subprocess.run(['open', '-n', '-g', '-j', '--env', f'PHOTODESK_DATA_ROOT={self.data}',
                        '--env', f'PHOTODESK_PREFERENCES_SUITE={self.suite}', str(self.app)], check=True)
        for _ in range(120):
            new = [p for p in sh('pgrep', '-f', f'^{self.exe}$').split() if p not in before]
            if new:
                self.pid = int(new[0]); break
            time.sleep(0.25)
        env = sh('ps', '-wwE', '-p', str(self.pid), '-o', 'command=')
        assert str(self.data) in env, 'not the isolated instance'
        self.t0 = time.time()
        threading.Thread(target=self.sample, daemon=True).start()
        return self.pid

    def sample(self):
        while not self.stop:
            now = time.time() - self.t0
            for line in sh('ps', '-axo', 'pid=,ppid=,time=,rss=,command=').splitlines():
                f = line.split(None, 4)
                if len(f) == 5 and f[1] == str(self.pid) and 'photo-engine' in f[4]:
                    p = int(f[0]); e = self.engines.setdefault(p, dict(first=now, last=now, cpu=0.0, rss_kb=0, fp_kb=0))
                    e['last'] = now; e['cpu'] = max(e['cpu'], cpu_s(f[2])); e['rss_kb'] = max(e['rss_kb'], int(f[3]))
                    fp = footprint_kb(p)
                    if fp: e['fp_kb'] = max(e['fp_kb'], fp)
            time.sleep(1)

    def engines_between(self, a, b):
        return {p: e for p, e in self.engines.items() if a <= e['first'] < b}

    def quit(self):
        self.stop = True
        for c in sh('pgrep', '-P', str(self.pid)).split():
            os.kill(int(c), signal.SIGTERM)
        os.kill(self.pid, signal.SIGTERM)
        for _ in range(40):
            if subprocess.run(['kill', '-0', str(self.pid)], capture_output=True).returncode:
                break
            time.sleep(0.25)
        else:
            os.kill(self.pid, signal.SIGKILL)
        subprocess.run(['defaults', 'delete', self.suite], capture_output=True)
        plist = Path.home() / f'Library/Preferences/{self.suite}.plist'
        if plist.exists():
            plist.unlink()


def dbwatch(stop, log):
    last = None
    while not stop.is_set():
        cur = []
        for p in (LIBDB, Path(str(LIBDB) + '-wal')):
            try:
                s = p.stat(); cur.append([s.st_mtime_ns, s.st_size])
            except FileNotFoundError:
                cur.append(None)
        if cur != last:
            log.write(json.dumps({'t': ts(), 'stamp': cur}) + '\n'); log.flush(); last = cur
        time.sleep(1)


def load():
    return sh('sysctl', '-n', 'vm.loadavg').strip()


def single(tag, app, settle=45, seconds=60):
    out = RUNS / tag; out.mkdir(parents=True, exist_ok=False)
    stop = threading.Event(); dblog = open(out / 'dbwatch.jsonl', 'w')
    threading.Thread(target=dbwatch, args=(stop, dblog), daemon=True).start()
    inst = Instance(tag, app, out)
    env = {'tag': tag, 'app': str(inst.app), 'start': ts(), 'load_start': load()}
    pid = inst.launch(); env['pid'] = pid
    while time.time() - inst.t0 < settle:
        time.sleep(0.5)
    env['window_start'] = ts(); w0 = time.time() - inst.t0
    m1 = subprocess.Popen(['python3', MEASURE, 'idle', str(pid), '--seconds', str(seconds)], stdout=subprocess.PIPE, text=True)
    m2 = subprocess.Popen(['python3', MEASURE, 'idle', str(pid), '--with-helpers', '--seconds', str(seconds)], stdout=subprocess.PIPE, text=True)
    main_out, helper_out = m1.communicate()[0], m2.communicate()[0]
    w1 = time.time() - inst.t0; env['window_end'] = ts(); env['load_end'] = load()
    fp_after = [footprint_kb(pid) for _ in range(3)]
    inst.quit(); stop.set()
    (out / 'measure_main.json').write_text(main_out); (out / 'measure_helpers.json').write_text(helper_out)
    engines = {str(p): dict(e, first=round(e['first'], 1), last=round(e['last'], 1)) for p, e in inst.engines.items()}
    summary = dict(env, window_s=[round(w0, 1), round(w1, 1)], main=json.loads(main_out)['idle'],
                   total=json.loads(helper_out)['idle'], footprint_after_kb=fp_after,
                   engines_all=engines, engines_in_window=len(inst.engines_between(w0, w1)))
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    shutil.rmtree(inst.data, ignore_errors=True)
    print(json.dumps({k: summary[k] for k in ('tag', 'engines_in_window', 'load_start')}, ensure_ascii=False),
          'main', summary['main']['footprint_mb'], summary['main']['cpu_pct'], 'total', summary['total']['footprint_mb'], summary['total']['cpu_pct'],
          'engines', [(e['first'], e['cpu'], round(e['rss_kb'] / 1024), round(e['fp_kb'] / 1024)) for e in engines.values()], flush=True)


def concurrent(minutes, pairs):
    out = RUNS / ('concurrent-' + datetime.datetime.now().strftime('%H%M')); out.mkdir(parents=True)
    stop = threading.Event(); dblog = open(out / 'dbwatch.jsonl', 'w')
    threading.Thread(target=dbwatch, args=(stop, dblog), daemon=True).start()
    insts = []
    for tag, app in pairs:
        (out / tag).mkdir()
        i = Instance(tag, app, out / tag); i.launch(); insts.append(i)
        print(ts(), 'launched', tag, i.pid, flush=True); time.sleep(20)
    settle_until = time.time() + 45
    while time.time() < settle_until:
        time.sleep(1)
    start = {i.tag: (time.time() - i.t0, cpu_s(sh('ps', '-o', 'time=', '-p', str(i.pid)))) for i in insts}
    env = {'start': ts(), 'load_start': load(), 'minutes': minutes}
    fps = {i.tag: [] for i in insts}
    end = time.time() + minutes * 60
    while time.time() < end:
        time.sleep(60)
        for i in insts:
            fps[i.tag].append(footprint_kb(i.pid))
        print(ts(), {i.tag: len(i.engines_between(start[i.tag][0], 1e9)) for i in insts}, flush=True)
    env['end'] = ts(); env['load_end'] = load()
    result = {}
    for i in insts:
        w0 = start[i.tag][0]; w1 = time.time() - i.t0
        main_cpu = cpu_s(sh('ps', '-o', 'time=', '-p', str(i.pid))) - start[i.tag][1]
        eng = i.engines_between(w0, w1)
        result[i.tag] = dict(app=str(i.app), window_s=round(w1 - w0, 1), main_cpu_s=round(main_cpu, 2),
                             main_cpu_pct=round(main_cpu / (w1 - w0) * 100, 3), engine_runs=len(eng),
                             engine_cpu_s=round(sum(e['cpu'] for e in eng.values()), 2),
                             engine_cpu_pct=round(sum(e['cpu'] for e in eng.values()) / (w1 - w0) * 100, 3),
                             engine_peak_rss_mb=[round(e['rss_kb'] / 1024) for e in eng.values()],
                             engine_peak_footprint_mb=[round(e['fp_kb'] / 1024) for e in eng.values()],
                             engine_starts_s=[round(e['first'] - w0, 1) for e in eng.values()],
                             main_footprint_mb_samples=[round((f or 0) / 1024, 1) for f in fps[i.tag]])
    for i in insts:
        i.quit()
    stop.set()
    (out / 'summary.json').write_text(json.dumps(dict(env=env, result=result), ensure_ascii=False, indent=1))
    for i in insts:
        shutil.rmtree(i.data, ignore_errors=True)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    if sys.argv[1] == 'single':
        single(sys.argv[2], sys.argv[3])
    else:
        concurrent(float(sys.argv[2]), [a.split('=', 1) for a in sys.argv[3:]])
