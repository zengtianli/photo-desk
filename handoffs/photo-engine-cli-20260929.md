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

- 推送 photo-desk / apple 仓、发行和主页部署由 Chapter 的「一键解决全部」接续；推送前按卡片风险节再 grep `/Users/`、猫名、`Dev/tools/kb`（本轮 diff 与冻结包检查为零）。
- 不在第一期：apple 根依赖瘦身、App 菜单「安装命令行工具…」、历史 plans/ocr 迁移、`~/Dev/tools/kb/bin/doc.py` 的 `SOURCE` 失效路径。
- 回滚：两仓各自 `git revert`；`chapter unarchive --app photo`（先 revert stub）；删 `~/.local/bin/photodesk`；旧 App 从废纸篓放回。
