# init_db.py —— SQLite 建表/补列脚本
import os
import sqlite3
from contextlib import closing

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 没有 python-dotenv 也能正常跑

# 默认 SQLite 数据库
DB_URL = os.getenv("DATABASE_URL", "sqlite:///instance/logistics.db")

def get_sqlite_path(db_url: str) -> str:
    """解析 sqlite:///xxx.db 到实际路径"""
    if db_url.startswith("sqlite:///"):
        return db_url.replace("sqlite:///", "", 1)
    if db_url.startswith("sqlite:////"):
        return "/" + db_url.replace("sqlite:////", "", 1)
    raise SystemExit("❌ 本脚本只支持 SQLite（sqlite:///xxx.db）")

def column_exists(conn, table, col) -> bool:
    with closing(conn.cursor()) as cur:
        cur.execute(f"PRAGMA table_info('{table}')")
        cols = [r[1] for r in cur.fetchall()]
    return col in cols

def ensure_tables_with_sqlalchemy():
    """用 SQLAlchemy 元数据创建缺失表（不会改已有结构）"""
    from app import app, db
    with app.app_context():
        db.create_all()
    print("√ 已检查并创建缺失表（不修改已有结构）")

def main():
    if not DB_URL.startswith("sqlite:"):
        raise SystemExit("❌ 当前 DATABASE_URL 不是 sqlite，退出。")

    db_path = get_sqlite_path(DB_URL)
    dir_path = os.path.dirname(db_path)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)

    # Step 1: 确保表存在
    ensure_tables_with_sqlalchemy()

    # Step 2: SQLite 原生补列
    with closing(sqlite3.connect(db_path)) as conn:
        conn.isolation_level = None  # autocommit

        patches = {
            "carrier_agent": [
                ("app_key", "TEXT"),
                ("app_token", "TEXT"),
                ("customer_code", "TEXT"),
            ],
            # 你以后要补新列就在这里加
            # "shipment": [("extra_field", "TEXT")],
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