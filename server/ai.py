"""多模态识别：把题目照片变成结构化数据。

走 OpenAI 兼容的 /chat/completions，配置全部从 settings 读，
所以换服务商只要改后台设置里的 base/model。
"""
from __future__ import annotations

import base64
import json
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


def _mime(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    return {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")


def recognize(image: Path, settings: dict, hint: str = "") -> dict:
    base = (settings.get("llm_base") or "").rstrip("/")
    key = (settings.get("llm_key") or "").strip()
    model = settings.get("llm_model") or "gpt-4o"
    prompt = (settings.get("llm_prompt") or "").strip() or DEFAULT_PROMPT

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
    return parse_json(content)


def parse_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError(f"模型没返回 JSON：{text[:200]}")
    try:
        return json.loads(t[start : end + 1])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON 解析失败：{e}") from e


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
