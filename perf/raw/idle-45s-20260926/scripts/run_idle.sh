#!/bin/bash
# 用法: run_idle.sh <App 路径> <标签>
# 被动测量：open -n -g -j 后台启动 → 静置 45s → measure.py idle 60s（主进程）；并记录引擎子进程 CPU；末尾 footprint/vmmap/sample；最后关闭自己启动的进程。
set -u
APP="$1"; TAG="$2"
D=<scratch>/lw/photodesk
RAW=~/Apps/photo-desk/perf/raw
OUT=$D/runs/$TAG; mkdir -p "$OUT"
EXE="$APP/Contents/MacOS/PhotoDesk"
if pgrep -f "^$EXE\$" >/dev/null; then echo "已有同路径进程在运行，退出"; exit 1; fi
{ echo "tag=$TAG app=$APP"; date "+start %F %T"; uptime; sysctl vm.swapusage; } > "$OUT/env.txt"
T0=$(python3 -c 'import time;print(time.time())')
open -n -g -j "$APP"
PID=""
for i in $(seq 1 60); do PID=$(pgrep -f "^$EXE\$" | head -1); [ -n "$PID" ] && break; sleep 0.5; done
[ -z "$PID" ] && { echo "未找到进程"; exit 1; }
echo "pid=$PID" >> "$OUT/env.txt"
# 子进程监视：全程每 0.5s 记录 ppid==PID 的引擎进程累计 CPU
( while kill -0 $PID 2>/dev/null; do
    python3 - "$PID" >> "$OUT/children.tsv" <<'PY'
import subprocess,sys,time
pid=sys.argv[1]
out=subprocess.run(["ps","-axo","pid=,ppid=,time=,rss=,command="],capture_output=True,text=True).stdout
now=time.time()
for line in out.splitlines():
    f=line.split(None,4)
    if len(f)==5 and f[1]==pid and "photo-engine" in f[4]:
        t=f[2]; d,_,r=t.rpartition("-"); parts=[float(x) for x in r.split(":")]
        s=sum(v*60**i for i,v in enumerate(reversed(parts)))+(int(d)*86400 if d else 0)
        print(f"{now:.2f}\t{f[0]}\t{s:.2f}\t{f[3]}")
PY
    sleep 0.5; done ) &
WATCH=$!
# 静置 45 秒（自进程出现起）
while python3 -c "import time,sys;sys.exit(0 if time.time()-$T0<45 else 1)"; do sleep 1; done
W0=$(python3 -c 'import time;print(time.time())')
python3 ~/Apps/.claude/skills/app-lightweight/scripts/measure.py idle "$EXE" --seconds 60 > "$OUT/measure.json" 2>&1
W1=$(python3 -c 'import time;print(time.time())')
echo "window $W0 $W1" >> "$OUT/env.txt"
footprint -v -p $PID > "$OUT/footprint.txt" 2>&1
vmmap --summary $PID > "$OUT/vmmap.txt" 2>&1
sample $PID 5 -file "$OUT/sample.txt" >/dev/null 2>&1
[ "${HEAP:-0}" = 1 ] && heap --sortBySize $PID > "$OUT/heap.txt" 2>&1
ps -o pid,etime,time,rss -p $PID >> "$OUT/env.txt"
{ date "+end %F %T"; uptime; } >> "$OUT/env.txt"
# 关闭自己启动的实例（及其引擎子进程）
for c in $(pgrep -P $PID); do kill $c 2>/dev/null; done
kill $PID 2>/dev/null; for i in $(seq 1 20); do kill -0 $PID 2>/dev/null || break; sleep 0.5; done
kill -0 $PID 2>/dev/null && kill -9 $PID
kill $WATCH 2>/dev/null
# 子进程 CPU：窗口内 = 每个子进程在窗口内的累计 CPU 增量
python3 - "$OUT/children.tsv" $T0 $W0 $W1 > "$OUT/children_summary.json" <<'PY'
import sys,json,collections
path,t0,w0,w1=sys.argv[1],float(sys.argv[2]),float(sys.argv[3]),float(sys.argv[4])
rows=collections.defaultdict(list)
try:
    for line in open(path):
        ts,pid,cpu,rss=line.split("\t"); rows[pid].append((float(ts),float(cpu),int(rss)))
except FileNotFoundError: pass
total_all=0; in_win=0; runs=[]
for pid,s in rows.items():
    s.sort(); first,last=s[0],s[-1]
    total_all+=last[1]
    before=[x for x in s if x[0]<w0]; inside=[x for x in s if w0<=x[0]<=w1]
    if inside:
        base=before[-1][1] if before else 0.0
        in_win+=inside[-1][1]-base
    runs.append({"pid":pid,"first_seen_s":round(first[0]-t0,1),"last_seen_s":round(last[0]-t0,1),"cpu_s":last[1],"peak_rss_mb":round(max(x[2] for x in s)/1024,1)})
print(json.dumps({"engine_runs":runs,"engine_cpu_s_total":round(total_all,2),"engine_cpu_s_in_window":round(in_win,2),"window_s":round(w1-w0,1),"engine_cpu_pct_in_window":round(in_win/(w1-w0)*100,2)},ensure_ascii=False,indent=1))
PY
cat "$OUT/measure.json"; cat "$OUT/children_summary.json"
