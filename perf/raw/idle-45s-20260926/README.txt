PhotoDesk 空闲实测原始样本（2026-09-25/26，Mac16,12 / Apple M4 / macOS 27.2，真实图库 6,373 项）
- base1, base2, base3：发布版 1.0.1 (10)（build/perf-run 解压副本），open -n -g -j 后台启动，静置 45s，measure.py idle 60s。
- next1, next2, nextA3, next4, next5, next6, next7, next8：本轮源码（LibraryStamp 跳过未变图库的重建），同一方法。
- next3-ab-relief-withdrawn：曾试加 malloc_zone_pressure_relief，脏页无可测差异，已撤回；仅作记录。
- children_summary.json：同一进程派生的 photo-engine 子进程（每 0.5s ps 采样）在窗口内的 CPU。
- photos-db-watch.txt：每 10s 记录 Photos.sqlite / -wal 的 mtime(秒) 与字节数，只在变化时写一行；用于判断窗口内的重建是否由真实图库写入触发。
- concurrent-0015-release-stalled：两实例同时启动时发布版未进入自动整理（0 次引擎、43MB 恒定），发布版数据作废；新版 10 分钟数据有效（期间图库无写入）。
- concurrent-0026：错开 20s 启动后并行 5 分钟，同一图库写入活动下的对比。
- 测量期间本机负载均值 13–400（前半段 100–400，00:37 之后降到 13–30）、交换区约 16–17 GB 几乎用满，另有用户自己的 /Applications/PhotoDesk 实例（build 18）在运行；进程自身内存与 CPU 可比，墙钟偏慢。
