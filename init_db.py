import sqlite3

DB_FILE = "logistics.db"
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()

# 货代表
c.execute('''
CREATE TABLE IF NOT EXISTS carriers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    type TEXT,
    login_url TEXT,
    track_url TEXT,
    api_user TEXT,
    api_pass TEXT,
    api_key TEXT
)
''')

# 订单表
c.execute('''
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT,
    carrier_id INTEGER,
    last_status TEXT,
    updated_at TEXT,
    FOREIGN KEY(carrier_id) REFERENCES carriers(id)
)
''')

conn.commit()
conn.close()
print("数据库初始化完成 ✅")