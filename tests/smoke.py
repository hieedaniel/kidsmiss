"""端到端冒烟测试：不依赖第三方库，直接打 HTTP 接口。

用法：
    python tests/smoke.py                      # 默认 http://127.0.0.1:8770
    python tests/smoke.py http://127.0.0.1:9000

覆盖：题库 CRUD、筛选、上传、识别降级、重做记录与星级、组卷出 PDF、
静态资源、路径穿越防护、错误处理。测试产生的题目会自动删掉。
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8770").rstrip("/")
ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "scans" / "p1.jpg"          # 本地真卷照片，没有就跳过上传测试
if not SCAN.exists():
    SCAN = ROOT.parent / "cuoti" / "scans" / "p1.jpg"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail else ""))


def req(method: str, path: str, payload=None):
    """返回 (status, body)。body 是解析后的 dict/list，或原始 bytes。"""
    url = BASE + path
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=180) as resp:
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype:
                return resp.status, json.loads(body)
            return resp.status, body
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def section(title: str) -> None:
    print(f"\n{title}")


# ---------------------------------------------------------------- 1. 概览
section("1. 概览 /api/meta")
st, meta = req("GET", "/api/meta")
check("返回 200", st == 200, f"status={st}")
if isinstance(meta, dict):
    check("含 stats.total", isinstance(meta.get("stats", {}).get("total"), int),
          f"total={meta.get('stats', {}).get('total')}")
    check("含 chapters 列表", isinstance(meta.get("chapters"), list),
          f"{len(meta.get('chapters', []))} 个章节")
    check("含 due 待复习列表", isinstance(meta.get("due"), list),
          f"{len(meta.get('due', []))} 条到期")

# ---------------------------------------------------------------- 2. 列表与筛选
section("2. 题库列表与筛选")
st, data = req("GET", "/api/items")
items = data.get("items", []) if isinstance(data, dict) else []
check("列表返回 200 且有数据", st == 200 and len(items) > 0, f"{len(items)} 题")

if items:
    ch = items[0]["chapter"]
    st, f1 = req("GET", f"/api/items?chapter={urllib.parse.quote(ch)}")
    fl = f1.get("items", []) if isinstance(f1, dict) else []
    check("按章节筛选结果一致", all(x["chapter"] == ch for x in fl) and len(fl) > 0,
          f"章节「{ch}」{len(fl)} 题")

    st, f2 = req("GET", "/api/items?status=mastered")
    fl2 = f2.get("items", []) if isinstance(f2, dict) else []
    check("按状态筛选 masterd 全部匹配",
          all(x["status"] == "mastered" for x in fl2), f"{len(fl2)} 题")

    kw = "分数"

    def _haystack(x: dict) -> str:
        k = x.get("knowledge")
        if isinstance(k, (list, tuple)):
            k = " ".join(str(i) for i in k)
        return " ".join([x.get("stem") or "", str(k or ""), x.get("error_cause") or ""])

    st, f3 = req("GET", f"/api/items?q={urllib.parse.quote(kw)}")
    fl3 = f3.get("items", []) if isinstance(f3, dict) else []
    # 必须比全量少，否则说明 q 参数根本没生效
    check("关键词搜索生效（结果收敛且命中）",
          len(fl3) > 0 and len(fl3) < len(items) and all(kw in _haystack(x) for x in fl3),
          f"搜「{kw}」→ {len(fl3)}/{len(items)} 题")

    st, f4 = req("GET", "/api/items?stars=3")
    fl4 = f4.get("items", []) if isinstance(f4, dict) else []
    check("星级筛选 ≥3 全部匹配", all((x.get("stars") or 0) >= 3 for x in fl4)
          and len(fl4) < len(items),
          f"{len(fl4)}/{len(items)} 题")

# ---------------------------------------------------------------- 3. 详情与 404
section("3. 详情与错误处理")
if items:
    iid = items[0]["id"]
    st, d = req("GET", f"/api/items/{iid}")
    check("详情返回 200 且 id 一致", st == 200 and d.get("item", {}).get("id") == iid, iid)

st, err = req("GET", "/api/items/NOT_EXIST_999")
check("不存在的题返回 404", st == 404, f"status={st}")

st, err2 = req("POST", "/api/items", {})
check("空题干被拒绝（400）", st == 400, f"status={st}")

st, err3 = req("POST", "/api/items", {"stem": "   "})
check("纯空格题干也被拒绝", st == 400, f"status={st}")

# ---------------------------------------------------------------- 4. 上传
section("4. 图片上传")
uploaded = None
if SCAN.exists():
    blob = SCAN.read_bytes()
    b64 = "data:image/jpeg;base64," + base64.b64encode(blob).decode()
    st, up = req("POST", "/api/upload", {"filename": "smoke_p1.jpg", "data": b64})
    ok = st == 200 and isinstance(up, dict) and up.get("file")
    check("上传返回文件名与尺寸", ok,
          f"{up.get('width')}x{up.get('height')}" if ok else f"status={st}")
    if ok:
        uploaded = up
        st2, raw = req("GET", up["url"])
        check("上传后的原图可访问", st2 == 200 and len(raw) > 1000,
              f"{len(raw) // 1024} KB" if st2 == 200 else f"status={st2}")
        st3, _ = req("GET", up["thumb"])
        check("缩略图可访问", st3 == 200, f"status={st3}")

    st, bad = req("POST", "/api/upload", {"filename": "x.jpg", "data": "not-base64!!"})
    check("非法 base64 返回 400 而非 500", st == 400, f"status={st}")
else:
    print("  SKIP  没找到原始试卷照片，跳过上传测试")

# ---------------------------------------------------------------- 5. 识别降级
section("5. AI 识别（未配置 Key 时应明确报错，不能崩）")
if uploaded:
    st, rec = req("POST", "/api/ai/recognize", {"file": uploaded["file"]})
    if st == 200:
        check("识别返回 draft", isinstance(rec.get("draft"), dict), "已配置 Key，跳过降级检查")
    else:
        check("未配置 Key 返回 502 + 中文提示",
              st == 502 and "error" in (rec or {}), f"status={st} {rec}")

    st, rec2 = req("POST", "/api/ai/recognize", {"file": "no_such_file.jpg"})
    check("识别不存在的图返回 400", st == 400, f"status={st}")

# ---------------------------------------------------------------- 6. 建题 / 改题
section("6. 建题、改题、删除")
new_id = None
st, created = req("POST", "/api/items", {
    "subject": "数学", "grade": "六年级上册", "chapter": "冒烟测试章节",
    "qtype": "choice", "points": 2,
    "stem": "冒烟测试题：3/4 的 2/3 是多少？",
    "options": ["A. 1/2", "B. 1/4", "C. 5/12", "D. 9/8"],
    "answer": "A", "student_answer": "C",
    "analysis": ["先算 3/4 × 2/3"],
    "error_cause": "分数乘法分子分母搞混",
    "status": "wrong", "stars": 1, "exam": "冒烟测试",
    "figures": ([{"src": uploaded["file"], "box": [993, 1002, 1234, 1222], "w": 48}]
                if uploaded else []),
})
if st == 200:
    new_id = created.get("item", {}).get("id")
    check("建题成功并返回 id", bool(new_id), new_id)
    it = created.get("item", {})
    check("初始 stars=1 / status=wrong",
          it.get("stars") == 1 and it.get("status") == "wrong",
          f"stars={it.get('stars')} status={it.get('status')}")
else:
    check("建题成功并返回 id", False, f"status={st} {created}")

if new_id:
    st, u = req("PUT", f"/api/items/{new_id}",
                {"stars": 2, "error_cause": "改过的错因", "knowledge": "分数乘法"})
    it = u.get("item", {}) if isinstance(u, dict) else {}
    check("更新字段生效", st == 200 and it.get("stars") == 2
          and it.get("error_cause") == "改过的错因",
          f"stars={it.get('stars')}")

    # ------------------------------------------------------------ 7. 重做与星级
    section("7. 重做记录与星级升降")
    st, a1 = req("POST", f"/api/items/{new_id}/attempt", {"result": "wrong"})
    st, d1 = req("GET", f"/api/items/{new_id}")
    it1 = d1.get("item", {})
    check("答错：星级 2→3（封顶）", it1.get("stars") == 3 and it1.get("status") == "wrong",
          f"stars={it1.get('stars')} status={it1.get('status')}")

    st, a2 = req("POST", f"/api/items/{new_id}/attempt", {"result": "correct"})
    check("答对请求成功", st == 200, f"status={st}")
    st, d2 = req("GET", f"/api/items/{new_id}")
    it2 = d2.get("item", {})
    check("星级>1 时答对仍待巩固（不是直接掌握）",
          it2.get("status") == "wrong", f"status={it2.get('status')}")

    st, a3 = req("POST", f"/api/items/{new_id}/attempt", {"result": "瞎写"})
    check("非法 result 值被拒绝（400）", st == 400, f"status={st}")

    st, d3 = req("GET", f"/api/items/{new_id}")
    atts = (d3.get("item") or {}).get("attempts", [])
    check("重做记录写入时间线", len(atts) >= 2, f"{len(atts)} 条记录")
    check("时间线按时间倒序", len(atts) >= 2 and atts[0]["created_at"] >= atts[-1]["created_at"],
          atts[0]["result"] if atts else "")

    st, up2 = req("PUT", f"/api/items/{new_id}", {})
    check("空 patch 更新不报 500", st == 200, f"status={st}")

# ---------------------------------------------------------------- 8. 设置
section("8. 设置与 Key 掩码")
st, s1 = req("GET", "/api/settings")
s = s1.get("settings", {}) if isinstance(s1, dict) else {}
check("读取设置", st == 200 and "llm_base" in s, f"model={s.get('llm_model')}")
orig_model = s.get("llm_model")

st, s2 = req("PUT", "/api/settings", {"llm_model": "smoke-test-model"})
check("保存设置", st == 200 and s2.get("settings", {}).get("llm_model") == "smoke-test-model",
      f"model={s2.get('settings', {}).get('llm_model')}")
st, s3 = req("GET", "/api/settings")
check("设置持久化", s3.get("settings", {}).get("llm_model") == "smoke-test-model")

# 还原
req("PUT", "/api/settings", {"llm_model": orig_model})

st, mask = req("PUT", "/api/settings", {"llm_key": "***"})
check("提交 *** 不会覆盖真实 Key",
      mask.get("settings", {}).get("llm_key") in ("***", ""), "掩码逻辑正常")

st, t1 = req("POST", "/api/settings/test", {})
check("测试连通：失败时返回 502 而非崩",
      st == 502 or (st == 200 and isinstance(t1, dict)), f"status={st}")

# ---------------------------------------------------------------- 9. 组卷
section("9. 组卷出 PDF")
paper_ids = []
if new_id:
    for mode in ("blank", "review"):
        st, p = req("POST", "/api/papers",
                    {"item_ids": [new_id], "mode": mode, "round": 1})
        ok = st == 200 and p.get("pdf")
        check(f"{mode} 卷生成 PDF", ok,
              f"{p.get('pdf')} ({p.get('count')} 题)" if ok else f"status={st} {p}")
        if ok:
            paper_ids.append(p)

    if paper_ids:
        p = paper_ids[0]
        st, pdf = req("GET", f"/api/papers/{p['id']}/file")
        size = len(pdf) if isinstance(pdf, bytes) else 0
        check("PDF 可下载且体积正常", st == 200 and size > 10000,
              f"{size // 1024} KB")

    st, pl = req("GET", "/api/papers")
    lst = pl.get("papers", []) if isinstance(pl, dict) else []
    check("卷子列表包含新生成的", len(lst) > 0 and any(
        x["id"] == paper_ids[0]["id"] for x in lst), f"历史 {len(lst)} 份")

st, e1 = req("POST", "/api/papers", {"item_ids": [], "mode": "blank"})
check("空选题返回 400", st == 400, f"status={st}")

# ---------------------------------------------------------------- 10. 批量
section("10. 批量入库接口")
st, bl = req("GET", "/api/batch/jobs")
check("任务列表可访问", st == 200 and isinstance((bl or {}).get("jobs"), list), f"status={st}")

st, _ = req("POST", "/api/batch/jobs", {"files": []})
check("空文件列表返回 400", st == 400, f"status={st}")

st, _ = req("POST", "/api/batch/jobs", {"files": "a.jpg"})
check("files 不是数组返回 400", st == 400, f"status={st}")

st, _ = req("GET", "/api/batch/jobs/nosuchjob")
check("不存在的任务返回 404", st == 404, f"status={st}")

st, _ = req("DELETE", "/api/batch/jobs/nosuchjob")
check("删不存在的任务不报错", st == 200, f"status={st}")

st, br = req("POST", "/api/batch/jobs", {"files": ["__not_exist__.jpg"]})
check("参考图缺失时服务不崩（200/502）", st in (200, 502), f"status={st}")
if st == 200:
    jid = br["job"]["id"]
    job = {}
    for _ in range(30):
        _, jr = req("GET", f"/api/batch/jobs/{jid}")
        job = (jr or {}).get("job", {})
        if job.get("status") == "done":
            break
        time.sleep(0.3)
    check("缺图的那张被标失败而不是卡住",
          job.get("status") == "done" and job.get("failed") == 1,
          f"failed={job.get('failed')} saved={job.get('saved')}")

# ---------------------------------------------------------------- 11. 安全
section("11. 静态资源与路径穿越")
st, _ = req("GET", "/")
check("首页可访问", st == 200, f"status={st}")
st, assets = req("GET", "/assets/")
# 目录请求应该落到 SPA 兜底（返回 index.html），而不是列出文件清单
check("assets 目录不暴露文件清单",
      st == 200 and isinstance(assets, bytes) and b'id="app"' in assets, f"status={st}")

for bad in ("/uploads/../../server/main.py", "/uploads/..%2f..%2fserver%2fmain.py",
            "/figs/../data/cuoti.db"):
    st, _ = req("GET", bad)
    check(f"拒绝路径穿越 {bad[:34]}", st in (400, 403, 404), f"status={st}")

# ---------------------------------------------------------------- 11. 清理
section("12. 清理测试数据")
if new_id:
    st, _ = req("DELETE", f"/api/items/{new_id}")
    check("删除测试题", st == 200, f"status={st}")
    st, _ = req("GET", f"/api/items/{new_id}")
    check("删除后确实查不到", st == 404, f"status={st}")

# ---------------------------------------------------------------- 汇总
passed = sum(1 for _, ok, _ in results if ok)
failed = len(results) - passed
print("\n" + "=" * 56)
print(f"  通过 {passed} / {len(results)}" + (f"　失败 {failed}" if failed else "　全部通过"))
if failed:
    print("\n  失败项：")
    for name, ok, detail in results:
        if not ok:
            print(f"   - {name}  [{detail}]")
print("=" * 56)
sys.exit(1 if failed else 0)
