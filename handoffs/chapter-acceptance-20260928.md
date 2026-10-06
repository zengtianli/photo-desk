# Chapter 固定验收 · 2026-09-28

本轮授权仅限本仓修改、合成输入实测与本地提交；没有 push、发版、装机、部署或系统图库写入。启动时已有未提交的 `perf/acceptance/`、`perf/delivery-evidence.json`，保留并由 Chapter 更新，不加入本轮提交。没有修改共享模块。

## 已落地

- `scripts/accept/_common.py` 共用隔离合成图库；通过 Chapter 原版 `verify_build_receipt` 核对当前源码、实际 App 可执行文件、版本及图标。旧包或缺来源记录会拒绝验收。
- `scripts/accept/build.py` 使用 Chapter `build-receipt` 实际构建，固定 `--no-install`。构建产物为 `build/DerivedData/Build/Products/Release/PhotoDesk.app`。源码范围覆盖 Swift、Python、vendor、锁文件与构建工具，不再遗漏后端。
- `project.yaml` 登记 functionality、recovery、privacy、native_ui 四个固定验收命令。
- 功能验收实跑 10 张合成图：时间线守恒、猫与会议归类、2 份重复/1 份预选、真实 Vision/OCR、计划/历史回读、实际 Swift decoder。
- 恢复验收实跑跨进程缓存恢复、坏请求/坏输入不污染状态、缺失计划重建、无变化不重写。
- 隐私验收用内核沙箱禁止子进程网络并作正控制，确认核心引擎/Vision仍能运行；验证演示模式拒绝写入/删除、路径与符号链接越界、引擎新建数据 owner-only 权限。
- App 的 `--ui-self-test` 在正常 SwiftUI 启动前分流；禁止激活、不创建可见窗口、不注册输入监视器。16 项断言覆盖首页先选中、片段/照片计数、多选固定成员、预览打开/关闭、片段详情、范围选择、搜索隔离、宽度自适应、设置保存与刷新。生成 5 张真实离屏截图，主 agent 已查看。
- 首次 UI 自检因设置页固定尺寸与容器期望不符失败；已修测试容器尺寸、背景和首次布局时机，同一固定脚本复验通过。设置页原生 TabView 顶部层未完整离屏捕获；表单可见，不宣称前台标签栏已视觉验收。
- 既有快捷键测试遗漏 `JourneyResult.digest` 参数，已补齐。`scripts/test.sh` 把 32 项 Python 回归和实际 Swift product-controls 检查接到 `sop.test`；主 agent 实跑通过，快捷键只用假注册器与独立偏好。
- `docs/demo/tutorial.md` 补面向用户的教程，并由双语 README 与 `sop.media` 引用。既有两段实录全片解码和 SHA-256 由主 agent 核对通过；本轮没有补录。录像仍为 1.0.1（10），发行资料为 1.0.1（21）；`recording.json` 补当前源代码与界面复核的沿用理由。

## 固定复现与最终原件

```bash
cd /Users/tianli/Apps/photo-desk
uv run python scripts/accept/build.py
~/Dev/.venv/bin/python ../chapter/engine/app_sop.py accept --app photo-desk \
  --check functionality --check recovery --check privacy --check native_ui --json
bash scripts/test.sh
```

主 agent 提交后再次构建并统一执行四项 accept。最终版本/构建/源码来源读 `perf/build-receipt.json`；各项原始日志、检查值和截图读 `perf/acceptance/`；通过结论只由 `app_sop accept` 写入 `perf/delivery-evidence.json`。这些机器原件保留本地，不手写通过、不把旧失败改成通过。发布包与已装版均保持原样。

## 需要本人及受阻

1. **installed_icon 仍由本人在 Chapter 确认。** 已准备当前候选 App、包内 `Contents/Resources/AppIcon.icns`、原图 `icon/AppIcon.png` 和离屏截图；没有替本人填写 Dock/Finder 显示验收，也没有装机。
2. **Chapter 全局锁存在其他任务竞争。** 没有终止其他任务；锁释放后 `run --test-only` 已于 02:10 确认当前代码测试通过，紧接的媒体重检再次收到 `busy`（75），保留给 Chapter 队列。后续复查命令：

   ```bash
   ~/Dev/.venv/bin/python ../chapter/engine/app_sop.py run --app photo-desk --test-only --now --offline --json
   ~/Dev/.venv/bin/python ../chapter/engine/app_sop.py run --app photo-desk --stage media --check-only --offline --json
   ```

   媒体检查确认截图/视频/教程齐全；已补充当前源码沿用复核元数据。Chapter 已排队的只读重检仍由 Chapter 执行。
3. **性能证据仍是已发行/已装 1.0.1（21）的实测。** 本轮不等空闲、不做长窗口采样；新自检仅在显式参数下运行，普通 UI 布局与识别算法没有重做，但不把旧数字改写成新候选包实测。后续确需测当前候选时，先由本人决定装机，再满足接电源、闲置 10 分钟及低负载门执行：

   ```bash
   # 仅在本人另行决定装机之后；本轮没有执行
   bash build.sh
   python3 ../.claude/skills/app-lightweight/scripts/batch_measure.py photo-desk
   ```

4. 受本轮不装机/不发版/不部署边界限制，当前候选的运行和教程只在本仓交付。Apple 图库授权、真实写回/删除与系统恢复没有在合成测试中验收；不得把这些脚本的通过扩展到该范围。

现有 `BackendClient.swift` 的 DispatchWorkItem Sendable 编译警告保留，未扩大成并发架构修改。

## 2026-10-05 三项标准收尾（并行轮，photo-desk 与 photo-desk-mobile）

本轮没有改源码、没有构建、没有重新装机，只做核对、推送和排队验收。

已验证：

- 登记测试在当前源码通过：Mac 任务 `923542bb…`、移动端任务 `61f39a93…`（均 19:38）。
- 装机不需要重做。`/Applications/PhotoDesk.app` 实际是 1.0.2 (56)，可执行文件 SHA-256 `bb56e3b2…8956` 与 `perf/build-receipt.json`（来源提交 `c1ee0ed`，无未提交改动）及 `dist/PhotoDesk-1.0.2-56-arm64` 三者一致；发布包 SHA-256 `8f6e93da…b3fe` 与 `dist/release.json`、GitHub Release `v1.0.2-56` 一致。Chapter 状态里的「装机 1.0.1 (50)」「README 领先远端 2 个提交」是 ship / promo 阶段没有重读的旧缓存：引擎自己的读取函数现在返回装机 1.0.2 (56)，`git log @{u}..HEAD -- README.md README_EN.md` 为空。
- `dc8c90a`（只含 `perf/` 下的原生界面验收回执和五张合成演示图库截图，逐张看过，无个人照片、无凭证）已推送到 `origin/main`。仓库没有 Pages、webhook、Actions 或 CI 文件，推送不触发构建或部署。

还在队列里：

- `photo-desk` 的整体重检 `2321c0a1…`：跑完后 install、readme 两项才会刷新。Chapter 的 worker 让 test / accept / perf 优先，check 要等这些排空才执行。

没有跑成、留到安静时再排：

- `photo-desk-mobile` 的 iPhone 启动冒烟，仍是「待覆盖」。`1656bed0…` 不是启动失败：共享模拟器车道拿到锁后在等 1 分钟负载降到 15 以下（19:54 读数 16.2），等待期间任务日志没有输出，被队列的 300 秒停滞规则收束，没有写出验收回执。重排的 `a8ce43d9…` 在执行前被取消（机器过热降频，负载门过不去）。Chapter 侧已修停滞误判（`5d7314a`）和重检被饿死（`4075605`）。安静时排一次：`chapter enqueue --app photo-desk-mobile --action accept --check launch_iphone`。

留给统一测量（本轮不测）：

- Mac：实测仍是 1.0.1 (50)，要在已装的 1.0.2 (56) 上重测。装机已是当前源码的已核验构建；`sop.measure` 只登记了 `archive: release`，App 没接 ready 信号，也没登记 `in_use` / `quiet_launch`，所以冷启动测量会在 Dock 冒图标，只能在本人离开时跑。
- iPhone / iPad / Apple Vision Pro：三条线当前输入同为 `1531f438…`。iPhone 旧实测绑定的是 `01c3eda7…`，iPad、Vision 还没有 `perf/platforms/<线>.json`。前置齐全：`sop.measure.command` 走 `scripts/native_platforms.py measure`（覆盖三条线，`in_use: true`），`LaneSignal` 已接，三条线都有 `-lane_demo YES` 启动参数。

本人决定项：移动端「App Store Connect / 实际设备：没有可回读的运行/发布来源」，本轮不处理，不上传、不提审。

## 2026-10-07 每项功能都能不点界面完成（photo-desk 与 photo-desk-mobile）

约定见 app 技能 `references/agent-cli.md`，缺口来源是 Chapter 的 `docs/PRD-agent-cli.md`（R5：`photodesk-import` 没有 `--json` 和读回；R6：`photodesk` 顶层帮助没有退出码）。

做了什么：

- Mac（提交 `1788e4e`）：`photodesk --help` 补齐读命令与写命令、`--json` 输出形状、退出码表、“仅在窗口中”。命令本身和 JSON 结构没改；用法错误仍按原样退出 1（已有测试钉着），帮助里照实写。`project.yaml` 新增 `sop.agent_cli`，读回命令是 `photodesk doctor`。
- 手机端（组件仓提交 `04efb74`）：`photodesk-import` 新增 `status`（不带参数报命令自身，`--package` 读结果包，`--container` 读 `import` 写出的容器）、`event --id`（片段详情与其中照片，`preview` 是核过 SHA 的预览文件路径），`search` 可读 `--container`。加 `--json` 时失败也在 stdout：`{"ok": false, "error": {"code", "message"}}`；用法错误退出 2，未知参数不再被忽略。片段条目新增 `end_date`、`count`、`place`、`tracks`，原有字段与不加 `--json` 时失败写 stderr 的行为不变。Core 与 App 源码没动，手机 App 不用重新构建。

对照结果（从 `Sources/` 与 `App/LibraryView.swift` 逐项列）：

| 组件 | 功能 | 有命令 | 仅真人或仅窗口 | 暂缺 |
|---|---|---|---|---|
| photo-desk | 75 | 49 | 14 | 12 |
| photo-desk-mobile | 13 | 9 | 3 | 1 |

Mac 暂缺 12 项：

- 共享生命周期模块暂无命令入口 5 项：使用 iCloud 记住配置、导出配置…、导入配置…、检查更新、升级到新版…。等共享模块统一出命令后改登记，本仓不各自实现。
- 快捷键 3 项：已绑定的快捷键与冲突提示、作用范围、清除绑定。`shortcuts.v1` 与设置同在一个偏好域，可照 `backend/preferences.py` 的做法加 `photodesk shortcuts`（读、清除、改范围）；组合键的显示名在 Swift 里算，别在 Python 再写一份。
- 暂停 / 继续自动整理、取消进行中的任务：命令够不到正在运行的 App 进程。
- 登录 Mac 时启动：由 App 进程向系统登记（SMAppService），命令读不到也改不了。
- 导入验收测试图…：经 PhotoKit 向系统图库新建合成测试图，只在 App 内。

手机端暂缺 1 项：命令够不到手机上的 App 容器，读不到手机当前导入的是哪一份，也不能替它导入或替换；只能读同一个结果包或 Mac 上 `import` 写出的容器。

怎么验的：

- Mac：`bash scripts/test.sh` 75 项 Python 加 Swift 控件通过。新增两项：帮助里有四样且对照表里的子命令都在帮助的命令列表、每个 human 项都在“仅在窗口中”；`doctor --json` 前后数据目录文件清单不变。
- 手机端：`bash scripts/test-core.sh` 28 个 XCTest 通过；`scripts/smoke_cli.py` 在临时合成结果包上覆盖 `status`、`event`、容器读回、`--json` 失败、退出 2、读命令不写文件；`scripts/test_cli_installation.py` 5 项通过。
- 装机：`scripts/accept/build.py` 从 `1788e4e` 构建 1.0.2 (62)（工作树干净），`scripts/install_app.py` 装机，PhotoDesk 当时未运行、装后没有启动；旧版 56 在废纸篓 `photodesk-install-20261007-010904-0730e8b8`。手机端命令按 README 的 bind → dry-run → install → check 装到 `~/Library/Application Support/PhotoDeskMobile/CLI`（二进制 `3f240628…`，旧版 `519e9ce0…` 目录仍在）。装前装后 `defaults export cyou.tianli.PhotoDesk` 逐字节相同，`~/Library/Application Support/PhotoDesk` 1,439 个文件的大小与修改时间全部相同；手机端运行目录只多了新版本目录并换了 `current.json`。
- 自查：`chapter sop accept --app <组件> --check agent_cli` 两个组件都是“暂缺”，登记与帮助的问题为零，读回命令输出可解析的 JSON。实跑 `photodesk doctor --json` 退出 0，`photodesk timeline --no-such-flag --json` 退出 1 并带 `error`；`photodesk-import status --json` 退出 0，`photodesk-import status --no-such-flag --json` 退出 2 并带 `error.code = usage`。

没做的：

- 上面 13 项暂缺。
- `README.md` / `README_EN.md` 的命令一节没有同步退出码与对照表说明（改 README 会牵动主页与卡片检查，留到下次动 README 时一起）。
- 没有推送、没有发行。装机的 62 比线上发行的 56 新，只差帮助文字与登记；本节提交之后 HEAD 再多一个文档提交。
- 重签名是 ad-hoc，与此前每次装机一样：系统里给 PhotoDesk.app 的完全磁盘访问 / 照片权限是否需要重新勾选，本轮没有打开 App 验证。
- 手机端 `scripts/static_check.py` 在本轮之前就不过（`launch_ipad` 前面带了 `SOP_FUNCTIONAL_THIN=1`，断言要求以 `python3 scripts/native_platforms.py launch` 开头），没有改。
