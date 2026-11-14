"""多模态识别：把题目照片变成结构化数据。

走 OpenAI 兼容的 /chat/completions，配置全部从 settings 读，
所以换服务商只要改后台设置里的 base/model。
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PROMPT = """你是小学数学老师，正在把试卷上的错题整理成可重做的结构化数据。

只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释：

{
  "chapter": "所属章节（如 分数乘法、位置与方向）",
  "knowledge": ["知识点，1-3 个，用教材说法"],
  "qtype": "choice | fill | solve 三选一",
  "points": 分值数字，没有就 null,
  "stem": "题干原文。分数写成 [a/b]，例如二分之一写 [1/2]；填空处写（　　）；不要包含选项和分值",
  "sub_items": ["若题干下有 ①②③④ 子项，逐条列出；没有给空数组"],
  "options": ["A. 内容", "B. ..."],
  "answer": "正确答案，自己算；算不出来填 ?",
  "student_answer": "学生在卷面上写的答案；没写填「未作答」；看不清填「无法辨认」",
  "analysis": ["解析步骤，每步一句话，要讲 why"],
  "error_cause": "错因，具体到思维动作，不要写「粗心」"
}

要求：
- 数学公式用纯文本加 [a/b] 写法，不要 LaTeX。
- 老师批改的红勾红叉订正标记不要写进题干。
- answer 必须自己算出来，不要照抄学生答案。"""


BATCH_PROMPT = """你是小学数学老师，正在批处理一张试卷照片，把上面的错题整理成可重做的结构化数据。

只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释：

{
  "items": [
    {
      "no": "卷面上的题号，如 12、(3)、四、1；看不出就填 ?",
      "chapter": "所属章节（如 分数乘法、位置与方向）",
      "knowledge": ["知识点，1-3 个，用教材说法"],
      "qtype": "choice | fill | solve 三选一",
      "points": 分值数字，没有就 null,
      "has_figure": true 或 false，这道题是否带几何图/统计图/表格,
      "stem": "题干原文。分数写成 [a/b]，例如二分之一写 [1/2]；填空处写（　　）；不要包含选项和分值",
      "sub_items": ["若题干下有 ①②③④ 子项，逐条列出；没有给空数组"],
      "options": ["A. 内容", "B. ..."],
      "answer": "正确答案，自己算；算不出来填 ?",
      "student_answer": "学生在卷面上写的答案；没写填「未作答」；看不清填「无法辨认」",
      "analysis": ["解析步骤，每步一句话，要讲 why"],
      "error_cause": "错因，具体到思维动作，不要写「粗心」"
    }
  ]
}

要求：
- 只收录被老师打叉、扣分、或明显写错的题；做对的题不要收。
- 一道题一个对象，按卷面顺序排列。一张图只有一道错题就只返回一个对象。
- 题干必须完整可独立成题：不要把前一道题的尾巴粘进来，也不要漏掉「如图」后面的条件。
- 【重要】[a/b] 这种方括号写法只用于真分数。普通整数、小数、字母、线段名、算式一律不加方括号，
  直接写 144、AB、□×□÷□，不要写成 [144]、[AB]。
- 题干里引用题目原有的引号时用“ ”或「」，不要用英文双引号 "，否则会破坏 JSON。
- 看不清、拿不准的地方照原样抄下来，不要自己加「（注：…）」「（可能为…）」这类推测性批注。
- 几何题（has_figure 为 true）的题干里保留「如图」字样，图形本身由家长后续框选补上，你不要描述图形长什么样。
- 数学公式用纯文本加 [a/b] 写法，不要 LaTeX。
- 老师批改的红勾红叉订正标记不要写进题干。
- answer 必须自己算出来，不要照抄学生答案；拿不准就填 ?，不要编。"""


def _mime(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    return {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")


def clean_markers(s) -> str:
    """把模型误加在普通数字/字母上的方括号去掉，只保留 [a/b] 形式的分数标记。

    实测模型会写 [144]、[AB]、[6]，渲染出来就是题干里夹着方括号，很难看。
    """
    if not isinstance(s, str) or "[" not in s:
        return s if isinstance(s, str) else str(s or "")
    slots: dict[str, str] = {}

    def keep(m):
        key = f"\x00{len(slots)}\x00"
        slots[key] = m.group(0)
        return key

    out = re.sub(r"\[\s*\d+\s*/\s*\d+\s*\]", keep, s)
    out = re.sub(r"\[([^\[\]\n]{1,24})\]", r"\1", out)
    for k, v in slots.items():
        out = out.replace(k, v)
    return out


def _chat(image: Path, prompt: str, settings: dict, hint: str = "", max_tokens: int | None = None) -> str:
    """发一次多模态请求，返回模型原始文本。"""
    base = (settings.get("llm_base") or "").rstrip("/")
    key = (settings.get("llm_key") or "").strip()
    model = settings.get("llm_model") or "gpt-4o"

    if not key:
        raise RuntimeError("还没配置大模型 API Key，请到「设置」里填一下。")
    if not base:
        raise RuntimeError("还没配置 API 地址（llm_base）。")

    b64 = base64.b64encode(image.read_bytes()).decode()
    text = prompt + (f"\n\n补充信息：{hint}" if hint else "")
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/{_mime(image)};base64,{b64}"},
                    },
                ],
            }
        ],
    }
    if max_tokens:
        # 整页多题时输出容易超默认上限被截断，截断的 JSON 必然解析失败
        payload["max_tokens"] = max_tokens

    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        raise RuntimeError(f"接口返回 {e.code}：{detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"连不上 {base}：{e.reason}") from e

    content = body["choices"][0]["message"]["content"]
    return content


def recognize(image: Path, settings: dict, hint: str = "") -> dict:
    """单张图 → 一道题的结构化草稿。"""
    prompt = (settings.get("llm_prompt") or "").strip() or DEFAULT_PROMPT
    draft = parse_json(_chat(image, prompt, settings, hint))
    return scrub(draft)


LIST_FIELDS = ("knowledge", "sub_items", "options", "analysis")
TEXT_FIELDS = ("chapter", "stem", "answer", "student_answer", "error_cause")


def scrub(draft: dict) -> dict:
    """统一清洗字段：去掉误加的方括号，列表字段转成干净的字符串数组。"""
    out = dict(draft)
    for k in TEXT_FIELDS:
        if k in out:
            out[k] = clean_markers(out[k]).strip()
    for k in LIST_FIELDS:
        v = out.get(k)
        if isinstance(v, list):
            out[k] = [clean_markers(x).strip() for x in v if str(x).strip()]
        elif isinstance(v, str) and v.strip():
            out[k] = [s.strip() for s in v.split("\n") if s.strip()]
        else:
            out[k] = []
    return out


def recognize_page(image: Path, settings: dict, hint: str = "") -> list[dict]:
    """整页图 → 多道错题（一张图只有一题也兼容）。"""
    prompt = (settings.get("llm_prompt_batch") or "").strip() or BATCH_PROMPT

    # 把章节字典告诉模型，省得它自己造出「分数乘除法」这种对不上的名字
    chapters = [c.strip() for c in (settings.get("chapter_list") or "").split(",") if c.strip()]
    extra = []
    if chapters:
        extra.append("可选章节（chapter 尽量从中选一个）：" + "、".join(chapters))
    if hint:
        extra.append(hint)

    rows = parse_items(_chat(image, prompt, settings, "\n".join(extra), max_tokens=8000))
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        item = scrub(r)
        if item.get("stem"):
            out.append(item)
    return out


def _json_body(text: str) -> str:
    """剥掉 markdown 代码块和前后废话，只留 JSON 主体。"""
    t = (text or "").strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) > 1:
            t = parts[1]
            if t.lstrip().lower().startswith("json"):
                t = t.lstrip()[4:]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError(f"模型没返回 JSON：{text[:200]}")
    return t[start : end + 1]


def _repair(t: str) -> str:
    """修常见的 JSON 手误：控制字符、行注释、尾随逗号、裸问号。"""
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    t = re.sub(r"(?m)^\s*//.*$", "", t)
    t = re.sub(r",\s*([}\]])", r"\1", t)
    t = re.sub(r'(:\s*)\?(?=\s*[,\n}\]])', r'\1"?"', t)
    return t


def _salvage(body: str) -> list[dict]:
    """整体解析失败时逐对象抠：坏的那道题跳过，别让整张图白跑。"""
    dec = json.JSONDecoder()
    out: list[dict] = []
    i = 0
    while i < len(body):
        i = body.find("{", i)
        if i < 0:
            break
        try:
            obj, end = dec.raw_decode(body[i:])
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            if isinstance(obj.get("items"), list):
                out.extend(x for x in obj["items"] if isinstance(x, dict))
                break
            if obj.get("stem"):
                out.append(obj)
        i += end
    return out


def parse_json(text: str) -> dict:
    body = _json_body(text)
    for cand in (body, _repair(body)):
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"JSON 解析失败：{body[:200]}")


def parse_items(text: str) -> list[dict]:
    """取题目数组，解析失败则尽量救回能救的对象。"""
    body = _json_body(text)
    for cand in (body, _repair(body)):
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows = data.get("items")
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
            if data.get("stem"):          # 模型按单题格式答了
                return [data]
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]

    rows = _salvage(body)
    if rows:
        return rows
    raise RuntimeError(f"JSON 解析失败，也没救回来：{body[:200]}")


def test_connection(settings: dict) -> dict:
    """用一次极小的文本请求确认 key / base / model 都对。"""
    base = (settings.get("llm_base") or "").rstrip("/")
    key = (settings.get("llm_key") or "").strip()
    model = settings.get("llm_model") or "gpt-4o"
    if not key:
        raise RuntimeError("还没填 API Key。")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "回复两个字：可用"}],
        "max_tokens": 16,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"接口返回 {e.code}：{e.read().decode('utf-8','ignore')[:200]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"连不上 {base}：{e.reason}")
    reply = body["choices"][0]["message"]["content"]
    return {"model": model, "reply": reply[:40]}
