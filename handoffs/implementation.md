# PhotoDesk · 2026-09-08

用户要求：修复已有相册整理工具，做成 Mac App。已安装 `/Applications/PhotoDesk.app`，源码本仓，bundle `cyou.tianli.PhotoDesk`。

## 已完成

- 原 `~/Apps/data/apple` 的 venv 曾指向旧目录 `~/Apps/apple`；`uv sync --locked --reinstall` 重装修复入口。
- 真实 `photocli audit` 随后发现 macOS 27 `Z_33ASSETS` 表结构不兼容；升级 osxphotos 0.75.9 → 0.76.1，锁文件与最低依赖同步。
- 原算法修正：受保护照片不进入待清理候选；无 OCR 文本判待核对；旧票据和无日期票据保留，不推断已报销。App 使用哈希清单校验的原版快照。
- SwiftUI 界面：图库概览、分类、截图票据、敏感识别、空标题建议、相同原片指纹只读核对、计划历史；缩略图、过滤、分页、逐项勾选、CSV 导出、确认写入。
- PyInstaller 引擎内置到 App Resources，约 90 MB，运行无开发目录依赖；收齐 utitools CSV 和 bitstring 动态模块。
- 执行前核对当前库路径和 Cloud GUID；排除共享内容；标题冲突中止；写后回读；失败保留 partial_or_failed 记录，不报成功。

## 本轮证据范围

- 原始 CLI 帮助、版本、真实 audit 均通过。
- 11 个规则及执行保护测试通过，含模拟真实适配器的相册/标题/标签正向写入和回读失败路径。**没有在用户图库执行自动写入测试。**
- 冻结可执行引擎：ping、真实 audit、五种计划、预检（confirmed=false）、Apple Vision 合成图片 OCR 均通过。三张真实候选图也经冻结 OCR 通路处理。
- 五份真实计划经 `Sources/Models.swift` 与实际 `Contract.decode` 解码通过。测试时个人项 4,659；分类建议 1,128、空标题 748、同指纹清单 24、截图抽测 3、敏感抽测命中 0。数字随图库同步变化，不是永久台账。
- CUA 实际打开安装版，见到概览计数、年份、相册；点分类并生成真实计划，缩略图与分组显示。用户随后接手操作并调整窗口，已停止 UI 输入。未替用户点击“确认写入”。
- catalog 落位 `mac`、bundle id、安装显示名对账通过；代码签名深度校验通过。

本机 `qa/` 是 gitignored 的私有证据（真实计划包含文件名/人物/路径），不得提交或上传。

## 实际限制

macOS 27 的搜索场景标签在此机不可读；界面会说明。年月和人物分类可用，OCR 候选目前主要为 PNG 截图，不宣称识别了全部拍摄证件。重复清单仅按原片指纹，不判断编辑效果和 Live Photo 动态部分，且没有删除入口。

首次实际写入可能弹出系统自动化授权，用户正常确认即可。生成/识别阶段已在安装版通过，不需要人为替用户添加完全磁盘访问权限。

## 复验

```bash
cd /Users/tianli/Apps/mac/photo-desk
uv run python -m unittest discover -s tests -v
uv run python scripts/verify_engine.py
source /Users/tianli/Dev/tools/dev/lib/tools/macapp/xcode_env.sh
xcode_env_use macosx
xcrun swiftc Sources/Models.swift tests/contract_check.swift -o qa/contract-check
qa/contract-check qa
bash build.sh
```
