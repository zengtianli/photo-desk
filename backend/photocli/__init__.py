"""photocli — 可维护的 iCloud Photos 整理工具。

设计原则:
- dry-run 默认,写库要显式 --apply
- 一切以 cloud_guid 为键(本地 UUID 在 repair/换机后会变)
- 共享相册只读(Apple 无写 API);删除永远用户手动 ⌘⌫
- plan-file 工作流:plan(本地)→ 用户审 → apply(回 iCloud)
"""
__version__ = "0.1.0"
