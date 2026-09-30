"""dedup-export + reconcile（仅命令行工具）。

App 自己的重复核对见 `photodesk duplicates`。这里处理外部去重工具圈出的相册：
- dedup-export: 从一个待删相册导出 cloud_guid 清单（剔除受保护的）
- reconcile: 删除后对账
本模块绝不删除照片。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

import click

from desk_cli import JSON_HELP, execute

from .lib import is_protected, load_config, load_db


@click.command("dedup-export")
@click.option("--album", required=True, help="外部去重工具标记的待删相册名")
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def dedup_export(ctx: click.Context, album: str, as_json: bool) -> None:
    """从一个待删相册导出 cloud_guid 清单（剔除受保护的），供外部去重流程对账。"""
    execute("dedup-export", as_json, lambda: _dedup_export(ctx.obj.get("config_path"), album))


def _dedup_export(config_path, album):
    cfg = load_config(config_path)
    db = load_db(cfg.library)
    target = next((a for a in db.album_info if a.title == album), None)
    if target is None:
        raise ValueError(f"找不到相册：{album}")

    out = cfg.path("plans") / f"dedup-{album}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    kept, protected = [], []
    for p in target.photos:
        if not p.cloud_guid:
            continue
        why = is_protected(p, cfg)
        (protected if why else kept).append((p, why))
    out.write_text("\n".join(p.cloud_guid for p, _ in kept) + "\n")
    lines = [f"相册 '{album}': {len(target.photos)} 张", f"  导出待删 cloud_guid: {len(kept)} → {out}"]
    if protected:
        lines.append(f"  ⚠ 剔除受保护 {len(protected)} 张(收藏/人物/保护keyword):")
        lines += [f"    - {p.original_filename} [{why}]" for p, why in protected[:10]]
    payload = dict(album=album, photos=len(target.photos), exported=len(kept), protected=len(protected),
                   protected_reasons=dict(Counter(why for _, why in protected)), path=str(out))
    return payload, lines


@click.command("reconcile")
@click.option("--json", "as_json", is_flag=True, help=JSON_HELP)
@click.pass_context
def reconcile(ctx: click.Context, as_json: bool) -> None:
    """对账（只读）：库总数 / 「最近删除」/ 待删相册余量 / 最近30天进最近删除。"""
    execute("reconcile", as_json, lambda: _reconcile(ctx.obj.get("config_path")))


def _reconcile(config_path):
    cfg = load_config(config_path)
    db = load_db(cfg.library)
    prefix = cfg.section("delete").get("album_prefix", "_TO_DELETE_BATCH_")
    total = len(db.photos())
    # intrash=True 只返回回收站里的照片,直接取长度即可(不要减总数)
    trashed = db.photos(intrash=True)
    pending = [dict(album=a.title, photos=len(a.photos)) for a in db.album_info if a.title.startswith(prefix)]
    cutoff = datetime.now().astimezone() - timedelta(days=30)
    recent = [p for p in trashed if p.date_trashed and p.date_trashed >= cutoff]
    lines = [f"本地图库总数: {total}", f"在「最近删除」: {len(trashed)}", "", "待删相册(尚未手动删):"]
    lines += [f"  - {a['album']}: {a['photos']} 张" for a in pending] or ["  (无)"]
    lines += ["", f"最近30天进最近删除: {len(recent)} 张", "",
              "对账: iCloud.com Photos 右下角张数应=本地总数;Mac/iPhone/iCloud.com「最近删除」应一致"]
    payload = dict(library=str(db.library_path), total=total, in_trash=len(trashed), album_prefix=prefix,
                   pending_albums=pending, trashed_last_30_days=len(recent))
    return payload, lines
