# PhotoDesk 固定验收

在仓库根目录运行（不会安装、发版或接触用户图库）：

```bash
uv run python scripts/accept/build.py
~/Dev/.venv/bin/python ../chapter/engine/app_sop.py accept --app photo-desk \
  --check functionality --check recovery --check privacy --check native_ui --json
```

构建由 Chapter 的 `build-receipt` 绑定当前 Swift、backend/photocli 与依赖输入。验收拒绝源码或可执行文件不匹配的旧包。四项命令共用 `_common.py`，每次生成独立临时合成图库、数据目录与 `PhotoDesk.Test.*` 偏好；不要求前台窗口、系统按键或剪贴板。

- `functionality.py`：实际包内引擎归集、Vision/OCR、字节重复建议、计划回读与生产 Swift decoder。
- `recovery.py`：独立进程恢复缓存、错误请求/坏输入保留状态、缺失计划重建、无变化不重写。
- `privacy.py`：合成模式的写入拒绝与数据隔离边界；具体执行断言见报告。
- `native_ui.py`：调用 App 的 `--ui-self-test`，离屏渲染实际 SwiftUI 视图，并执行选择、预览关闭、刷新等动作路径。

`app_sop accept` 是交付证据的唯一写入者，报告在 `perf/acceptance/`，汇总在 `perf/delivery-evidence.json`。各脚本独立调试默认输出到被 Git 忽略的 `build/acceptance/`；单独调试通过不等于 Chapter 已验收。

这些证据只覆盖合成输入下的本地构建。个人图库授权、Apple“照片”实际写入/删除与系统“最近删除”恢复、Dock/Finder 装机图标须另行验收，不从这里推断通过。截图只包含明确标注的合成内容。
