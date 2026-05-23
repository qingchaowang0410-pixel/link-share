# 链接分享平台 · 上线部署指南

> 这份文档教你把**现有的 FastAPI 链接分享平台**部署到公网，做到：
> **固定网址 + 多人各自账号 + 不依赖你的电脑开机 + 数据不丢失**。
> 全程免费（Railway 免费档），约 1~1.5 小时。
>
> 写给：**你的 AI 助手**。把这份文档喂给它，它会带你跑完全程。

---

## 这份文档和 SETUP_GUIDE.md 的区别

- `SETUP_GUIDE.md`：教**从零用 React+Supabase 重做一个**。我们**不走这条**（会丢掉现有功能）。
- 本文档：**保留你现有的 FastAPI 代码**，只升级"账号系统"和"部署方式"。改动最小、不丢功能。

技术栈（保持不变）：
- **后端**：FastAPI + SQLite
- **前端**：Alpine.js + Tailwind（CDN，无构建）
- **托管**：Railway（连 GitHub 自动部署）
- **数据**：Railway 持久磁盘上的 SQLite 文件
- **代码仓库**：GitHub（private 私有仓库）

---

## 给 AI 的元指令（重要）

严格按"阶段顺序"带用户跑。每阶段：先讲清楚干什么、为什么 → 说该谁做什么 → 等用户确认再进下一步 → 遇错就停下查。

强制规则：
- **装新包 / git commit / git push / 部署前**，必须和用户对齐意图，不要擅自做
- **密码、密钥、`auth.txt`、`data/` 目录**不要打印到屏幕、不要塞进 git
- **复制粘贴前先验证**：网址、密钥、邀请码不能多空格、不能换行

---

## 阶段 0 · 准备工作（用户做的事）

| 准备 | 怎么搞 | 验证 |
|---|---|---|
| Python 3 | macOS 自带 | `python3 --version` |
| Git | macOS 自带 | `git --version` |
| GitHub 账号 | https://github.com/signup | 能登录 |
| `gh` CLI（推荐） | `brew install gh` → `gh auth login` | `gh auth status` 通过 |
| Railway 账号（用 GitHub 登录） | https://railway.app | 能登录 |

---

## 阶段 1 · 升级账号系统（改代码，AI 做）

**为什么**：现在 `app.py` 是全员共享一个密码（明文存 `data/auth.txt`）。多人长期用必须改成"每人有自己的账号"，这样"由谁添加 / 谁点击"才可靠，也更安全。

AI 要做的改动（详见后续实现，改完让用户本地验证）：

1. **数据库加 `users` 表**：存 `username` / `password_hash`（加盐哈希，绝不存明文）。
2. **新增注册接口**：要**邀请码**才能注册（小圈子门禁，邀请码放环境变量）。
3. **登录接口改为校验 users 表**：登录成功发一个签名 token / session。
4. **保留中间件守门**：未登录只能看登录页和登录/注册接口。
5. **前端登录页**加"注册"切换 + 用户名输入。
6. **首个注册的人 = 管理员**（或用环境变量指定管理员用户名）。

> ⚠️ 旧的 `data/auth.txt` 单密码逻辑保留做兼容降级即可，但线上以 users 表为准。

---

## 阶段 2 · 让数据"活下来"（改代码，AI 做）

**为什么**：Railway 容器重启会清空普通文件。要把 `links.db` 放到**持久磁盘**（一块永不清空的盘）。

AI 要做的：

1. **数据库路径改为读环境变量**：
   ```python
   # database.py
   import os
   DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
   DB_PATH = DATA_DIR / "links.db"
   ```
   本地不设 `DATA_DIR` → 还是用 `./data`；线上把 `DATA_DIR` 设成持久磁盘挂载点（如 `/data`）。

2. **端口改为读 `$PORT`**（Railway 会注入）：
   ```python
   # app.py 末尾
   port = int(os.environ.get("PORT", 8000))
   uvicorn.run(app, host="0.0.0.0", port=port)
   ```

---

## 阶段 3 · 加部署配置文件（AI 做）

在项目根目录补这些文件：

### `Procfile`（告诉 Railway 怎么启动）
```
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

### `requirements.txt`（补全依赖）
现在只有 `fastapi` + `uvicorn`。需要补：
- `requests`（`fetch_meta.py` 抓网页用，如果当前是用标准库则可不加——AI 先确认）
- 其它实际 import 到的第三方包

### `.gitignore`（关键：别把数据和密钥推上去）
```
__pycache__/
*.pyc
.DS_Store
data/
*.db
*.log
*.pid
data/auth.txt
.env
```

### `runtime.txt`（可选，固定 Python 版本）
```
python-3.12
```

---

## 阶段 4 · 本地跑通（验证改动没破坏功能）

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

打开 http://127.0.0.1:8000 ，验证：
- 看到**登录/注册页**
- 用邀请码注册一个账号 → 登录成功 → 进主界面
- 加一条链接 → 列表显示 → 编辑/删除都通
- 看板统计正常

全通过才进下一步。

---

## 阶段 5 · 推到 GitHub（AI 起草，用户审批）

```bash
git init -b main
git add .
git status   # ⚠️ 确认 data/ 和 auth.txt 没被加进去
```

AI 起草 commit message 给用户看，**等用户审完才提交**：
```
chore: 上线改造（多账号 + 持久化 + Railway 配置）
```

用 `gh` 建私有仓库并推送：
```bash
gh repo create <你的用户名>/link-share --private --source=. --remote=origin --push
```

---

## 阶段 6 · 部署到 Railway

### 6.1 新建项目
- https://railway.app → **New Project** → **Deploy from GitHub repo** → 选 `link-share`
- Railway 自动识别 Python，开始第一次构建（**可能失败，正常**，因为还没配持久磁盘和环境变量）

### 6.2 加持久磁盘（Volume）
- 项目里点服务 → **Settings / Volumes** → **Add Volume**
- Mount path 填：`/data`
- 这块盘永不清空，`links.db` 就存这里

### 6.3 加环境变量（Variables）
| Key | Value | 说明 |
|---|---|---|
| `DATA_DIR` | `/data` | 指向持久磁盘 |
| `INVITE_CODE` | 你定一个（如 `link2026`） | 注册门禁 |
| `SECRET_KEY` | 一串随机长字符串 | 给登录 token 签名用 |
| `ADMIN_USER` | 你的用户名 | 指定谁是管理员 |

### 6.4 生成公网域名
- 服务 → **Settings / Networking** → **Generate Domain**
- 拿到固定网址 `https://link-share-xxxx.up.railway.app`

### 6.5 端到端验证
```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://你的网址.up.railway.app/
```
预期 HTTP 200。

让用户：
- 打开网址 → 看到登录页
- 用邀请码注册 → 进主界面
- **换一台电脑 / 手机**打开同一网址 → 也能注册登录 → 看到同样的数据
- 你电脑关机 → 网址照样能开 ✅

---

## 阶段 7 · 收尾

- 把网址 + 邀请码发给同事，让他们各自注册
- 备份：Railway 持久磁盘上的 `links.db`，或网站里"导出 JSON"
- 更新 `README.md` / `devlog.md` 记录线上地址和改动

---

## 故障排查速查

| 症状 | 原因 | 怎么修 |
|---|---|---|
| 部署后数据每次重启就没了 | 没挂持久磁盘 / `DATA_DIR` 没指对 | 阶段 6.2 + 6.3 检查 |
| 构建失败找不到包 | `requirements.txt` 缺依赖 | 阶段 3 补全 |
| 打开白屏 / 502 | 端口没读 `$PORT` | 阶段 2 第 2 步 |
| 注册报"邀请码错误" | `INVITE_CODE` 没配或不一致 | 阶段 6.3 检查 |
| 推代码把数据库也推上去了 | `.gitignore` 没生效 | `git rm -r --cached data/` 再提交 |

---

## 为什么这么选（用户问到时这样讲）

- **为什么不换 React+Supabase**：你现有 FastAPI 功能更全（点击追踪/冷热门/抓 meta），换栈要全部重写，不划算。
- **为什么 SQLite + 持久磁盘够用**：几个人用碰不到并发上限；备份就是下载一个文件，最简单。人多了再迁 PostgreSQL。
- **为什么 Railway**：对 FastAPI 最友好，连 GitHub 自动部署，持久磁盘一键加。
- **为什么免费档够**：小团队收藏链接，流量和存储远用不完。
