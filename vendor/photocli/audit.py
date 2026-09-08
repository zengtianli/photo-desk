"""audit — 扫库出分布画像(只读)。JSON + 可选 HTML。"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import click

from .lib import iter_photos, load_config, photo_date


@click.command("audit")
@click.option("--json", "as_json", is_flag=True, help="输出 JSON 到 stdout")
@click.option("--all-scope", is_flag=True, help="含共享相册照片(默认仅个人库)")
@click.pass_context
def audit(ctx: click.Context, as_json: bool, all_scope: bool) -> None:
    """库画像:总数/年份/类型/标签/人脸/可清理候选。"""
    cfg = load_config(ctx.obj.get("config_path"))
    photos = iter_photos(cfg, scope_personal=not all_scope)
    n = len(photos)

    years = collections.Counter((p.date.year if p.date else "?") for p in photos)
    uti = collections.Counter(p.uti or "?" for p in photos)
    labels = collections.Counter()
    for p in photos:
        for l in (p.labels or []):
            labels[l] += 1
    faces = collections.Counter()
    for p in photos:
        for person in (p.persons or []):
            if person:
                faces[person] += 1

    stats = {
        "scope": "all" if all_scope else "personal",
        "total": n,
        "photos": sum(1 for p in photos if p.isphoto),
        "movies": sum(1 for p in photos if p.ismovie),
        "favorites": sum(1 for p in photos if p.favorite),
        "edited": sum(1 for p in photos if p.hasadjustments),
        "live": sum(1 for p in photos if p.live_photo),
        "with_gps": sum(1 for p in photos if p.latitude is not None),
        "by_year": dict(sorted(years.items(), key=lambda kv: str(kv[0]))),
        "by_type": dict(uti.most_common()),
        "top_labels": dict(labels.most_common(20)),
        "top_faces": dict(faces.most_common(15)),
    }

    if as_json:
        click.echo(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    click.echo(f"范围: {stats['scope']}  总数: {n}  (照片 {stats['photos']} / 视频 {stats['movies']})")
    click.echo(f"收藏 {stats['favorites']} · 已编辑 {stats['edited']} · Live {stats['live']} · 含GPS {stats['with_gps']}")
    click.echo("\n按年:")
    for y, c in stats["by_year"].items():
        click.echo(f"  {y}: {c}")
    click.echo("\n类型:")
    for t, c in stats["by_type"].items():
        click.echo(f"  {t}: {c}")
    click.echo("\nTop 标签:")
    for l, c in list(stats["top_labels"].items())[:10]:
        click.echo(f"  {l}: {c}")
    click.echo("\nTop 人脸:")
    for face, c in stats["top_faces"].items():
        click.echo(f"  {face}: {c}")

    out = cfg.path("reports") / "audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    click.echo(f"\n已写 {out}")
