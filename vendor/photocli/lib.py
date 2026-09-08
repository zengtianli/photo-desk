"""共享接口层 — 所有子命令(audit/classify/ocr/shared/dedup)都依赖这里。

模块 agent 实现 classify.py / ocr.py 时,通过本文件的函数拿 db / 照片 / 配置 / 保护判断,
不要各自重复 PhotosDB 加载或 scope 逻辑。
"""
from __future__ import annotations

import csv
import datetime as _dt
import functools
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO_ROOT = Path(os.environ.get("PHOTOCLI_DATA_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_PATH = Path(os.environ.get("PHOTOCLI_CONFIG", Path(__file__).resolve().parents[1] / "config.yaml"))


# ---------------- 配置 ----------------
@dataclass
class Config:
    raw: dict[str, Any]

    @property
    def library(self) -> str | None:
        lib = self.raw.get("library")
        if not lib:
            return None
        return os.path.expanduser(lib)

    def path(self, key: str) -> Path:
        p = Path(self.raw.get("paths", {}).get(key, f"data/{key}"))
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def personal_only(self) -> bool:
        return bool(self.raw.get("scope", {}).get("personal_only", True))

    @property
    def protect(self) -> dict[str, Any]:
        return self.raw.get("protect", {})

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name, {})


@functools.lru_cache(maxsize=1)
def load_config(path: str | None = None) -> Config:
    p = Path(path) if path else CONFIG_PATH
    data = yaml.safe_load(p.read_text()) or {}
    return Config(raw=data)


# ---------------- 日志 ----------------
def get_logger(name: str, cfg: Config | None = None) -> logging.Logger:
    cfg = cfg or load_config()
    logdir = cfg.path("logs")
    logdir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(logdir / f"{_dt.date.today():%Y%m%d}.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ---------------- PhotosDB ----------------
@functools.lru_cache(maxsize=1)
def load_db(library: str | None = None):
    """加载 PhotosDB(慢,缓存)。返回 osxphotos.PhotosDB。"""
    from osxphotos import PhotosDB
    return PhotosDB(dbfile=library) if library else PhotosDB()


def iter_photos(cfg: Config | None = None, *, scope_personal: bool | None = None) -> list:
    """按 scope 返回照片列表。personal=只要不在共享相册的(--not-shared 等价)。"""
    cfg = cfg or load_config()
    db = load_db(cfg.library)
    photos = db.photos()
    personal = cfg.personal_only if scope_personal is None else scope_personal
    if personal:
        photos = [p for p in photos if not p.shared]
    return photos


@functools.lru_cache(maxsize=1)
def cloud_guid_index(library: str | None = None) -> dict[str, Any]:
    """cloud_guid -> PhotoInfo。跨次操作的稳定映射(铁律 #6)。"""
    db = load_db(library)
    return {p.cloud_guid: p for p in db.photos() if p.cloud_guid}


# ---------------- 保护规则 ----------------
def is_protected(photo, cfg: Config | None = None) -> str | None:
    """命中保护返回原因字符串,否则 None。classify/ocr/dedup 圈待删前必须调。"""
    cfg = cfg or load_config()
    pr = cfg.protect
    if pr.get("favorites") and getattr(photo, "favorite", False):
        return "收藏"
    if pr.get("named_persons"):
        persons = [x for x in (getattr(photo, "persons", []) or []) if x and x != "_UNKNOWN_"]
        if persons:
            return f"人物({persons[0]})"
    guard_kw = set(pr.get("keywords", []))
    if guard_kw & set(getattr(photo, "keywords", []) or []):
        return "保护keyword"
    return None


# ---------------- plan-file ----------------
@dataclass
class PlanRow:
    cloud_guid: str
    filename: str
    date: str
    action: str          # add-album / add-keyword / set-favorite ...
    target: str          # 相册名 / keyword 名
    note: str = ""


def write_plan(rows: Iterable[PlanRow], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["cloud_guid", "filename", "date", "action", "target", "note"])
        w.writeheader()
        for r in rows:
            w.writerow(r.__dict__)
    return len(rows)


def read_plan(path: Path) -> list[PlanRow]:
    if not path.exists():
        raise SystemExit(f"❌ plan 文件不存在: {path}")
    out = []
    with path.open() as f:
        for d in csv.DictReader(f):
            out.append(PlanRow(**d))
    return out


def photo_date(photo) -> str:
    d = getattr(photo, "date", None)
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else ""
