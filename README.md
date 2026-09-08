# PhotoDesk

原生 macOS 相册整理应用。读取 Apple Photos 图库，生成建议，预览缩略图并勾选，再确认写入。

## 使用

打开 `/Applications/PhotoDesk.app`。默认读取最近打开的照片图库，也可从右上角选择 `.photoslibrary`。

- **图库概览**：个人照片、视频、收藏、本地原片、年份分布和现有相册。
- **全部照片**：按月份倒序浏览、搜索、放大查看；勾选后点击右下角红色“删除所选 N 张照片…”。本地尚未同步的照片也可选择。
- **分类整理**：年月、人物、宠物相册及可读场景标签；跳过已存在的归类，收藏和人物照片不进入待清理候选。
- **截图与票据**：Apple Vision 本地 OCR；可选最近 50、100 或全部候选。已有“待清理候选”相册时优先分析该相册，否则分析 PNG 和文档候选。缺少原片或识别失败时待核对；旧票据不推断为已报销。
- **敏感照片**：本地识别证件、银行卡及手机号，计划只展示类型，不展示完整号码。
- **照片标题**：补充空标题，保留已有标题；执行前重新核对，避免覆盖刚发生的编辑。
- **重复核对**：相同原片指纹分组，可放大核对后手动选择删除。不是相似图片算法，不比较编辑效果和 Live Photo 动态部分，不自动推荐保留哪张。
- **整理记录**：恢复最近 30 份计划、导出完整 CSV；本地记录保留计划和执行结果。

整理写入要先勾选、预检，再点击“确认写入”。所有照片列表都有独立的删除按钮：逐张核对后点击“确认删除”提交给系统 Photos；系统可能另外弹出确认。删除的是原照片，会随 iCloud 同步；通常可在“照片 → 最近删除”中于 30 天内恢复。共享相册、共享图库和未保存的共享消息照片不参与写入或删除。删除前后都通过 PhotoKit 核对准确的照片标识，执行记录保存在本地 history 目录。

若提示无权访问，请在系统设置 → 隐私与安全性 → 完全磁盘访问权限中启用 PhotoDesk 并重启。删除还需要“照片”访问权限。第一次整理写入时，系统还可能询问是否允许控制“照片”。

**当前 macOS 27 限制**：此机系统搜索索引的场景标签暂不可读，界面会提示；人物与年月分类仍可用。OCR 候选主要覆盖 PNG 截图，不能声称覆盖所有拍摄的证件。未下载原片的照片可看本地预览，但不进行 OCR，也不自动下载。

## 数据与运行时

- 运行数据：`~/Library/Application Support/PhotoDesk/`，包括 plans、ocr、history、progress。OCR 全文仅在本地缓存；目录权限受当前用户保护。
- SwiftUI 原生窗口，不启动 HTTP 服务。内置 Python、osxphotos、photoscript 和 ocrmac，经 stdin/stdout JSON 调用；运行不依赖 uv、Homebrew、开发目录或其他 App 项目。
- 保留 Python 的原因：实际调用 `PhotosDB`、`PhotoInfo` 的人物/标签/Cloud GUID/指纹解析，以及 `PhotosAlbum` 的层级相册和 photoscript 写回接口。仅用公开 PhotoKit 不能等价替代现有整理能力。
- `vendor/photocli/` 是原 apple/photo 引擎的可验证源码快照。正常构建仅使用本仓快照，不 import 另一个 App；`scripts/vendor_engine.py --sync` 是显式更新入口，manifest 保存源文件哈希。业务算法修正在 apple/photo 原版完成后同步快照。

## 构建和验证

```bash
cd /Users/tianli/Apps/mac/photo-desk
uv sync --locked --group build
uv run python -m unittest discover -s tests -v
bash build.sh                 # 构建内置引擎、SwiftUI、签名、安装
bash build.sh --no-install    # 仅生成应用
```

Xcode 选择和图标工厂复用总部现有引擎。构建产物位于 `build/DerivedData/Build/Products/Release/PhotoDesk.app`；本机版本为 Apple Silicon，采用本地签名，未进行 App Store 发布或公证分发。

引擎诊断：`build/engine/photo-engine/photo-engine` 接受 JSON stdin，例如 `{"command":"audit"}`、`{"command":"ocr-probe"}`。只读分析结果可用 `tests/contract_check.swift` 经实际 Swift 模型与解码器验证；原图库写入不得用作无人值守测试数据。

第三方来源：[osxphotos](https://github.com/RhetTbull/osxphotos)、[PyInstaller 打包说明](https://pyinstaller.org/en/stable/usage.html)。osxphotos 0.76.1 包含 macOS 27 初步兼容修复，仍需针对实际系统验证。
