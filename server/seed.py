"""把 cuoti/data/items.json 里的 8 道题导入新库，顺便造几条重做记录。

只在题库为空时跑一次（main.py 启动时自动判断）。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import db

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent.parent          # 2026-11-14-10-44-29
SRC = ROOT / "cuoti" / "data" / "items.json"
SCANS = ROOT / "cuoti" / "scans"
UPLOADS = BASE / "data" / "uploads"

CHAPTER = {
    "S1-Q01": ("位置与方向", "choice"),
    "S1-Q03": ("分数乘法", "choice"),
    "S1-Q04": ("分数除法", "choice"),
    "S1-Q05": ("位置与方向", "choice"),
    "S1-Q06": ("分数除法", "choice"),
    "S2-Q03": ("分数除法", "solve"),
    "S2-Q04": ("分数乘法", "solve"),
    "S2-Q05": ("分数除法", "solve"),
}


def run() -> None:
    if not SRC.exists():
        return
    data = json.loads(SRC.read_text(encoding="utf-8"))

    # 原卷照片搬进 uploads，让 figures 的 src 能直接解析
    if SCANS.exists():
        UPLOADS.mkdir(parents=True, exist_ok=True)
        for p in SCANS.glob("*.jpg"):
            dst = UPLOADS / p.name
            if not dst.exists():
                shutil.copy(p, dst)

    for idx, old in enumerate(data["items"]):
        chapter, qtype = CHAPTER.get(old["id"], ("未分类", "choice"))
        item = {
            "id": old["id"],
            "subject": "数学",
            "grade": "六年级上册",
            "chapter": chapter,
            "knowledge": old.get("knowledge") or [],
            "qtype": qtype,
            "status": old.get("status", "wrong"),
            "stars": old.get("stars", 1),
            "points": old.get("points") or 0,
            "space_mm": old.get("space_mm") or 0,
            "stem": old.get("stem", ""),
            "sub_items": old.get("sub_items") or [],
            "options": old.get("options") or [],
            "answer": old.get("answer", ""),
            "student_answer": old.get("student_answer", ""),
            "analysis": old.get("analysis") or [],
            "error_cause": old.get("error_cause", ""),
            "figures": old.get("figures") or [],
            "exam": "期中测试卷",
            "exam_date": "2026-11-14",
            "sort": idx,
            "created_at": (
                datetime(2026, 11, 14, 9, 30) + timedelta(hours=idx)
            ).strftime("%Y-%m-%d %H:%M:%S"),
        }
        db.create_item(item)

    # 造几条重做记录，让掌握情况页有东西看
    samples = [
        ("S1-Q01", "wrong", 12),
        ("S1-Q01", "correct", 9),
        ("S1-Q06", "wrong", 13),
        ("S1-Q06", "wrong", 8),
        ("S1-Q04", "correct", 6),
        ("S1-Q04", "correct", 3),
        ("S2-Q03", "wrong", 5),
        ("S2-Q05", "correct", 2),
    ]
    now = datetime.now()
    for item_id, result, days_ago in samples:
        ts = (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
        with db.connect() as c:
            c.execute(
                "INSERT INTO attempts (item_id,result,note,created_at) VALUES (?,?,?,?)",
                (item_id, result, "示例记录", ts),
            )
