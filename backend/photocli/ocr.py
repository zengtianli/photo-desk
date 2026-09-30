"""本机 OCR：Apple Vision（ocrmac）识别与候选规则，以及 ocr-extract 全文导出。

敏感照片识别（原 ocr-scan）由 App 引擎 bridge.build_plan(kind='sensitive') 负责，命令为
`photodesk plan sensitive`。OCR 文本含个人信息：只写本机 PhotoDesk 数据目录，不外发、不进 git。
OCR 必须本机离线：首选 Apple Vision，失败兜底 tesseract。
"""
from __future__ import annotations

import datetime as _dt
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click

from .lib import (
    get_logger,
    iter_photos,
    load_config,
    photo_date,
)


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


# ---------------- 命令 ----------------
@click.command("ocr-extract")
@click.option("--limit", type=int, default=None, help="只处理前 N 张(抽测)")
@click.option("--out", default=None, help="输出 jsonl 路径（默认 PhotoDesk/cli/ocr/fulltext-<日期>.jsonl）")
@click.pass_context
def ocr_extract(ctx: click.Context, limit: int | None, out: str | None) -> None:
    """对 OCR 候选图导出全文 jsonl（仅命令行工具，供本机其他整理流程复用）。

    全文含个人信息，只写本机 PhotoDesk 数据目录（默认 cli/ocr/），不外发。
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
