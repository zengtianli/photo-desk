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
