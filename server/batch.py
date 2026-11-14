"""批量入库流水线：多张试卷照片 → AI 整页识别 → 自动去重 → 直接入库。

设计取舍：
- **识别并行、入库串行**。识别是网络等待，2 个并发能省一半时间；入库必须串行，
  否则两个线程同时算 next_id 会撞号（items.id 是主键，撞了整张图都白跑）。
- **任务状态只在内存**。进程重启任务列表就没了，但已入库的题在 SQLite 里，不会丢。
  自用场景没必要为此上数据库。
- **不自动裁配图**。模型给的图形坐标不可靠，裁歪了孩子做题时看到的是半张图，
  比没有图更糟。识别时只标记 has_figure，前端提示家长去详情页框一下。
"""
from __future__ import annotations

import re
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import ai
import db

MAX_PARALLEL = 2          # 并发识别数，模型接口限流紧就调成 1
MAX_FILES = 30            # 一次批量最多几张图
JOB_KEEP = 20             # 内存里保留最近多少个任务

JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()
_DB_LOCK = threading.Lock()   # 入库串行

QTYPE_ALIAS = {
    "choice": "choice", "选择题": "choice", "选择": "choice",
    "fill": "fill", "填空题": "fill", "填空": "fill",
    "solve": "solve", "解答题": "solve", "解答": "solve", "应用题": "solve",
}


# ---------------------------------------------------------------- 工具
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _as_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [s.strip() for s in v.split("\n") if s.strip()]
    return []


def _fingerprint(stem: str) -> str:
    """题干指纹：去掉所有非字母数字汉字，取前 40 字。"""
    return re.sub(r"[^\w\u4e00-\u9fff]", "", stem or "")[:40]


def _answer_key(s: str) -> str:
    """答案比对用：抹掉空格、单位符号、括号这类不影响对错的差异。"""
    return re.sub(r"[\s\[\]()（）,，。:：]", "", str(s or "")).lower()


def match_chapter(name: str, chapters: list[str]) -> str:
    """把模型给的章节归到字典里，归不上就保留原值（别丢信息）。"""
    n = (name or "").strip()
    if not n:
        return ""
    for c in chapters:
        if c == n:
            return c
    for c in chapters:
        if c and (c in n or n in c):
            return c
    return n


def normalize(draft: dict, opt: dict, chapters: list[str], sort_base: int) -> dict:
    """模型草稿 → items 表能直接插的结构。"""
    stem = str(draft.get("stem") or "").strip()
    answer = str(draft.get("answer") or "").strip() or "?"
    qtype = QTYPE_ALIAS.get(str(draft.get("qtype") or "").strip(), "choice")
    sub_items = _as_list(draft.get("sub_items"))
    options = _as_list(draft.get("options"))

    points = draft.get("points")
    try:
        points = int(points)
    except (TypeError, ValueError):
        points = 0

    student = str(draft.get("student_answer") or "").strip()
    # 答案没算出来，或者和学生写的一样（八成是做对了、只是过程/格式被判错）→ 标「待核对」，
    # 别让它混进正常错题里，否则重做卷会印出孩子本来就会的题。
    answered = answer not in ("", "?")
    same = answered and _answer_key(answer) == _answer_key(student) and bool(_answer_key(student))
    status = "unverified" if (not answered or same) else "wrong"

    return {
        "subject": opt.get("subject") or "数学",
        "grade": opt.get("grade") or "六年级上册",
        "chapter": match_chapter(draft.get("chapter", ""), chapters),
        "knowledge": _as_list(draft.get("knowledge")),
        "qtype": qtype,
        "status": status,
        "stars": 1,
        "points": max(0, points),
        "space_mm": 50 if qtype == "solve" else 0,
        "stem": stem,
        "sub_items": sub_items,
        "options": options,
        "answer": answer,
        "student_answer": str(draft.get("student_answer") or "").strip(),
        "analysis": _as_list(draft.get("analysis")),
        "error_cause": str(draft.get("error_cause") or "").strip(),
        "figures": [],
        "exam": opt.get("exam") or "批量导入",
        "exam_date": opt.get("exam_date") or datetime.now().strftime("%Y-%m-%d"),
        "sort": sort_base,
        "no": str(draft.get("no") or "").strip(),
        "has_figure": bool(draft.get("has_figure")),
    }


# ---------------------------------------------------------------- 任务
def create_job(files: list[str], options: dict) -> dict:
    files = [Path(str(f)).name for f in files if str(f).strip()]
    if not files:
        raise ValueError("没有要处理的图片")
    if len(files) > MAX_FILES:
        raise ValueError(f"一次最多 {MAX_FILES} 张，分几批传吧")

    settings = db.get_settings()
    if not (settings.get("llm_key") or "").strip():
        raise RuntimeError("还没配置大模型 API Key，先去「设置」里填一下再批量识别。")

    job_id = "b" + datetime.now().strftime("%m%d%H%M%S")
    job = {
        "id": job_id,
        "status": "running",
        "created_at": _now(),
        "finished_at": None,
        "total": len(files),
        "done": 0,
        "items": 0,          # 识别出的题数
        "saved": 0,          # 入库的题数
        "skipped": 0,        # 去重跳过的题数
        "unverified": 0,     # 入库但标了「待核对」的题数
        "failed": 0,         # 识别失败的图片数
        "options": options,
        "files": [
            {
                "file": f,
                "status": "pending",
                "stage": "排队中",
                "count": 0,
                "saved_ids": [],
                "figs": [],       # 含图形、待家长框选配图的题目 id
                "dups": [],
                "error": "",
            }
            for f in files
        ],
        "saved_ids": [],
    }
    with _JOB_LOCK:
        JOBS[job_id] = job
        for old in sorted(JOBS, key=lambda k: JOBS[k]["created_at"])[:-JOB_KEEP]:
            JOBS.pop(old, None)

    threading.Thread(target=_run, args=(job_id,), daemon=True).start()
    return snapshot(job_id)


def snapshot(job_id: str) -> dict | None:
    job = JOBS.get(job_id)
    if not job:
        return None
    # 深拷贝一层，避免序列化时被后台线程改到一半
    out = dict(job)
    out["files"] = [
        {**f, "saved_ids": list(f["saved_ids"]), "figs": list(f["figs"]), "dups": list(f["dups"])}
        for f in job["files"]
    ]
    out["saved_ids"] = list(job["saved_ids"])
    return out


def list_jobs(limit: int = 5) -> list[dict]:
    rows = sorted(JOBS.values(), key=lambda j: j["created_at"], reverse=True)[:limit]
    return [
        {
            "id": j["id"],
            "status": j["status"],
            "created_at": j["created_at"],
            "total": j["total"],
            "saved": j["saved"],
            "failed": j["failed"],
        }
        for j in rows
    ]


# ---------------------------------------------------------------- 执行
def _run(job_id: str) -> None:
    job = JOBS.get(job_id)
    if not job:
        return
    opt = job["options"]
    settings = db.get_settings()
    chapters = [c.strip() for c in (settings.get("chapter_list") or "").split(",") if c.strip()]
    # 指纹集合先建好，去重就不用每题翻全表
    seen = {_fingerprint(it.get("stem", "")) for it in db.list_items({})} - {""}

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        list(pool.map(lambda i: _one(job, i, settings, chapters, opt, seen), range(job["total"])))

    job["status"] = "done"
    job["finished_at"] = _now()


def _one(job: dict, idx: int, settings: dict, chapters: list[str], opt: dict, seen: set) -> None:
    row = job["files"][idx]
    row["status"] = "running"
    row["stage"] = "识别中"

    src = Path(__file__).resolve().parent / "data" / "uploads" / row["file"]
    if not src.exists():
        row.update(status="failed", stage="图片不见了", error="上传文件已不存在")
        job["failed"] += 1
        job["done"] += 1
        return

    try:
        drafts = ai.recognize_page(src, settings, opt.get("hint", ""))
    except Exception as e:  # 网络错 / 模型没给 JSON，都算这张图失败，不影响别人
        row.update(status="failed", stage="识别失败", error=str(e))
        job["failed"] += 1
        job["done"] += 1
        return

    if not drafts:
        row.update(status="done", stage="这张没找到错题", count=0)
        job["done"] += 1
        return

    row["stage"] = f"入库 {len(drafts)} 题"
    job["items"] += len(drafts)

    for draft in drafts:
        with _DB_LOCK:
            try:
                item = _save_one(draft, opt, chapters, job, seen)
            except Exception:
                traceback.print_exc()
                row["error"] = "有题目入库失败，看服务端日志"
                continue
        if item is None:
            job["skipped"] += 1
            row["dups"].append(str(draft.get("stem") or "")[:24])
        else:
            job["saved"] += 1
            row["count"] += 1
            row["saved_ids"].append(item["id"])
            job["saved_ids"].append(item["id"])
            if item.get("status") == "unverified":
                job["unverified"] += 1
            if draft.get("has_figure"):
                row["figs"].append(item["id"])

    row["status"] = "done"
    row["stage"] = f"入库 {row['count']} 题" + (f"，重复 {len(row['dups'])}" if row["dups"] else "")
    job["done"] += 1


def _save_one(draft: dict, opt: dict, chapters: list[str], job: dict, seen: set) -> dict | None:
    """归一化 → 去重 → 入库。返回新题，重复或空题干则返回 None。"""
    data = normalize(draft, opt, chapters, sort_base=job["saved"])

    fp = _fingerprint(data["stem"])
    if not fp:
        return None
    if fp in seen:
        return None
    seen.add(fp)

    data.pop("no", None)
    data.pop("has_figure", None)
    return db.create_item(data)
