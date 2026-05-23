from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from pathlib import Path
from contextlib import contextmanager

# 数据目录：本地默认 ./data；线上部署时设 DATA_DIR 环境变量指向持久磁盘（如 /data）
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
DB_PATH = DATA_DIR / "links.db"


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS sharers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '其他',
                sharer_id INTEGER,
                is_read INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (sharer_id) REFERENCES sharers(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS link_tags (
                link_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,
                PRIMARY KEY (link_id, tag_id),
                FOREIGN KEY (link_id) REFERENCES links(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS link_clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link_id INTEGER NOT NULL,
                clicked_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                clicked_by TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (link_id) REFERENCES links(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_links_created_at ON links(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_links_category ON links(category);
            CREATE INDEX IF NOT EXISTS idx_links_sharer ON links(sharer_id);
            CREATE INDEX IF NOT EXISTS idx_clicks_link ON link_clicks(link_id);
            CREATE INDEX IF NOT EXISTS idx_clicks_time ON link_clicks(clicked_at DESC);
            """
        )
        # 增量迁移：旧库可能没有这些字段
        existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(links)").fetchall()}
        if "added_by" not in existing_cols:
            conn.execute("ALTER TABLE links ADD COLUMN added_by TEXT NOT NULL DEFAULT ''")
        if "updated_by" not in existing_cols:
            conn.execute("ALTER TABLE links ADD COLUMN updated_by TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in existing_cols:
            conn.execute("ALTER TABLE links ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
        if "click_count" not in existing_cols:
            conn.execute("ALTER TABLE links ADD COLUMN click_count INTEGER NOT NULL DEFAULT 0")
        if "last_opened_at" not in existing_cols:
            conn.execute("ALTER TABLE links ADD COLUMN last_opened_at TEXT NOT NULL DEFAULT ''")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
    """创建用户。用户名重复会抛 sqlite3.IntegrityError，由调用方处理。"""
    username = username.strip()
    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, salt, is_admin) VALUES (?, ?, ?, ?)",
        (username, pwd_hash, salt, 1 if is_admin else 0),
    )
    return {"id": cur.lastrowid, "username": username, "is_admin": is_admin}


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
    cur = conn.execute("INSERT INTO sharers (name) VALUES (?)", (name,))
    return cur.lastrowid


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
            cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            ids.append(cur.lastrowid)
    return ids


def set_link_tags(conn, link_id: int, tag_ids: list[int]):
    conn.execute("DELETE FROM link_tags WHERE link_id = ?", (link_id,))
    for tid in tag_ids:
        conn.execute(
            "INSERT OR IGNORE INTO link_tags (link_id, tag_id) VALUES (?, ?)",
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
        "SELECT DISTINCT l.id FROM links l",
        "LEFT JOIN sharers s ON s.id = l.sharer_id",
        "LEFT JOIN link_tags lt ON lt.link_id = l.id",
        "LEFT JOIN tags t ON t.id = lt.tag_id",
        "WHERE 1=1",
    ]
    params: list = []
    if q:
        sql.append(
            "AND (l.url LIKE ? OR l.title LIKE ? OR l.description LIKE ? "
            "OR s.name LIKE ? OR t.name LIKE ? OR l.note LIKE ?)"
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
        params.append(1 if is_read else 0)
    sql.append("ORDER BY l.created_at DESC")

    ids = [r["id"] for r in conn.execute(" ".join(sql), params).fetchall()]
    return [fetch_link_with_relations(conn, i) for i in ids]
