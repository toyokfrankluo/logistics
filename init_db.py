# init_db.py —— 一次性补列 & 建表脚本（适用于 SQLite）
import os
import sqlite3
from contextlib import closing

DB_URL = os.getenv("DATABASE_URL", "sqlite:///logistics.db")

def get_sqlite_path(db_url: str) -> str:
    # 支持 sqlite:///xxx.db 或 sqlite:////absolute/path.db
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "", 1)
    if db_url.startswith("sqlite:////"):
        return "/" + db_url.replace("sqlite:////", "", 1)
    # 其他驱动不处理
    raise SystemExit("本脚本只支持 SQLite（sqlite:///xxx.db）")

def column_exists(conn, table, col) -> bool:
    with closing(conn.cursor()) as cur:
        cur.execute(f"PRAGMA table_info('{table}')")
        cols = [r[1] for r in cur.fetchall()]
    return col in cols

def ensure_tables_with_sqlalchemy():
    """
    用 SQLAlchemy 的 metadata 创建缺失的表。
    不会改已有表结构（所以仅用于'建表'）。
    """
    from app import app, db  # 复用你 app.py 里定义的 db
    with app.app_context():
        db.create_all()
    print("√ 已检查并创建缺失表（不修改已有表结构）")

def main():
    if not DB_URL.startswith("sqlite:"):
        raise SystemExit("当前 DATABASE_URL 不是 sqlite，退出。")

    db_path = get_sqlite_path(DB_URL)
    dir_path = os.path.dirname(db_path)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)

    # 先确保表存在（用 SQLAlchemy 创建）
    ensure_tables_with_sqlalchemy()

    # 再用 SQLite 原生补列
    with closing(sqlite3.connect(db_path)) as conn:
        conn.isolation_level = None  # autocommit
        # 需要补列的表和列
        patches = {
            "carrier_agent": [
                ("app_key", "TEXT"),
                ("app_token", "TEXT"),
                ("customer_code", "TEXT"),
            ]
        }
        for table, cols in patches.items():
            for col, typ in cols:
                if not column_exists(conn, table, col):
                    sql = f"ALTER TABLE {table} ADD COLUMN {col} {typ}"
                    try:
                        conn.execute(sql)
                        print(f"√ {table} 添加列 {col} ({typ})")
                    except Exception as e:
                        print(f"! {table} 添加列 {col} 失败：{e}")
                else:
                    print(f"- {table} 已存在列 {col}，跳过")

    print("=== 数据库检查/补列完成 ===")

if __name__ == "__main__":
    main()