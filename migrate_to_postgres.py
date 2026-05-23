"""一次性数据迁移：把本地 SQLite (data/links.db) 的数据搬进 PostgreSQL。

用法：
    export DATABASE_URL="你的 Neon 连接串"
    python3 migrate_to_postgres.py

特点：
  - 保留原始 id（links / sharers / tags 的外键靠 id 关联）
  - 迁完把每张表的自增序列重置到 max(id)+1，避免之后新增主键冲突
  - 幂等保护：目标表非空时会拒绝执行（防止重复导入），加 --force 可清空重来
  - 不迁 users 表（旧库没有；账号到线上用邀请码重新注册）
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SQLITE_PATH = Path(__file__).parent / "data" / "links.db"

# 迁移顺序：先无外键依赖的，再有依赖的
TABLES = ["sharers", "tags", "links", "link_tags", "link_clicks"]

# 各表列（显式写出，避免 SELECT * 顺序问题；带 id 以保留关联）
COLUMNS = {
    "sharers": ["id", "name"],
    "tags": ["id", "name"],
    "links": [
        "id", "url", "title", "description", "category", "sharer_id",
        "is_read", "note", "added_by", "updated_by", "updated_at",
        "click_count", "last_opened_at", "created_at",
    ],
    "link_tags": ["link_id", "tag_id"],
    "link_clicks": ["id", "link_id", "clicked_at", "clicked_by"],
}

# 有自增主键 id 的表，迁完要重置序列
SERIAL_TABLES = ["sharers", "tags", "links", "link_clicks"]

# SQLite 里存 0/1、PG 里是 BOOLEAN 的列
BOOL_COLS = {"links": {"is_read"}}

# SQLite 里可能是空字符串 ''、PG 里是 TIMESTAMPTZ 可空的列：空串要转 None
TS_COLS = {
    "links": {"updated_at", "last_opened_at", "created_at"},
    "link_clicks": {"clicked_at"},
}


def sqlite_rows(scon, table):
    cols = COLUMNS[table]
    # 旧 SQLite 库可能缺某些后加的列；用 PRAGMA 查实际有哪些
    have = {r["name"] for r in scon.execute(f"PRAGMA table_info({table})").fetchall()}
    sel = [c for c in cols if c in have]
    rows = scon.execute(f"SELECT {', '.join(sel)} FROM {table}").fetchall()
    out = []
    for r in rows:
        d = {c: (r[c] if c in have else None) for c in cols}
        # bool 转换
        for bc in BOOL_COLS.get(table, set()):
            d[bc] = bool(d[bc]) if d[bc] is not None else False
        # 时间空串转 None
        for tc in TS_COLS.get(table, set()):
            if d[tc] == "" or d[tc] is None:
                d[tc] = None
        out.append(d)
    return out


def main():
    force = "--force" in sys.argv
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("✗ 请先 export DATABASE_URL=你的Neon连接串")
        sys.exit(1)
    if not SQLITE_PATH.exists():
        print(f"✗ 找不到 SQLite 库：{SQLITE_PATH}")
        sys.exit(1)

    # 确保 PG 表已建好
    import database
    database.init_db()
    print("✓ PostgreSQL 表结构已就绪")

    scon = sqlite3.connect(SQLITE_PATH)
    scon.row_factory = sqlite3.Row

    with psycopg.connect(db_url, row_factory=dict_row) as pcon:
        # 幂等保护：检查目标是否已有数据
        existing = pcon.execute("SELECT COUNT(*) AS c FROM links").fetchone()["c"]
        if existing > 0 and not force:
            print(f"✗ 目标 links 表已有 {existing} 行。如确认要重导，加 --force 清空重来。")
            sys.exit(1)
        if force:
            print("⚠ --force：清空目标表后重导")
            for t in reversed(TABLES):
                pcon.execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE")

        total = {}
        for table in TABLES:
            rows = sqlite_rows(scon, table)
            cols = COLUMNS[table]
            if rows:
                placeholders = ", ".join(["%s"] * len(cols))
                collist = ", ".join(cols)
                sql = f"INSERT INTO {table} ({collist}) VALUES ({placeholders})"
                with pcon.cursor() as cur:
                    cur.executemany(sql, [[r[c] for c in cols] for r in rows])
            total[table] = len(rows)
            print(f"  {table}: 迁入 {len(rows)} 行")

        # 重置自增序列到 max(id)+1
        for table in SERIAL_TABLES:
            pcon.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                f"(SELECT COUNT(*) FROM {table}) > 0)"
            )
        pcon.commit()
        print("✓ 自增序列已重置")

        # 校验：逐表比对行数
        print("\n=== 校验(SQLite → PostgreSQL 行数应一致) ===")
        ok = True
        for table in TABLES:
            pg_count = pcon.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            mark = "✓" if pg_count == total[table] else "✗"
            if pg_count != total[table]:
                ok = False
            print(f"  {mark} {table}: SQLite {total[table]} → PG {pg_count}")
        print("\n✓ 迁移完成，数据一致" if ok else "\n✗ 行数不一致，请检查")

    scon.close()


if __name__ == "__main__":
    main()
