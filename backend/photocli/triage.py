"""triage — 截图分桶。把"待清理候选"截图分四桶(junk/receipt/reimbursed/unsure)
并标进 _TRIAGE_* 相册,待删两桶额外进 _TO_DELETE_BATCH_triage,供用户人工审后手动删。

铁律:绝不自动删照片。本命令最多打相册;最后一锤(⌘⌫)永远是用户在 Photos.app 手动。
保护(收藏/已命名人物/🔒敏感)优先 → 一律进 unsure(留),绝不进 junk/reimbursed。
全文 PII 只读 gitignored jsonl,HTML/stdout 一律不显示完整号码。
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import json
import re
from pathlib import Path

import click

from .lib import (
    REPO_ROOT,
    get_logger,
    is_protected,
    iter_photos,
    load_config,
    photo_date,
)

# ---------------- 文本规则 ----------------
_RECEIPT_KW = [
    "火车", "高铁", "动车", "航班", "机票", "发票", "行程单", "12306",
    "票号", "座位", "检票", "订单号", "金额", "¥", "登机牌",
]

# 出行/行程日期抽取(取最晚一个)
_DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), None),
    (re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日"), None),
    (re.compile(r"(\d{4})/(\d{2})/(\d{2})"), None),
    (re.compile(r"(\d{4})\.(\d{2})\.(\d{2})"), None),
]


def _is_receipt(text: str) -> bool:
    return any(kw in text for kw in _RECEIPT_KW)


def _is_guide(text: str, guide_kw: list[str]) -> bool:
    return any(kw in text for kw in guide_kw)


def _latest_date(text: str) -> _dt.date | None:
    """从全文抽所有日期,返回最晚一个(合法范围内)。抽不到返回 None。"""
    found: list[_dt.date] = []
    for rx, _ in _DATE_PATTERNS:
        for m in rx.findall(text):
            try:
                y, mo, d = int(m[0]), int(m[1]), int(m[2])
                if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                    found.append(_dt.date(y, mo, d))
            except (ValueError, IndexError):
                continue
    return max(found) if found else None


def _months_ago(months: int) -> _dt.date:
    today = _dt.date.today()
    m = today.month - months
    y = today.year
    while m <= 0:
        m += 12
        y -= 1
    # clamp day
    import calendar
    d = min(today.day, calendar.monthrange(y, m)[1])
    return _dt.date(y, m, d)


def _meaningful_len(text: str) -> int:
    """去掉空白/标点后的有效字符数(判 junk 的"信息量")。"""
    return len(re.sub(r"[\s\W_]+", "", text or "", flags=re.UNICODE))


# ---------------- 分桶 ----------------
def _classify(photo, text: str, cfg, threshold: _dt.date, guide_kw: list[str]) -> tuple[str, str]:
    """返回 (bucket, reason)。每张照片恰好落一个桶。"""
    prot = is_protected(photo, cfg)
    if prot:
        return "unsure", f"保护({prot})"

    if not text.strip():
        return "unsure", "无可用 OCR 文本，需人工查看"

    if _is_receipt(text):
        latest = _latest_date(text)
        if latest is not None and latest >= threshold:
            return "receipt", f"票据·行程 {latest.isoformat()}(近期)"
        if latest is not None:
            return "receipt", f"旧票据·行程 {latest.isoformat()}（报销状态未知）"
        return "receipt", "票据·日期及报销状态未知"

    if _is_guide(text, guide_kw):
        return "unsure", "攻略(另有库存档,留)"

    ml = _meaningful_len(text)
    if ml < 15:
        return "junk", f"信息量极低({ml}字)"

    return "unsure", "未匹配任何规则"


# ---------------- 候选选取 ----------------
def _select_candidates(cfg) -> list:
    """优先取"待清理候选"相册成员;取不到则 uti==public.png 或 labels 含 Document。"""
    photos = iter_photos(cfg)
    in_album = [p for p in photos if "待清理候选" in (p.albums or [])]
    if in_album:
        return in_album, "待清理候选相册"
    fallback = [
        p
        for p in photos
        if (getattr(p, "uti", None) == "public.png")
        or ("Document" in (p.labels or []))
    ]
    return fallback, "uti=public.png / labels∋Document(无待清理相册,兜底)"


# ---------------- HTML(脱敏) ----------------
_BUCKET_META = {
    "junk": ("🗑 纯垃圾", "#f85149", "待删候选"),
    "reimbursed": ("📄 已报销估计", "#d29922", "待删候选"),
    "receipt": ("🎫 票据(近期)", "#3fb950", "留"),
    "unsure": ("❓ 存疑", "#58a6ff", "留人工"),
    "protected": ("🔒 保护", "#a371f7", "留"),
}


def _render_html(counts: dict, samples: dict, source: str, total: int) -> str:
    # 同 ocr.py:打进 HTML 的生成时间带偏移量;裸 date.today() 是无时区本地日。
    today = _dt.datetime.now(_dt.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %z")
    kpis = []
    for b in ("junk", "reimbursed", "receipt", "unsure"):
        label, color, fate = _BUCKET_META[b]
        kpis.append(
            f"<div class='kpi'><div class='n' style='color:{color}'>{counts.get(b, 0)}</div>"
            f"<div class='l'>{label}<br><span class='fate'>{fate}</span></div></div>"
        )
    kpi_html = "\n".join(kpis)

    sections = []
    for b in ("junk", "reimbursed", "receipt", "unsure"):
        label, color, fate = _BUCKET_META[b]
        rows = []
        for s in samples.get(b, []):
            rows.append(
                f"<tr><td>{_html.escape(s['filename'] or '')}</td>"
                f"<td>{_html.escape(s['date'] or '')}</td>"
                f"<td class='r'>{_html.escape(s['reason'])}</td></tr>"
            )
        body = "\n".join(rows) or "<tr><td colspan='3' class='empty'>(空)</td></tr>"
        sections.append(
            f"<h2 style='color:{color}'>{label} · {counts.get(b, 0)} 张 <span class='fate'>[{fate}]</span></h2>"
            f"<table><thead><tr><th>文件名</th><th>拍摄日期</th><th>判定理由</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
    sec_html = "\n".join(sections)

    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>截图分桶 triage</title>
<style>
:root{{color-scheme:dark}}
body{{background:#0d1117;color:#c9d1d9;font:14px/1.6 -apple-system,Segoe UI,sans-serif;margin:0;padding:2rem}}
h1{{color:#f0f6fc;font-size:1.5rem;margin-bottom:.3rem}}
h2{{font-size:1.15rem;margin:2rem 0 .6rem}}
.meta{{color:#8b949e;margin-bottom:1.5rem}}
.warn{{background:#1d2d3d;border:1px solid #388bfd;color:#79c0ff;padding:.6rem 1rem;border-radius:6px;margin-bottom:1.5rem}}
.kpis{{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1rem}}
.kpi{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem 1.4rem;text-align:center;min-width:120px}}
.kpi .n{{font-size:2rem;font-weight:700}}
.kpi .l{{color:#8b949e;font-size:.85rem;margin-top:.3rem}}
.fate{{color:#6e7681;font-size:.8rem}}
table{{border-collapse:collapse;width:100%;margin-bottom:1rem}}
th,td{{padding:.4rem .8rem;border-bottom:1px solid #21262d;text-align:left;vertical-align:top}}
th{{color:#8b949e;font-weight:600;border-bottom:2px solid #30363d}}
td.r{{color:#8b949e}}
td.empty{{color:#6e7681;text-align:center}}
tr:hover{{background:#161b22}}
</style></head><body>
<h1>📸 截图分桶 triage(人工审核稿)</h1>
<div class="meta">候选来源: {_html.escape(source)} · 共 {total} 张 · 生成: {today}</div>
<div class="warn">⚠ 本工具只打相册,绝不自动删。待删两桶(纯垃圾+已报销估计,已排除保护)进
 <code>_TO_DELETE_BATCH_triage</code>,最后一锤请你在 Photos.app 手动 ⌘⌫。本报告不含任何完整号码/PII。</div>
<div class="kpis">{kpi_html}</div>
{sec_html}
</body></html>"""


# ---------------- 命令 ----------------
@click.command("triage")
@click.option("--limit", type=int, default=None, help="只处理前 N 张候选(抽测)")
@click.option("--samples", "n_samples", type=int, default=15, help="HTML 每桶展示样本数")
@click.option("--apply", "apply_", is_flag=True, default=False, help="写库:进 _TRIAGE_* 相册(默认 dry-run)")
@click.pass_context
def triage(ctx: click.Context, limit: int | None, n_samples: int, apply_: bool) -> None:
    """截图分四桶(junk/receipt/reimbursed/unsure)并标进相册,供人工审后手动删。

    默认 dry-run(只分桶+出报告,不写库)。--apply 才进 _TRIAGE_*/_TO_DELETE_BATCH_ 相册。
    绝不自动删照片。
    """
    cfg = load_config(ctx.obj.get("config_path") if ctx.obj else None)
    logger = get_logger("triage", cfg)
    sec = cfg.section("triage")
    delete_sec = cfg.section("delete")

    reimburse_months = int(sec.get("reimburse_months", 6))
    guide_kw = list(sec.get("guide_keywords", []) or [])
    buckets = dict(sec.get("buckets", {}) or {})
    delete_album = (delete_sec.get("album_prefix", "_TO_DELETE_BATCH_") or "_TO_DELETE_BATCH_") + "triage"
    threshold = _months_ago(reimburse_months)

    # 全文映射:cloud_guid -> text
    ft_rel = sec.get("fulltext", "data/ocr/fulltext-20260519.jsonl")
    ft_path = Path(ft_rel)
    if not ft_path.is_absolute():
        ft_path = REPO_ROOT / ft_rel
    guid_text: dict[str, str] = {}
    if ft_path.exists():
        for line in ft_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            g = rec.get("cloud_guid")
            if g:
                guid_text[g] = rec.get("text", "") or ""
    else:
        click.echo(f"⚠ 全文 jsonl 不存在: {ft_path}(无文本的照片按空文本处理)")

    # 选候选
    candidates, source = _select_candidates(cfg)
    click.echo(f"候选: {len(candidates)} 张(来源: {source})")
    if limit is not None:
        candidates = candidates[:limit]
        click.echo(f"  --limit {limit} → 实际处理 {len(candidates)} 张")

    # 分桶
    bucketed: dict[str, list] = {"junk": [], "receipt": [], "reimbursed": [], "unsure": []}
    samples: dict[str, list] = {"junk": [], "receipt": [], "reimbursed": [], "unsure": []}
    protected_count = 0
    for p in candidates:
        text = guid_text.get(p.cloud_guid, "")
        bucket, reason = _classify(p, text, cfg, threshold, guide_kw)
        bucketed[bucket].append(p)
        if reason.startswith("保护"):
            protected_count += 1
        if len(samples[bucket]) < n_samples:
            samples[bucket].append(
                {"filename": getattr(p, "original_filename", None), "date": photo_date(p), "reason": reason}
            )

    counts = {b: len(v) for b, v in bucketed.items()}
    counts["protected"] = protected_count
    total = len(candidates)
    classified = sum(len(v) for v in bucketed.values())
    unclassified = total - classified

    click.echo(
        f"分桶: junk={counts['junk']} receipt={counts['receipt']} "
        f"reimbursed={counts['reimbursed']} unsure={counts['unsure']} "
        f"(其中保护→unsure {protected_count}) · unclassified={unclassified}"
    )

    # 写 coverage json + html
    ocr_dir = cfg.path("ocr")
    ocr_dir.mkdir(parents=True, exist_ok=True)
    cov_path = ocr_dir / "triage-coverage.json"
    cov_path.write_text(
        json.dumps(
            {
                "total": total,
                "junk": counts["junk"],
                "receipt": counts["receipt"],
                "reimbursed": counts["reimbursed"],
                "unsure": counts["unsure"],
                "protected": protected_count,
                "unclassified": unclassified,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    reports_dir = cfg.path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    html_path = reports_dir / "screenshot-triage.html"
    html_path.write_text(_render_html(counts, samples, source, total))

    click.echo(f"coverage: {cov_path}")
    click.echo(f"报告: {html_path}")

    if unclassified != 0:
        logger.info(f"⚠ unclassified={unclassified} (应为 0)")
        click.echo(f"⚠ unclassified={unclassified}(应为 0,请检查分桶逻辑)")

    # 写库 / dry-run
    if not apply_:
        del_n = sum(
            1
            for b in ("junk", "reimbursed")
            for p in bucketed[b]
            if not is_protected(p, cfg)
        )
        click.echo(
            f"[dry-run] 将把各桶进 _TRIAGE_* 相册;待删 {del_n} 张(junk+reimbursed,排除保护)"
            f"进 '{delete_album}'(加 --apply 执行)"
        )
        return

    from osxphotos.photosalbum import PhotosAlbum

    for b, photos in bucketed.items():
        album_name = buckets.get(b)
        if not album_name or not photos:
            continue
        todo = [p for p in photos if album_name not in (p.albums or [])]
        if todo:
            PhotosAlbum(album_name).extend(todo)
        click.echo(f"  [apply] {album_name}: +{len(todo)}(已在 {len(photos)-len(todo)})")

    # 待删候选:junk + reimbursed,排除任何保护
    to_delete = [
        p
        for b in ("junk", "reimbursed")
        for p in bucketed[b]
        if not is_protected(p, cfg)
    ]
    todo_del = [p for p in to_delete if delete_album not in (p.albums or [])]
    if todo_del:
        PhotosAlbum(delete_album).extend(todo_del)
    click.echo(
        f"  [apply] {delete_album}(待删候选): +{len(todo_del)}(已在 {len(to_delete)-len(todo_del)})"
    )
    logger.info(
        f"triage apply: total={total} junk={counts['junk']} receipt={counts['receipt']} "
        f"reimbursed={counts['reimbursed']} unsure={counts['unsure']} to_delete={len(to_delete)}"
    )
