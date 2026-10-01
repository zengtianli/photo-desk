# 照片引擎并入 PhotoDesk 与 photodesk 命令 · 2026-09-29

需求卡：`~/Apps/chapter/requests/photodesk-owns-photo-engine.md`（第一期）。上一轮 Codex 做完三路并行改动后额度用尽，本轮 Claude 接续集成、构建、装机与验收。本轮只做本地提交和装机，未推送、未发布、未部署。

## 结果

- 引擎唯一源码：`backend/photocli/`（apple 仓 75d955b 的 11 个 .py，只拷文件，未引入 apple 历史）。`vendor/`、`scripts/vendor_engine.py` 已删。
- 冻结引擎按参数分派：带参数进 click CLI（`photodesk`，12 个子命令 + `--version`，版本读 App Info.plist）；无参数管道仍走 JSON 契约；终端无参数打印帮助。CLI 产物在 `~/Library/Application Support/PhotoDesk/cli/`（0700），私有配置 `cli-config.yaml` 在同一数据目录，不进仓库。
- 公开版去私人内容：`title.py` 猫名读 `classify.pet_faces`，App 把设置里的猫名随请求传入；文档库只认 `PHOTOCLI_DOCS_DB` 或配置 `docs_db`，只读打开。
- 包内 `Contents/Resources/bin/photodesk` 是指向 `../Engine/photo-engine` 的相对软链；`install_app.py` 维护 `~/.local/bin/photodesk`（已有非软链或指向别的 App 时拒绝）；`check_distribution.py` 从移动后的包调用 `--help`。
- apple 仓（f81910f）：`photo/photocli/photocli/cli.py` 17 行转发 stub（提示后 exec photodesk，找不到退出 69）；删子目录 pyproject/uv.lock/config.yaml；`scripts/lightweight.py` 只删 photo 分支；文档写明去向。根 README/CLAUDE 里 Notihub 卡的未提交段落没有一起提交。
- Chapter：photo 已归档到「已并入 PhotoDesk」。`~/Apps/project.yaml` 的 `apps:photo-capability` 改指 photo-desk（98ec863）；`hq_capabilities.yaml` OCR 例外改新路径（Dev/tools/dev bfeb271）。`apps-portal/site/webapps/appledata.html` 已改为 photodesk（门户自动 sync 提交 97a8ab9），线上位置未核到，随门户下次部署。

## 证据（构建 1.0.1 (36)，源码 9b70f7b）

- `bash scripts/test.sh`：47 项 Python 单测 + Swift 控件测试通过。
- `app_sop accept`：functionality / recovery / privacy / native_ui / cli_entry 全部 passed（`perf/acceptance/`）。privacy 在真实图库只读跑 `photodesk audit --json`（4,692 项），Photos.sqlite/-wal 前后哈希一致。
- 移动后发行包 `check_distribution.py`：relocated-cli-help 等 5 项通过。
- 装机：`/Applications/PhotoDesk.app` = 36，签名 `--deep --strict` 通过；`~/.local/bin/photodesk --version` → 1.0.1 (36)。旧版在 `~/.Trash/photodesk-install-*`。
- 旧入口：`~/Apps/apple-data/engine/.venv/bin/photocli --help` 先打迁移提示再出 photodesk 帮助；`photo/scripts/accept/legacy_forwarding.py` 9 项通过；`uv lock --check` 通过。
- 体积：安装包 89,876 KB，比 1.0.1 (33) 增 16 KB；无第二份 Python。
- CLI 任务资源（`perf/lightweight.json` 的 `cli_task`）：峰值 RSS 226 MB（预算 250），墙钟中位 2.05 s，CPU 中位 1.93 s。

## 后续

- 推送 photo-desk / apple 仓、发行和主页部署由 Chapter 的「一键解决全部」接续；推送前按卡片风险节再查私人路径、猫名与本机知识库路径（本轮 diff 与冻结包检查为零）。
- 不在第一期：apple 根依赖瘦身、App 菜单「安装命令行工具…」、历史 plans/ocr 迁移、本机知识库 doc.py 的 SOURCE 失效路径。
- 回滚：两仓各自 `git revert`；`chapter unarchive --app photo`（先 revert stub）；删 `~/.local/bin/photodesk`；旧 App 从废纸篓放回。

## 发行与性能接续（2026-09-29 03:00）

- 推送 main 到 zengtianli/photo-desk（公开仓，Actions/Webhooks 均为 0，推送不触发构建）。推送前新提交 diff 中私人路径、猫名、本机知识库路径均为零。
- GitHub Release v1.0.1-36（target 9b70f7b）：ZIP 37,369,897 B，SHA-256 647fcef8…，回读一致。`scripts/release.py --reuse-build` 的移动后发行包检查 5 项通过。
- 主页按 `apps-portal/site/deploy.sh --products-only --dry-run` → `--deploy --plan <plan>` 单产品部署两次（发行、实测数字），16 个文件哈希核验通过；线上 release.json = 36 / 9b70f7b，页面含 photodesk 命令说明与新数字。
- project.yaml 新增 `sop.measure: {archive: release}`；batch_measure 对发布包 36 实测：空闲 81 MB（页面按十进制显示 84.9 MB）、CPU 0.02%、冷启动中位 479 ms，负载均值约 7。旧 build 21 的后台任务长窗口数据被测量工具按版本移除，README 轻量块已由 perf_block 重生成。
- Chapter check-only：perf / build-receipt / install / release / test 均 ok；cli_entry 验收 passed。

仍待：演示素材（界面源码自 09-10 录制后有变化，需重录）；门户目录卡片数字由 Chapter 的门户部署自动项更新；装机图标由本人在 Chapter 确认（当前装机 36，包内 AppIcon.icns 与 icon/AppIcon.png 未改）。

## 推广页与素材接续（2026-09-29 04:00）

- homepage_mobile 失败原因：安装教程里新增的长 `ln -s` 命令在 390px 不换行（scrollWidth 456）。`site/style.css` 加 `.cli-note code` 断行规则，单产品部署后 homepage_mobile / homepage_desktop 固定验收均 passed。
- 演示素材：`docs/demo/recording.json` 的 `reused_for` 登记 1.0.1 (36) 沿用 09-10 真实录像。依据：自 33 起界面源码只改 ViewModel 请求参数（附带猫名）；离屏自检 timeline.png 与原录像截图布局、文案一致。Chapter media 已 ok。
- 目录卡片（apps 目录站）数字仍旧：修复需运行整站 `apps-portal/site/deploy.sh`（会刷新全部产品卡片与目录站 nginx 配置），超出本组件部署边界，留待本人授权或 Chapter 门户批量部署。
- 装机 1.0.1 (36)、Chapter install ok；装机图标由本人确认。

## 装机复核（2026-09-29 05:40）

- 回读 /Applications/PhotoDesk.app = 1.0.1 (36)，包内 AppIcon.icns 与当前构建产物逐字节一致；Chapter check-only 的 install、build-receipt 均 ok，未重装。仅剩本人在 Chapter 确认 Dock/Finder 图标。

## 主页 facts.json 上线（2026-09-29 10:10）

- apps-site 在本仓加的 facts.json 生成（a56aa58）已推送；`build_site.py` 重建后按 `deploy.sh --products-only --dry-run` → `--deploy --plan` 单产品部署 17 个文件，哈希核验通过。
- 回读：主页 facts.json 与门户 `/api/facts` 均为 build 36、卡片文字「安装包 37.4 MB（安装后 92.0 MB） · 空闲内存 84.9 MB · 空闲 CPU 0.02% · 速度 479 ms」；homepage_desktop/mobile 复验 passed；Chapter check-only 的 card、install 均 ok。上轮「需整站门户部署」的决策因此不再需要。
- 装机 1.0.1 (36) 已是当前构建，未重装；仅剩本人确认 Dock/Finder 图标。

## 装机复核（2026-09-30 00:05）

- 回读装机 1.0.1 (36)，AppIcon.icns 与当前构建逐字节一致；Chapter check-only 的 install、build-receipt 均 ok，其余项无非 ok，未重装。仅剩本人确认 Dock/Finder 图标。

## Agent CLI：App 功能全部可由 photodesk 驱动（2026-09-30）

- 新增 `backend/desk_cli.py`（命令）与 `backend/preferences.py`（按 App 方式读写 UserDefaults 设置）；`bridge.handle()` 成为 App 管道与命令共用的调度，演示护栏与权限翻译不再只在管道里。新命令：timeline、refresh、audit（改为 App 图库概览口径）、photos、duplicates、plan、plans、plan-show、apply、delete-check、records、progress、settings / settings set、doctor；读命令 `--json` 输出 `{ok,...}`，失败 exit 1。删除仍只在 App 内，命令止于 delete-check；apply 默认预检，`--confirm` 才写，写入加 `locks/apply.lock` 与 App 互斥；timeline 重建加 `journey/<hash>/.lock`。
- 旧命令 classify-plan/title-plan/triage/ocr-scan/classify-apply/title-apply 改为 plan/apply 的别名，旧的第二套写入实现（覆盖已有标题、截图进删除相册、无回执）已删；backup、ocr-extract、shared-list、dedup-export、reconcile 保留为命令行工具。`lib.editable` 成为唯一个人范围。
- 顺带修正共用引擎缺陷：共享 Cloud GUID 的副本在标题/分类计划里取错副本（真实库 833 条标题建议中 3 条预检失败，写入会落到已有标题的副本）；现在每行绑定自身 local_uuid，写入按 local_uuid 解析。
- 验证：`bash scripts/test.sh` 64 项 Python + Swift 控件通过；`bash build.sh --no-install` 与 `scripts/accept/build.py` 构建 1.0.1 (48)（未装机）；functionality 11/11、recovery 11/11、privacy 12/12（真实图库只读审计 passed）。包内 photodesk 读真实数据（时间线 6,393/2,722、概览 4,703 与管道一致、重复 6 组 12 张）；写入类只在沙盒数据目录 + 内核禁写图库下验证（分类 2,804 / 标题 833 行预检通过，changed 0）；settings 与真实 Swift 解码器双向往返。
- 待办：提交后按原流程 `bash build.sh` 装机（PhotoDesk 需退出）并复跑 cli_entry；公开仓推送、发行与主页部署另行授权。管道 `plan kind=duplicates`（仅 QA 脚本用的指纹版重复计划）未退役。
- 复核后修正（同日）：`reconcile`、`shared-list`、`dedup-export` 加 `--json`（`backup`、`ocr-extract` 仍为文本进度，README 已写明）；`--json` 下命令开始前的失败（参数错误、演示护栏、数据目录不可写）也在 stdout 输出 `{ok:false}`，数据目录的建目录/收权限改为尽力而为，读命令不再因元数据写失败而失败；`doctor` 的 app_running、photos_automation 改为 `ok: null`（只说明、未验证），另给 `app_running` 布尔字段；跟随系统图库时 `timeline`/`duplicates`/`delete-check --event/--recommended` 总是核对“照片”最近打开的图库，缓存属于别的图库即报错提示 refresh。最近图库由 `preferences.photos_last_library()` 读取（与 osxphotos 同一 plist 与书签解析，单测核对两者一致），不为读缓存加载 osxphotos：timeline 约 1 s / 120 MB，而导入 osxphotos 需约 3 s / 180 MB。`scripts/test.sh` 与验收 fixture 结束时删除各自的隔离偏好 plist；此前遗留的 26 个空测试 plist 已移到 `~/.Trash/photodesk-cli-20260930/Library/Preferences/`。`bash scripts/test.sh` 73 项通过，重建 1.0.1 (48) 未装机，functionality/recovery 11/11、privacy 12/12。

## 1.0.1 (50) 装机、发行与主页（2026-10-01 11:15）

- 构建：`scripts/accept/build.py` 从干净源码 f9b2d8a 构建 1.0.1 (50)，receipt 输入哈希 376a7362…（与未装机的 48 相同输入，现已提交）；`scripts/install_app.py` 装机（PhotoDesk 未运行，旧版 36 在废纸篓），回读 Info.plist = 50、可执行 SHA-256 与 receipt 一致、`codesign --deep --strict` 通过、`~/.local/bin/photodesk --version` = 1.0.1 (50)。
- 验收（`chapter sop accept`）：functionality、recovery、privacy、native_ui、cli_entry、installed_icon（离屏 IconServices 对比，256/512 px 均差 4.8/5.73）、icon_review、homepage_desktop、homepage_mobile、media_playback 全部 passed。首轮主页/播放三项因本机负载均值约 600 时无界面浏览器超时失败，单独复现通过后重跑一次通过。
- 发行：`scripts/release.py --reuse-build` 生成 ZIP 37,386,079 B，SHA-256 aa4eb6d8…；推送 main（f9b2d8a）后建 GitHub Release v1.0.1-50（target f9b2d8a，latest）。`gh release create/upload` 上传大文件时本机代理多次 reset 连接（gh 失败时会删掉草稿）；改为先建草稿、`curl --http1.1 --limit-rate 2M` 上传 ZIP、再 `gh release upload` 校验文件并发布。线上资产 digest 与本地一致。
- 主页：`site/changelog.html` 首条原用 `{{BUILD}}` 套在构建 33 的内容上，36、50 未记；改为固定的 50、36、33 三条。`build_site.py` → `deploy.sh --products-only photo-desk --dry-run` → `--deploy --plan` 单产品部署 17 个文件哈希核验；线上 release.json / facts.json = 50、下载 ZIP 长度与 checksum 回读一致。
- 未做：perf 阶段的 input-binding / auto-measure 需对已装 50 重新实测（留给统一测量阶段）；页面与卡片资源数字仍是 36 的实测。`perf/acceptance/`、`perf/build-receipt.json`、`perf/delivery-evidence.json` 含本机路径与真实图库计数，公开仓不提交，仍由 Chapter 在工作树维护。

## 演示素材沿用到 1.0.1 (50)（2026-10-01 14:45）

- Chapter media 项原为 stale（录像 09-10 之后界面源码改过 4 次：19f7b73 图标、32a3ad8 后台图库变化检测、e809a8d 离屏自检入口、6af660d 请求带猫名）。录制方式依赖前台窗口操作，不是离屏安全的，所以没有重录，改为离屏对照后标注沿用。
- 对照入口：`uv run python scripts/media_reuse_check.py label=/path/PhotoDesk.app …`。录制版本 build 10 没有自检入口，做法是在独立克隆里取录像源码 ef19e90、加入 e809a8d 的 Swift 自检改动、用当前 Xcode 27.0 构建，再把可执行文件放进 build 10 原包副本（保留 build 10 引擎），ad-hoc 重签后参与对照；36、50 直接用 `dist/` 发行包。
- 结果：三个包各跑两次 `--ui-self-test`，5 张离屏截图（时间线、选中片段、预览、片段详情、设置）6 次全部逐字节相同，并与 `perf/acceptance/native_ui.json` 一致；三个引擎在合成图库上按 App 默认开内容识别跑 snapshot→enrich，事件（Design review meeting（文字线索）3、猫咪的日常 3、生活片段 4）、计划与重复行（2 行 1 项预选）完全相同，与录像画面一致。36 与 50 的可执行 Mach-O UUID 相同，只差签名里的 64 字节。
- 记录：`docs/demo/recording.json` 的 `reused_for["1.0.1 (50)"]`。随后 `chapter sop accept --check media_playback` 通过（线上页 2 个视频无界面浏览器实际播放），`chapter sop run --app photo-desk --check-only --retry` 为 current_passed / complete，18 项全部 ok。素材文件未变，线上页已写明 build 50 沿用录像，未重新部署。
- 下次界面源码再变：对新发行包跑同一脚本（与 `dist/PhotoDesk-1.0.1-36-arm64` 或上次对照的包比），截图或引擎结果有差异就重录受影响场景。
