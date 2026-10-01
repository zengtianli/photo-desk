# PhotoDesk

**中文** | [English](README_EN.md)

原生 macOS 照片时间线。打开即自动扫描整个图库，把生活、猫咪、人物、会议与资料联系起来，并准备重复照片清理建议。

产品主页与安装教程：[PhotoDesk](https://app-mac-photodesk.tianli.cyou/)。主页发布状态以实际访问结果为准。

仓库内可直接阅读[上手教程与字幕演示](docs/demo/tutorial.md)；开发验收入口见[固定验收说明](scripts/accept/README.md)。

<!-- lightweight:start -->
## 资源占用

| 安装包 | 空闲内存 | 空闲 CPU | 冷启动到窗口出现 |
|---|---|---|---|
| **37.4 MB**（装好后 92.0 MB） | **122 MB** | **0%** | **402 ms** |

SwiftUI 原生窗口，不开 HTTP 服务；照片解析交给包内 PyInstaller 打包的 Python 引擎（安装体积主要来自它），以子进程运行、做完即退出。打开期间每 60 秒只读查一次引擎实际用到的照片数据，系统分析、搜索索引等无关写入不算变化；图库没变就不启动引擎，变了才重建时间线，结果与当前显示相同时不重写文件、不重绘。首次内容识别期间才连续按每批 12 张处理。

<sub>v1.0.1 (50) · Mac16,12 / Apple M4 / macOS 27.2 · 真实照片图库 6,393 项（2,722 个时间线片段） · 2026-10-01。数字来自所列设备实测，版本更新后重新测量。内存口径为 phys_footprint；CPU 为 60 秒采样窗内 CPU 时间 ÷ 墙钟；大小按十进制 MB。原始数据见 [perf/lightweight.json](perf/lightweight.json)。</sub>
<!-- lightweight:end -->

## 使用

打开 `/Applications/PhotoDesk.app`。默认读取最近打开的照片图库，也可从右上角选择 `.photoslibrary`。

首页直接进入“我的时间线”。先用时间、地点、人物和已有相册完成全库归集，随后后台用 Apple Vision 分类及本地 OCR 补充内容。可以边整理边浏览；首次内容识别需要时间，界面显示真实完成数，退出后下次继续，新照片默认每分钟自动检查。

按 **⌘,** 或左下角“设置…”打开原生设置窗口：自动整理、登录启动、图库与共享范围、外观、照片大小、检查频率、识别强度、事件间隔与距离、会议资料关联范围、猫的名字、重复预选均可配置并自动保存。

照片列表沿用 Mac 操作习惯：单击选择，⌘单击增减，⇧单击连续选择；方向键移动，⇧方向键扩选；**空格快速预览**，再按空格或 Esc 关闭，左右键翻图；双击或“放大查看”进入同一预览。视频原片使用原生播放器。⌘A 全选当前筛选结果，⌘F 搜索，⌘⌫ 打开删除预检与确认。文本输入时保留系统编辑行为。网格随窗口宽度和照片大小自适应，键盘导航会滚动并跨页。

首页时间线卡片也先选择：单击选中整个片段，边框和勾选标记反馈，底栏显示片段数及可操作照片数。支持 ⌘/⇧ 多选和 Space 预览封面，关闭预览保留选择。双击或独立“查看片段”按钮进入详情，随后可以逐张选择。共享照片不计入可删除数量；后台归类不会改变正在核对的片段成员。

照片右键菜单、放大预览底部及“照片”菜单提供“在‘照片’中打开”，按所选图片的本地资产标识直接定位 Apple“照片”中的同一张图片。时间线右键可打开片段封面；首次使用可能需要系统自动化授权。

“设置 → 快捷键”支持录制、清除、冲突提示与作用范围。自定义绑定默认全部为空；显示窗口、设置、暂停整理可设为全局，其余仅在 PhotoDesk 内有效。原生应用内标准按键不注册成全局快捷键。

- **个人与猫时间线**：按拍摄先后聚合片段，支持按已命名人物或宠物、日期、地点搜索和筛选。识别为猫但没有名字的照片不会擅自命名。
- **会议与工作**：结合会议场景、照片标题、已有相册与 OCR 的会议/项目线索。文档与截图可关联同日 90 分钟内、已知位置不超过 1 公里的会议线索；这种时间推断会明确显示，不能当成已确认事件。
- **自动联系规则**：同日、同主题，拍摄间隔不超过 3 小时且已知位置相距不超过 8 公里，组成一个片段。共享相册可归集浏览，删除保持只读边界。
- **自动重复清理建议**：先按原片指纹找组，再对可读静态原片做 SHA-256。只有文件一致、保留副本覆盖已有相册/标题/说明/关键词/人物且时间地点一致时才预选删除。收藏、隐藏、独立编辑、Live Photo 和视频不自动预选。点击“重复核对”即可检查已勾选建议，最终删除仍需确认。

自动时间线分类保存在 PhotoDesk 本地索引，不向 Apple“照片”批量新建相册。需要把分类、关键词或标题写回 Apple“照片”时，使用“整理 → 高级整理”。

- **图库概览**：个人照片、视频、收藏、本地原片、年份分布和现有相册。
- **全部照片**：按月份倒序浏览、搜索、放大查看；勾选后点击右下角红色“删除所选 N 张照片…”。本地尚未同步的照片也可选择。
- **分类整理**：年月、人物、宠物相册及可读场景标签；跳过已存在的归类，收藏和人物照片不进入待清理候选。
- **截图与票据**：Apple Vision 本地 OCR；可选最近 50、100 或全部候选。已有“待清理候选”相册时优先分析该相册，否则分析 PNG 和文档候选。缺少原片或识别失败时待核对；旧票据不推断为已报销。
- **敏感照片**：本地识别证件、银行卡及手机号，计划只展示类型，不展示完整号码。
- **照片标题**：补充空标题，保留已有标题；执行前重新核对，避免覆盖刚发生的编辑。
- **重复核对**：自动产生分组、保留理由和预选建议；不把相似画面当作完全重复，不比较 Live Photo 动态内容。
- **整理记录**：恢复最近 30 份计划、导出完整 CSV；本地记录保留计划和执行结果。

整理写入要先勾选、预检，再点击“确认写入”。所有照片列表都有独立的删除按钮：逐张核对后点击“确认删除”提交给系统 Photos；系统可能另外弹出确认。删除的是原照片，会随 iCloud 同步；通常可在“照片 → 最近删除”中于 30 天内恢复。共享相册、共享图库和未保存的共享消息照片不参与写入或删除。删除前后都通过 PhotoKit 核对准确的照片标识，执行记录保存在本地 history 目录。

若提示无权访问，请在系统设置 → 隐私与安全性 → 完全磁盘访问权限中启用 PhotoDesk 并重启。删除还需要“照片”访问权限。第一次整理写入时，系统还可能询问是否允许控制“照片”。

**识别范围**：此机 macOS 27 的系统搜索场景索引不可读，自动时间线直接对可用预览运行本机 Vision 分类补足。OCR 覆盖 PNG 与图像识别出的文档/会议候选；缺少原片时不做 OCR。视频仅根据元数据和已有预览归类，不理解完整动态内容。不自动下载原片，也不把推测称为确定事实。

## 数据与运行时

- 运行数据：`~/Library/Application Support/PhotoDesk/`，包括 plans、ocr、history、progress。OCR 全文仅在本地缓存；目录权限受当前用户保护。
- SwiftUI 原生窗口，不启动 HTTP 服务。内置 Python、osxphotos、photoscript 和 ocrmac，经 stdin/stdout JSON 调用；运行不依赖 uv、Homebrew、开发目录或其他 App 项目。
- 保留 Python 的原因：实际调用 `PhotosDB`、`PhotoInfo` 的人物/标签/Cloud GUID/指纹解析，以及 `PhotosAlbum` 的层级相册和 photoscript 写回接口。仅用公开 PhotoKit 不能等价替代现有整理能力。
- 照片引擎源码在 `backend/`：`bridge.py` 是 App 与命令行共用的调度（`handle()`），`journey.py` 是时间线索引，`photocli/` 是分类、OCR、标题等算法（源自 apple 仓 `75d955b`），`desk_cli.py` 把 App 功能做成 `photodesk` 命令，`preferences.py` 按 App 的方式读写设置。GUI 和 `photodesk` 使用同一内置引擎，修复、测试和打包均在本仓完成；旧 `photocli` 仅转发到已安装的 PhotoDesk。

## 命令行

App 内已包含 `photodesk`，无需另装 Python。本仓安装脚本会建立 `~/.local/bin/photodesk`；下载版拖入“应用程序”后，可在终端执行：

```sh
mkdir -p "$HOME/.local/bin"
ln -s /Applications/PhotoDesk.app/Contents/Resources/bin/photodesk "$HOME/.local/bin/photodesk"
export PATH="$HOME/.local/bin:$PATH"
photodesk --help
```

如果命令路径已存在，请先核对其来源再替换。缺少读库权限时，需给当前终端“完全磁盘访问权限”；第一次 `apply --confirm` 写入时，系统可能询问是否允许终端控制“照片”。

窗口给人用，命令给 agent 用：`photodesk` 调用与窗口相同的引擎函数，读写同一份时间线缓存、计划、执行记录和设置，所以命令生成的计划会出现在 App 的“整理记录”里，App 生成的时间线命令也能直接读。图库默认与 App 相同（App 里选择的图库，否则“照片”最近打开的图库），可用 `--library PATH` 指定。所有读取命令加 `--json` 输出一个对象 `{"ok": true, "command": …, …}`；失败输出 `{"ok": false, "error": …}` 并以 1 退出（参数错误、数据目录不可写等命令开始前的失败也一样），不加 `--json` 时错误写到 stderr。跟随系统图库时，`timeline`、`duplicates` 和 `delete-check --event/--recommended` 只读“照片”最近打开的图库的时间线缓存；缓存属于别的图库时报错，先 `photodesk refresh`。

```sh
photodesk timeline --json --limit 20            # 我的时间线：片段、识别进度（读缓存，不重建）
photodesk timeline --event <片段ID> --json      # 查看片段里的照片
photodesk refresh --json                        # 同 ⌘R：重建时间线，只写 PhotoDesk 自己的索引
photodesk refresh --enrich --max-batches 5      # 继续本机内容识别，每批数量默认取 App 设置
photodesk audit --json                          # 图库概览，数字与 App 一致
photodesk photos --month 2026-09 --json         # 全部照片（只读，不保存计划）
photodesk duplicates --json                     # 重复核对：保留副本与建议删除项
photodesk plan classify --json                  # 生成建议（library/classify/triage/sensitive/title）
photodesk plans --json                          # 整理记录（最近 30 份）
photodesk plan-show <计划ID> --group <分组> --csv-out 清单.csv
photodesk apply <计划ID> --select-all           # 检查并写入：默认只预检，不改图库
photodesk apply <计划ID> --select 3,7 --confirm # 确认写入“照片”，写后回读，记录进 history/
photodesk delete-check --event <片段ID> --json  # 删除前核对，只给数量；--verbose 列出照片
photodesk records --json                        # 写入回执与删除记录
photodesk settings --json                       # App 设置（13 项与图库）
photodesk settings set eventHours 4             # 修改一项；PhotoDesk 运行时拒绝
photodesk doctor --json                         # 引擎、数据目录、读库权限、缓存（说明项 ok 为 null）；--ocr 另写一张合成样本图核对 OCR
```

| App 里的操作 | 命令 |
|---|---|
| 我的时间线、切换时间线、搜索片段、显示更早的片段 | `timeline [--track] [--search] [--limit/--offset]` |
| 查看片段 | `timeline --event ID` |
| 刷新图库（⌘R）、后台识别、重试失败的识别 | `refresh [--enrich] [--batch] [--max-batches] [--retry-failed]` |
| 图库概览 | `audit [--details]` |
| 全部照片（按月浏览、搜索） | `photos [--month] [--search]` |
| 分类整理、截图与票据、敏感照片、照片标题、全部照片的“生成建议” | `plan KIND [--limit]`（OCR 类有 `--request-id`，另开终端 `progress ID`） |
| 重复核对 | `duplicates [--recommended-only]` |
| 整理记录、打开计划、导出清单 | `plans`、`plan-show ID [--group] [--search] [--csv-out]` |
| 选择（单击/⌘/⇧、⌘A、选中片段、重复预选） | `--select ID,…`、`--select-group`、`--select-all`、`--event`、`--recommended` |
| 检查并写入 → 确认写入 | `apply ID …`（加 `--confirm` 才写，与 App 的写入互斥） |
| 删除前核对（⌘⌫） | `delete-check …` |
| 本地记录 | `records [--kind apply]`、`records --kind delete` |
| 设置窗口 | `settings`、`settings set KEY VALUE` |

只留在 App 里的：**删除照片**（PhotoKit 与系统确认只在 App 内，命令止于 `delete-check`）；暂停/继续自动整理（运行中 App 的状态，持久的“自动整理”开关用 `settings set automatic`）；登录启动；在“照片”中打开、打开“照片”、在 Finder 中显示记录、权限设置链接；导入验收测试图；空格预览、放大、视频播放、网格大小、外观切换的即时效果、快捷键录制与取消任务等界面动作。`settings set` 只接受设置窗口能选出的值，App 运行时会拒绝（运行中的 App 会覆盖外部修改）；`photos` 不保存计划，要核对删除请用 `plan library`。

旧命令名保留为同一流程的别名：`classify-plan`/`title-plan` = `plan classify|title`，`triage`/`ocr-scan` = `plan triage|sensitive`（`--apply` 再对新计划全部写入），`classify-apply`/`title-apply` = `apply <最近同类计划> --select-all`（`--apply` 才写）。旧 CSV 计划已停用；标题只补空标题，截图分桶不再建删除相册。仅命令行才有的工具：`backup`、`ocr-extract`、`shared-list`、`dedup-export`、`reconcile`，产物保存在 `~/Library/Application Support/PhotoDesk/cli/`；其中 `reconcile`（只读对账）、`shared-list`（写共享相册手动清单）、`dedup-export` 支持 `--json`，`backup`、`ocr-extract` 是长任务，只输出文本进度；它们读私有 YAML（`--config` 或 `PHOTOCLI_CONFIG`，默认数据目录的 `cli-config.yaml`，不存在时用中性默认）。显式传 `--config` 时，其中的 `library` 也用于其他命令。个人配置不包含在 App 或公开仓库中。

App 与引擎之间的 JSON 管道（无参数、stdin 输入）是 App 内部契约：失败也以 0 退出，由 App 读取 JSON 里的错误；agent 请用上面的命令。

## 构建和验证

```bash
# 在仓库根目录执行
uv sync --locked --group build
uv run python -m unittest discover -s tests -v
bash build.sh                 # 构建内置引擎、SwiftUI、签名、安装
bash build.sh --no-install    # 仅生成应用
```

Xcode 选择和图标工厂复用总部现有引擎。构建产物位于 `build/DerivedData/Build/Products/Release/PhotoDesk.app`；本机版本为 Apple Silicon，采用本地签名，未进行 App Store 发布或公证分发。

引擎诊断：`photodesk doctor --ocr --json`；App 内部契约可直接给 `build/engine/photo-engine/photo-engine` 输入 JSON stdin，例如 `{"command":"audit"}`、`{"command":"ocr-probe"}`。只读分析结果可用 `tests/contract_check.swift` 经实际 Swift 模型与解码器验证；原图库写入不得用作无人值守测试数据。

第三方来源：[osxphotos](https://github.com/RhetTbull/osxphotos)、[PyInstaller 打包说明](https://pyinstaller.org/en/stable/usage.html)。osxphotos 0.76.1 包含 macOS 27 初步兼容修复，仍需针对实际系统验证。

## 直接分发与主页

`python3 scripts/release.py` 构建但不装机，在 `dist/` 生成 ZIP、SHA-256 和 `release.json`，并从移动后的应用包检查内置运行时、合成 OCR、缺失图库与错误契约。只读检查不访问系统照片；不能代替新电脑上的首次授权、GUI 或删除恢复验收。包内包含第三方许可，源码见[现有公开仓库](https://github.com/zengtianli/photo-desk)。

`python3 scripts/build_site.py --preview` 生成亮色预览到 `build/site/`。真实截图、视频和证据契约见 [docs/demo/README.md](docs/demo/README.md)。正式 `python3 scripts/build_site.py` 要求完整发行包和经过核对的真实媒体；公开文件通过 `site-manifest.json` 白名单交给既有站群部署入口，禁止同步源码目录或原始录屏。

分发版默认宠物名字为空；已有保存设置保持原样。`PHOTODESK_PREFERENCES_SUITE`、`PHOTODESK_DATA_ROOT`、`PHOTODESK_DEMO_ROOT` 用于独立合成验收；演示隔离强制拒绝连接、修改系统 Photos 图库，不是通用文件夹导入功能。
