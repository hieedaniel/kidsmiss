# syntax=docker/dockerfile:1
#
# 错题集系统 —— 单镜像部署
#   前端 Vite 构建 → 静态文件；后端标准库 HTTP 服务托管静态文件 + API
#   镜像里装了 chromium，用来把组卷的 HTML 打成 A4 PDF
#
# 构建： docker build -t kidsmiss:local .
# 运行： docker run -d -p 8770:8770 -v $(pwd)/data:/app/server/data kidsmiss:local

# ============ 第一阶段：构建前端 ============
FROM node:22-alpine AS web-builder

WORKDIR /build

# 先只拷锁文件，改动源码时能命中依赖缓存
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY web/ ./
RUN npm run build


# ============ 第二阶段：运行时 ============
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

# chromium：组卷出 PDF 用（--no-sandbox 已在代码里加上）
# fonts-noto-cjk：Windows 上是宋体/黑体，Linux 靠思源字体顶上，缺了卷面会变豆腐块
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        fonts-noto-cjk \
        fonts-liberation \
        ca-certificates \
        tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY server/ ./server/
COPY --from=web-builder /build/dist ./web/dist

# 数据目录（数据库、原图、配图、卷子）留给 volume
RUN mkdir -p server/data/uploads server/data/figs server/data/papers

ENV CUOTI_SEED=0 \
    CHROME_PATH=/usr/bin/chromium

VOLUME ["/app/server/data"]
EXPOSE 8770

HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8770/api/meta', timeout=5).status == 200 else 1)"

CMD ["python", "server/main.py", "--host", "0.0.0.0", "--port", "8770"]
