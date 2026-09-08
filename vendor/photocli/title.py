"""title-plan / title-apply — 给个人库每张照片生成有意义的标题。

标题模板:`YYYY-MM · 地点 · 场景/人物`
- 人物/宠物 > 敏感证件(只类型+人名,绝不放号码)> 场景标签(中文)
- 文件名改不了 → 只写库内 title 字段(可逆);PII 绝不进标题。
"""
from __future__ import annotations

import collections
import datetime as _dt
import sqlite3
import os
from pathlib import Path

import click

from .lib import (
    PlanRow,
    cloud_guid_index,
    get_logger,
    iter_photos,
    load_config,
    photo_date,
    read_plan,
    write_plan,
)

DOCS_DB = Path(os.environ.get("PHOTOCLI_DOCS_DB", Path.home() / "Dev/tools/kb/data/documents.db"))

# 场景标签 → 中文(只映射常见的,未命中跳过该标签)
SCENE_CN = {
    "Cat": "猫", "Feline": "猫", "Felinae": "猫", "Kitten": "猫",
    "Dog": "狗", "Animal": "动物", "Mammal": "动物", "Bird": "鸟",
    "Document": "文档", "Text": "文档", "Menu": "菜单", "Receipt": "票据",
    "People": "人物", "Person": "人物", "Selfie": "自拍",
    "Food": "美食", "Meal": "美食", "Dessert": "甜点", "Drink": "饮品",
    "Plant": "植物", "Flower": "花", "Tree": "树", "Garden": "花园",
    "Sky": "天空", "Cloud": "天空", "Sunset": "日落", "Mountain": "山",
    "Beach": "海滩", "Sea": "海", "Water": "水", "Lake": "湖",
    "Building": "建筑", "Architecture": "建筑", "Street": "街景", "City": "城市",
    "Car": "车", "Vehicle": "车", "Furniture": "家具", "Art": "艺术",
    "Snow": "雪", "Night": "夜景",
}
PET_NAMES = {"大白"}


def _place_part(photo) -> str:
    pl = getattr(photo, "place", None)
    if not pl or not pl.name:
        return ""
    # 取最具体的一段(POI/地名),英文也行
    return pl.name.split(",")[0].strip()


def _subject_part(photo, sens_map: dict) -> str:
    guid = photo.cloud_guid
    # 1) 敏感证件:只 类型+人名,绝不放号码
    if guid in sens_map:
        person, doc_type = sens_map[guid]
        return f"证件·{doc_type}" + (f"·{person}" if person and person != "未定" else "")
    # 2) 命名人物 / 宠物
    persons = [p for p in (photo.persons or []) if p and p != "_UNKNOWN_"]
    if persons:
        p0 = persons[0]
        return f"猫·{p0}" if p0 in PET_NAMES else p0
    # 3) 场景标签(第一个能映射成中文的)
    for lab in (photo.labels or []):
        if lab in SCENE_CN:
            return SCENE_CN[lab]
    return ""


def _load_sensitive_map() -> dict:
    """cloud_guid -> (person, doc_type),来自 documents.db(只读类型/人名,不读号码)。"""
    if not DOCS_DB.exists():
        return {}
    out = {}
    con = sqlite3.connect(DOCS_DB)
    try:
        for guid, person, dtype in con.execute(
            "SELECT cloud_guid, person, doc_type FROM documents WHERE cloud_guid IS NOT NULL"
        ):
            if guid:
                out[guid] = (person, dtype)
    except sqlite3.OperationalError:
        pass
    con.close()
    return out


def _make_title(photo, sens_map: dict) -> str:
    d = getattr(photo, "date", None)
    date_part = d.strftime("%Y-%m") if d else ""
    place = _place_part(photo)
    subj = _subject_part(photo, sens_map)
    parts = [x for x in (date_part, place, subj) if x]
    return " · ".join(parts)


def _build_rows(cfg) -> list[PlanRow]:
    sens_map = _load_sensitive_map()
    rows = []
    for p in iter_photos(cfg):
        if not p.cloud_guid:
            continue
        title = _make_title(p, sens_map)
        if not title:
            continue
        rows.append(PlanRow(p.cloud_guid, p.original_filename or "", photo_date(p), "set-title", title))
    return rows


@click.command("title-plan")
@click.option("--out", "out_path", default=None)
@click.pass_context
def title_plan(ctx: click.Context, out_path: str | None) -> None:
    """生成标题 plan-file(只读,不写库)。"""
    cfg = load_config(ctx.obj.get("config_path"))
    log = get_logger("title-plan", cfg)
    rows = _build_rows(cfg)
    path = Path(out_path) if out_path else cfg.path("plans") / f"title-{_dt.date.today():%Y%m%d}.csv"
    n = write_plan(rows, path)
    log.info("title-plan: %d titles", n)
    click.echo(f"生成标题: {n} 条 → {path}")
    click.echo("样本(前 8):")
    for r in rows[:8]:
        click.echo(f"  {r.filename}: {r.target}")


def _latest(cfg) -> Path:
    plans = sorted(cfg.path("plans").glob("title-*.csv"))
    if not plans:
        raise SystemExit("❌ 无 title-*.csv,先 title-plan")
    return plans[-1]


@click.command("title-apply")
@click.option("--plan", "plan_path", default=None)
@click.option("--apply", "do_apply", is_flag=True, help="真写库(需 Photos.app 运行)")
@click.option("--limit", type=int, default=None, help="只处理前 N 条(smoke 用)")
@click.pass_context
def title_apply(ctx: click.Context, plan_path: str | None, do_apply: bool, limit: int | None) -> None:
    """把标题写回库 title 字段。默认 dry-run,--apply 才写。幂等。"""
    cfg = load_config(ctx.obj.get("config_path"))
    log = get_logger("title-apply", cfg)
    path = Path(plan_path) if plan_path else _latest(cfg)
    rows = read_plan(path)
    if limit:
        rows = rows[:limit]
    click.echo(f"plan: {path} ({len(rows)} 条) · 模式: {'APPLY' if do_apply else 'DRY-RUN'}")

    idx = cloud_guid_index(cfg.library)
    targets = [(r, idx[r.cloud_guid]) for r in rows if r.cloud_guid in idx]
    todo = [(r, p) for r, p in targets if (p.title or "") != r.target]
    click.echo(f"匹配 {len(targets)} / 待写 {len(todo)} / 已是目标 {len(targets)-len(todo)}")
    if not do_apply:
        click.echo("DRY-RUN,未写库。加 --apply 落库。")
        return

    from photoscript import PhotosLibrary

    pl = PhotosLibrary()
    written = 0
    by_uuid = {p.uuid: r.target for r, p in todo}
    for ph in pl.photos(uuid=list(by_uuid.keys())):
        ph.title = by_uuid[ph.uuid]
        written += 1
    log.info("title-apply: wrote %d", written)
    click.echo(f"✓ 写入标题 {written} 条")
