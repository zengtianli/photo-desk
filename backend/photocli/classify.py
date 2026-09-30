"""分类建议规则：年月相册、场景关键词、人物/宠物相册与待清理候选。

由 App 引擎 bridge.build_plan(kind='classify') 调用（`photodesk plan classify`）；
去掉已有归类、写入与核对都在 bridge 完成。
"""
from __future__ import annotations

from .lib import PlanRow, is_protected, iter_photos, photo_date


# ---------------- plan 生成 ----------------
def _build_rows(cfg) -> list[PlanRow]:
    return [row for row, _ in _build_pairs(cfg)]


def _build_pairs(cfg) -> list[tuple[PlanRow, object]]:
    """(建议, 照片)：共享 Cloud GUID 的副本各自对应自己的建议。"""
    sec = cfg.section("classify")
    pet_faces = set(sec.get("pet_faces", []) or [])
    scene_labels = set(sec.get("scene_labels", []) or [])

    rows: list[tuple[PlanRow, object]] = []
    for p in iter_photos(cfg):
        guid = p.cloud_guid
        if not guid:
            continue  # 无 cloud_guid 不进跨次映射
        fname = p.original_filename or ""
        date = photo_date(p)

        # 1. 时间相册
        d = getattr(p, "date", None)
        if d:
            target = f"{d.year}/{d.year}-{d.month:02d}"
            rows.append((PlanRow(guid, fname, date, "add-album", target), p))

        # 2. 场景 keyword
        for label in sorted(set(p.labels or []) & scene_labels):
            rows.append((PlanRow(guid, fname, date, "add-keyword", f"场景:{label}"), p))

        # 3. 人物相册(_UNKNOWN_ 跳过;宠物归宠物相册)
        for name in (p.persons or []):
            if not name or name == "_UNKNOWN_":
                continue
            base = "宠物" if name in pet_faces else "人物"
            rows.append((PlanRow(guid, fname, date, "add-album", f"{base}/{name}"), p))

        # 4. 可清理候选(PNG 或 含 Document 标签)
        hits = []
        if p.uti == "public.png":
            hits.append("PNG")
        if "Document" in (p.labels or []):
            hits.append("Document标签")
        if hits and not is_protected(p, cfg):
            rows.append((PlanRow(guid, fname, date, "add-album", "待清理候选", "+".join(hits)), p))
    return rows
