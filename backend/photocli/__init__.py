"""PhotoDesk 照片引擎的算法模块（源自 photocli）。

- 一切以 cloud_guid 为键（本地 UUID 在修复或换机后会变）；删除解析另用行内 local_uuid
- 共享内容只读；删除只在 App 内经系统确认
- 计划先生成、再勾选确认写入（bridge.build_plan / apply_plan）
"""
__version__ = "0.1.0"
