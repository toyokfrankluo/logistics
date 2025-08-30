import sqlite3

conn = sqlite3.connect('logistics.db')
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    last_status TEXT,
    updated_at TEXT
)
''')

conn.commit()
conn.close()
print("数据库初始化完成")