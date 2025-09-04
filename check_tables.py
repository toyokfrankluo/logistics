# check_tables.py
import sqlite3
import os
from app import app
from pathlib import Path

def get_sqlite_path(uri):
    if not uri:
        return None
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "", 1)
    if uri.startswith("sqlite:////"):
        return "/" + uri.replace("sqlite:////", "", 1)
    return None

def table_columns(conn, table):
    cur = conn.execute(f"PRAGMA table_info('{table}')")
    return [r[1] for r in cur.fetchall()]

def main():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    db_path = get_sqlite_path(uri)
    if not db_path:
        print("当前 DATABASE_URI 不是 sqlite（或未设置），脚本仅支持 sqlite。")
        return
    db_file = Path(db_path)
    print("sqlite db file:", db_file.resolve())
    if not db_file.exists():
        print("数据库文件不存在（还未创建）。请先运行应用一次或使用 create_tables.py 创建。")
        return

    conn = sqlite3.connect(str(db_file))
    tables_needed = {
        "carrier_agent": ["id","name","api_url","username","password","app_key","app_token","customer_code"],
        "shipment": ["id","tracking_number","customer_id","agent_id","carrier_id","origin","destination",
                     "channel","product_type","pieces","weight","unit_price","fee",
                     "surcharge_extra","operation_fee","high_value_fee","status","note","created_at","updated_at"],
        "customer": ["id","name","bank_info"],
        "user": ["id","username","password_hash","is_admin"],
        "order_info": ["id","order_no","shipment_id","created_at"]
    }

    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing = {r[0] for r in cur.fetchall()}
    for t, cols in tables_needed.items():
        print("Table:", t, "=> exists:" , ("YES" if t in existing else "NO"))
        if t in existing:
            present = table_columns(conn, t)
            missing = [c for c in cols if c not in present]
            if missing:
                print("  Missing columns:", missing)
            else:
                print("  All expected columns present.")
        else:
            print("  Table missing entirely.")
    conn.close()

if __name__ == "__main__":
    with app.app_context():
        main()