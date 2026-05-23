from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

# ============================================================
# 数据库：PostgreSQL（线上 Neon / 本地也可连同一个 Neon 库）
# 连接串从环境变量 DATABASE_URL 读，形如：
#   postgresql://user:pass@host/dbname?sslmode=require
# ============================================================
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


class _CursorWrapper:
    """包一层游标，让旧的 SQLite 风格调用尽量不改就能用：
    - 把 SQL 里的 `?` 占位符自动换成 psycopg 的 `%s`
    - execute() 返回 self，支持链式 .fetchone() / .fetchall()
    - 行是 dict（dict_row），所以 row["col"] 照常工作
    - lastrowid：靠调用方在 INSERT 时自己写 RETURNING id（见下方说明）
    """

    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None

    def execute(self, sql: str, params=None):
        sql = sql.replace("?", "%s")
        self._cur.execute(sql, params or ())
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount


class _ConnWrapper:
    """包一层连接，提供 .execute() 直达游标（兼容旧代码 conn.execute(...)）。"""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=None):
        cur = _CursorWrapper(self._conn.cursor())
        return cur.execute(sql, params)

    def cursor(self):
        return _CursorWrapper(self._conn.cursor())


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL 环境变量未设置。本地开发请先 export DATABASE_URL=...（你的 Neon 连接串）"
        )
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
    try:
        yield _ConnWrapper(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        # PostgreSQL 建表：SERIAL 自增、BOOLEAN、timestamptz 默认 now()
        statements = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sharers (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS links (
                id SERIAL PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '其他',
                sharer_id INTEGER REFERENCES sharers(id) ON DELETE SET NULL,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                note TEXT NOT NULL DEFAULT '',
                added_by TEXT NOT NULL DEFAULT '',
                updated_by TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ,
                click_count INTEGER NOT NULL DEFAULT 0,
                last_opened_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS tags (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS link_tags (
                link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
                tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (link_id, tag_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS link_clicks (
                id SERIAL PRIMARY KEY,
                link_id INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
                clicked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                clicked_by TEXT NOT NULL DEFAULT ''
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_links_created_at ON links(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_links_category ON links(category)",
            "CREATE INDEX IF NOT EXISTS idx_links_sharer ON links(sharer_id)",
            "CREATE INDEX IF NOT EXISTS idx_clicks_link ON link_clicks(link_id)",
            "CREATE INDEX IF NOT EXISTS idx_clicks_time ON link_clicks(clicked_at DESC)",
        ]
        for sql in statements:
            conn.execute(sql)


# ============================================================
# 用户账号（多账号登录用）
# 密码用 PBKDF2-HMAC-SHA256 加盐哈希，绝不存明文。纯标准库，无额外依赖。
# ============================================================

def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000
    )
    return dk.hex()


def count_users(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def get_user(conn, username: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM users WHERE username = ?", (username.strip(),)
    ).fetchone()
    return dict(row) if row else None


def create_user(conn, username: str, password: str, is_admin: bool = False) -> dict:
    """创建用户。用户名重复会抛 psycopg.errors.UniqueViolation，由调用方处理。"""
    username = username.strip()
    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    row = conn.execute(
        "INSERT INTO users (username, password_hash, salt, is_admin) "
        "VALUES (?, ?, ?, ?) RETURNING id",
        (username, pwd_hash, salt, is_admin),
    ).fetchone()
    return {"id": row["id"], "username": username, "is_admin": is_admin}


def update_password(conn, username: str, new_password: str) -> bool:
    """修改用户密码，重新生成 salt。成功返回 True。"""
    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(new_password, salt)
    cur = conn.execute(
        "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
        (pwd_hash, salt, username.strip()),
    )
    return cur.rowcount > 0


def verify_user(conn, username: str, password: str) -> dict | None:
    """校验用户名+密码，成功返回用户信息，失败返回 None。用恒定时间比较防时序攻击。"""
    user = get_user(conn, username)
    if not user:
        return None
    expected = user["password_hash"]
    actual = _hash_password(password, user["salt"])
    if not secrets.compare_digest(expected, actual):
        return None
    return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"])}


def upsert_sharer(conn, name: str | None) -> int | None:
    if not name or not name.strip():
        return None
    name = name.strip()
    row = conn.execute("SELECT id FROM sharers WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "INSERT INTO sharers (name) VALUES (?) RETURNING id", (name,)
    ).fetchone()
    return row["id"]


def upsert_tags(conn, tag_names: list[str]) -> list[int]:
    ids = []
    for raw in tag_names:
        name = (raw or "").strip()
        if not name:
            continue
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            ids.append(row["id"])
        else:
            row = conn.execute(
                "INSERT INTO tags (name) VALUES (?) RETURNING id", (name,)
            ).fetchone()
            ids.append(row["id"])
    return ids


def set_link_tags(conn, link_id: int, tag_ids: list[int]):
    conn.execute("DELETE FROM link_tags WHERE link_id = ?", (link_id,))
    for tid in tag_ids:
        conn.execute(
            "INSERT INTO link_tags (link_id, tag_id) VALUES (?, ?) "
            "ON CONFLICT DO NOTHING",
            (link_id, tid),
        )


def fetch_link_with_relations(conn, link_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT l.*, s.name AS sharer_name
        FROM links l
        LEFT JOIN sharers s ON s.id = l.sharer_id
        WHERE l.id = ?
        """,
        (link_id,),
    ).fetchone()
    if not row:
        return None
    tags = [
        t["name"]
        for t in conn.execute(
            """
            SELECT t.name FROM tags t
            JOIN link_tags lt ON lt.tag_id = t.id
            WHERE lt.link_id = ?
            ORDER BY t.name
            """,
            (link_id,),
        ).fetchall()
    ]
    d = dict(row)
    d["tags"] = tags
    d["is_read"] = bool(d["is_read"])
    # 时间字段统一转成字符串，前端按字符串展示（保持和旧 SQLite 行为一致）
    for k in ("created_at", "updated_at", "last_opened_at"):
        if d.get(k) is not None and not isinstance(d[k], str):
            d[k] = d[k].isoformat(sep=" ", timespec="seconds")
        elif d.get(k) is None:
            d[k] = ""
    return d


def fetch_links(
    conn,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    sharer: str | None = None,
    is_read: bool | None = None,
) -> list[dict]:
    sql = [
        "SELECT DISTINCT l.id, l.created_at FROM links l",
        "LEFT JOIN sharers s ON s.id = l.sharer_id",
        "LEFT JOIN link_tags lt ON lt.link_id = l.id",
        "LEFT JOIN tags t ON t.id = lt.tag_id",
        "WHERE 1=1",
    ]
    params: list = []
    if q:
        sql.append(
            "AND (l.url ILIKE ? OR l.title ILIKE ? OR l.description ILIKE ? "
            "OR s.name ILIKE ? OR t.name ILIKE ? OR l.note ILIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like, like, like])
    if category:
        sql.append("AND l.category = ?")
        params.append(category)
    if sharer:
        sql.append("AND s.name = ?")
        params.append(sharer)
    if tag:
        sql.append(
            "AND l.id IN (SELECT lt2.link_id FROM link_tags lt2 "
            "JOIN tags t2 ON t2.id = lt2.tag_id WHERE t2.name = ?)"
        )
        params.append(tag)
    if is_read is not None:
        sql.append("AND l.is_read = ?")
        params.append(is_read)
    sql.append("ORDER BY l.created_at DESC")

    ids = [r["id"] for r in conn.execute(" ".join(sql), params).fetchall()]
    return [fetch_link_with_relations(conn, i) for i in ids]
