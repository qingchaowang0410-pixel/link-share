# 链接分享平台

一个团队共用的链接收藏平台。数据保存在 PostgreSQL，支持多账号登录、权限控制、点击追踪与看板统计，可部署到公网。

## 功能

- **看板**：总链接数、本周新增、本周点击数、分类占比、Top 5 分享人、最近 10 条、🔥 高频 Top 5、❄️ 冷门候选
- **添加链接**：粘贴 URL 自动按域名规则猜分类，并尝试抓取网页标题/简介；手动填标题、简介、分享人、标签、备注
- **链接库**：按标题/URL/分享人/标签/备注关键词搜索；按分类、已读状态筛选；标记已读 / 编辑 / 删除
- **分享人**：点任一名字查看 TA 分享过的全部链接

## 账号与权限

- **多账号登录**：每个用户独立账号，密码用 PBKDF2-HMAC-SHA256 加盐哈希存储（不存明文），登录后下发 HMAC 签名 token。
- **邀请码注册**：设置了 `INVITE_CODE` 才开放注册，注册时需填对邀请码。
- **管理员**：由 `ADMIN_USER` 指定；若未指定，则首个注册的用户自动成为管理员。
- **权限控制**：只有管理员或链接的添加者本人才能编辑/删除该链接（后端强制校验，前端隐藏按钮仅为体验）。
- **修改密码**：登录后可自行修改密码。

## 环境变量

| 变量 | 作用 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL 连接串 | 必填。形如 `postgresql://user:pass@host/dbname?sslmode=require`。本地开发指向 Neon 库，线上由部署平台注入。 |
| `SECRET_KEY` | 给登录 token 签名 | 线上务必设一个随机长串。本地有不安全的默认值，仅供开发。 |
| `INVITE_CODE` | 注册门禁 | 为空 = 关闭注册（只有已存在的账号能登录）；设值后凭该邀请码才能注册。 |
| `ADMIN_USER` | 指定管理员用户名 | 注册时该用户名自动标记为管理员。留空则首个注册者即管理员。 |
| `TOKEN_TTL` | 登录 token 有效期（秒） | 可选，默认 30 天（`2592000`）。 |

## 本地开发

需要先把 `DATABASE_URL` 指向一个 PostgreSQL 库（如你的 Neon 库）才能运行：

```bash
python3 -m pip install --user -r requirements.txt   # 首次
export DATABASE_URL='postgresql://user:pass@host/dbname?sslmode=require'
python3 app.py
# 浏览器打开 http://127.0.0.1:8000
```

首次启动会自动建表。其余环境变量本地可不设（用默认值），但若要测试注册流程需 `export INVITE_CODE=...`。

## 线上部署

完整部署步骤（Render + Neon）见 [RENDER_DEPLOY.md](RENDER_DEPLOY.md)。

- 线上访问地址：（部署后填写）

## 数据存储

数据保存在 PostgreSQL（本地连 Neon 库或线上同一个库），不再使用本地 SQLite 文件。

**备份方式**：

- 用 `pg_dump` 导出整库，例如：
  ```bash
  pg_dump "$DATABASE_URL" > backup.sql
  ```
- 或在网站里导出 JSON。

## 自定义域名规则

打开 [domain_rules.py](domain_rules.py)，在 `DOMAIN_RULES` 字典里加一行即可：

```python
"example.com": "你的分类名",
```

修改 `CATEGORIES` 可调整可选分类。

## 技术栈

- 后端：FastAPI + PostgreSQL（psycopg3 驱动）
- 前端：Alpine.js + Tailwind（均走 CDN，无构建步骤）
- 依赖：`fastapi`、`uvicorn`、`psycopg`（见 [requirements.txt](requirements.txt)）
