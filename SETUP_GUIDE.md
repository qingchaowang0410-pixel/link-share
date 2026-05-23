# LinkStash 完整搭建指南

> 这份文档教你从零搭建一个跟 m4air 同款的 LinkStash —— 公开网址 + 账号系统 + 云数据库 + RLS 权限。
> 写给：**你的 AI 助手（Claude / Codex / Cursor 等）**。把这份文档全文喂给它，它会带你跑完全程。
>
> 总耗时：约 1.5~2 小时（含等待）。总成本：**0 元**（全部免费档）。

---

## 给 AI 的元指令（重要）

你拿到这份文档后，**严格按"阶段顺序"带用户跑**。每个阶段：

1. **先讲清楚这一步要干什么、为什么**
2. **告诉用户该做什么 / 你该做什么**
3. **等用户确认完成或截图反馈，再进下一步**
4. **遇到错误就停下查，不要硬冲**

强制规则：
- **任何"装新包"、"git commit"、"git push" 前**，必须和用户对齐意图，不要擅自做
- **`.env.local` / 数据库密码 / API key** 写入 / 读取要谨慎，不要打印到屏幕、不要往 git 里塞
- **任何 SQL 改动**先给用户看，让用户在 Supabase SQL Editor 里手动跑，**不要自动跑**
- **复制粘贴前先验证**：URL、key、邀请码不能多空格、不能换行

技术栈固定为：
- **前端**：Vite + React 19 + TypeScript + Tailwind v4
- **数据库 + 账号**：Supabase（PostgreSQL + Auth + RLS）
- **托管**：Vercel
- **代码仓库**：GitHub（private 仓库）
- **包管理器**：pnpm

---

## 阶段 0 · 准备工作（用户做的事）

**必须先有这些**：

| 准备 | 怎么搞 | 验证 |
|---|---|---|
| macOS / Linux / Windows 电脑 | — | `node -v` 能跑 |
| Node.js ≥ 20 | https://nodejs.org 装最新 LTS | `node -v` 显示 v20+ |
| pnpm | `npm i -g pnpm` | `pnpm -v` |
| Git | macOS 自带；Windows 装 Git for Windows | `git --version` |
| GitHub 账号 | https://github.com/signup | 能登录 |
| `gh` CLI（可选但强烈推荐）| `brew install gh`（mac）/ https://cli.github.com（windows）| `gh auth login` 完成 |
| Vercel 账号（用 GitHub 登录）| https://vercel.com/signup | 能登录 |
| Supabase 账号（用 GitHub 登录）| https://supabase.com | 能登录 |

**如果用户没这些**，AI 先帮用户检查 + 安装。

---

## 阶段 1 · 初始化项目骨架

### 1.1 选个项目目录

让用户选一个干净的目录，比如 `~/projects/`。**不要选已有 git 仓库的子目录**。

### 1.2 用 Vite 创建项目

```bash
cd ~/projects
pnpm create vite@latest link-stash -- --template react-ts
cd link-stash
```

⚠️ **检查脚手架结果**：进 `src/` 看是否有 `App.tsx`（React 模板）。如果只有 `main.ts` + `counter.ts`，是 vanilla 模板搞错了——按下面手动改：

- 重写 `index.html` 把 `<div id="app">` 改成 `<div id="root">`，`/src/main.ts` 改成 `/src/main.tsx`
- 删 `src/counter.ts` `src/main.ts` `src/style.css`
- 后面 `main.tsx` 自己建

### 1.3 装依赖

**告诉用户**接下来要装这些包，得到许可后再装：

```bash
pnpm install   # 装 vite 模板默认依赖
pnpm add react react-dom @supabase/supabase-js
pnpm add -D @types/react @types/react-dom @vitejs/plugin-react tailwindcss @tailwindcss/vite
```

### 1.4 改 `tsconfig.json`

加 `"jsx": "react-jsx"`、`"strict": true`、`"lib": ["ES2023", "DOM", "DOM.Iterable"]`。

### 1.5 建 `vite.config.ts`

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
})
```

### 1.6 验证

```bash
pnpm dev
```

打开 `http://localhost:5173/`，看到 Vite 默认页面就 OK。

---

## 阶段 2 · 建 Supabase 项目 + 数据库

### 2.1 注册 + 建 Organization

引导用户：
- 打开 https://supabase.com → Sign in with GitHub
- 建 organization：Personal 类型、Free plan、名字随便（如用户的 GitHub username）

### 2.2 建 Project

填这些：

| 字段 | 填什么 |
|---|---|
| Project name | `link-stash` |
| Database Password | **点 "Generate a password"，复制到密码管理器** ⚠️ |
| Region | **Northeast Asia (Tokyo)**（中国大陆用户最快）或 Singapore |
| Pricing Plan | Free |
| Security · Enable Data API | ✅ 勾选 |
| Security · Automatically expose new tables | ❌ **不勾**（安全考虑，手动 grant 更可控）|
| Security · Enable automatic RLS | ✅ 勾选 |

⚠️ **数据库密码**：用户自己保管，**AI 永远不要存这个密码、不要让用户贴对话里**。AI 只用 API key 操作。

点 **Create new project**，等 1~3 分钟数据库就绪。

### 2.3 跑建表 SQL（公开模板）

进入项目主页 → 左侧 **SQL Editor**（`> _` 图标）→ 新建 query → 贴下面这段 → Run。

```sql
-- ============================================
-- LinkStash 数据库结构
-- ============================================

-- 1. 链接表
create table public.links (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  url text not null,
  description text not null default '',
  favicon_url text not null default '',
  added_by text not null,
  shared_by text not null default '',
  added_at timestamptz not null default now(),
  used_for text not null,
  created_at timestamptz not null default now()
);

-- 2. 索引
create index links_owner_added_at_idx on public.links (owner_id, added_at desc);

-- 3. 开启行级权限
alter table public.links enable row level security;

-- 4. 任何人可读
create policy "anyone can read links"
  on public.links for select using (true);

-- 5. 登录用户能加自己的
create policy "only owner can insert"
  on public.links for insert with check (auth.uid() = owner_id);

-- 6. 只能改自己加的
create policy "only owner can update"
  on public.links for update
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

-- 7. 只能删自己加的
create policy "only owner can delete"
  on public.links for delete using (auth.uid() = owner_id);

-- 8. 授权给角色（重要：因为 Automatically expose 关了，要手动 grant）
grant select on public.links to anon;
grant select, insert, update, delete on public.links to authenticated;
```

### 2.4 跑 admin SQL（用户**改邮箱**！）

⚠️ **AI 要让用户先把 `'your-admin-email@example.com'` 改成 ta 自己的邮箱**，再跑：

```sql
-- ============================================
-- Admin 权限补丁
-- ⚠️ 把 'your-admin-email@example.com' 改成你自己的邮箱
-- ============================================

create or replace function public.is_admin()
returns boolean language sql security definer stable as $$
  select coalesce(
    (select email = 'your-admin-email@example.com' from auth.users where id = auth.uid()),
    false
  );
$$;

create policy "admin can update any"
  on public.links for update
  using (public.is_admin()) with check (public.is_admin());

create policy "admin can delete any"
  on public.links for delete using (public.is_admin());
```

### 2.5 关掉邮箱确认

引导用户：
- 左侧 **Authentication** 🔒 → **Sign In / Providers** → **Email** → 关闭 **"Confirm email"** → Save

理由：Supabase 免费档没配 SMTP，开着这个会导致**注册时收不到验证邮件 → 注册失败**。关掉后注册即立刻可用。

### 2.6 拿 API key

左侧 **Project Settings ⚙️** → **API Keys** → 复制：

- **Project URL**：长这样 `https://xxxxxxxxxxx.supabase.co`
- **Publishable key**（新版叫法；旧版叫 `anon key`）：长这样 `sb_publishable_xxxxx...`

⚠️ **绝对不要碰 Secret keys 区域**。Secret key 暴露 = 数据库被完全控制。

让用户**直接发 publishable key 给你**（这个是设计上公开的，可以贴对话），用于配置代码。

### 2.7 用 curl 验证 key 通了

AI 用这条命令验证（替换 `<URL>` 和 `<KEY>`）：

```bash
curl -s -H "apikey: <KEY>" "<URL>/rest/v1/links?select=id"
```

**预期**：返回 `[]`（空数组）。
- 返回 `[]` → ✅ 通了，进下一步
- 返回 `permission denied for table links` → grant SQL 没跑成功，回 2.3 检查
- 返回 401 → key 错了，让用户重新复制
- 返回其他错误 → 截图给用户看，让用户在 Supabase 后台手动检查

---

## 阶段 3 · 写前端代码

按这个**文件清单 + 代码骨架**逐个建。AI 应该**完整写每个文件**，不要省略。

下面给出关键文件的"骨架要点"，详细完整代码 AI 参照 [m4air 的 LinkStash 仓库](https://github.com/Ea12421/link-stash) 实现（如果对方愿意公开）。

如果仓库不公开，AI 按以下要点自己写：

### 文件清单

```
src/
├── main.tsx          React 入口
├── index.css         Tailwind import + 暖米白底全局样式
├── App.tsx           顶层：auth 守门 + 列表/看板 tab + 顶部 header
├── types.ts          LinkEntry 类型定义
├── supabase.ts       Supabase client 单例
├── auth.ts           signIn/signUp/signOut/getCurrentUser/isAdmin/canEdit
├── storage.ts        fetchAllEntries / insertEntry / updateEntry / deleteEntry
├── metadata.ts       URL → favicon（用 microlink 或 Google favicon API）
└── components/
    ├── LoginPage.tsx        登录/注册切换，注册要邀请码
    ├── LinkForm.tsx         新增/编辑表单
    ├── LinkList.tsx         列表渲染（空态在这里）
    ├── LinkItem.tsx         单条目（按 canEdit prop 控制按钮显隐）
    ├── Toolbar.tsx          搜索 + 筛选 + 导出 JSON
    └── Dashboard.tsx        看板：总数 / 用在哪 / 分享人 / 域名
```

### 关键设计要点

**`LinkEntry` 字段**：
```ts
{ id, ownerId, url, description, faviconUrl, addedBy, sharedBy, addedAt, usedFor }
```

注意 camelCase 前端 vs snake_case 数据库的转换在 `storage.ts` 的 `rowToEntry` / `entryToInsert` 里处理。

**`supabase.ts` 单例**：
```ts
import { createClient } from '@supabase/supabase-js'
const url = import.meta.env.VITE_SUPABASE_URL
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY
if (!url || !key) throw new Error('Supabase env vars missing')
export const supabase = createClient(url, key)
export const INVITE_CODE: string = import.meta.env.VITE_INVITE_CODE ?? ''
```

**`auth.ts` 邀请码逻辑**：
```ts
export async function signUp(email, password, inviteCode) {
  if (!INVITE_CODE) throw new Error('注册暂未开放')
  if (inviteCode.trim() !== INVITE_CODE) throw new Error('邀请码不正确')
  const { data, error } = await supabase.auth.signUp({ email, password })
  if (error) throw error
  return data.user
}

export function isAdmin(user: User | null): boolean {
  return user?.email === 'your-admin-email@example.com'  // ⚠️ 改成用户的邮箱
}

export function canEdit(user, ownerId) {
  if (!user) return false
  if (isAdmin(user)) return true
  return user.id === ownerId
}
```

**`App.tsx` auth 守门**：
```tsx
if (!authReady) return <载入中…>
if (!user) return <LoginPage />
return <主界面 />
```

**`LinkItem` 按权限显示编辑/删除**：
```tsx
{canEdit && (
  <div>
    <button onClick={onEdit}>编辑</button>
    <button onClick={onDelete}>删除</button>
  </div>
)}
```

### UI 风格

Notion 风暖色：
- 全局背景 `#FBF9F6`
- 主文字 `text-stone-900`
- 主按钮 `bg-stone-900 text-white`
- 强调色 `emerald-700`（链接 hover / 按钮聚焦 ring）
- 标签三色：emerald（用途）/ amber（分享人）/ stone（录入人）
- 圆角 `rounded-2xl`（卡片）`rounded-lg`（输入框）
- 阴影 `shadow-[0_1px_2px_rgba(0,0,0,0.03)]`

---

## 阶段 4 · 本地跑通

### 4.1 建 `.env.local`

⚠️ **AI 要先和用户确认值再写入**：

```
VITE_SUPABASE_URL=https://你的项目id.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_xxxxxxxxxx
VITE_INVITE_CODE=你定一个邀请码（比如 link2026）
```

⚠️ **确认 `.gitignore` 包含 `.env.local`**（Vite 模板默认有 `*.local`）。

### 4.2 typecheck + build

```bash
pnpm exec tsc --noEmit
pnpm build
```

两个都通过才能继续。

### 4.3 启动 dev server

```bash
pnpm dev
```

打开 http://localhost:5173/，应该看到登录页。

### 4.4 注册测试

- 用用户**自己真实邮箱**（admin 邮箱）
- 密码自己定（≥6 位）
- 邀请码：跟 `.env.local` 里的 `VITE_INVITE_CODE` 一致

预期：登录成功 → 主界面 → 顶部有邮箱 + 琥珀色 ADMIN 徽章。

加一条链接试试 → 看列表 → 编辑/删除 → 都通 → 本地验证完成。

---

## 阶段 5 · 推到 GitHub

### 5.1 初始化 git

```bash
git init -b main
git add .
```

**AI 起草 commit message** 给用户看，**等用户审完才提交**：

```
chore: 初始化 LinkStash 项目

Co-Authored-By: ...
```

### 5.2 用 `gh` 建私有仓库 + 推送

```bash
gh repo create <github-username>/link-stash --private --source=. --remote=origin --push --description "Personal link bookmarking tool"
```

如果用户没装 `gh`：让用户去 https://github.com/new 手动建 private 仓库，然后：

```bash
git remote add origin https://github.com/<username>/link-stash.git
git push -u origin main
```

---

## 阶段 6 · 部署到 Vercel

### 6.1 导入项目

引导用户：
- https://vercel.com/dashboard → **Import Git Repository**
- 第一次会让"Install Vercel GitHub App"，选 **Only select repositories** → 勾 `link-stash` → Install
- 回到 Vercel → 看到 `link-stash` → 点 **Import**

### 6.2 配置（基本默认）

| 字段 | 值 |
|---|---|
| Framework Preset | **Vite**（自动识别）|
| Build Command | `pnpm run build`（自动）|
| Output Directory | `dist`（自动）|
| Install Command | 留空（Vercel 自动跑 pnpm install）|
| Environment Variables | 这里**暂时不填**，部署后再加 |

点 **Deploy**。第一次部署**预计会失败**（缺环境变量），这是预期。

### 6.3 加环境变量

部署完后进 Project → Settings → **Environment Variables**：

**关键陷阱**：Vercel 默认会把 key 名带 `KEY`、`CODE` 的标成 **Sensitive**，会导致前端读不到。**点 Key 旁边的橙色 ⚠️ 图标 → 取消 Sensitive 标记**。

添加 3 个变量，每个**所有环境都勾**（Production / Preview / Development）：

| Key | Value |
|---|---|
| `VITE_SUPABASE_URL` | `https://你的项目id.supabase.co` |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_xxxxx` |
| `VITE_INVITE_CODE` | 你定的邀请码 |

Save。

### 6.4 重新触发部署

两种方式选一：
- **Vercel 的弹窗会显示 "Redeploy" 按钮**，点它
- 或者本地推一条无意义的 commit（比如改 README）`git push`

部署成功后，Vercel 给一个网址 `https://link-stash-xxxxx.vercel.app`。

### 6.5 端到端验证

AI 用 curl 验证：

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://你的网址.vercel.app/
```

预期 HTTP 200。

让用户：
- 打开网址（强制刷新 `Cmd+Shift+R`）→ 看到登录页
- 用 admin 邮箱注册 → 进主界面 → 顶部有 ADMIN 徽章
- 加一条链接 → 编辑删除都能用
- 开**隐身窗口**访问同一网址 → 应该看到登录页（不显示数据，因为我们设了"未登录不可看"）

---

## 阶段 7 · 收尾 · 写文档

让 AI 把这些信息记到项目根目录：

### `CLAUDE.md`（项目说明）

记录：
- 项目定位
- 数据库 schema 和 RLS 规则简介
- 环境变量清单
- 部署网址、Supabase 项目 ID、GitHub 仓库地址
- 升级路径（以后想加什么）

### `devlog.md`（开发日志）

按时间倒序记每次有意义的改动。**新对话从这里能秒接上**。

---

## 完工 · 常见后续

| 想做的事 | 怎么做 |
|---|---|
| 改邀请码 | 在 Vercel 改 `VITE_INVITE_CODE` 环境变量 → Redeploy |
| 加新 admin | 改 SQL 里的 `is_admin()` 函数 + `src/auth.ts` 里的 `isAdmin()` 函数中的邮箱，重新部署 |
| 自定义域名 | Vercel → Domains → 加域名（域名要自己买）|
| 备份数据 | 网站里点"导出 JSON" / 或在 Supabase Table Editor 直接导出 |
| 给同学发链接 | 把网址 + 邀请码告诉同学，让他自己注册 |
| 删某个同学的账号 | Supabase → Authentication → Users → 找到他 → Delete user |

---

## 故障排查速查

| 症状 | 可能原因 | 怎么修 |
|---|---|---|
| 注册时报 "注册失败" 没具体原因 | Supabase 邮箱验证开着 | 阶段 2.5 关掉 |
| 注册时报 "email_address_invalid" | Supabase 拒绝某些假邮箱域 | 换真实邮箱试试 |
| 部署后白屏 | 环境变量没配 / Sensitive 没关 | 阶段 6.3 检查 |
| curl 返回 "permission denied for table links" | grant SQL 没跑 | 阶段 2.3 重跑 |
| curl 返回 401 | publishable key 错或被截断 | 用 Vercel/Supabase 后台的 Copy 按钮重新复制 |
| 加链接报错 "new row violates row-level security policy" | RLS 阻止 | 用户没登录 / `owner_id` 没传 |
| admin 徽章不显示 | 邮箱拼错 | 检查 `auth.ts` 里的 `isAdmin()` 和 SQL 里的 `is_admin()` 邮箱是否一致 |

---

## 给 AI 的最后提醒

按这份文档跑下来，每一步都做对，应该 1.5~2 小时完成（用户操作时间为主，AI 写代码很快）。**别跳步**——尤其阶段 2.5（关邮箱验证）、阶段 6.3（关 Sensitive）这两个**最常踩坑的地方**。

用户问到"为什么这么做"，按以下原则讲：
- **为什么 RLS**：数据库层面的强制权限，前端代码绕不过，最安全
- **为什么邀请码在前端验**：小圈子门禁够用，懂技术的人按 F12 能看到但不影响实际安全（因为 RLS 才是真正护城河）
- **为什么免费档够**：Vercel 100GB 带宽/月、Supabase 500MB 数据库 + 5 万月活，个人用一辈子用不完

祝好运。
