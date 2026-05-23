from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import (
    count_users,
    create_user,
    fetch_link_with_relations,
    fetch_links,
    get_conn,
    init_db,
    set_link_tags,
    upsert_sharer,
    upsert_tags,
    verify_user,
)
from domain_rules import CATEGORIES, guess_category
from fetch_meta import fetch_meta

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# ---- 部署相关配置（全部从环境变量读，本地有默认值）----
# SECRET_KEY：给登录 token 签名。线上务必在 Railway 设一个随机长串。
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-secret-change-me")
# INVITE_CODE：注册门禁。为空 = 关闭注册（只有已存在的账号能登录）。
INVITE_CODE = os.environ.get("INVITE_CODE", "").strip()
# ADMIN_USER：指定哪个用户名是管理员（注册时自动标记）。也可留空，首个注册者即管理员。
ADMIN_USER = os.environ.get("ADMIN_USER", "").strip()
# token 有效期（秒），默认 30 天
TOKEN_TTL = int(os.environ.get("TOKEN_TTL", 30 * 24 * 3600))

app = FastAPI(title="链接分享平台")


# ============================================================
# 签名 token：把 {用户名, 过期时间} 用 HMAC-SHA256 签名后给前端。
# 服务端无需存 session，凭签名即可验真伪。格式：base64(payload).hex(sig)
# ============================================================

def _make_token(username: str) -> str:
    payload = {"u": username, "exp": int(time.time()) + TOKEN_TTL}
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    sig = hmac.new(SECRET_KEY.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def _verify_token(token: str) -> Optional[str]:
    """校验 token，有效则返回用户名，否则 None。"""
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    expected = hmac.new(SECRET_KEY.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload.get("u")


def _current_user(request: Request) -> Optional[str]:
    token = request.headers.get("x-auth-token") or request.cookies.get("linkhub_auth")
    return _verify_token(token) if token else None


@app.on_event("startup")
def _startup():
    init_db()


# 不需要登录就能访问的路径
PUBLIC_PATHS = {"/", "/api/auth-status", "/api/login", "/api/register"}
PUBLIC_PREFIXES = ("/static/",)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return await call_next(request)

    if _current_user(request):
        return await call_next(request)

    return JSONResponse({"detail": "需要登录"}, status_code=401)


@app.get("/api/auth-status")
def api_auth_status():
    """前端用来决定登录页是否显示"注册"入口。"""
    return {
        "required": True,           # 线上始终要求登录
        "register_open": bool(INVITE_CODE),  # 是否开放注册
    }


class RegisterIn(BaseModel):
    username: str
    password: str
    invite_code: str = ""


@app.post("/api/register")
def api_register(payload: RegisterIn):
    username = (payload.username or "").strip()
    password = payload.password or ""
    if not username or len(username) > 32:
        raise HTTPException(400, "用户名为空或过长（≤32 字）")
    if len(password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    if not INVITE_CODE:
        raise HTTPException(403, "注册暂未开放")
    if (payload.invite_code or "").strip() != INVITE_CODE:
        raise HTTPException(403, "邀请码不正确")

    with get_conn() as conn:
        # 管理员判定：用户名匹配 ADMIN_USER，或（没指定 ADMIN_USER 时）是第一个注册的人
        is_admin = (
            (ADMIN_USER and username == ADMIN_USER)
            or (not ADMIN_USER and count_users(conn) == 0)
        )
        try:
            user = create_user(conn, username, password, is_admin=bool(is_admin))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "用户名已被占用")
    return {"ok": True, "token": _make_token(username), "user": user}


class LoginIn(BaseModel):
    username: str = ""
    password: str


@app.post("/api/login")
def api_login(payload: LoginIn):
    username = (payload.username or "").strip()
    if not username:
        raise HTTPException(400, "请输入用户名")
    with get_conn() as conn:
        user = verify_user(conn, username, payload.password or "")
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    return {"ok": True, "token": _make_token(user["username"]), "user": user}


@app.get("/api/me")
def api_me(request: Request):
    username = _current_user(request)
    if not username:
        raise HTTPException(401, "未登录")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT username, is_admin FROM users WHERE username = ?", (username,)
        ).fetchone()
    if not row:
        raise HTTPException(401, "用户不存在")
    return {"username": row["username"], "is_admin": bool(row["is_admin"])}


class LinkIn(BaseModel):
    url: str
    title: str = ""
    description: str = ""
    category: Optional[str] = None
    sharer: Optional[str] = None
    tags: List[str] = []
    note: str = ""
    is_read: bool = False


class LinkPatch(BaseModel):
    url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    sharer: Optional[str] = None
    tags: Optional[List[str]] = None
    note: Optional[str] = None
    is_read: Optional[bool] = None


@app.get("/api/guess-category")
def api_guess_category(url: str):
    return {"category": guess_category(url), "categories": CATEGORIES}


@app.get("/api/fetch-meta")
def api_fetch_meta(url: str):
    """抓取网页 <title> 和 <meta description>，并返回猜测分类。失败时 title/description 为空。"""
    meta = fetch_meta(url)
    return {
        "title": meta["title"],
        "description": meta["description"],
        "category": guess_category(url),
        "ok": meta["ok"],
        "error": meta["error"],
    }


@app.get("/api/categories")
def api_categories():
    return {"categories": CATEGORIES}


@app.get("/api/links")
def api_list_links(
    q: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    sharer: Optional[str] = None,
    is_read: Optional[bool] = None,
):
    with get_conn() as conn:
        return {"links": fetch_links(conn, q, category, tag, sharer, is_read)}


@app.get("/api/links/{link_id}")
def api_get_link(link_id: int):
    with get_conn() as conn:
        link = fetch_link_with_relations(conn, link_id)
    if not link:
        raise HTTPException(404, "链接不存在")
    return link


def _actor(request: Request, x_user_name: Optional[str] = None) -> str:
    """记录"由谁操作"。优先用登录用户名（可信），无则退回前端传的显示名。"""
    user = _current_user(request)
    if user:
        return user[:32]
    if x_user_name:
        # HTTP 头里中文需要 URL 编码，前端传过来后这里解码
        import urllib.parse
        return urllib.parse.unquote(x_user_name).strip()[:32]
    return ""


@app.post("/api/links")
def api_create_link(payload: LinkIn, request: Request, x_user_name: Optional[str] = Header(default=None)):
    if not payload.url.strip():
        raise HTTPException(400, "URL 不能为空")
    actor = _actor(request, x_user_name)
    category = payload.category or guess_category(payload.url)
    with get_conn() as conn:
        sharer_id = upsert_sharer(conn, payload.sharer)
        cur = conn.execute(
            """
            INSERT INTO links (url, title, description, category, sharer_id, is_read, note, added_by, updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """,
            (
                payload.url.strip(),
                payload.title.strip(),
                payload.description.strip(),
                category,
                sharer_id,
                1 if payload.is_read else 0,
                payload.note.strip(),
                actor,
                actor,
            ),
        )
        link_id = cur.lastrowid
        tag_ids = upsert_tags(conn, payload.tags)
        set_link_tags(conn, link_id, tag_ids)
        return fetch_link_with_relations(conn, link_id)


@app.patch("/api/links/{link_id}")
def api_update_link(link_id: int, payload: LinkPatch, request: Request, x_user_name: Optional[str] = Header(default=None)):
    actor = _actor(request, x_user_name)
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM links WHERE id = ?", (link_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "链接不存在")

        fields, params = [], []
        if payload.url is not None:
            fields.append("url = ?")
            params.append(payload.url.strip())
        if payload.title is not None:
            fields.append("title = ?")
            params.append(payload.title.strip())
        if payload.description is not None:
            fields.append("description = ?")
            params.append(payload.description.strip())
        if payload.category is not None:
            fields.append("category = ?")
            params.append(payload.category)
        if payload.note is not None:
            fields.append("note = ?")
            params.append(payload.note.strip())
        if payload.is_read is not None:
            fields.append("is_read = ?")
            params.append(1 if payload.is_read else 0)
        if payload.sharer is not None:
            sharer_id = upsert_sharer(conn, payload.sharer)
            fields.append("sharer_id = ?")
            params.append(sharer_id)

        # 总是更新 updated_by / updated_at
        fields.append("updated_by = ?")
        params.append(actor)
        fields.append("updated_at = datetime('now', 'localtime')")

        if fields:
            params.append(link_id)
            conn.execute(f"UPDATE links SET {', '.join(fields)} WHERE id = ?", params)

        if payload.tags is not None:
            tag_ids = upsert_tags(conn, payload.tags)
            set_link_tags(conn, link_id, tag_ids)

        return fetch_link_with_relations(conn, link_id)


@app.delete("/api/links/{link_id}")
def api_delete_link(link_id: int):
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "链接不存在")
    return {"ok": True}


@app.post("/api/links/{link_id}/click")
def api_record_click(link_id: int, request: Request, x_user_name: Optional[str] = Header(default=None)):
    """记录一次点击，更新累计次数和最近打开时间。前端不必等待。"""
    actor = _actor(request, x_user_name)
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM links WHERE id = ?", (link_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "链接不存在")
        conn.execute(
            "UPDATE links SET click_count = click_count + 1, "
            "last_opened_at = datetime('now', 'localtime') WHERE id = ?",
            (link_id,),
        )
        conn.execute(
            "INSERT INTO link_clicks (link_id, clicked_by) VALUES (?, ?)",
            (link_id, actor),
        )
    return {"ok": True}


@app.get("/api/sharers")
def api_list_sharers():
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.name, COUNT(l.id) AS link_count
            FROM sharers s
            LEFT JOIN links l ON l.sharer_id = s.id
            GROUP BY s.id, s.name
            ORDER BY link_count DESC, s.name
            """
        ).fetchall()
    return {"sharers": [dict(r) for r in rows]}


@app.get("/api/tags")
def api_list_tags():
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT t.name, COUNT(lt.link_id) AS link_count
            FROM tags t
            LEFT JOIN link_tags lt ON lt.tag_id = t.id
            GROUP BY t.id, t.name
            ORDER BY link_count DESC, t.name
            """
        ).fetchall()
    return {"tags": [dict(r) for r in rows]}


@app.get("/api/stats")
def api_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM links").fetchone()["c"]
        week_new = conn.execute(
            "SELECT COUNT(*) AS c FROM links "
            "WHERE created_at >= datetime('now', '-7 days', 'localtime')"
        ).fetchone()["c"]
        # 本周点击总次数（团队活跃度）
        week_clicks = conn.execute(
            "SELECT COUNT(*) AS c FROM link_clicks "
            "WHERE clicked_at >= datetime('now', '-7 days', 'localtime')"
        ).fetchone()["c"]
        by_category = [
            dict(r)
            for r in conn.execute(
                "SELECT category, COUNT(*) AS count FROM links "
                "GROUP BY category ORDER BY count DESC"
            ).fetchall()
        ]
        recent_rows = conn.execute(
            "SELECT id FROM links ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        recent = [fetch_link_with_relations(conn, r["id"]) for r in recent_rows]
        top_sharers = [
            dict(r)
            for r in conn.execute(
                """
                SELECT s.name, COUNT(l.id) AS link_count
                FROM sharers s
                JOIN links l ON l.sharer_id = s.id
                GROUP BY s.id, s.name
                ORDER BY link_count DESC
                LIMIT 5
                """
            ).fetchall()
        ]
        # 🔥 高频：点击数最多 Top 5（点击数 > 0）
        top_clicked_rows = conn.execute(
            "SELECT id FROM links WHERE click_count > 0 "
            "ORDER BY click_count DESC, last_opened_at DESC LIMIT 5"
        ).fetchall()
        top_clicked = [fetch_link_with_relations(conn, r["id"]) for r in top_clicked_rows]

        # ❄️ 冷门候选：从未点击 + 加入 ≥ 30 天，按"加入越久越靠前"
        cold_rows = conn.execute(
            "SELECT id FROM links WHERE click_count = 0 "
            "AND created_at <= datetime('now', '-30 days', 'localtime') "
            "ORDER BY created_at ASC LIMIT 5"
        ).fetchall()
        cold_links = [fetch_link_with_relations(conn, r["id"]) for r in cold_rows]

    return {
        "total": total,
        "week_clicks": week_clicks,
        "week_new": week_new,
        "by_category": by_category,
        "recent": recent,
        "top_sharers": top_sharers,
        "top_clicked": top_clicked,
        "cold_links": cold_links,
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    # 端口：线上平台（Railway）通过 $PORT 注入；本地默认 8000
    # 监听 0.0.0.0 让同一局域网的同事也能访问（同事浏览器打开 http://你的IP:8000）
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
