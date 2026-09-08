"""ocr-scan — 离线 OCR 档案候选,识别 PII,标敏感(留库保护)。

接口契约(cli.py 依赖):
  ocr_scan : 命令名 "ocr-scan"

安全铁律:OCR 出的文本是 PII。完整号码绝不打 stdout、绝不进 git。
完整信息只写 cfg.path('ocr')(已 gitignore);stdout / HTML 一律脱敏(掩码)。
OCR 必须本机离线:首选 Apple Vision(ocrmac),失败兜底 tesseract。
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click

from .lib import (
    get_logger,
    iter_photos,
    load_config,
    photo_date,
)


# ---------------- 脱敏 ----------------
def mask(s: str) -> str:
    """保留前 4 后 4,中间星号。短串(<=8)全星。"""
    s = (s or "").strip()
    if len(s) <= 8:
        return "*" * len(s)
    return s[:4] + "*" * (len(s) - 8) + s[-4:]


# PIL 打不开的格式(ocrmac 内部走 PIL)→ 先用 macOS 自带 sips 转 JPEG。
# 关键:HEIC 占库内近半,不转就会静默漏掉 HEIC 拍的身份证/护照。
_NEEDS_SIPS = (".heic", ".heif", ".tif", ".tiff")


def _to_pil_readable(image_path: str) -> tuple[str, bool]:
    """返回 (可被 PIL/ocrmac 读取的路径, 是否临时文件需删除)。"""
    import subprocess
    import tempfile

    if not image_path.lower().endswith(_NEEDS_SIPS):
        return image_path, False
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    subprocess.run(
        ["sips", "-s", "format", "jpeg", image_path, "--out", tmp.name],
        capture_output=True, check=True,
    )
    return tmp.name, True


def _ocr_vision(image_path: str) -> str:
    """Apple Vision(ocrmac)。HEIC 等先经 sips 转 JPEG。返回识别全文。"""
    import os

    from ocrmac import ocrmac

    path, is_tmp = _to_pil_readable(image_path)
    try:
        # 注意:此 Vision 版本要求完整 locale code(不接受裸 "en")
        res = ocrmac.OCR(path, language_preference=["zh-Hans", "en-US"]).recognize()
        return "\n".join(t for (t, _conf, _bbox) in res)
    finally:
        if is_tmp:
            os.unlink(path)


def _ocr_tesseract(image_path: str) -> str:
    """兜底:tesseract(本机离线)。"""
    import pytesseract  # type: ignore
    from PIL import Image  # type: ignore

    return pytesseract.image_to_string(Image.open(image_path), lang="chi_sim+eng")


def _pick_engine(logger) -> tuple:
    """探测可用 OCR 引擎,返回 (name, fn)。优先 Vision。"""
    try:
        from ocrmac import ocrmac  # noqa: F401

        return "apple-vision(ocrmac)", _ocr_vision
    except Exception as e:  # pragma: no cover
        logger.info(f"ocrmac 不可用({e}),尝试 tesseract 兜底")
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401

        return "tesseract", _ocr_tesseract
    except Exception as e:
        raise SystemExit(f"❌ 无可用 OCR 引擎(ocrmac/tesseract 均失败): {e}")


# ---------------- 候选选取 ----------------
def _is_candidate(photo, candidate_labels: set, candidate_uti: set) -> bool:
    # 排除视频:OCR 无意义且 PIL 打不开
    if getattr(photo, "ismovie", False):
        return False
    uti = getattr(photo, "uti", None) or ""
    if uti.startswith(("public.movie", "com.apple.quicktime")) or uti.endswith(("-movie", ".mpeg-4")):
        return False
    labels = set(getattr(photo, "labels", []) or [])
    if labels & candidate_labels:
        return True
    return bool(uti and uti in candidate_uti)


# ---------------- HTML(脱敏) ----------------
def _render_html(records: list, engine: str) -> str:
    # 打进 HTML 的生成时间必须带偏移量(套件 CLAUDE.md「时间戳口径」)。裸 date.today()
    # 只有一个本地日、无时区,跨 TZ 读这份报告会差一整天且字符串上看不出来。
    today = _dt.datetime.now(_dt.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %z")
    rows = []
    for r in records:
        types = ", ".join(_html.escape(t) for t in r["matched_types"])
        samples = "<br>".join(_html.escape(s) for s in r["masked_samples"])
        rows.append(
            f"<tr><td>{_html.escape(r['original_filename'] or '')}</td>"
            f"<td class='t'>{types}</td>"
            f"<td class='m'>{samples}</td>"
            f"<td>{_html.escape(r['date'] or '')}</td></tr>"
        )
    body = "\n".join(rows) or "<tr><td colspan='4'>(无命中)</td></tr>"
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>OCR 敏感档案(脱敏)</title>
<style>
:root{{color-scheme:dark}}
body{{background:#0d1117;color:#c9d1d9;font:14px/1.6 -apple-system,Segoe UI,sans-serif;margin:0;padding:2rem}}
h1{{color:#f0f6fc;font-size:1.4rem}}
.meta{{color:#8b949e;margin-bottom:1.5rem}}
.warn{{background:#3d1d1d;border:1px solid #f85149;color:#ffa198;padding:.6rem 1rem;border-radius:6px;margin-bottom:1.5rem}}
table{{border-collapse:collapse;width:100%}}
th,td{{padding:.5rem .8rem;border-bottom:1px solid #21262d;text-align:left;vertical-align:top}}
th{{color:#8b949e;font-weight:600;border-bottom:2px solid #30363d}}
td.t{{color:#d29922}}
td.m{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#58a6ff}}
tr:hover{{background:#161b22}}
</style></head><body>
<h1>🔒 OCR 敏感档案识别(脱敏报告)</h1>
<div class="meta">引擎: {_html.escape(engine)} · 生成: {today} · 命中 {len(records)} 张</div>
<div class="warn">⚠ 本报告已脱敏(掩码前4后4)。完整号码仅存于 data/ocr/(gitignore),绝不外发。</div>
<table>
<thead><tr><th>文件名</th><th>命中类型</th><th>掩码样本</th><th>拍摄日期</th></tr></thead>
<tbody>
{body}
</tbody></table>
</body></html>"""


# ---------------- 命令 ----------------
@click.command("ocr-scan")
@click.option("--limit", type=int, default=None, help="只处理前 N 张候选(抽测建议 --limit 50)")
@click.option("--apply", "apply_", is_flag=True, default=False, help="写库:打 keyword + 进敏感相册(默认 dry-run)")
@click.pass_context
def ocr_scan(ctx: click.Context, limit: int | None, apply_: bool) -> None:
    """OCR 档案候选,识别 PII,标敏感(留库保护)。

    默认 dry-run(只识别+出报告,不写库)。--apply 才打 keyword/进相册。
    """
    cfg = load_config(ctx.obj.get("config_path") if ctx.obj else None)
    logger = get_logger("ocr", cfg)
    sec = cfg.section("ocr")

    candidate_labels = set(sec.get("candidate_labels", []) or [])
    candidate_uti = set(sec.get("candidate_uti", []) or [])
    patterns_raw = sec.get("patterns", {}) or {}
    patterns = {name: re.compile(rx) for name, rx in patterns_raw.items()}
    sensitive_album = sec.get("sensitive_album", "🔒敏感档案")

    protect_keywords = list(cfg.protect.get("keywords", []) or [])
    sens_keyword = protect_keywords[0] if protect_keywords else "🔒敏感"

    # 1. 选候选
    photos = iter_photos(cfg)
    candidates = [p for p in photos if _is_candidate(p, candidate_labels, candidate_uti)]
    click.echo(f"候选: {len(candidates)} 张(共 {len(photos)} 张库内照片)")
    if limit is not None:
        candidates = candidates[:limit]
        click.echo(f"  --limit {limit} → 实际处理 {len(candidates)} 张")

    engine_name, ocr_fn = _pick_engine(logger)
    click.echo(f"OCR 引擎: {engine_name}")

    # 并行 OCR：每张独立，结果按原序汇总
    def _ocr_one(idx_p):
        """对单张候选图跑 OCR + pattern 匹配，返回 (idx, record_or_None, skip_missing, ocr_err)。"""
        idx, p = idx_p
        path = getattr(p, "path", None)
        if not path or not Path(path).exists():
            return idx, None, True, False
        try:
            text = ocr_fn(path)
        except Exception as e:
            logger.info(f"OCR 失败 {p.cloud_guid}: {e}")
            return idx, None, False, True

        matched_types: list = []
        masked_samples: list = []
        for name, rx in patterns.items():
            hits = rx.findall(text)
            if hits:
                matched_types.append(name)
                for h in hits[:3]:
                    if isinstance(h, tuple):
                        h = next((x for x in h if x), "")
                    masked_samples.append(f"{name}: {mask(str(h))}")
        if matched_types:
            record = {
                "cloud_guid": p.cloud_guid,
                "original_filename": getattr(p, "original_filename", None),
                "date": photo_date(p),
                "matched_types": matched_types,
                "masked_samples": masked_samples,
            }
            return idx, record, False, False
        return idx, None, False, False

    # 收集结果，保持原序
    result_map: dict = {}
    skipped_missing = 0
    ocr_errors = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        futs = {executor.submit(_ocr_one, (i, p)): i
                for i, p in enumerate(candidates)}
        for fut in as_completed(futs):
            idx, record, is_missing, is_err = fut.result()
            if is_missing:
                skipped_missing += 1
            elif is_err:
                ocr_errors += 1
            else:
                result_map[idx] = record

    # 按原序组装 records（只含命中的）
    records: list = [result_map[i] for i in sorted(result_map) if result_map[i] is not None]

    click.echo(
        f"识别完成: 命中敏感 {len(records)} 张 · 跳过未下载 {skipped_missing} · OCR 错误 {ocr_errors}"
    )

    # 4. 写完整 JSON(gitignore 区)+ 脱敏 HTML
    # 豁免「必带偏移量」: 这个只做文件名 tag(sensitive-YYYYMMDD.json),按本地日分档
    # 才符合"我今天跑的"直觉;文件名里塞不下偏移量,产物正文的时间另有带 %z 的字段。
    today_tag = _dt.datetime.now(_dt.timezone.utc).astimezone().strftime("%Y%m%d")
    ocr_dir = cfg.path("ocr")
    ocr_dir.mkdir(parents=True, exist_ok=True)
    json_path = ocr_dir / f"sensitive-{today_tag}.json"
    # 完整(未脱敏)清单 — 仅落 gitignore 区,绝不打 stdout
    full_records = []
    for r in records:
        full = dict(r)
        full["masked_samples"] = r["masked_samples"]  # 已是脱敏样本,JSON 也只存脱敏即可
        full_records.append(full)
    json_path.write_text(
        json.dumps(
            # generated 写进 JSON 产物 -> 必带偏移量(套件 CLAUDE.md「时间戳口径」)
            {"engine": engine_name,
             "generated": _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(),
             "records": full_records},
            ensure_ascii=False,
            indent=2,
        )
    )

    reports_dir = cfg.path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    html_path = reports_dir / "ocr-sensitive.html"
    html_path.write_text(_render_html(records, engine_name))

    click.echo(f"清单(完整,gitignore): {json_path}")
    click.echo(f"脱敏报告: {html_path}")

    # 脱敏预览(stdout 安全)
    for r in records[:10]:
        click.echo(
            f"  · {r['original_filename']} [{', '.join(r['matched_types'])}] {'; '.join(r['masked_samples'])}"
        )

    # 5. 写库(apply)/ dry-run
    if not records:
        return
    if not apply_:
        click.echo(f"[dry-run] 将给 {len(records)} 张打 keyword '{sens_keyword}' + 进相册 '{sensitive_album}'(加 --apply 执行)")
        return

    from osxphotos.photosalbum import PhotosAlbum
    from photoscript import PhotosLibrary

    guid_to_photo = {p.cloud_guid: p for p in candidates if p.cloud_guid}
    photos = [guid_to_photo[r["cloud_guid"]] for r in records if r["cloud_guid"] in guid_to_photo]

    # 相册:osxphotos PhotosAlbum(幂等,已在的不重复)
    album = PhotosAlbum(sensitive_album)
    todo_album = [p for p in photos if sensitive_album not in (p.albums or [])]
    if todo_album:
        album.extend(todo_album)

    # keyword:PhotoInfo 只读,必须经 photoscript 写
    todo_kw = [p for p in photos if sens_keyword not in (p.keywords or [])]
    if todo_kw:
        pl = PhotosLibrary()
        for ph in pl.photos(uuid=[p.uuid for p in todo_kw]):
            ph.keywords = list(set(ph.keywords or []) | {sens_keyword})

    click.echo(
        f"[apply] {len(photos)} 张敏感:相册 +{len(todo_album)}(已在 {len(photos)-len(todo_album)})"
        f" · keyword +{len(todo_kw)}(已有 {len(photos)-len(todo_kw)})"
    )
    logger.info(f"ocr-scan apply: total={len(photos)} album+={len(todo_album)} kw+={len(todo_kw)}")


@click.command("ocr-extract")
@click.option("--limit", type=int, default=None, help="只处理前 N 张(抽测)")
@click.option("--out", default=None, help="输出 jsonl 路径(默认 data/ocr/fulltext-<日期>.jsonl)")
@click.pass_context
def ocr_extract(ctx: click.Context, limit: int | None, out: str | None) -> None:
    """对候选图一次性 OCR 全文 → gitignored jsonl(给 doc/guide/triage 复用)。

    全文含 PII,只落 data/ocr/(gitignore),绝不进 git/外发。
    """
    cfg = load_config(ctx.obj.get("config_path") if ctx.obj else None)
    logger = get_logger("ocr-extract", cfg)
    sec = cfg.section("ocr")
    candidate_labels = set(sec.get("candidate_labels", []) or [])
    candidate_uti = set(sec.get("candidate_uti", []) or [])

    photos = iter_photos(cfg)
    candidates = [p for p in photos if _is_candidate(p, candidate_labels, candidate_uti)]
    if limit is not None:
        candidates = candidates[:limit]
    click.echo(f"候选 {len(candidates)} 张,开始全文 OCR...")

    engine_name, ocr_fn = _pick_engine(logger)
    click.echo(f"引擎: {engine_name}")

    out_path = Path(out) if out else cfg.path("ocr") / f"fulltext-{_dt.date.today():%Y%m%d}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _extract_one(idx_p):
        """对单张跑 OCR，返回 (idx, jsonl_str_or_None, is_skip, is_err)。"""
        idx, p = idx_p
        path = getattr(p, "path", None)
        if not path or not Path(path).exists():
            return idx, None, True, False
        try:
            text = ocr_fn(path)
        except Exception as e:
            errs_inner = e
            logger.info(f"OCR 失败 {p.cloud_guid}: {errs_inner}")
            return idx, None, False, True
        line = json.dumps(
            {
                "cloud_guid": p.cloud_guid,
                "filename": p.original_filename,
                "date": photo_date(p),
                "uti": p.uti,
                "labels": list(p.labels or []),
                "text": text,
            },
            ensure_ascii=False,
        )
        return idx, line, False, False

    extract_map: dict = {}
    skipped = errs = 0
    with ThreadPoolExecutor(max_workers=4) as executor:
        futs = {executor.submit(_extract_one, (i, p)): i
                for i, p in enumerate(candidates)}
        for fut in as_completed(futs):
            idx, line, is_skip, is_err = fut.result()
            if is_skip:
                skipped += 1
            elif is_err:
                errs += 1
            elif line is not None:
                extract_map[idx] = line

    n = 0
    with out_path.open("w") as f:
        for idx in sorted(extract_map):
            f.write(extract_map[idx] + "\n")
            n += 1
    click.echo(f"全文导出: {n} 条 / 跳过 {skipped} / 错误 {errs} → {out_path}")
    logger.info(f"ocr-extract: n={n} skipped={skipped} errs={errs} -> {out_path}")
