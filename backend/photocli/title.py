"""照片标题建议：`YYYY-MM · 地点 · 人物/宠物/场景`。

由 App 引擎 bridge.build_plan(kind='title') 调用（`photodesk plan title`），只为空标题补建议，
已有标题不覆盖，写入前再核对。只写库内 title 字段（可逆）；个人号码等信息绝不进标题。
"""
from __future__ import annotations

from .lib import load_config

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

def _place_part(photo) -> str:
    pl = getattr(photo, "place", None)
    if not pl or not pl.name:
        return ""
    # 取最具体的一段(POI/地名),英文也行
    return pl.name.split(",")[0].strip()


def _subject_part(photo, cfg=None) -> str:
    # 1) 命名人物 / 宠物
    persons = [p for p in (photo.persons or []) if p and p != "_UNKNOWN_"]
    if persons:
        p0 = persons[0]
        pet_names = set((cfg or load_config()).section('classify').get('pet_faces', []) or [])
        return f"猫·{p0}" if p0 in pet_names else p0
    # 2) 场景标签(第一个能映射成中文的)
    for lab in (photo.labels or []):
        if lab in SCENE_CN:
            return SCENE_CN[lab]
    return ""


def _make_title(photo, cfg=None) -> str:
    d = getattr(photo, "date", None)
    date_part = d.strftime("%Y-%m") if d else ""
    place = _place_part(photo)
    subj = _subject_part(photo, cfg)
    parts = [x for x in (date_part, place, subj) if x]
    return " · ".join(parts)
