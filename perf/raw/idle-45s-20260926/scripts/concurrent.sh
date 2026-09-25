#!/bin/bash
# 发布版与新版同时后台启动（open -n -g -j），静置 45s 后同时观测 SECS 秒：主进程 CPU 增量、footprint（每 30s）、引擎子进程次数与 CPU；结束后关闭两者。
set -u
SECS=${SECS:-600}
D=<scratch>/lw/photodesk
OUT=$D/runs/concurrent-$(date +%H%M); mkdir -p $OUT
declare -a APPS=(~/Apps/photo-desk/build/perf-run/PhotoDesk-1.0.1-10-arm64/PhotoDesk.app ~/Apps/photo-desk/build/perf-next/PhotoDesk.app)
{ date "+start %F %T"; uptime; sysctl vm.swapusage; } > $OUT/env.txt
PIDS=()
for A in "${APPS[@]}"; do open -n -g -j "$A"; sleep 20; E="$A/Contents/MacOS/PhotoDesk"; P=""; for i in $(seq 1 60); do P=$(pgrep -f "^$E\$" | head -1); [ -n "$P" ] && break; sleep 0.5; done; PIDS+=("$P"); echo "$A pid=$P" >> $OUT/env.txt; done
T0=$(date +%s)
python3 - "$OUT" "$SECS" "${PIDS[0]}" "${PIDS[1]}" <<'PY'
import subprocess, sys, time, json, re
out, secs, pids = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
names = ['release_1.0.1_10', 'next']
def cpu(t):
    d,_,r = t.rpartition('-'); parts=[float(x) for x in r.split(':')]
    return sum(v*60**i for i,v in enumerate(reversed(parts))) + (int(d)*86400 if d else 0)
def snapshot():
    rows = subprocess.run(['ps','-axo','pid=,ppid=,time=,command='],capture_output=True,text=True).stdout.splitlines()
    main = {}; kids = {}
    for line in rows:
        f = line.split(None,3)
        if len(f) < 4: continue
        if f[0] in pids: main[f[0]] = cpu(f[2])
        if f[1] in pids and 'photo-engine' in f[3]: kids[f[0]] = (f[1], cpu(f[2]))
    return main, kids
def footprint(pid):
    o = subprocess.run(['footprint','-p',pid],capture_output=True,text=True).stdout
    m = re.search(r'Footprint:\s*([\d.]+)\s*(KB|MB|GB)', o)
    return float(m.group(1)) * {'KB':1/1024,'MB':1,'GB':1024}[m.group(2)] if m else None
start = time.time()
while time.time() - start < 45: time.sleep(1)
print("settle-children", snapshot()[1], flush=True)
main0, kids0 = snapshot(); w0 = time.time()
seen = {}  # child pid -> (parent, first cpu in window baseline, last cpu)
for k,(p,c) in kids0.items(): seen[k] = [p, c, c]
fps = {p: [] for p in pids}; last_fp = 0
while time.time() - w0 < secs:
    main, kids = snapshot()
    for k,(p,c) in kids.items():
        if k in seen: seen[k][2] = c
        else: seen[k] = [p, 0.0, c]
    if time.time() - last_fp >= 30:
        for p in pids: fps[p].append(footprint(p))
        last_fp = time.time()
    time.sleep(0.5)
main1, _ = snapshot(); w1 = time.time()
res = {'window_s': round(w1-w0,1)}
for n,p in zip(names,pids):
    runs = [(k, round(v[2]-v[1],2)) for k,v in seen.items() if v[0]==p and v[2]-v[1] > 0.05]
    eng = sum(c for _,c in runs)
    res[n] = {'pid': p, 'main_cpu_pct': round((main1[p]-main0[p])/(w1-w0)*100,2),
              'engine_runs_started_or_active': len(runs), 'engine_cpu_s': round(eng,2),
              'engine_cpu_pct': round(eng/(w1-w0)*100,2),
              'footprint_mb_samples': [round(x,1) if x else None for x in fps[p]],
              'footprint_mb_peak': max(x for x in fps[p] if x), 'footprint_mb_median': sorted(x for x in fps[p] if x)[len([x for x in fps[p] if x])//2]}
json.dump(res, open(out+'/summary.json','w'), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
PY
{ date "+end %F %T"; uptime; } >> $OUT/env.txt
for P in "${PIDS[@]}"; do for c in $(pgrep -P $P); do kill $c 2>/dev/null; done; kill $P 2>/dev/null; done
sleep 3; for P in "${PIDS[@]}"; do kill -0 $P 2>/dev/null && kill -9 $P; done
echo done
