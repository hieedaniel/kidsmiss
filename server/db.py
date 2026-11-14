"""SQLite 数据层 —— 只用标准库。

表结构：
  items     错题库
  attempts  每次重做的结果（掌握情况全靠它算）
  papers    生成的卷子
  settings  LLM 等配置（键值对）
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DB_PATH = DATA / "cuoti.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id             TEXT PRIMARY KEY,
    subject        TEXT NOT NULL DEFAULT '数学',
    grade          TEXT NOT NULL DEFAULT '六年级上册',
    chapter        TEXT DEFAULT '',
    knowledge      TEXT DEFAULT '[]',
    qtype          TEXT DEFAULT 'choice',
    status         TEXT DEFAULT 'wrong',
    stars          INTEGER DEFAULT 1,
    points         INTEGER DEFAULT 0,
    space_mm       INTEGER DEFAULT 0,
    stem           TEXT DEFAULT '',
    sub_items      TEXT DEFAULT '[]',
    options        TEXT DEFAULT '[]',
    answer         TEXT DEFAULT '',
    student_answer TEXT DEFAULT '',
    analysis       TEXT DEFAULT '[]',
    error_cause    TEXT DEFAULT '',
    figures        TEXT DEFAULT '[]',
    exam           TEXT DEFAULT '',
    exam_date      TEXT DEFAULT '',
    sort           INTEGER DEFAULT 0,
    created_at     TEXT DEFAULT '',
    updated_at     TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id    TEXT NOT NULL,
    paper_id   INTEGER,
    result     TEXT NOT NULL,
    note       TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS papers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    round      INTEGER DEFAULT 1,
    mode       TEXT DEFAULT 'blank',
    item_ids   TEXT DEFAULT '[]',
    file       TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    k TEXT PRIMARY KEY,
    v TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_chapter ON items(chapter);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_attempts_item ON attempts(item_id);
"""

JSON_FIELDS = ("knowledge", "sub_items", "options", "analysis", "figures")


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


# ---------------------------------------------------------------- 序列化
def _load(row: sqlite3.Row) -> dict:
    d = dict(row)
    for f in JSON_FIELDS:
        try:
            d[f] = json.loads(d.get(f) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[f] = []
    d["stars"] = d.get("stars") or 0
    return d


def _dump(item: dict) -> dict:
    d = dict(item)
    for f in JSON_FIELDS:
        if f in d and not isinstance(d[f], str):
            d[f] = json.dumps(d[f], ensure_ascii=False)
    return d


# ---------------------------------------------------------------- items
def next_id() -> str:
    with connect() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM items").fetchone()
        n = row["n"] + 1
        while True:
            cand = f"Q{n:04d}"
            if not c.execute("SELECT 1 FROM items WHERE id=?", (cand,)).fetchone():
                return cand
            n += 1


def list_items(filters: dict) -> list[dict]:
    sql = "SELECT * FROM items WHERE 1=1"
    args: list = []

    if filters.get("subject"):
        sql += " AND subject=?"
        args.append(filters["subject"])
    if filters.get("chapter"):
        sql += " AND chapter=?"
        args.append(filters["chapter"])
    if filters.get("status"):
        sql += " AND status=?"
        args.append(filters["status"])
    if filters.get("qtype"):
        sql += " AND qtype=?"
        args.append(filters["qtype"])
    if filters.get("stars"):
        sql += " AND stars>=?"
        args.append(int(filters["stars"]))
    if filters.get("q"):
        sql += " AND (stem LIKE ? OR knowledge LIKE ? OR error_cause LIKE ?)"
        like = f"%{filters['q']}%"
        args += [like, like, like]
    if filters.get("since"):
        sql += " AND created_at>=?"
        args.append(filters["since"])
    if filters.get("ids"):
        ids = filters["ids"]
        sql += f" AND id IN ({','.join('?' * len(ids))})"
        args += ids

    order = {
        "new": "created_at DESC",
        "old": "created_at ASC",
        "stars": "stars DESC, created_at DESC",
        "chapter": "chapter ASC, sort ASC",
    }.get(filters.get("sort") or "new", "created_at DESC")
    sql += f" ORDER BY {order}"

    with connect() as c:
        rows = c.execute(sql, args).fetchall()
    return [_load(r) for r in rows]


def get_item(item_id: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    return _load(row) if row else None


def create_item(item: dict) -> dict:
    item = dict(item)
    item.setdefault("id", next_id())
    item["created_at"] = item.get("created_at") or now()
    item["updated_at"] = item["created_at"]
    d = _dump(item)
    cols = ",".join(d)
    marks = ",".join("?" * len(d))
    with connect() as c:
        c.execute(f"INSERT INTO items ({cols}) VALUES ({marks})", list(d.values()))
    return get_item(item["id"])


def update_item(item_id: str, patch: dict) -> dict | None:
    if not get_item(item_id):
        return None
    patch = dict(patch)
    patch.pop("id", None)
    patch.pop("created_at", None)
    patch["updated_at"] = now()
    d = _dump(patch)
    sets = ",".join(f"{k}=?" for k in d)
    with connect() as c:
        c.execute(f"UPDATE items SET {sets} WHERE id=?", [*d.values(), item_id])
    return get_item(item_id)


def delete_item(item_id: str) -> bool:
    with connect() as c:
        c.execute("DELETE FROM attempts WHERE item_id=?", (item_id,))
        cur = c.execute("DELETE FROM items WHERE id=?", (item_id,))
    return cur.rowcount > 0


# ---------------------------------------------------------------- attempts
def add_attempt(item_id: str, result: str, note: str = "", paper_id=None) -> dict:
    """记一次重做结果，同时调整星级：错了 +1，连对两次 -1（最低 1）。"""
    ts = now()
    with connect() as c:
        c.execute(
            "INSERT INTO attempts (item_id,paper_id,result,note,created_at)"
            " VALUES (?,?,?,?,?)",
            (item_id, paper_id, result, note, ts),
        )
        item = c.execute("SELECT stars FROM items WHERE id=?", (item_id,)).fetchone()
        if item:
            stars = item["stars"] or 1
            if result == "wrong":
                stars = min(3, stars + 1)
                status = "wrong"
            else:
                status = "mastered" if stars <= 1 else "wrong"
            c.execute(
                "UPDATE items SET stars=?, status=?, updated_at=? WHERE id=?",
                (stars, status, ts, item_id),
            )
    return {"item_id": item_id, "result": result, "created_at": ts}


def list_attempts(item_id: str | None = None) -> list[dict]:
    sql = "SELECT * FROM attempts"
    args: list = []
    if item_id:
        sql += " WHERE item_id=?"
        args.append(item_id)
    sql += " ORDER BY created_at DESC"
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def mastery_map() -> dict[str, dict]:
    """每个题的最新重做情况 + 下次该复习的时间（简易间隔重复）。"""
    intervals = {0: 1, 1: 3, 2: 7, 3: 21}
    with connect() as c:
        rows = c.execute(
            "SELECT item_id, result, created_at FROM attempts ORDER BY created_at ASC"
        ).fetchall()

    by_item: dict[str, list] = {}
    for r in rows:
        by_item.setdefault(r["item_id"], []).append(
            {"result": r["result"], "created_at": r["created_at"]}
        )

    out = {}
    for item_id, hist in by_item.items():
        streak = 0
        for h in reversed(hist):
            if h["result"] == "correct":
                streak += 1
            else:
                break
        last = hist[-1]["created_at"]
        try:
            base = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            base = datetime.now()
        gap = intervals[min(streak, 3)]
        due = base + timedelta(days=gap)
        out[item_id] = {
            "attempts": len(hist),
            "streak": streak,
            "last_result": hist[-1]["result"],
            "last_at": last,
            "due_at": due.strftime("%Y-%m-%d"),
            "overdue": due.date() <= datetime.now().date(),
        }
    return out


# ---------------------------------------------------------------- papers
def create_paper(title: str, round_no: int, mode: str, item_ids: list[str], file: str) -> int:
    with connect() as c:
        cur = c.execute(
            "INSERT INTO papers (title,round,mode,item_ids,file,created_at)"
            " VALUES (?,?,?,?,?,?)",
            (title, round_no, mode, json.dumps(item_ids), file, now()),
        )
        return cur.lastrowid


def list_papers() -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM papers ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["item_ids"] = json.loads(d.get("item_ids") or "[]")
        d["count"] = len(d["item_ids"])
        out.append(d)
    return out


def get_paper(pid: int) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["item_ids"] = json.loads(d.get("item_ids") or "[]")
    return d


# ---------------------------------------------------------------- settings
DEFAULT_SETTINGS = {
    "llm_base": "https://api.vectorengine.ai/v1",
    "llm_key": "",
    "llm_model": "gpt-4o",
    "llm_prompt": "",
    "chapter_list": "分数乘法,分数除法,位置与方向,比,圆,百分数",
}


def get_settings() -> dict:
    with connect() as c:
        rows = c.execute("SELECT k,v FROM settings").fetchall()
    d = dict(DEFAULT_SETTINGS)
    d.update({r["k"]: r["v"] for r in rows})
    return d


def save_settings(patch: dict) -> dict:
    with connect() as c:
        for k, v in patch.items():
            c.execute(
                "INSERT INTO settings (k,v) VALUES (?,?)"
                " ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (k, str(v)),
            )
    return get_settings()


# ---------------------------------------------------------------- stats
def stats() -> dict:
    with connect() as c:
        total = c.execute("SELECT COUNT(*) n FROM items").fetchone()["n"]
        active = c.execute(
            "SELECT COUNT(*) n FROM items WHERE status!='mastered'"
        ).fetchone()["n"]
        mastered = c.execute(
            "SELECT COUNT(*) n FROM items WHERE status='mastered'"
        ).fetchone()["n"]
        by_chapter = c.execute(
            "SELECT chapter, COUNT(*) n FROM items"
            " WHERE chapter!='' GROUP BY chapter ORDER BY n DESC"
        ).fetchall()
        by_status = c.execute(
            "SELECT status, COUNT(*) n FROM items GROUP BY status"
        ).fetchall()
        week = c.execute(
            "SELECT substr(created_at,1,10) d, COUNT(*) n FROM items"
            " GROUP BY d ORDER BY d DESC LIMIT 14"
        ).fetchall()
        attempts_trend = c.execute(
            "SELECT substr(created_at,1,10) d,"
            " SUM(result='correct') ok, SUM(result='wrong') bad"
            " FROM attempts GROUP BY d ORDER BY d DESC LIMIT 14"
        ).fetchall()
    return {
        "total": total,
        "active": active,
        "mastered": mastered,
        "by_chapter": [dict(r) for r in by_chapter],
        "by_status": [dict(r) for r in by_status],
        "recent_items": [dict(r) for r in week],
        "attempt_trend": [dict(r) for r in attempts_trend],
    }
