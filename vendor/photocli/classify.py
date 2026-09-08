"""classify-plan / classify-apply — 分类模块。

classify-plan : 纯只读,遍历个人库生成本地 plan-file(csv) + HTML 摘要,不写库。
classify-apply: 默认 dry-run,--apply 才真把 plan 写回 Photos 库(加相册/keyword,幂等)。

接口契约(cli.py 依赖这两个 click command):
  classify_plan  : 命令名 "classify-plan"
  classify_apply : 命令名 "classify-apply"
"""
from __future__ import annotations

import collections
import datetime as _dt
import html
from pathlib import Path

import click

from .lib import (
    PlanRow,
    cloud_guid_index,
    get_logger,
    iter_photos,
    is_protected,
    load_config,
    photo_date,
    read_plan,
    write_plan,
)


# ---------------- plan 生成 ----------------
def _build_rows(cfg) -> list[PlanRow]:
    sec = cfg.section("classify")
    pet_faces = set(sec.get("pet_faces", []) or [])
    scene_labels = set(sec.get("scene_labels", []) or [])

    rows: list[PlanRow] = []
    for p in iter_photos(cfg):
        guid = p.cloud_guid
        if not guid:
            continue  # 铁律 #6:无 cloud_guid 不进跨次映射
        fname = p.original_filename or ""
        date = photo_date(p)

        # 1. 时间相册
        d = getattr(p, "date", None)
        if d:
            target = f"{d.year}/{d.year}-{d.month:02d}"
            rows.append(PlanRow(guid, fname, date, "add-album", target))

        # 2. 场景 keyword
        for label in sorted(set(p.labels or []) & scene_labels):
            rows.append(PlanRow(guid, fname, date, "add-keyword", f"场景:{label}"))

        # 3. 人物相册(_UNKNOWN_ 跳过;宠物归宠物相册)
        for name in (p.persons or []):
            if not name or name == "_UNKNOWN_":
                continue
            base = "宠物" if name in pet_faces else "人物"
            rows.append(PlanRow(guid, fname, date, "add-album", f"{base}/{name}"))

        # 4. 可清理候选(PNG 或 含 Document 标签)
        hits = []
        if p.uti == "public.png":
            hits.append("PNG")
        if "Document" in (p.labels or []):
            hits.append("Document标签")
        if hits and not is_protected(p, cfg):
            rows.append(
                PlanRow(guid, fname, date, "add-album", "待清理候选", "+".join(hits))
            )
    return rows


# ---------------- HTML 摘要 ----------------
def _write_html(rows: list[PlanRow], path: Path, n_photos: int) -> None:
    by_target = collections.Counter()
    albums = collections.Counter()
    keywords = collections.Counter()
    persons = collections.Counter()
    pets = collections.Counter()
    cleanup = 0
    for r in rows:
        by_target[(r.action, r.target)] += 1
        if r.action == "add-keyword":
            keywords[r.target] += 1
        elif r.action == "add-album":
            if r.target == "待清理候选":
                cleanup += 1
            elif r.target.startswith("人物/"):
                persons[r.target.split("/", 1)[1]] += 1
            elif r.target.startswith("宠物/"):
                pets[r.target.split("/", 1)[1]] += 1
            else:
                albums[r.target] += 1

    def _table(title, items, c1, c2):
        if not items:
            return f"<h2>{html.escape(title)}</h2><p>无。</p>"
        body = "".join(
            f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>" for k, v in items
        )
        return (
            f"<h2>{html.escape(title)}</h2>"
            f"<table><tr><th>{c1}</th><th>{c2}</th></tr>{body}</table>"
        )

    top_albums = albums.most_common(20)
    sec = [
        _table(f"Top 时间相册(共 {len(albums)} 个,显示前 20)", top_albums, "相册", "张数"),
        _table(f"场景 keyword(共 {len(keywords)} 类)", keywords.most_common(), "keyword", "张数"),
        _table(f"人物相册(共 {len(persons)} 人)", persons.most_common(), "人物", "张数"),
        _table(f"宠物相册(共 {len(pets)} 只)", pets.most_common(), "宠物", "张数"),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>classify plan 摘要</title><style>
body{{font:15px/1.6 -apple-system,"PingFang SC",sans-serif;background:#0d1117;color:#e6edf3;max-width:900px;margin:0 auto;padding:30px}}
h1{{font-size:22px}} h2{{border-bottom:1px solid #30363d;padding-bottom:6px;margin-top:30px}}
table{{width:100%;border-collapse:collapse}} td,th{{border-bottom:1px solid #30363d;padding:8px;text-align:left}}
.kpi{{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0}}
.kpi div{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 20px}}
.kpi b{{font-size:24px;color:#56d4dd;display:block}}
.note{{background:rgba(210,153,34,.1);border-left:3px solid #d29922;padding:10px 14px;border-radius:0 8px 8px 0}}</style></head><body>
<h1>📂 分类 plan 摘要</h1>
<div class="note">本 plan 为<b>只读生成</b>,尚未写库。审查无误后用 <code>classify-apply --apply</code> 落库。</div>
<div class="kpi">
<div><b>{n_photos}</b>个人库照片</div>
<div><b>{len(rows)}</b>计划动作</div>
<div><b>{len(albums)}</b>时间相册</div>
<div><b>{cleanup}</b>待清理候选</div>
</div>
{''.join(sec)}
</body></html>""",
    )


@click.command("classify-plan")
@click.option("--out", "out_path", default=None, help="覆盖 plan-file 输出路径")
@click.pass_context
def classify_plan(ctx: click.Context, out_path: str | None) -> None:
    """遍历个人库,只读生成分类 plan-file(csv) + HTML 摘要,不写库。"""
    cfg = load_config(ctx.obj.get("config_path"))
    log = get_logger("classify-plan", cfg)

    rows = _build_rows(cfg)
    n_photos = len({r.cloud_guid for r in rows})

    if out_path:
        plan_path = Path(out_path)
    else:
        plan_path = cfg.path("plans") / f"classify-{_dt.date.today():%Y%m%d}.csv"
    n = write_plan(rows, plan_path)

    html_path = cfg.path("reports") / "classify-plan.html"
    _write_html(rows, html_path, n_photos)

    by_action = collections.Counter(r.action for r in rows)
    log.info("classify-plan: %d 张照片 → %d 计划动作", n_photos, n)
    click.echo(f"个人库照片(有 cloud_guid): {n_photos}")
    click.echo(f"计划动作总数: {n}")
    for action, cnt in by_action.most_common():
        click.echo(f"  {action}: {cnt}")
    click.echo(f"plan-file: {plan_path}")
    click.echo(f"HTML 摘要: {html_path}")


# ---------------- apply ----------------
def _latest_plan(cfg) -> Path:
    plans = sorted(cfg.path("plans").glob("classify-*.csv"))
    if not plans:
        raise SystemExit("❌ plans 目录无 classify-*.csv,先跑 classify-plan")
    return plans[-1]


@click.command("classify-apply")
@click.option("--plan", "plan_path", default=None, help="plan-file 路径(默认最新 classify-*.csv)")
@click.option("--apply", "do_apply", is_flag=True, help="真写库;不带=dry-run 只打印")
@click.pass_context
def classify_apply(ctx: click.Context, plan_path: str | None, do_apply: bool) -> None:
    """读 plan-file 把分类写回 Photos 库。默认 dry-run,--apply 才真写。幂等。"""
    cfg = load_config(ctx.obj.get("config_path"))
    log = get_logger("classify-apply", cfg)

    path = Path(plan_path) if plan_path else _latest_plan(cfg)
    rows = read_plan(path)
    click.echo(f"plan-file: {path} ({len(rows)} 行)")
    mode = "APPLY(写库)" if do_apply else "DRY-RUN(只打印)"
    click.echo(f"模式: {mode}")

    idx = cloud_guid_index(cfg.library)

    # 反查 + 记录缺失
    missing: list[PlanRow] = []
    resolved: list[tuple[PlanRow, object]] = []
    for r in rows:
        p = idx.get(r.cloud_guid)
        if p is None:
            missing.append(r)
        else:
            resolved.append((r, p))
    if missing:
        miss_path = path.with_suffix(path.suffix + ".missing")
        miss_path.write_text(
            "\n".join(f"{r.cloud_guid},{r.filename}" for r in missing)
        )
        click.echo(f"⚠️ {len(missing)} 行 cloud_guid 在当前库找不到,已记: {miss_path}")

    # 按 (action,target) 分组
    groups: dict[tuple[str, str], list] = collections.defaultdict(list)
    for r, p in resolved:
        groups[(r.action, r.target)].append(p)

    pl = None  # photoscript 句柄,惰性初始化
    for (action, target), photos in sorted(groups.items()):
        if action == "add-album":
            # target 可能是 "2025/2025-08" 这种层级;p.albums 给的是叶子名,按叶子判幂等
            leaf = target.rsplit("/", 1)[-1]
            todo = [p for p in photos if leaf not in (p.albums or [])]
            skip = len(photos) - len(todo)
            click.echo(f"[add-album] {target}: {len(todo)} 待加 / {skip} 已在(跳过)")
            if do_apply and todo:
                from osxphotos.photosalbum import PhotosAlbum

                PhotosAlbum(target, split_folder="/").extend(todo)
                log.info("add-album %s: +%d", target, len(todo))
        elif action == "add-keyword":
            kw = target
            todo = [p for p in photos if kw not in (p.keywords or [])]
            skip = len(photos) - len(todo)
            click.echo(f"[add-keyword] {kw}: {len(todo)} 待加 / {skip} 已有(跳过)")
            if do_apply and todo:
                if pl is None:
                    from photoscript import PhotosLibrary

                    pl = PhotosLibrary()
                for ph in pl.photos(uuid=[p.uuid for p in todo]):
                    ph.keywords = list(set(ph.keywords or []) | {kw})
                log.info("add-keyword %s: +%d", kw, len(todo))
        else:
            click.echo(f"[skip] 未知 action: {action} -> {target} ({len(photos)})")

    if not do_apply:
        click.echo("\nDRY-RUN 结束,未改库。确认后加 --apply 落库(需 Photos.app 运行)。")
