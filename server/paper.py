"""组卷：把题目渲染成 A4 卷子，并转成 PDF。

两种卷：
  blank  空白重做卷（给孩子）
  review 复盘页（答案 + 解析 + 错因）
"""
from __future__ import annotations

import html as _html
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

BASE = Path(__file__).resolve().parent
FIG_DIR = BASE / "data" / "figs"
UPLOAD_DIR = BASE / "data" / "uploads"
CSS_FILE = BASE / "templates" / "print.css"

FRAC_RE = re.compile(r"\[(\d+)\s*/\s*(\d+)\]")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

STATUS_LABEL = {
    "wrong": ("错题", "badge"),
    "format": ("过程不规范", "badge"),
    "unverified": ("待核对", "badge ask"),
    "teacher_error": ("批改存疑·已核对为对", "badge ok"),
    "mastered": ("已掌握", "badge ok"),
}

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def esc(text) -> str:
    s = _html.escape(str(text or ""), quote=False)
    return FRAC_RE.sub(
        lambda m: f'<span class="frac"><span class="num">{m.group(1)}</span>'
        f'<span class="den">{m.group(2)}</span></span>',
        s,
    )


def find_browser() -> str | None:
    """找浏览器。容器里用 CHROME_PATH 显式指定，优先级最高。"""
    env = (os.environ.get("CHROME_PATH") or os.environ.get("BROWSER_PATH") or "").strip()
    if env and Path(env).exists():
        return env
    for p in BROWSERS:
        if Path(p).exists():
            return p
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


# ---------------------------------------------------------------- 图形
def clean_scan(im, thresh: int = 105, blue_delta: int = 22):
    r, _, b = im.split()
    mask = ImageChops.subtract(b, r).point(lambda p: 255 if p > blue_delta else 0)
    im = Image.composite(Image.new("RGB", im.size, (255, 255, 255)), im, mask)
    g = ImageOps.autocontrast(im.convert("L"), cutoff=2)
    return g.point(lambda p: 0 if p < thresh else 255, mode="1").convert("RGB")


def crop_figures(item: dict, scale: float = 1.6) -> list[dict]:
    """把题目引用的原图按 box 裁出来，返回 [{file, w}]。"""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for i, f in enumerate(item.get("figures") or []):
        src = UPLOAD_DIR / Path(str(f.get("src", ""))).name
        if not src.exists():
            continue
        im = Image.open(src).convert("RGB")
        box = f.get("box")
        if box:
            x1, y1, x2, y2 = [int(v) for v in box]
            w, h = im.size
            x1, y1 = max(0, x1 - 2), max(0, y1 - 2)
            x2, y2 = min(w, x2 + 2), min(h, y2 + 2)
            im = im.crop((x1, y1, x2, y2))
        if f.get("clean"):
            im = clean_scan(im)
        im = im.resize(
            (int(im.width * scale), int(im.height * scale)), Image.LANCZOS
        )
        name = f"{item['id']}_{i}.png"
        im.save(FIG_DIR / name)
        out.append({"file": name, "w": f.get("w")})
    return out


# ---------------------------------------------------------------- 组件
def fig_html(item) -> str:
    parts = []
    for g in crop_figures(item):
        style = f' style="width:{g["w"]}mm"' if g.get("w") else ""
        parts.append(
            f'<div class="fig inline"><img src="../figs/{g["file"]}"{style} alt=""></div>'
        )
    return "".join(parts)


def options_html(item) -> str:
    opts = item.get("options") or []
    if not opts:
        return ""
    cls = "options" if max(len(o) for o in opts) <= 26 else "options vertical"
    return f'<div class="{cls}">' + "".join(
        f'<span class="opt">{esc(o)}</span>' for o in opts
    ) + "</div>"


def subs_html(item) -> str:
    subs = item.get("sub_items") or []
    if not subs:
        return ""
    rows = "".join(
        f'<div class="sub"><span class="mark">{CIRCLED[i]}</span>'
        f"<span>{esc(s)}</span></div>"
        for i, s in enumerate(subs)
    )
    return f'<div class="subs">{rows}</div>'


def space_html(item) -> str:
    h = item.get("space_mm") or 0
    return f'<div class="space" style="height:{h}mm"></div>' if h > 0 else ""


def head_html(title: str, sub: str, blank: bool) -> str:
    fields = ""
    if blank:
        fields = (
            '<div class="paper-fields">'
            '<span>姓名：<span class="fill"></span></span>'
            '<span>日期：<span class="fill"></span></span>'
            '<span>用时：<span class="fill"></span> 分钟</span>'
            '<span>得分：<span class="fill"></span></span>'
            "</div>"
        )
    return (
        f'<div class="paper-head"><div class="paper-title">{esc(title)}</div>'
        f'<div class="paper-sub">{esc(sub)}</div>{fields}</div>'
    )


def record_html() -> str:
    return (
        '<div class="record"><div class="r-title">重做记录</div><table>'
        "<tr><th>轮次</th><th>日期</th><th>用时</th><th>做对题数</th>"
        "<th>仍未掌握（题号）</th></tr>"
        '<tr><td class="lbl">第 1 次</td><td></td><td></td><td></td><td></td></tr>'
        '<tr><td class="lbl">第 2 次</td><td></td><td></td><td></td><td></td></tr>'
        '<tr><td class="lbl">第 3 次</td><td></td><td></td><td></td><td></td></tr>'
        "</table></div>"
    )


# ---------------------------------------------------------------- 页面
def render_blank(items, title, sub) -> str:
    chunks, prev_page = [], None
    for n, it in enumerate(items, 1):
        pg = it.get("page_group")
        cls = "item start-page" if (pg and prev_page and pg != prev_page) else "item"
        prev_page = pg or prev_page
        pts = it.get("points")
        pts_tag = f'<span class="pts">（{pts} 分）</span>' if pts else ""
        body = []
        if it.get("sub_items"):
            body.append(f'<div>{esc(it["stem"])}</div>')
            body.append(subs_html(it))
        else:
            body.append(f'<div>{esc(it["stem"])}{pts_tag}</div>')
        body.append(fig_html(it))
        body.append(options_html(it))
        body.append(space_html(it))
        chunks.append(
            f'<div class="{cls}"><div class="stem"><div class="no">{n}.</div>'
            f'<div class="body">{"".join(body)}</div></div></div>'
        )
    return (
        head_html(title, sub, True)
        + '<div class="item-wrap">' + "".join(chunks) + "</div>"
        + '<div class="end-mark">—— 卷终 ——</div>'
        + record_html()
    )


def render_review(items, title, sub) -> str:
    out = []
    for n, it in enumerate(items, 1):
        label, badge_cls = STATUS_LABEL.get(it.get("status", "wrong"), ("错题", "badge"))
        stars = "★" * (it.get("stars") or 0)
        body = [f'<div>{esc(it["stem"])}<span class="{badge_cls}">'
                f"{esc(label)}</span></div>"]
        if it.get("sub_items"):
            body.append(subs_html(it))
        body.append(fig_html(it))
        body.append(options_html(it))
        body.append(
            '<div class="review-grid">'
            f'<div class="cell"><span class="k">我的答案</span>'
            f'<span class="v wrong">{esc(it.get("student_answer") or "—")}</span></div>'
            f'<div class="cell"><span class="k">正确答案</span>'
            f'<span class="v right">{esc(it.get("answer") or "—")}</span></div>'
            f'<div class="cell"><span class="k">知识点</span>'
            f'<span class="v">{esc("、".join(it.get("knowledge") or []))}</span></div>'
            f'<div class="cell"><span class="k">星级</span>'
            f'<span class="v">{stars or "—"}</span></div></div>'
        )
        steps = "".join(f"<li>{esc(s)}</li>" for s in it.get("analysis") or [])
        if steps:
            body.append(
                f'<div class="block"><span class="label">解析步骤</span>'
                f"<ol>{steps}</ol></div>"
            )
        if it.get("error_cause"):
            body.append(
                '<div class="block cause"><span class="label">错在哪 / 怎么改</span>'
                f'{esc(it["error_cause"])}</div>'
            )
        out.append(
            f'<div class="item"><div class="stem"><div class="no">{n}.</div>'
            f'<div class="body">{"".join(body)}</div></div></div>'
        )
    return head_html(title, sub, False) + "".join(out)


def page(title: str, style: str, content: str) -> str:
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        f"<title>{esc(title)}</title><style>{style}</style></head>"
        f"<body>{content}</body></html>"
    )


def to_pdf(browser: str, html_path: Path, pdf_path: Path) -> bool:
    tmp = tempfile.mkdtemp(prefix="cuoti_pdf_")
    try:
        subprocess.run(
            [
                browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                # 容器默认 /dev/shm 只有 64MB，不加这个容易渲染中途崩溃
                "--disable-dev-shm-usage", "--disable-software-rasterizer",
                "--hide-scrollbars", "--no-pdf-header-footer",
                f"--user-data-dir={tmp}",
                f"--print-to-pdf={pdf_path}", html_path.as_uri(),
            ],
            capture_output=True, timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return pdf_path.exists() and pdf_path.stat().st_size > 1000


def build(items: list[dict], title: str, sub: str, mode: str, out_stem: Path) -> dict:
    """产物：out_stem.html / out_stem.pdf"""
    items = [{**it, "page_group": it.get("page_group")} for it in items]
    style = CSS_FILE.read_text(encoding="utf-8")
    content = (
        render_blank(items, title, sub) if mode == "blank"
        else render_review(items, title, sub)
    )
    html_path = out_stem.with_suffix(".html")
    html_path.write_text(page(title, style, content), encoding="utf-8")

    pdf_path = out_stem.with_suffix(".pdf")
    browser = find_browser()
    ok = to_pdf(browser, html_path, pdf_path) if browser else False
    return {"html": html_path.name, "pdf": pdf_path.name if ok else None}
