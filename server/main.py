"""错题集系统 —— HTTP 服务（标准库实现，零第三方依赖）

启动：
    python server/main.py            # 默认 http://127.0.0.1:8770
    python server/main.py --port 9000

首次启动会自动建库，并在题库为空时导入示例数据。
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import ai  # noqa: E402
import batch  # noqa: E402
import db  # noqa: E402
import paper  # noqa: E402

WEB_DIST = BASE.parent / "web" / "dist"
UPLOADS = BASE / "data" / "uploads"
THUMBS = UPLOADS / "thumbs"
PAPERS = BASE / "data" / "papers"
FIGS = BASE / "data" / "figs"
MAX_UPLOAD = 24 * 1024 * 1024  # 24MB

for d in (UPLOADS, THUMBS, PAPERS, FIGS):
    d.mkdir(parents=True, exist_ok=True)


class ApiError(Exception):
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code


# ---------------------------------------------------------------- 路由表
ROUTES: list[tuple[str, re.Pattern, object]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn

    return deco


# ---------------------------------------------------------------- 题库
@route("GET", r"/api/items")
def api_list_items(h):
    items = db.list_items(h.query)
    mastery = db.mastery_map()
    for it in items:
        it["mastery"] = mastery.get(it["id"])
    return {"items": items, "total": len(items)}


@route("POST", r"/api/items")
def api_create_item(h):
    payload = h.json_body()
    # 题干是唯一必填项：空题干进库等于一条废题，后面组卷会出空白
    if not str(payload.get("stem") or "").strip():
        raise ApiError("题干不能为空")
    if not str(payload.get("chapter") or "").strip():
        payload["chapter"] = "未分类"
    if payload.get("stars") is not None:
        try:
            payload["stars"] = max(1, min(3, int(payload["stars"])))
        except (TypeError, ValueError):
            payload["stars"] = 1
    item = db.create_item(payload)
    return {"item": item}


@route("GET", r"/api/items/(?P<item_id>[\w-]+)")
def api_get_item(h, item_id):
    item = db.get_item(item_id)
    if not item:
        raise ApiError("题目不存在", 404)
    item["mastery"] = db.mastery_map().get(item_id)
    item["attempts"] = db.list_attempts(item_id)
    return {"item": item}


@route("PUT", r"/api/items/(?P<item_id>[\w-]+)")
def api_update_item(h, item_id):
    item = db.update_item(item_id, h.json_body())
    if not item:
        raise ApiError("题目不存在", 404)
    return {"item": item}


@route("DELETE", r"/api/items/(?P<item_id>[\w-]+)")
def api_delete_item(h, item_id):
    if not db.delete_item(item_id):
        raise ApiError("题目不存在", 404)
    return {"ok": True}


@route("POST", r"/api/items/(?P<item_id>[\w-]+)/attempt")
def api_add_attempt(h, item_id):
    if not db.get_item(item_id):
        raise ApiError("题目不存在", 404)
    body = h.json_body()
    result = body.get("result")
    if result not in ("correct", "wrong"):
        raise ApiError("result 只能是 correct 或 wrong")
    db.add_attempt(item_id, result, body.get("note", ""), body.get("paper_id"))
    return {"item": db.get_item(item_id), "mastery": db.mastery_map().get(item_id)}


# ---------------------------------------------------------------- 上传 / 识别
@route("POST", r"/api/upload")
def api_upload(h):
    body = h.json_body()
    raw = body.get("data") or ""
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw)
    except Exception:
        raise ApiError("图片数据解析失败")
    if len(blob) > MAX_UPLOAD:
        raise ApiError("图片太大，请压缩到 20MB 以内")

    name = (body.get("filename") or "scan.jpg").replace(" ", "_")
    stem = datetime.now().strftime("%Y%m%d_%H%M%S_") + str(abs(hash(blob)) % 10000)
    ext = Path(name).suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".jpg"
    file = f"{stem}{ext}"
    (UPLOADS / file).write_bytes(blob)

    try:
        im = Image.open(UPLOADS / file)
        w, hgt = im.size
        thumb = im.convert("RGB")
        thumb.thumbnail((520, 520), Image.LANCZOS)
        thumb.save(THUMBS / f"{stem}.jpg", quality=82)
        thumb_name = f"{stem}.jpg"
    except Exception:
        w = hgt = 0
        thumb_name = file

    return {
        "file": file,
        "url": f"/uploads/{file}",
        "thumb": f"/uploads/thumbs/{thumb_name}",
        "width": w,
        "height": hgt,
    }


@route("POST", r"/api/ai/recognize")
def api_recognize(h):
    body = h.json_body()
    name = Path(str(body.get("file") or "")).name
    src = UPLOADS / name
    if not src.exists():
        raise ApiError("先上传图片再识别")
    try:
        draft = ai.recognize(src, db.get_settings(), body.get("hint", ""))
    except RuntimeError as e:
        raise ApiError(str(e), 502)
    return {"draft": draft}


# ---------------------------------------------------------------- 批量流水线
@route("POST", r"/api/batch/jobs")
def api_batch_start(h):
    body = h.json_body()
    files = body.get("files") or []
    if not isinstance(files, list):
        raise ApiError("files 要传文件名的数组")
    opt = {
        "subject": body.get("subject") or "数学",
        "grade": body.get("grade") or "六年级上册",
        "exam": body.get("exam") or "批量导入",
        "exam_date": body.get("exam_date") or datetime.now().strftime("%Y-%m-%d"),
        "hint": body.get("hint") or "",
    }
    try:
        job = batch.create_job(files, opt)
    except ValueError as e:
        raise ApiError(str(e))
    except RuntimeError as e:
        raise ApiError(str(e), 502)
    return {"job": job}


@route("GET", r"/api/batch/jobs/(?P<job_id>[\w-]+)")
def api_batch_get(h, job_id):
    job = batch.snapshot(job_id)
    if not job:
        raise ApiError("任务不存在（服务重启后历史任务会清空）", 404)
    return {"job": job}


@route("GET", r"/api/batch/jobs")
def api_batch_list(h):
    return {"jobs": batch.list_jobs()}


@route("DELETE", r"/api/batch/jobs/(?P<job_id>[\w-]+)")
def api_batch_drop(h, job_id):
    batch.JOBS.pop(job_id, None)
    return {"ok": True}


# ---------------------------------------------------------------- 设置
@route("GET", r"/api/settings")
def api_get_settings(h):
    s = db.get_settings()
    s["llm_key"] = "***" if s.get("llm_key") else ""
    return {"settings": s}


@route("PUT", r"/api/settings")
def api_save_settings(h):
    patch = h.json_body()
    if patch.get("llm_key") == "***":
        patch.pop("llm_key")
    s = db.save_settings(patch)
    s["llm_key"] = "***" if s.get("llm_key") else ""
    return {"settings": s}


@route("POST", r"/api/settings/test")
def api_test_settings(h):
    try:
        return {"ok": True, **ai.test_connection(db.get_settings())}
    except RuntimeError as e:
        raise ApiError(str(e), 502)


# ---------------------------------------------------------------- 组卷
@route("POST", r"/api/papers")
def api_build_paper(h):
    body = h.json_body()
    ids = body.get("item_ids") or []
    if not ids:
        raise ApiError("至少选一道题")
    mode = body.get("mode") or "blank"
    round_no = int(body.get("round") or 1)

    items = []
    for i in ids:
        it = db.get_item(i)
        if it:
            items.append(it)
    if not items:
        raise ApiError("题目不存在")

    stamp = datetime.now().strftime("%m%d_%H%M%S")
    title = body.get("title") or f"错题重做卷（第 {round_no} 轮）"
    if mode == "review":
        title = body.get("title") or f"错题复盘（第 {round_no} 轮）"
    sub = f"共 {len(items)} 题　|　生成于 {datetime.now():%Y-%m-%d %H:%M}"

    stem = PAPERS / f"{mode}_r{round_no}_{stamp}"
    result = paper.build(items, title, sub, mode, stem)

    pid = db.create_paper(title, round_no, mode, ids, result["pdf"] or result["html"])
    return {"id": pid, **result, "count": len(items)}


@route("GET", r"/api/papers")
def api_list_papers(h):
    return {"papers": db.list_papers()}


@route("GET", r"/api/papers/(?P<pid>\d+)/file")
def api_paper_file(h, pid):
    p = db.get_paper(pid)
    if not p:
        raise ApiError("卷子不存在", 404)
    f = PAPERS / p["file"]
    if not f.exists():
        raise ApiError("文件已丢失", 404)
    h.send_file(f, download_name=p["file"])
    return None


# ---------------------------------------------------------------- 概览
@route("GET", r"/api/meta")
def api_meta(h):
    s = db.get_settings()
    chapters = [c.strip() for c in (s.get("chapter_list") or "").split(",") if c.strip()]
    with db.connect() as c:
        used = [r["chapter"] for r in c.execute(
            "SELECT DISTINCT chapter FROM items WHERE chapter!='' ORDER BY chapter"
        ).fetchall()]
    for ch in used:
        if ch not in chapters:
            chapters.append(ch)

    st = db.stats()
    mastery = db.mastery_map()
    due = [
        {"item_id": k, **v}
        for k, v in mastery.items()
        if v["overdue"] and v["last_result"] == "wrong"
    ]
    due.sort(key=lambda x: x["due_at"])
    return {
        "chapters": chapters,
        "subjects": ["数学", "语文", "英语"],
        "stats": st,
        "due": due,
        "has_key": bool(db.get_settings().get("llm_key")),
    }


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "CuotiPOC/1.0"

    def log_message(self, fmt, *args):
        if not self.path.startswith(("/uploads/", "/figs/", "/assets/")):
            sys.stderr.write("  %s\n" % (fmt % args))

    # ---- 工具
    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def json_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ApiError("请求体不是合法 JSON")

    def send_file(self, path: Path, download_name: str | None = None):
        path = Path(path)
        if not path.exists() or not path.is_file():
            self._json({"error": "文件不存在"}, 404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{download_name}"'
            )
        self.end_headers()
        self.wfile.write(data)

    # ---- 分发
    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        self.query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        for m, pat, fn in ROUTES:
            if m != method:
                continue
            match = pat.match(path)
            if not match:
                continue
            try:
                result = fn(self, **match.groupdict())
            except ApiError as e:
                self._json({"error": e.message}, e.code)
                return
            except Exception:
                traceback.print_exc()
                self._json({"error": "服务器内部错误"}, 500)
                return
            if result is not None:
                self._json(result)
            return

        if path.startswith("/api/"):
            self._json({"error": f"没有这个接口：{path}"}, 404)
            return

        # 静态资源
        if path.startswith("/uploads/"):
            rel = path[len("/uploads/"):]
            self._send_under(UPLOADS, rel)
            return
        if path.startswith("/figs/"):
            self._send_under(FIGS, path[len("/figs/"):])
            return
        self._serve_spa(path)

    def _send_under(self, root: Path, rel: str):
        target = (root / rel).resolve()
        if not str(target).startswith(str(root.resolve())):
            self._json({"error": "非法路径"}, 403)
            return
        self.send_file(target)

    def _serve_spa(self, path: str):
        if not WEB_DIST.exists():
            self._json(
                {
                    "error": "前端还没构建",
                    "hint": "cd web && npm install && npm run build",
                },
                503,
            )
            return
        rel = path.lstrip("/") or "index.html"
        target = (WEB_DIST / rel).resolve()
        if str(target).startswith(str(WEB_DIST.resolve())) and target.is_file():
            self.send_file(target)
            return
        self.send_file(WEB_DIST / "index.html")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    db.init()
    with db.connect() as c:
        n = c.execute("SELECT COUNT(*) n FROM items").fetchone()["n"]
    # 容器部署通常不想带示例题，设 CUOTI_SEED=0 关掉
    seed_on = os.environ.get("CUOTI_SEED", "1").strip().lower() not in ("0", "false", "no", "off")
    if n == 0 and seed_on:
        try:
            import seed

            seed.run()
            print("  已导入示例题库")
        except Exception as e:
            print(f"  ! 示例数据导入失败：{e}")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"\n  错题集系统已启动  →  http://{args.host}:{args.port}")
    print("  后台入口：/admin    手机上传：/upload")
    if not WEB_DIST.exists():
        print("  ! web/dist 不存在，先执行：cd web && npm install && npm run build")
    print("  Ctrl+C 停止\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止")


if __name__ == "__main__":
    main()
