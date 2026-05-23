# 链接分享平台 · Render + Neon 上线部署指南

> 这份文档教你把**现有的 FastAPI 链接分享平台**部署到公网，做到：
> **固定网址 + 多人各自账号 + 不依赖你的电脑开机 + 数据存在云端不丢失**。
> 全程免费（Render 免费 Web 档 + Neon 免费 PostgreSQL，**两边都不绑卡**），约 1~1.5 小时。
>
> 写给：**你的 AI 助手**。把这份文档喂给它，它会带你跑完全程。

---

## 这份文档和 `DEPLOY_GUIDE.md` 的区别

- `DEPLOY_GUIDE.md`：旧版，用 **Railway + 持久磁盘上的 SQLite**。
- 本文档：用 **Render（跑代码）+ Neon（存数据库）**。数据库已经从 SQLite 换成 PostgreSQL，连接串从环境变量 `DATABASE_URL` 读。这是当前推荐路线。

当前技术栈：
- **后端**：FastAPI（`app.py`）+ psycopg 3（`psycopg[binary]==3.2.13`，已在 `requirements.txt`）
- **前端**：Alpine.js + Tailwind（CDN，无构建）
- **数据库**：**Neon**（云端 PostgreSQL，免费档）
- **托管**：**Render**（连 GitHub 自动部署，免费 Web 档）
- **代码仓库**：GitHub（**private 私有仓库**）

> 关键理解：**代码跑在 Render，数据存在 Neon**。两者分开，所以 Render 重启 / 重新部署，数据都不会丢。

---

## 给 AI 的元指令（重要，先读）

严格按"阶段顺序"带用户跑。每阶段：先讲清楚干什么、为什么 → 说该谁做什么 → 等用户确认再进下一步 → 遇错就停下查。

**强制规则：**
- **装新包 / `git commit` / `git push` / 在 Render 触发部署前**，必须先和用户对齐意图，**不要擅自做**。
- **密钥绝不外泄**：`DATABASE_URL`（含数据库密码）、`SECRET_KEY`、`INVITE_CODE` —— **不打印到屏幕、不写进 git、不写进任何会提交的文件**。需要时让用户自己在网页后台粘贴。
- `export DATABASE_URL=...` 只在本地终端临时设置，**不要写进 `app.py`/`database.py`/任何 `.py` 或 `.env` 提交文件**。`.gitignore` 已忽略 `.env`，但仍以"不写进文件"为准。
- **复制粘贴前先验证**：网址、连接串、密钥、邀请码不能多空格、不能换行。Neon 连接串结尾的 `?sslmode=require` 不要漏。
- 本文档只描述操作，**不要由 AI 真去执行部署命令**（建仓、推送、迁移这类命令需用户明确同意后再跑）。

---

## 阶段 0 · 准备工作（用户做的事）

| 准备 | 怎么搞 | 验证 |
|---|---|---|
| Python 3 | macOS 自带 | `python3 --version`（≥ 3.10） |
| Git | macOS 自带 | `git --version` |
| GitHub 账号 | https://github.com/signup | 能登录 |
| `gh` CLI（推荐） | `brew install gh` → `gh auth login` | `gh auth status` 通过 |
| Neon 账号（用 GitHub 登录） | https://neon.tech | 能登录，**不要求绑卡** |
| Render 账号（用 GitHub 登录） | https://render.com | 能登录，**不要求绑卡** |

确认项目里这几个文件已就绪（本仓库都有）：
- `requirements.txt` 含 `psycopg[binary]==3.2.13` ✅
- `runtime.txt` 写 `python-3.12` ✅
- `migrate_to_postgres.py` 迁移脚本 ✅
- `.gitignore` 已忽略 `data/`、`*.db`、`.env` ✅

---

## 阶段 1 · 注册 Neon，建数据库，拿连接串

**为什么**：先要有一个云端 PostgreSQL，后面本地迁数据和线上跑都连它。

1. 打开 https://neon.tech → **Sign up** → 选 **Continue with GitHub** 登录（免费档不绑卡）。
2. 登录后会引导你 **Create a project**：
   - Project name：随便（如 `linkhub`）
   - Postgres version：默认即可
   - Region：选离你近的（如 **Asia Pacific (Singapore)** 或 **US East**，越近越快）
3. 建好后，在项目页找 **Connection string / Connect**，复制那串连接串。形如：
   ```
   postgresql://用户名:密码@ep-xxx-xxx.region.aws.neon.tech/dbname?sslmode=require
   ```
   - 选 **Pooled connection** 或直连都可以；务必带上结尾的 `?sslmode=require`。
   - ⚠️ 这串里**含数据库密码**，当机密对待，别截图发群、别贴进代码。

> 这一串就是后面到处要用的 `DATABASE_URL`。先放在你自己的密码管理器 / 备忘录里。

---

## 阶段 2 · 本地把现有数据迁到 Neon

**为什么**：你本地 `data/links.db`（SQLite）里已有的链接数据，要搬到 Neon 上，这样上线后老数据还在。

> 用的是仓库里的 `migrate_to_postgres.py`。它的行为（先读 docstring 了解）：
> - 从 `data/links.db` 读，写进 `DATABASE_URL` 指向的 Neon 库；
> - **保留原始 id**，迁完会重置自增序列；
> - **幂等保护**：目标 `links` 表非空时会拒绝执行，加 `--force` 才清空重来；
> - **不迁 `users` 表**（旧库没有账号；账号到线上用邀请码重新注册，见阶段 6）。

操作（在项目根目录 `/Users/wangqingchao/链接分享平台`）：

1. 先确认依赖装好（迁移脚本要用 psycopg）：
   ```bash
   python3 -m pip install -r requirements.txt
   ```
2. 把阶段 1 的连接串临时设进当前终端环境变量（**只在终端里设，不写进文件**）：
   ```bash
   export DATABASE_URL="postgresql://用户名:密码@ep-xxx.region.aws.neon.tech/dbname?sslmode=require"
   ```
   （AI 提示用户自己粘贴真实串；AI 不要把真实串回显或写进任何文件。）
3. 跑迁移：
   ```bash
   python3 migrate_to_postgres.py
   ```
   预期输出：先打印 `✓ PostgreSQL 表结构已就绪`，再逐表打印迁入行数，最后 `✓ 迁移完成，数据一致`（SQLite → PG 各表行数一致）。
4. 如果你**之前已经迁过一次、想清空重来**，再加 `--force`（会先 TRUNCATE 目标表）：
   ```bash
   python3 migrate_to_postgres.py --force
   ```

> 若你本地**没有历史数据 / 是全新开始**：可以跳过迁移。线上首次启动时 `init_db()` 会自动建好所有表（见 `database.py` 的 `@app.on_event("startup")`）。

---

## 阶段 3 · 推代码到 GitHub（私有仓库）

**为什么**：Render 通过连接 GitHub 仓库来拉代码、自动部署。

> AI 起草命令和 commit message 给用户看，**等用户审批后再执行**。

1. 推送前自查，**确认敏感文件没被加进去**：
   ```bash
   git status
   ```
   `data/`、`*.db`、`.env` 应被 `.gitignore` 忽略（本仓库已配置）。若发现数据库被跟踪了：
   ```bash
   git rm -r --cached data/
   ```
2. 提交（commit message 示例，由用户确认）：
   ```bash
   git add .
   git commit -m "docs: 增加 Render + Neon 部署文档"
   ```
3. 推到 GitHub 私有仓库。若仓库还没建，用 `gh`：
   ```bash
   gh repo create <你的用户名>/link-share --private --source=. --remote=origin --push
   ```
   若已有 remote，直接 `git push`。

---

## 阶段 4 · 在 Render 新建 Web Service

**为什么**：让代码跑在公网，拿到固定网址。

### 4.1 创建服务
1. 打开 https://render.com → 用 **GitHub 登录**（免费档不绑卡）。
2. **New +** → **Web Service** → 连接并选你刚推的 GitHub repo（首次需授权 Render 访问你的 GitHub）。

### 4.2 填配置

| 项 | 值 |
|---|---|
| Name | 随便（如 `linkhub`，会成为网址前缀） |
| Region | 选离你近的（建议和 Neon 同区域，延迟低） |
| Branch | `main` |
| Runtime / Language | **Python**（Render 会自动识别） |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app:app --host 0.0.0.0 --port $PORT` |
| Instance Type | **Free** |

> 说明：`$PORT` 由 Render 自动注入，`app.py` 已经读 `PORT` 环境变量。仓库里虽然也有 `Procfile`，但 Render 用上面填的 Start Command 即可。`runtime.txt` 里的 `python-3.12` 会让 Render 用 Python 3.12。

### 4.3 加环境变量（Environment / Environment Variables）

在创建页或服务的 **Environment** 标签里加这几条（**值由用户粘贴，AI 不代填真实密钥**）：

| Key | Value | 必填 | 说明 |
|---|---|---|---|
| `DATABASE_URL` | 阶段 1 的 Neon 连接串（带 `?sslmode=require`） | ✅ 必填 | 不设会启动即报错 |
| `SECRET_KEY` | 一串随机长字符串 | ✅ 必填 | 给登录 token 签名。不设会用不安全的默认值 |
| `INVITE_CODE` | 你定一个（如 `link2026`） | 建议填 | 注册门禁；**留空 = 关闭注册**，没人能注册新账号 |
| `ADMIN_USER` | 你打算用的管理员用户名 | 可选 | 指定谁是管理员；留空则"第一个注册的人"自动当管理员 |
| `TOKEN_TTL` | 默认 `2592000`（30 天，单位秒） | 可选 | 登录有效期；一般不用改 |

> `PORT` **不用手动加**，Render 自动注入。
>
> 生成随机 `SECRET_KEY` 的办法（让用户自己在本地终端跑，复制结果粘进 Render，**不要写进文件、不要回显进 git**）：
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(32))"
> ```

### 4.4 创建并首次部署
点 **Create Web Service**。Render 会拉代码 → 跑 Build Command → 跑 Start Command。
- 看 **Logs**：应看到 `Uvicorn running on ...`。
- 启动时 `init_db()` 会在 Neon 上把表建好（已迁过数据的话表已存在，`CREATE TABLE IF NOT EXISTS` 不会重复建）。

---

## 阶段 5 · 拿到固定网址 + curl 验证

部署成功后，Render 服务页顶部有固定网址，形如：
```
https://linkhub-xxxx.onrender.com
```

命令行验证（HTTP 200 即通）：
```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://你的网址.onrender.com/
```
预期 `HTTP 200`。

> ⚠️ **免费档第一次访问会很慢**：如果服务刚被唤醒（见下方"诚实须知"），这条 curl 可能要等 **30~50 秒**才返回。先等一下再判断失败。

---

## 阶段 6 · 端到端验证（多设备）

让用户实际走一遍：

1. 浏览器打开网址 → 看到**登录 / 注册页**。
2. **用邀请码注册一个账号**（用 `ADMIN_USER` 指定的那个用户名，或第一个注册即管理员）→ 进主界面。
   - 旧的 SQLite 单密码 / `auth.txt` **不迁移**，账号必须在线上重新注册（见下方诚实须知）。
3. 加一条链接 → 列表出现 → 编辑 / 删除都通 → 看板统计正常。
4. **换一台电脑 / 手机**打开同一网址 → 也能注册 / 登录 → 看到同样的数据。
5. **你电脑关机** → 网址照样能开 ✅（代码在 Render，数据在 Neon，都不靠你的电脑）。

把网址 + 邀请码发给同事，让他们各自注册自己的账号。

---

## 诚实须知（免费档的真实代价，务必告诉用户）

- **Render 免费 Web 档会休眠**：闲置约 **15 分钟**后服务进入休眠。下一次访问时要**冷启动，等约 30~50 秒**页面才出来；之后一段时间内访问正常。这是免费档的代价，不是 bug。
  - 想避免：升级 Render 付费档（常驻不休眠），或用外部定时器（如 cron-job.org）每隔几分钟 ping 一下网址保活（保活也属灰色用法，自行权衡）。
- **Neon 免费档数据库也可能 suspend**：闲置后数据库会自动挂起，但**下次连接时会自动唤醒，数据不丢**。第一次唤醒会让该次请求稍慢。
- **数据存在 Neon，不在 Render 的磁盘上**：所以 Render **重启 / 重新部署 / 换实例，数据都不会丢**。这正是用 Neon 的原因。
- **账号要重新注册**：旧版 SQLite 的单密码 / `auth.txt` 机制**不迁移**。迁移脚本只搬链接相关数据（sharers / tags / links / link_tags / link_clicks），**不迁 `users` 表**。线上账号一律用邀请码重新注册。

---

## 故障排查速查表

| 症状 | 可能原因 | 怎么修 |
|---|---|---|
| 首次打开要等半分钟 / 第一下超时 | Render 免费档休眠后冷启动 | 正常现象，多等 30~50 秒；介意就保活或升级 |
| 部署日志报 `DATABASE_URL 环境变量未设置` | Render 没配 `DATABASE_URL` | 阶段 4.3 加上，且值正确 |
| 启动报连接 / SSL 错误 | 连接串漏了 `?sslmode=require` 或有多余空格/换行 | 重新从 Neon 复制完整串，去掉首尾空格 |
| 注册报"注册暂未开放" | `INVITE_CODE` 没配（留空 = 关闭注册） | 阶段 4.3 设一个邀请码 |
| 注册报"邀请码不正确" | 输入的邀请码和 `INVITE_CODE` 不一致 | 核对，注意空格 / 大小写 |
| 登录后还是被踢回登录页 | `SECRET_KEY` 在两次部署间变了，旧 token 失效 | 重新登录即可；别频繁改 `SECRET_KEY` |
| 构建失败找不到包 | `requirements.txt` 缺依赖 | 确认 Build Command 是 `pip install -r requirements.txt`，依赖齐全 |
| 本地迁移报"目标 links 表已有 N 行" | 之前迁过，幂等保护拦住 | 确认要重导再加 `--force`（会清空目标表） |
| 本地迁移报"找不到 SQLite 库" | `data/links.db` 不存在 | 全新项目无需迁移，跳过即可（线上会自动建表） |
| curl 返回非 200 但稍后正常 | 冷启动期间访问 | 等服务唤醒后重试 |
| 同事看不到你加的数据 | 没连同一个 Neon 库 / 看错网址 | 确认大家用同一个 Render 网址、`DATABASE_URL` 一致 |

---

## 为什么这么选（用户问到时这样讲）

- **为什么 Render + Neon，而不是 Railway**：Render 免费 Web 档 + Neon 免费 PG **都不绑卡**，组合零成本起步；代码与数据分离，部署更新不怕丢数据。
- **为什么数据库换成 PostgreSQL**：托管平台的容器磁盘是临时的，SQLite 文件容易随重启丢失；用云端 Neon 才能"重启不丢、多实例可扩展"。
- **为什么忍受冷启动**：免费档的唯一明显代价就是闲置休眠后首访变慢。对"小团队偶尔查收藏"的场景完全可接受；嫌慢随时升级付费档即可。
