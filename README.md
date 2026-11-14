# 错题集系统（POC）

手机拍照上传 → AI 识别 → 人工核对入库 → 按章节组卷 → 打印重做 → 记录掌握情况。

前台（手机）用来拍和看，后台（桌面）用来整理和出卷，同一个 Web 应用，响应式切换。

---

## 一、跑起来

```bash
cd cuoti-app
./start.bat            # Windows 双击也行；首次会自动 npm install + build
```

打开 http://127.0.0.1:8770

首次启动会自动建库，并导入 `../cuoti/data/items.json` 里的 8 道题作为演示数据。

**开发模式**（改前端热更新）：

```bash
python server/main.py --port 8770      # 终端 1：后端
cd web && npm run dev                  # 终端 2：前端 5173，自动代理到 8770
```

前端改完要上线，`cd web && npm run build`，后端会自动托管 `dist/`。

---

## 二、为什么后端不用 FastAPI

这台机器的 Python 3.13 装不了任何第三方包（`pip` 报 `No matching distribution`，索引里连 pydantic 都查不到）。
所以后端用**纯标准库**实现：`http.server` + `sqlite3` + `urllib`，唯一的第三方依赖是 Pillow（本来就装着，用来裁图洗图）。

好处是零安装、换机器直接跑；坏处是没有 ORM 和自动文档。POC 阶段这个取舍是划算的。
如果以后要迁 FastAPI，`db.py` 的查询逻辑和 `main.py` 的路由表都能直接搬。

---

## 三、目录

```
cuoti-app/
  start.bat / start.sh      一键启动
  Dockerfile                单镜像部署（前端构建 + chromium + 后端）
  docker-compose.yml        服务器上 `docker compose up -d` 即可
  .github/workflows/        推 main 自动构建镜像推到 GHCR
  server/
    main.py                 HTTP 服务 + 路由表（所有接口都在这儿）
    db.py                   SQLite 数据层（items / attempts / papers / settings）
    paper.py                组卷渲染 + PDF（复用 A4 打印样式）
    ai.py                   多模态识别（OpenAI 兼容，配置化）
    batch.py                批量入库流水线（识别并行 / 入库串行 / 去重 / 归一）
    seed.py                 首次启动的示例数据
    templates/print.css     A4 卷面样式
    data/
      cuoti.db              题库（SQLite）
      uploads/              原图 + thumbs/ 缩略图
      figs/                 组卷时裁出来的图形
      papers/               生成的 html/pdf
  web/
    src/views/              Home / Batch / Upload / Items / ItemDetail / Paper / Settings
    src/components/CropBox.vue   拖框裁图组件
    dist/                  构建产物，后端托管（不入库，`npm run build` 生成）
  docs/                     界面截图 + 两份示例卷
```

备份只需要拷 `server/data` 整个目录。`server/data`、`web/dist`、`web/node_modules` 都不入库。

---

## 四、功能

| 页面 | 做什么 |
|---|---|
| **概览** | 总题数 / 待掌握 / 已掌握 / 今天该复习；章节分布；最近录入 |
| **批量入库** | 一次传多张整页试卷照片，后台逐张识别、自动去重、直接入库，只回来看结果 |
| **单张录入** | 拍一张 → 拖框圈出图形 → AI 识别 → 改一改 → 入库（要精细改字段时用这个） |
| **错题库** | 按章节分组，按章节/状态/星级/时间筛选，支持关键词搜题干和知识点；每条可一键标记「重做对了/又错了」 |
| **题目详情** | 全字段编辑、重做时间线、掌握度与下次复习日期、重新裁图 |
| **组卷** | 筛题 → 勾选 → 选轮次 → 生成空白卷和/或复盘页（A4 PDF，直接打印） |
| **设置** | LLM 接口地址 / Key / 模型 / 提示词；章节字典 |

### 批量入库怎么走

两条录入路径共用一套题库，区别只在「谁来核对字段」：

```
批量入库：选多张 → 逐张整页识别（一张出 N 题）→ 去重 → 直接落库 → 你看汇总、只补图形
单张录入：选一张 → 识别单题 → 表单里逐项核对 → 存
```

流水线上的几个决定：

- **识别并行、入库串行**。识别是网络等待，2 路并发能省一半时间；入库必须串行，否则两个线程同时取 `next_id` 会撞号（`items.id` 是主键，撞了整张图都白跑）。
- **自动去重**。题干抹掉标点和空格取前 40 字做指纹，跟库里已有题目比，重复的跳过并在汇总里报数。同一张卷子拍两次不会进两遍。
- **答案和孩子的笔迹一致时标「待核对」**。这种情况八成是做对了、只是过程或格式被判错，不该塞进错题卷让孩子重做。模型没算出答案（`?`）的同样标待核对。
- **章节自动归到字典**。设置里的章节字典会一起喂给模型；模型仍造出新名字时，用包含匹配兜一层，匹配不上就保留原值不丢信息。
- **不自动裁配图**。模型给的图形坐标不可靠，裁歪了孩子看到的是半张图，比没图更糟。识别时只标记 `has_figure`，页面给出题号列表，你点进去用现成的拖框组件补。
- **任务状态只在内存**。服务重启后历史任务列表清空，但已经入库的题在 SQLite 里，不丢。

单张上限 30 张，识别失败的那张不会拖垮整批，失败原因会显示在缩略图卡片上。

### 掌握情况怎么算

每次点「对 / 错」写一条 `attempts` 记录，同时：

- 答错 → 星级 +1（最高 3 星），状态回到 `wrong`
- 答对且星级 ≤1 → 状态变 `mastered`

下次复习日期按连续答对次数拉长间隔：0 次 → 1 天，1 次 → 3 天，2 次 → 7 天，3 次 → 21 天。
到期且上次答错的题，会出现在概览页的「该复习了」。

这就是最简单的间隔重复，够用且好理解。

---

## 五、配大模型

到「设置」里填三样：接口地址、API Key、模型名。默认给的是 vectorengine 的 `gpt-4o`。

点「测试连通」会用一句「回复两个字：可用」验证 key 和地址，不消耗多少 token。

识别走 `/chat/completions` 的 vision 格式，所以任何 OpenAI 兼容的多模态服务都能用：
`gpt-4o`、`gemini-2.0-flash`、`qwen-vl-max`、`glm-4v` 都行。

内置提示词要求模型返回结构化 JSON（章节、知识点、题干、选项、答案、解析、错因），
分数用 `[3/4]` 写法——前端和印刷都会渲染成真正的上下分数。
想改识别风格，在设置里覆盖提示词即可，不用动代码：单张录入读 `llm_prompt`，批量入库读 `llm_prompt_batch`（留空用内置的）。

**批量入库对模型挑一些**。一张卷子要读多题、还要判断哪几道被打叉，小模型容易漏题或把做对的题也收进来；
实测 `gemini-3.1-flash-lite` 能跑通但要人工核对，换更稳的 vision 模型（gpt-4o、qwen-vl-max）漏得少。

**Key 存在本地 SQLite，接口返回时会被替换成 `***`，不会回传到前端。**

---

## 六、已知限制

1. **识别要人复核**。答案、错因、章节都可能错，尤其是几何图的坐标判读。批量入库跑完会告诉你「几题待核对」，别直接拿去组卷。
2. **批量是整页识别，不是切图**。一道错题对应库里一条记录，但卷面上的图形没被一起切下来——批量模式只标记 `has_figure`，图形要靠单张录入的拖框补。真自动切图（版面分析 + 逐题 OCR）POC 没做。
3. **排版不会完美**。长题干换行、公式位置偶尔别扭，生成的 HTML 在 `server/data/papers/` 里，能直接改。
4. **没做用户体系**。按你的要求，单机自用、无登录。别把它暴露到公网。
5. **PDF 依赖 chromium**。本地用 Edge/Chrome 的 headless 打印，容器里装的是 Debian 的 chromium；两者都找不到时只出 HTML，不会报错但也拿不到 PDF。
6. **批量任务不能断点续跑**。服务重启后，正在跑的任务列表会清空（已入库的题不受影响），需要重新传那几张图。

---

## 七、部署到服务器

### 1. 推代码，自动构建镜像

推送到 `main` 后，Actions 会自动跑 `.github/workflows/docker.yml`：构建前端 → 装 chromium 和中文字体 → 推镜像到 GHCR。

```bash
git remote add origin https://github.com/hieedaniel/kidsmiss.git
git branch -M main
git push -u origin main
```

镜像地址：`ghcr.io/hieedaniel/kidsmiss:latest`，同时会生成 `sha-xxxxxxx` 便于回滚。打 `v1.0.0` 这类标签则会额外生成版本 tag。实测构建约 2 分钟，镜像 389MB（大头是 chromium 和中文字体）。

**推完先看一眼 Actions 页面**。如果「登录 GHCR」那步报 403，去仓库 `Settings → Actions → General → Workflow permissions` 改成 **Read and write permissions** 再重跑。另外 GHCR 的包默认继承仓库可见性——仓库是 public 时镜像也能匿名拉取，此时服务器不需要登录；仓库转 private 后服务器要先 `docker login ghcr.io`。

### 2. 服务器上拉取运行

```bash
mkdir -p ~/kidsmiss/data && cd ~/kidsmiss
curl -O https://raw.githubusercontent.com/hieedaniel/kidsmiss/main/docker-compose.yml
docker compose pull && docker compose up -d
```

或者不用 compose：

```bash
docker run -d --name kidsmiss --restart unless-stopped \
  -p 8770:8770 \
  -v ~/kidsmiss/data:/app/server/data \
  -e TZ=Asia/Shanghai \
  ghcr.io/hieedaniel/kidsmiss:latest
```

数据全在挂载的 `data/` 里（`cuoti.db` + `uploads/` + `figs/` + `papers/`），容器删了重建数据还在。

### 3. 把本地已有题库搬上去

服务器上启动的是空库。本地已经录了题的话，把 `server/data` 打包传过去（**先传数据再启动容器**，避免属主变成 root）：

```bash
# 本地：打包
cd cuoti-app
tar -czf data.tgz -C server data

# 传到服务器
scp data.tgz root@<服务器IP>:~/kidsmiss/

# 服务器：解压到挂载点，再起容器
cd ~/kidsmiss && mkdir -p data
tar -xzf data.tgz --strip-components=1 -C data
docker compose up -d
```

如果容器已经跑起来了，就先 `docker compose down`，解压后 `chown -R 1000:1000 data`（或直接 `docker compose up -d` 前确认目录权限），再启动。

### 4. 首次使用

浏览器打开 `http://服务器IP:8770` → 侧栏「设置」→ 填大模型接口地址、API Key、模型名 → 点「测试连通」。配好之后上传页的识别才能真正用起来。不配也能用，只是识别要手动填。

### 5. 几个环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CUOTI_SEED` | `0`（镜像内） | 首次启动是否导入 9 道示例题。想要就设 `1` |
| `CHROME_PATH` | `/usr/bin/chromium` | PDF 用的浏览器，一般不用改 |
| `TZ` | `Asia/Shanghai` | 影响卷子文件名里的时间戳 |

### 6. 更新版本

```bash
docker compose pull && docker compose up -d
```

### 7. 安全提醒

**这套东西没有登录**。直接对公网开放等于谁都能翻你家孩子的错题、改你的题库（里面还存着大模型 Key）。至少做一层：

```nginx
# 放在 vhost 里，套一层 Basic Auth
location / {
    auth_basic "restricted";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:8770;
    proxy_set_header Host $host;
    client_max_body_size 30m;   # 上传原图要放宽，默认 1m 会失败
}
```

或者干脆只挂 VPN / 内网访问。

---

## 八、自测

服务起来后跑一遍冒烟测试，53 项覆盖题库 CRUD、筛选、上传、识别降级、重做与星级、组卷出 PDF、批量任务、路径穿越防护、错误处理：

```bash
python server/main.py &          # 或 start.sh
python tests/smoke.py            # 默认打 http://127.0.0.1:8770
```

脚本只用标准库，不依赖第三方包。测试会自己建一道题、跑完整流程、最后删掉，只在题库里留一份上传的图片文件和两份卷子。跑完退出码 0 表示全通过。

配了大模型 Key 时，第 5 节会真调一次识别（约 20 秒），其余用例不打模型、不花钱。

测试里几个刻意检查的点，都是踩过的坑：

- **关键词搜索必须收敛**。只断言"有结果"是无效的——参数名写错时后端会忽略它并返回全量，看着像通过了。
- **`result` 只接受 `correct` / `wrong`**，传 `right` 会 400。
- **星级 >1 时答对不会直接变"已掌握"**，要连续对才行。
- **空题干必须被拒**，否则库里会进废题，组卷时出空白。
- **缺图的那张要标失败而不是卡住**。批量任务里有张图找不到时，整批仍要跑完并收尾成 `done`。

---

## 九、下一步可以加什么

- 自动切题：现在批量入库是整页识别出多题，但图形还得手动框；真正的切图要版面分析 + 逐题定位
- 批量任务断点续跑：服务重启后从上次那张继续，而不是重传
- 知识点树：现在章节是扁平字符串，可以换成「章 — 节 — 知识点」三级
- 同类题推送：识别出知识点后调用题库/搜索接口补充变式题
- 艾宾浩斯可视化：把每道题的复习曲线画出来
- 换 FastAPI + SQLAlchemy：要多人用、要 API 文档的时候再迁
