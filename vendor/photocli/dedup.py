"""dedup-export + reconcile。

去重检测本身用 PhotoSweeper X(GUI,直连 Photos)。本模块只负责:
- dedup-export: PhotoSweeper 圈定后,从待删相册导出 cloud_guid 清单 + 对账表
- reconcile: 删除后对账
删除永远用户手动 ⌘⌫(本模块绝不删)。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import click

from .lib import is_protected, load_config, load_db, photo_date


@click.command("dedup-export")
@click.option("--album", required=True, help="PhotoSweeper 标记的待删相册名")
@click.pass_context
def dedup_export(ctx: click.Context, album: str) -> None:
    """从待删相册导出 cloud_guid 清单(剔除被保护的),供 30-mark 用。"""
    cfg = load_config(ctx.obj.get("config_path"))
    db = load_db(cfg.library)
    target = next((a for a in db.album_info if a.title == album), None)
    if target is None:
        raise SystemExit(f"❌ 找不到相册: {album}")

    out = cfg.path("plans") / f"dedup-{album}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    kept, protected = [], []
    for p in target.photos:
        if not p.cloud_guid:
            continue
        why = is_protected(p, cfg)
        (protected if why else kept).append((p, why))
    out.write_text("\n".join(p.cloud_guid for p, _ in kept) + "\n")
    click.echo(f"相册 '{album}': {len(target.photos)} 张")
    click.echo(f"  导出待删 cloud_guid: {len(kept)} → {out}")
    if protected:
        click.echo(f"  ⚠ 剔除受保护 {len(protected)} 张(收藏/人物/保护keyword):")
        for p, why in protected[:10]:
            click.echo(f"    - {p.original_filename} [{why}]")


@click.command("reconcile")
@click.pass_context
def reconcile(ctx: click.Context) -> None:
    """对账:库总数 / 待删相册余量 / 最近30天进最近删除。"""
    cfg = load_config(ctx.obj.get("config_path"))
    db = load_db(cfg.library)
    prefix = cfg.section("delete").get("album_prefix", "_TO_DELETE_BATCH_")

    click.echo(f"本地图库总数: {len(db.photos())}")
    # intrash=True 只返回回收站里的照片,直接取长度即可(不要减总数)
    click.echo(f"在「最近删除」: {len(db.photos(intrash=True))}")
    click.echo("\n待删相册(尚未手动删):")
    any_found = False
    for a in db.album_info:
        if a.title.startswith(prefix):
            click.echo(f"  - {a.title}: {len(a.photos)} 张")
            any_found = True
    if not any_found:
        click.echo("  (无)")
    cutoff = datetime.now().astimezone() - timedelta(days=30)
    recent = [p for p in db.photos(intrash=True) if p.date_trashed and p.date_trashed >= cutoff]
    click.echo(f"\n最近30天进最近删除: {len(recent)} 张")
    click.echo("\n对账: iCloud.com Photos 右下角张数应=本地总数;Mac/iPhone/iCloud.com「最近删除」应一致")
