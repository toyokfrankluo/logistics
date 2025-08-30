import tkinter as tk
from tkinter import messagebox
import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime

DB_FILE = "logistics.db"

# ---- 数据库初始化 ----
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
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
    c.execute('''
    CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        carrier_id INTEGER,
        last_status TEXT,
        updated_at TEXT,
        FOREIGN KEY(carrier_id) REFERENCES carriers(id)
    )
    ''')
    conn.commit()
    conn.close()

# 程序启动时确保数据库表存在
init_db()

DB_FILE = "logistics.db"

# ---- 数据库操作 ----
def save_carrier(name, carrier_type, login_url, track_url, api_user, api_pass, api_key):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO carriers(name,type,login_url,track_url,api_user,api_pass,api_key)
        VALUES(?,?,?,?,?,?,?)
    ''',(name, carrier_type, login_url, track_url, api_user, api_pass, api_key))
    conn.commit()
    conn.close()

def save_order(order_id, carrier_id, last_status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute('''
        INSERT INTO orders(order_id, carrier_id, last_status, updated_at)
        VALUES(?,?,?,?)
        ON CONFLICT(order_id) DO UPDATE SET
            carrier_id=excluded.carrier_id,
            last_status=excluded.last_status,
            updated_at=excluded.updated_at
    ''',(order_id, carrier_id, last_status, now))
    conn.commit()
    conn.close()

def get_carriers():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, name FROM carriers")
    data = c.fetchall()
    conn.close()
    return data

# ---- 抓取方法 ----
def fetch_tracking(order_id, carrier_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT type, login_url, track_url, api_user, api_pass, api_key FROM carriers WHERE id=?",(carrier_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return "货代信息不存在"
    carrier_type, login_url, track_url, api_user, api_pass, api_key = row

    try:
        if carrier_type=="api":
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            auth = (api_user, api_pass) if api_user and api_pass else None
            url = track_url.format(order_id)
            r = requests.get(url, headers=headers, auth=auth)
            if r.status_code==200:
                return r.text
            else:
                return f"API抓取失败，状态码{r.status_code}"
        else:
            session = requests.Session()
            session.post(login_url, data={"username": api_user,"password": api_pass})
            r = session.get(track_url.format(order_id))
            soup = BeautifulSoup(r.text,"html.parser")
            status_div = soup.find("div", class_="status")
            return status_div.text.strip() if status_div else "抓取失败"
    except Exception as e:
        return str(e)

# ---- GUI ----
root = tk.Tk()
root.title("物流管理软件")

# 货代录入
tk.Label(root, text="货代名称").pack()
entry_name = tk.Entry(root); entry_name.pack()
var_type = tk.StringVar(value="api")
tk.Radiobutton(root, text="API型", variable=var_type, value="api").pack()
tk.Radiobutton(root, text="网页抓取型", variable=var_type, value="web").pack()
tk.Label(root, text="登录网址").pack()
entry_login = tk.Entry(root); entry_login.pack()
tk.Label(root, text="抓取网址").pack()
entry_track = tk.Entry(root); entry_track.pack()
tk.Label(root, text="账号").pack()
entry_user = tk.Entry(root); entry_user.pack()
tk.Label(root, text="密码").pack()
entry_pass = tk.Entry(root, show="*"); entry_pass.pack()
tk.Label(root, text="API Key").pack()
entry_key = tk.Entry(root); entry_key.pack()

def add_carrier_gui():
    save_carrier(entry_name.get(), var_type.get(), entry_login.get(), entry_track.get(),
                 entry_user.get(), entry_pass.get(), entry_key.get())
    messagebox.showinfo("提示","货代保存成功")
tk.Button(root, text="保存货代", command=add_carrier_gui).pack()

# 订单录入
tk.Label(root, text="订单号").pack()
entry_order = tk.Entry(root); entry_order.pack()
carrier_list = tk.Listbox(root)
carrier_list.pack()
for c in get_carriers():
    carrier_list.insert(tk.END, f"{c[0]}:{c[1]}")

def add_order_gui():
    sel = carrier_list.curselection()
    if not sel:
        messagebox.showwarning("提示","请选择货代")
        return
    carrier_id = int(carrier_list.get(sel[0]).split(":")[0])
    order_id = entry_order.get()
    status = fetch_tracking(order_id, carrier_id)
    save_order(order_id, carrier_id, status)
    messagebox.showinfo("提示",f"订单已保存，抓取结果：\n{status}")

tk.Button(root, text="添加订单并抓取轨迹", command=add_order_gui).pack()

root.mainloop()