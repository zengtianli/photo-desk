"""截图与票据分桶规则：junk（文字较少）/ receipt（票据）/ unsure（待核对）。

由 App 引擎 bridge.build_plan(kind='triage') 调用（`photodesk plan triage`），引擎负责本机 OCR
和相册映射：文字较少与待核对只进“待核对”相册，票据进“保留”相册，不建删除相册。
保护（收藏/已命名人物/保护关键词）优先 → 一律 unsure；空 OCR 不当垃圾；不推断报销状态。
"""
from __future__ import annotations

import datetime as _dt
import re

from .lib import is_protected, iter_photos

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
