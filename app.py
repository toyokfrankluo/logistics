# app.py — 完整后端（含 5 大需求）
import os
import io
import json
import time
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path
from contextlib import closing
from flask_migrate import Migrate

import requests
from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from werkzeug.security import generate_password_hash, check_password_hash

from flask import (
    Flask, request, render_template, render_template_string,
    redirect, url_for, flash, send_file, abort
)
from flask_cors import CORS


try:
    import pandas as pd
except Exception:
    pd = None

from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from jinja2 import TemplateNotFound

# 使用你提供的 models.py 定义
from models import db, Customer, CarrierAgent, Shipment, ManualTrack, BankAccount

# ------------------------------
# 基本应用与配置
# ------------------------------
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.secret_key = os.getenv("FLASK_SECRET", "change-this-secret-for-dev")

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

from views import views
app.register_blueprint(views)

app.config["JSON_AS_ASCII"] = False
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///logistics.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
migrate = Migrate(app, db)

# 登录
login_manager = LoginManager(app)
login_manager.login_view = "login"

# 管理后台
admin = Admin(app, name="后台管理", template_mode="bootstrap4")

# 环境配置
DEFAULT_API_URL = os.getenv("API_URL", "http://ywsl.rtb56.com/webservice/PublicService.asmx/ServiceInterfaceUTF8")
CARRIERS_LIST = [c.strip() for c in os.getenv("CARRIERS", "rtb56").split(",") if c.strip()]
CARRIERS = {}
for cid in CARRIERS_LIST:
    key_prefix = cid.upper()
    CARRIERS[cid] = {
        "id": cid,
        "name": os.getenv(f"{key_prefix}_NAME", cid),
        "token": os.getenv(f"{key_prefix}_TOKEN"),
        "key": os.getenv(f"{key_prefix}_KEY"),
        "api_url": os.getenv(f"{key_prefix}_API_URL", DEFAULT_API_URL)
    }

PUBLIC_MODE = os.getenv("PUBLIC_MODE", "0") == "1"  # 公共查询页屏蔽批量

# 简单缓存
CACHE = {}
CACHE_TTL = int(os.getenv("CACHE_TTL", "600"))

# 17Track API配置
TRACK17_API_KEY = os.getenv("TRACK17_API_KEY", "")
TRACK17_API_URL = os.getenv("TRACK17_API_URL", "https://api.17track.net/track/v2/gettrackinfo")

# ------------------------------
# 工具：sqlite 文件路径
# ------------------------------
def get_sqlite_path_from_uri(uri: str):
    if not uri:
        return None
    uri = uri.strip()
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "", 1)
    if uri.startswith("sqlite:////"):
        return "/" + uri.replace("sqlite:////", "", 1)
    return None

# ------------------------------
# 用户模型（仅后端使用）
# ------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

# Admin
admin.add_view(ModelView(User, db.session))
admin.add_view(ModelView(Customer, db.session))
admin.add_view(ModelView(CarrierAgent, db.session))
admin.add_view(ModelView(Shipment, db.session))
admin.add_view(ModelView(ManualTrack, db.session))
admin.add_view(ModelView(BankAccount, db.session))

# ------------------------------
# 登录回调
# ------------------------------
@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

# ------------------------------
# 模板安全渲染
# ------------------------------
def render_template_safe(template_name, **context):
    try:
        return render_template(template_name, **context)
    except TemplateNotFound:
        fallback = f"""
        <!doctype html>
        <html>
        <head><meta charset="utf-8"><title>{template_name} - 占位</title></head>
        <body style="font-family: -apple-system, Arial;">
        <h2>缺少页面模板：{template_name}</h2>
        <p>请在 <code>templates/</code> 目录中添加 <strong>{template_name}</strong> 模板文件。</p>
        <pre>渲染数据（调试用）:</pre>
        <div style="white-space:pre-wrap;border:1px solid #ddd;padding:10px;">{context}</div>
        <p><a href="{url_for('index')}">返回首页</a></p>
        </body>
        </html>
        """
        return render_template_string(fallback)

# ------------------------------
# 启动时自动补列（SQLite）
# ------------------------------
def ensure_sqlite_columns():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    sqlite_path = get_sqlite_path_from_uri(uri)
    if not sqlite_path:
        app.logger.info("非 SQLite，跳过自动补列。")
        return

    db_file = Path(sqlite_path)
    if not db_file.exists():
        app.logger.info(f"SQLite {sqlite_path} 不存在，create_all 已创建。")
        return

    app.logger.info(f"开始检查并补列 SQLite 数据库: {sqlite_path}")
    try:
        with closing(sqlite3.connect(str(db_file))) as conn:
            cur = conn.cursor()

            def table_has_col(table, col):
                cur.execute(f"PRAGMA table_info('{table}')")
                rows = cur.fetchall()
                cols = [r[1] for r in rows]
                return col in cols

            patches = {
                "carrier_agent": [
                    ("api_url", "TEXT"), ("username", "TEXT"), ("password", "TEXT"),
                    ("app_key", "TEXT"), ("app_token", "TEXT"), ("customer_code", "TEXT"),
                    ("supports_api", "INTEGER DEFAULT 1"), ("is_active", "INTEGER DEFAULT 1")
                ],
                "shipment": [
                    ("customer_id", "INTEGER"), ("agent_id", "INTEGER"), ("carrier_id", "TEXT"),
                    ("origin", "TEXT"), ("destination", "TEXT"), ("channel", "TEXT"),
                    ("product_type", "TEXT"), ("pieces", "INTEGER DEFAULT 1"),
                    ("weight", "REAL DEFAULT 0"), ("unit_price", "REAL DEFAULT 0"),
                    ("fee", "REAL DEFAULT 0"), ("surcharge_extra", "REAL DEFAULT 0"),
                    ("operation_fee", "REAL DEFAULT 0"), ("high_value_fee", "REAL DEFAULT 0"),
                    ("status", "TEXT"), ("note", "TEXT"),
                    ("agent_tracking_number", "TEXT"), ("third_party_tracking_number", "TEXT"),
                    ("created_at", "TEXT"), ("updated_at", "TEXT")
                ],
                "manual_track": [
                    ("shipment_id", "INTEGER"), ("happen_time", "TEXT"),
                    ("location", "TEXT"), ("description", "TEXT"), ("author", "TEXT"),
                    ("created_at", "TEXT"), ("updated_at", "TEXT")
                ],
                "bank_account": [
                    ("account_type", "TEXT"), ("bank_name", "TEXT"),
                    ("account_name", "TEXT"), ("account_no", "TEXT"),
                    ("is_default", "INTEGER DEFAULT 0"), ("remark", "TEXT"),
                    ("created_at", "TEXT"), ("updated_at", "TEXT")
                ],
                "customer": [
                    ("bank_info", "TEXT"),
                    ("created_at", "TEXT"), ("updated_at", "TEXT")
                ]
            }

            for table, cols in patches.items():
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                if cur.fetchone() is None:
                    app.logger.info(f"表 {table} 不存在，跳过补列（create_all 已处理）。")
                    continue
                app.logger.info(f"检查表 {table} 的列...")
                for col, typ in cols:
                    if not table_has_col(table, col):
                        sql = f"ALTER TABLE {table} ADD COLUMN {col} {typ}"
                        try:
                            cur.execute(sql)
                            app.logger.info(f"成功为 {table} 添加列 {col} ({typ})")
                        except Exception as e:
                            app.logger.error(f"为 {table} 添加列 {col} 失败: {str(e)}")
                    else:
                        app.logger.debug(f"表 {table} 已存在列 {col}，跳过。")

            conn.commit()
            app.logger.info("补列操作完成。")
    except Exception as e:
        app.logger.exception(f"补列过程中发生全局错误: {str(e)}")

# ------------------------------
# 17Track API 调用函数
# ------------------------------
def call_17track(tracking_number):
    """调用17Track API获取轨迹信息"""
    if not TRACK17_API_KEY:
        return {"error": "17Track API密钥未配置"}
    
    try:
        headers = {
            "Content-Type": "application/json",
            "17token": TRACK17_API_KEY
        }
        
        payload = {
            "number": tracking_number,
            "carrier": None  # 自动识别快递公司
        }
        
        response = requests.post(TRACK17_API_URL, headers=headers, json=payload, timeout=15)
        
        if response.status_code != 200:
            return {"error": f"17Track API返回错误 {response.status_code}"}
            
        data = response.json()
        
        # 检查API响应状态
        if data.get("status") != 200:
            return {"error": f"17Track API错误: {data.get('message', '未知错误')}"}
            
        # 解析轨迹数据
        tracks = []
        if data.get("data") and isinstance(data["data"], list) and len(data["data"]) > 0:
            for event in data["data"][0].get("track", []):
                tracks.append({
                    "track_occur_date": event.get("time", ""),
                    "track_location": event.get("location", ""),
                    "track_description": event.get("description", event.get("info", ""))
                })
        
        return {
            "success": "1",
            "cnmessage": "17Track轨迹查询成功",
            "data": [{"details": tracks}]
        }
        
    except Exception as e:
        return {"error": f"17Track API请求失败: {str(e)}"}

# ------------------------------
# NextSLS API 调用函数（通用版本）
# ------------------------------
def call_nextsls(agent, tracking_number):
    """调用NextSLS API获取轨迹信息（通用版本）"""
    try:
        # 使用代理配置的API URL
        url = agent.api_url
        if not url:
            return {"error": "未配置NextSLS API地址"}
        
        # 根据NextSLS文档构建请求头
        headers = {
            "Content-Type": "application/json"
        }
        
        # 添加认证信息（根据不同代理的配置方式）
        if agent.app_token:
            headers["Authorization"] = f"Bearer {agent.app_token}"
        
        # 构建请求体 - 支持多种查询方式
        payload = {}
        
        # 方式1: 使用客户参考号（client_reference）查询
        payload["shipment"] = {
            "client_reference": tracking_number,
            "language": "zh"
        }
        
        # 方式2: 如果有access_token参数，添加到请求中（某些NextSLS版本需要）
        if agent.app_token and "access_token" not in payload:
            payload["access_token"] = agent.app_token
            
        # 方式3: 某些NextSLS版本可能需要不同的参数结构
        # 这里可以根据代理的具体配置进行调整
        
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        
        if response.status_code != 200:
            return {"error": f"NextSLS API返回错误 {response.status_code}: {response.text}"}
            
        data = response.json()
        
        # 检查API响应状态 - 支持多种响应格式
        if data.get("status") not in [1, "1", 200, "200", True]:
            error_msg = data.get("info") or data.get("message") or data.get("error") or "未知错误"
            return {"error": f"NextSLS API错误: {error_msg}"}
            
        # 解析轨迹数据 - 支持多种响应格式
        tracks = []
        
        # 格式1: data.shipment.traces (标准NextSLS格式)
        if data.get("data") and data["data"].get("shipment"):
            shipment_data = data["data"]["shipment"]
            for trace in shipment_data.get("traces", []):
                # 转换时间戳为日期时间字符串
                timestamp = trace.get("time")
                if timestamp and isinstance(timestamp, int):
                    time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    time_str = trace.get("time", "")
                    
                tracks.append({
                    "track_occur_date": time_str,
                    "track_location": trace.get("location", ""),
                    "track_description": trace.get("info", trace.get("description", ""))
                })
        
        # 格式2: 直接包含tracks数组
        elif data.get("tracks"):
            for trace in data.get("tracks", []):
                tracks.append({
                    "track_occur_date": trace.get("occur_date", trace.get("time", "")),
                    "track_location": trace.get("location", ""),
                    "track_description": trace.get("info", trace.get("description", ""))
                })
        
        # 格式3: 其他可能的格式
        elif data.get("data") and isinstance(data["data"], list):
            for item in data["data"]:
                tracks.append({
                    "track_occur_date": item.get("occur_date", item.get("time", "")),
                    "track_location": item.get("location", ""),
                    "track_description": item.get("info", item.get("description", ""))
                })
        
        # 如果没有找到轨迹数据，返回错误
        if not tracks:
            return {"error": "未找到轨迹信息"}
        
        return {
            "success": "1",
            "cnmessage": "NextSLS轨迹查询成功",
            "data": [{"details": tracks}]
        }
        
    except Exception as e:
        return {"error": f"NextSLS API请求失败: {str(e)}"}

# ------------------------------
# 多货代 API：gettrack（TXFBA 强制 POST 版本）
# ------------------------------
def call_gettrack(carrier_id=None, tracking_number=None, agent_id=None, timeout=15):
    if not tracking_number:
        return {"error": "必须提供 tracking_number"}

    cache_key = (f"agent:{agent_id}" if agent_id else f"carrier:{carrier_id}", tracking_number)
    now = time.time()
    if cache_key in CACHE:
        ts, data = CACHE[cache_key]
        if now - ts < CACHE_TTL:
            return data

    # ------------------------------
    # 本地手工轨迹
    # ------------------------------
    def local_manual():
        s = Shipment.query.filter_by(tracking_number=tracking_number).first()
        if not s or not s.manual_tracks:
            return None
        details = []
        for t in sorted(s.manual_tracks, key=lambda x: (x.happen_time or x.created_at or datetime.utcnow()), reverse=True):
            details.append({
                "track_occur_date": (t.happen_time or t.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                "track_location": t.location or "",
                "track_description": t.description
            })
        return {
            "success": "1",
            "cnmessage": "手工轨迹",
            "data": [{"details": details}]
        }

    # ------------------------------
    # 获取 shipment
    # ------------------------------
    shipment = Shipment.query.filter_by(tracking_number=tracking_number).first()
    if not shipment:
        return {"error": f"未找到运单号: {tracking_number}"}

    shipment_id_to_use = shipment.agent_tracking_number
    if not shipment_id_to_use:
        return {"error": f"未找到对应的 shipment_id（agent_tracking_number）: {tracking_number}"}

    # ------------------------------
    # 使用 DB agent
    # ------------------------------
    if agent_id or shipment.agent_id:
        agent = CarrierAgent.query.get(int(agent_id or shipment.agent_id))
        if not agent or not agent.is_active:
            data = {"error": "未找到指定代理或已停用"}
            CACHE[cache_key] = (now, data)
            return data

        if not agent.supports_api:
            data = local_manual() or {"error": "该代理不支持抓取，且无手工轨迹"}
            CACHE[cache_key] = (now, data)
            return data

        # ----------------
        # NextSLS 逻辑
        # ----------------
        is_nextsls = "nextsls" in (agent.api_url or "").lower() or "sls" in (agent.api_url or "").lower()
        if is_nextsls:
            payload = {
                "shipment": {
                    "shipment_id": shipment_id_to_use,
                    "language": "zh"
                }
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {agent.app_token or API_TOKEN}"
            }
            try:
                r = requests.post(agent.api_url or API_URL, json=payload, headers=headers, timeout=timeout)
                r.encoding = "utf-8"
                data = r.json()
                if data.get("status") != 1:
                    data["hint"] = f"疑似 shipment_id 错误: {shipment_id_to_use}"
                CACHE[cache_key] = (now, data)
                return data
            except Exception as e:
                data = {"error": f"请求代理接口出错: {e}"}
                CACHE[cache_key] = (now, data)
                return data

        # ----------------
        # TXFBA 强制 POST
        # ----------------
        if "txfba.com" in (agent.api_url or "").lower():
            payload = {
                "appToken": agent.app_token or "",
                "appKey": agent.app_key or "",
                "serviceMethod": "gettrack",
                "paramsJson": json.dumps({"tracking_number": tracking_number}, ensure_ascii=False)
            }
            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            # 🔹 调试打印
            print("TXFBA 请求 URL:", agent.api_url)
            print("请求 payload:", payload)
            print("请求 headers:", headers)

            try:
                r = requests.post(agent.api_url, data=payload, headers=headers, timeout=timeout)
                r.encoding = "utf-8"
                try:
                    data = r.json()
                except Exception:
                    data = {"raw_text": r.text}
                if isinstance(data, dict) and data.get("success") == "0" and "appToken" in (data.get("cnmessage") or ""):
                    data["hint"] = "疑似 appKey/appToken 或客户号配置错误，或该代理未开通 API 权限"
                CACHE[cache_key] = (now, data)
                return data
            except Exception as e:
                data = {"error": f"请求代理接口出错: {e}"}
                CACHE[cache_key] = (now, data)
                return data

        # ----------------
        # RTB56 / 其他代理逻辑
        # ----------------
        if agent.app_key or agent.app_token:
            try:
                payload = {
                    "appToken": agent.app_token or "",
                    "appKey": agent.app_key or "",
                    "serviceMethod": "gettrack",
                    "paramsJson": json.dumps({"tracking_number": tracking_number}, ensure_ascii=False)
                }
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                r = requests.post(agent.api_url, data=payload, headers=headers, timeout=timeout)
                r.encoding = "utf-8"
                try:
                    data = r.json()
                except Exception:
                    data = {"raw_text": r.text}
                CACHE[cache_key] = (now, data)
                return data
            except Exception as e:
                data = {"error": f"请求代理接口出错: {e}"}
                CACHE[cache_key] = (now, data)
                return data

        # ----------------
        # 用户名/密码方式
        # ----------------
        try:
            payload = {
                "username": agent.username or "",
                "password": agent.password or "",
                "tracking_number": tracking_number
            }
            r = requests.post(agent.api_url, data=payload, timeout=timeout)
            r.encoding = "utf-8"
            try:
                data = r.json()
            except Exception:
                data = {"raw_text": r.text}
            CACHE[cache_key] = (now, data)
            return data
        except Exception as e:
            data = {"error": f"请求代理接口出错: {e}"}
            CACHE[cache_key] = (now, data)
            return data

    # ----------------
    # 使用环境 carrier
    # ----------------
    carrier = CARRIERS.get(carrier_id) if carrier_id else CARRIERS.get(CARRIERS_LIST[0]) if CARRIERS_LIST else None
    if not carrier:
        data = {"error": "未配置可用的货代（env）"}
        CACHE[cache_key] = (now, data)
        return data

    payload = {
        "appToken": carrier.get("token"),
        "appKey": carrier.get("key"),
        "serviceMethod": "gettrack",
        "paramsJson": json.dumps({"tracking_number": tracking_number}, ensure_ascii=False)
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        r = requests.post(carrier.get("api_url", DEFAULT_API_URL), data=payload, headers=headers, timeout=timeout)
        r.encoding = "utf-8"
        try:
            data = r.json()
        except Exception:
            data = {"raw_text": r.text}
        if isinstance(data, dict) and data.get("success") == "0":
            local = local_manual()
            if local:
                data = local
        CACHE[cache_key] = (now, data)
        return data
    except Exception as e:
        data = local_manual() or {"error": f"请求出错: {e}"}
        CACHE[cache_key] = (now, data)
        return data

# ------------------------------
# 轨迹格式化
# ------------------------------
def format_tracks_from_data(data):
    if not data:
        return "没有返回数据"
    if isinstance(data, dict) and data.get("error"):
        return f"错误: {data.get('error')}"
    if isinstance(data, dict) and "raw_text" in data:
        return data["raw_text"][:10000]
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], list) and data["data"]:
        first = data["data"][0]
        details = first.get("details") or []
        if not details:
            return data.get("cnmessage", "暂无轨迹信息")
        parts = []
        for d in details:
            t = (d.get("track_occur_date") or "").strip()
            loc = (d.get("track_location") or "").strip()
            desc = (d.get("track_description") or d.get("track_description_en") or "").strip()
            line = " — ".join([x for x in [loc, desc] if x])
            parts.append(f"{line}\n{t}".strip())
        return "\n\n".join(parts) if parts else "暂无轨迹信息"
    try:
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        return str(data)

# ------------------------------
# Excel 导出
# ------------------------------
def generate_invoice_xlsx(company_name, customer_name, bank_info, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "账单"

    ws.merge_cells("A1:I1")
    ws["A1"] = company_name

    ws["A3"] = "客户名称:"
    ws["B3"] = customer_name

    headers = ["序号", "日期", "订单号", "服务商单号", "件数", "计费重/KG", "目的地", "运输渠道", "合计费用", "账单摘要"]
    ws.append(headers)

    start_row = ws.max_row + 1
    for idx, r in enumerate(rows, start=1):
        r2 = r + [""] * (9 - len(r))
        ws.append([idx] + r2[:9])

    total = 0.0
    data_start = start_row
    for i in range(len(rows)):
        try:
            cell = ws.cell(row=data_start + i, column=9)
            if cell.value is not None:
                total += float(str(cell.value))
        except Exception:
            pass

    summary_row = data_start + len(rows) + 1
    ws[f"H{summary_row}"] = "合计费用"
    ws[f"I{summary_row}"] = total

    info_row = summary_row + 2
    ws[f"A{info_row}"] = "收款银行信息"
    ws[f"A{info_row+1}"] = bank_info

    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                val = str(cell.value) if cell.value else ""
                if len(val) > max_length:
                    max_length = len(val)
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_length + 2, 60)

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio

# ------------------------------
# 登录/登出
# ------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("请输入用户名与密码")
            return redirect(url_for("login"))
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            flash("用户名或密码错误")
            return redirect(url_for("login"))
        login_user(user)
        flash("登录成功")
        return redirect(url_for("index"))
    try:
        return render_template("login.html")
    except TemplateNotFound:
        return render_template_string("""
        <!doctype html><meta charset="utf-8"><title>登录</title>
        <h2>登录</h2>
        <form method="post">
            用户名: <input name="username"><br><br>
            密码: <input name="password" type="password"><br><br>
            <button type="submit">登录</button>
        </form>
        """)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("已登出")
    return redirect(url_for("login"))

# ------------------------------
# 首页
# ------------------------------
@app.route("/")
@login_required
def index():
    return redirect(url_for("shipments"))

# ------------------------------
# 代理管理：新增 / 列表（兼容你的模板）
# 新增：编辑、软删除
# ------------------------------
@app.route("/agents", methods=["GET", "POST"])
@login_required
def agents():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        api_url = request.form.get("api_url", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        app_key = request.form.get("app_key", "").strip()
        app_token = request.form.get("app_token", "").strip()
        customer_code = request.form.get("customer_code", "").strip()
        if not name:
            flash("代理名称不能为空")
            return redirect(url_for("agents"))
        a = CarrierAgent(
            name=name, api_url=api_url, username=username, password=password,
            app_key=app_key, app_token=app_token, customer_code=customer_code,
            is_active=True
        )
        db.session.add(a)
        db.session.commit()
        flash("代理已保存")
        return redirect(url_for("agents"))
    data = CarrierAgent.query.filter_by(is_active=True).order_by(CarrierAgent.name).all()
    return render_template_safe("agent.html", agents=data)

@app.route("/agents/<int:agent_id>/edit", methods=["GET", "POST"])
@login_required
def edit_agent(agent_id):
    a = CarrierAgent.query.get_or_404(agent_id)
    if not a.is_active:
        flash("该代理已停用")
        return redirect(url_for("agents"))
    if request.method == "POST":
        a.name = request.form.get("name", a.name).strip() or a.name
        a.api_url = request.form.get("api_url", a.api_url).strip()
        a.username = request.form.get("username", a.username).strip()
        a.password = request.form.get("password", a.password).strip()
        a.app_key = request.form.get("app_key", a.app_key).strip()
        a.app_token = request.form.get("app_token", a.app_token).strip()
        a.customer_code = request.form.get("customer_code", a.customer_code).strip()
        a.supports_api = (request.form.get("supports_api", "1") == "1")
        db.session.commit()
        flash("代理已更新")
        return redirect(url_for("agents"))
    # 提供一个简单占位编辑表单（若没有前端模板）
    return render_template_string("""
    <h3>编辑代理</h3>
    <form method="post">
      名称 <input name="name" value="{{a.name}}"><br>
      API  <input name="api_url" value="{{a.api_url or ''}}"><br>
      账号 <input name="username" value="{{a.username or ''}}"><br>
      密码 <input name="password" value="{{a.password or ''}}"><br>
      appKey <input name="app_key" value="{{a.app_key or ''}}"><br>
      appToken <input name="app_token" value="{{a.app_token or ''}}"><br>
      客户号 <input name="customer_code" value="{{a.customer_code or ''}}"><br>
      支持API <select name="supports_api"><option value="1" {% if a.supports_api %}selected{% endif %}>是</option>
      <option value="0" {% if not a.supports_api %}selected{% endif %}>否</option></select><br><br>
      <button>保存</button> <a href="{{url_for('agents')}}">返回</a>
    </form>
    """, a=a)

@app.route("/agents/<int:agent_id>/delete", methods=["POST"])
@login_required
def delete_agent(agent_id):
    a = CarrierAgent.query.get_or_404(agent_id)
    # 软删除：解除运单关联，避免外键错误
    Shipment.query.filter_by(agent_id=a.id).update({"agent_id": None})
    a.is_active = False
    db.session.commit()
    flash("已停用该代理（软删除），并解绑相关运单。")
    return redirect(url_for("agents"))

# ------------------------------
# 运单管理：列表 / 新增 / 导入
# ------------------------------
@app.route("/shipments")
@login_required
def shipments():
    data = Shipment.query.order_by(Shipment.created_at.desc()).all()
    # 兼容你的模板（shipments.html 里直接渲染已有 data）
    return render_template_safe("shipments.html",
                                shipments=data,
                                customers=Customer.query.order_by(Customer.name).all(),
                                agents=CarrierAgent.query.filter_by(is_active=True).order_by(CarrierAgent.name).all(),
                                destinations=["美国", "香港", "中国", "英国", "德国", "其他"])

def _calc_fee(weight, unit_price, surcharge_extra, operation_fee, high_value_fee, manual_fee):
    try:
        w = float(weight or 0)
        p = float(unit_price or 0)
        s1 = float(surcharge_extra or 0)
        s2 = float(operation_fee or 0)
        s3 = float(high_value_fee or 0)
        if manual_fee is not None and str(manual_fee).strip() != "":
            return float(manual_fee)
        return round(w * p + s1 + s2 + s3, 2)
    except Exception:
        return float(manual_fee or 0)

@app.route("/shipments/add", methods=["GET", "POST"])
@login_required
def add_shipment():
    customers = Customer.query.order_by(Customer.name).all()
    agents = CarrierAgent.query.filter_by(is_active=True).order_by(CarrierAgent.name).all()
    carriers = CARRIERS
    destinations = ["美国", "香港", "中国", "英国", "德国", "其他"]
    if request.method == "POST":
        tn = request.form.get("tracking_number", "").strip()
        if not tn:
            flash("请填写运单号")
            return redirect(url_for("add_shipment"))

        # 获取 shipment_id
        shipment_id = request.form.get("shipment_id", "").strip()
        third_party_tracking_number = request.form.get("third_party_tracking_number", "").strip()

        # 可选字段
        customer_id = request.form.get("customer_id") or None
        agent_id = request.form.get("agent_id") or None
        carrier_id = request.form.get("carrier_id") or None
        destination = request.form.get("destination", "").strip()
        channel = request.form.get("channel", "").strip()
        product_type = request.form.get("product_type", "").strip()
        pieces = int(request.form.get("pieces", "1") or 1)

        weight = request.form.get("weight")
        unit_price = request.form.get("unit_price")
        surcharge_extra = request.form.get("surcharge_extra")
        operation_fee = request.form.get("operation_fee")
        high_value_fee = request.form.get("high_value_fee")

        manual_fee = request.form.get("fee")  # 如果你仍在页面上手填合计，这里优先生效
        fee = _calc_fee(weight, unit_price, surcharge_extra, operation_fee, high_value_fee, manual_fee)

        note = request.form.get("note", "")

        s = Shipment(
            tracking_number=tn,
            shipment_id=shipment_id,  # 使用 shipment_id
            third_party_tracking_number=third_party_tracking_number,
            carrier_id=carrier_id,
            agent_id=int(agent_id) if agent_id else None,
            customer_id=int(customer_id) if customer_id else None,
            origin=request.form.get("origin", ""),
            destination=destination,
            channel=channel,
            product_type=product_type,
            pieces=pieces,
            weight=float(weight or 0),
            unit_price=float(unit_price or 0),
            surcharge_extra=float(surcharge_extra or 0),
            operation_fee=float(operation_fee or 0),
            high_value_fee=float(high_value_fee or 0),
            fee=fee,
            note=note,
            status="已录入"
        )
        db.session.add(s)
        db.session.commit()
        flash("运单已保存")
        return redirect(url_for("shipments"))
    return render_template_safe("add_shipment.html",
                                customers=customers, agents=agents, carriers=carriers, destinations=destinations)

@app.route("/shipments/import", methods=["POST"])
@login_required
def import_shipments():
    if pd is None:
        flash("未安装 pandas，无法使用 Excel 导入。请安装 pandas")
        return redirect(url_for("shipments"))
    f = request.files.get("file")
    if not f:
        flash("未上传文件")
        return redirect(url_for("shipments"))
    try:
        df = pd.read_excel(f)
    except Exception as e:
        flash(f"读取 Excel 出错: {e}")
        return redirect(url_for("shipments"))
    count = 0
    for _, row in df.iterrows():
        tn = str(row.get("tracking_number", "")).strip()
        if not tn or Shipment.query.filter_by(tracking_number=tn).first():
            continue
        s = Shipment(
            tracking_number=tn,
            origin=row.get("origin", ""),
            destination=row.get("destination", ""),
            weight=float(row.get("weight") or 0),
            unit_price=float(row.get("unit_price") or 0),
            surcharge_extra=float(row.get("surcharge_extra") or 0),
            operation_fee=float(row.get("operation_fee") or 0),
            high_value_fee=float(row.get("high_value_fee") or 0),
            fee=_calc_fee(row.get("weight"), row.get("unit_price"),
                          row.get("surcharge_extra"), row.get("operation_fee"),
                          row.get("high_value_fee"), row.get("fee")),
            status="已导入"
        )
        db.session.add(s)
        count += 1
    db.session.commit()
    flash(f"共导入 {count} 条运单")
    return redirect(url_for("shipments"))

# 额外：运单编辑/删除（避免误录无法改）
@app.route("/shipments/<int:sid>/edit", methods=["GET", "POST"])
@login_required
def edit_shipment(sid):
    s = Shipment.query.get_or_404(sid)
    if request.method == "POST":
        # 更新新字段
        s.agent_tracking_number = request.form.get("agent_tracking_number", s.agent_tracking_number)
        s.third_party_tracking_number = request.form.get("third_party_tracking_number", s.third_party_tracking_number)
        
        for f in ["destination", "channel", "product_type", "note", "status", "origin"]:
            setattr(s, f, request.form.get(f, getattr(s, f)))
        s.customer_id = int(request.form.get("customer_id")) if request.form.get("customer_id") else s.customer_id
        s.agent_id = int(request.form.get("agent_id")) if request.form.get("agent_id") else s.agent_id
        s.pieces = int(request.form.get("pieces", s.pieces) or s.pieces)
        s.weight = float(request.form.get("weight", s.weight) or s.weight)
        s.unit_price = float(request.form.get("unit_price", s.unit_price) or s.unit_price)
        s.surcharge_extra = float(request.form.get("surcharge_extra", s.surcharge_extra) or s.surcharge_extra)
        s.operation_fee = float(request.form.get("operation_fee", s.operation_fee) or s.operation_fee)
        s.high_value_fee = float(request.form.get("high_value_fee", s.high_value_fee) or s.high_value_fee)
        manual_fee = request.form.get("fee")
        s.fee = _calc_fee(s.weight, s.unit_price, s.surcharge_extra, s.operation_fee, s.high_value_fee, manual_fee)
        db.session.commit()
        flash("运单已更新")
        return redirect(url_for("shipments"))
    return render_template_string("""
    <h3>编辑运单 {{s.tracking_number}}</h3>
    <form method="post">
      代理系统单号 <input name="agent_tracking_number" value="{{s.agent_tracking_number or ''}}"><br>
      17Track单号 <input name="third_party_tracking_number" value="{{s.third_party_tracking_number or ''}}"><br>
      目的地 <input name="destination" value="{{s.destination or ''}}"><br>
      渠道 <input name="channel" value="{{s.channel or ''}}"><br>
      产品类型 <input name="product_type" value="{{s.product_type or ''}}"><br>
      件数 <input name="pieces" value="{{s.pieces or 1}}"><br>
      重量 <input name="weight" value="{{s.weight or 0}}"><br>
      单价 <input name="unit_price" value="{{s.unit_price or 0}}"><br>
      附加费 <input name="surcharge_extra" value="{{s.surcharge_extra or 0}}"><br>
      操作费 <input name="operation_fee" value="{{s.operation_fee or 0}}"><br>
      超值费 <input name="high_value_fee" value="{{s.high_value_fee or 0}}"><br>
      合计(可手填覆盖) <input name="fee" value="{{s.fee or 0}}"><br>
      备注 <input name="note" value="{{s.note or ''}}"><br><br>
      <button>保存</button> <a href="{{url_for('shipments')}}">返回</a>
    </form>
    """, s=s)

@app.route("/shipments/<int:sid>/delete", methods=["POST"])
@login_required
def delete_shipment(sid):
    s = Shipment.query.get_or_404(sid)
    # 允许删除（无外键约束影响其他表）
    ManualTrack.query.filter_by(shipment_id=s.id).delete()
    db.session.delete(s)
    db.session.commit()
    flash("运单已删除")
    return redirect(url_for("shipments"))

# ------------------------------
# 客户管理（兼容原有模板）
# ------------------------------
@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bankinfo = request.form.get("bankinfo", "").strip()
        if not name:
            flash("客户名称不能为空")
            return redirect(url_for("customers"))
        c = Customer(name=name, bank_info=bankinfo)
        db.session.add(c)
        db.session.commit()
        flash("客户已保存")
        return redirect(url_for("customers"))
    data = Customer.query.order_by(Customer.name).all()
    return render_template_safe("customer.html", customers=data)

# ------------------------------
# 财务模块（时间筛选 + 选用收款账户 + 导出）
# ------------------------------
@app.route("/finance", methods=["GET", "POST"])
@login_required
def finance():
    total_shipments = Shipment.query.count()
    total_fees = db.session.query(db.func.sum(Shipment.fee)).scalar() or 0.0

    customers = Customer.query.order_by(Customer.name).all()
    accounts = BankAccount.query.order_by(BankAccount.is_default.desc(), BankAccount.id.desc()).all()

    selected_customer_id = None
    shipments = []
    date_from = None
    date_to = None
    bank_account_id = None

    if request.method == "POST":
        selected_customer_id = request.form.get("customer_id") or None
        date_from_raw = request.form.get("date_from") or ""
        date_to_raw = request.form.get("date_to") or ""
        bank_account_id = request.form.get("bank_account_id") or None

        q = Shipment.query
        if selected_customer_id:
            q = q.filter(Shipment.customer_id == int(selected_customer_id))
        if date_from_raw:
            try:
                date_from = datetime.strptime(date_from_raw + " 00:00:00", "%Y-%m-%d %H:%M:%S")
                q = q.filter(Shipment.created_at >= date_from)
            except Exception:
                pass
        if date_to_raw:
            try:
                date_to = datetime.strptime(date_to_raw + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                q = q.filter(Shipment.created_at <= date_to)
            except Exception:
                pass

        shipments = q.order_by(Shipment.created_at.desc()).all()

        if request.form.get("export") == "1":
            rows = []
            company_name = os.getenv("COMPANY_NAME", "公司名称")
            customer = Customer.query.get(int(selected_customer_id)) if selected_customer_id else None

            # 选中的收款账户文本
            bank_info_text = ""
            if bank_account_id:
                acc = BankAccount.query.get(int(bank_account_id))
                if acc:
                    bank_info_text = f"{'公账' if acc.account_type=='public' else '私人'}\n开户行：{acc.bank_name}\n户名：{acc.account_name}\n账号：{acc.account_no}"
            else:
                # 使用客户默认 bank_info 或默认账户
                if customer and customer.bank_info:
                    bank_info_text = customer.bank_info
                else:
                    acc = BankAccount.query.filter_by(is_default=True).first()
                    if acc:
                        bank_info_text = f"{'公账' if acc.account_type=='public' else '私人'}\n开户行：{acc.bank_name}\n户名：{acc.account_name}\n账号：{acc.account_no}"

            for s in shipments:
                rows.append([
                    s.created_at.strftime("%Y-%m-%d") if s.created_at else "",
                    "", s.tracking_number, "",
                    (s.pieces or 1), (s.weight or 0),
                    s.destination or "", s.channel or "",
                    (s.fee or 0), s.note or ""
                ])
            bio = generate_invoice_xlsx(company_name, customer.name if customer else "客户", bank_info_text or "", rows)
            filename = f"invoice_{customer.name if customer else 'customer'}_{int(time.time())}.xlsx"
            return send_file(bio, as_attachment=True, download_name=filename,
                             mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return render_template_safe("finance.html",
                                total_shipments=total_shipments,
                                total_fees=total_fees,
                                customers=customers,
                                shipments=shipments,
                                selected_customer_id=selected_customer_id,
                                accounts=accounts,
                                bank_account_id=bank_account_id,
                                date_from=date_from.strftime("%Y-%m-%d") if date_from else "",
                                date_to=date_to.strftime("%Y-%m-%d") if date_to else "")

# 简易银行账户管理（占位路由，可在 Admin 里直接维护）
@app.route("/bank_accounts", methods=["GET", "POST"])
@login_required
def bank_accounts():
    if request.method == "POST":
        acc = BankAccount(
            account_type=request.form.get("account_type", "private"),
            bank_name=request.form.get("bank_name", "").strip(),
            account_name=request.form.get("account_name", "").strip(),
            account_no=request.form.get("account_no", "").strip(),
            is_default=(request.form.get("is_default") == "1"),
            remark=request.form.get("remark", "").strip(),
        )
        if acc.is_default:
            BankAccount.query.update({"is_default": False})
        db.session.add(acc)
        db.session.commit()
        flash("已新增收款账户")
        return redirect(url_for("bank_accounts"))
    data = BankAccount.query.order_by(BankAccount.is_default.desc(), BankAccount.id.desc()).all()
    return render_template_string("""
    <h3>收款账户</h3>
    <form method="post">
      类型 <select name="account_type"><option value="private">私人</option><option value="public">公账</option></select><br>
      开户行 <input name="bank_name"><br>
      户名 <input name="account_name"><br>
      账号 <input name="account_no"><br>
      默认 <input type="checkbox" name="is_default" value="1"><br>
      备注 <input name="remark"><br><br>
      <button>新增</button>
    </form>
    <hr>
    <ul>
      {% for a in data %}
      <li>[{{'默认' if a.is_default else ' '}}] {{a.bank_name}} / {{a.account_name}} / {{a.account_no}} ({{'公账' if a.account_type=='public' else '私人'}})</li>
      {% endfor %}
    </ul>
    """, data=data)

# ------------------------------
# 手工轨迹：为不支持抓取的代理/单票添加
# ------------------------------
from datetime import datetime
from flask import request, redirect, url_for, flash, render_template_string, jsonify
from flask_login import login_required, current_user

# 注意：utils.py 如果存在 call_gettrack 等，需确保导入正确
# 假设 utils.py 有这些函数
try:
    from utils import call_gettrack, format_tracks_from_data
except ImportError:
    pass  # 如果没有，忽略或定义

# ------------------------------
# 手工轨迹
# ------------------------------
@app.route("/shipments/<int:sid>/tracks", methods=["GET", "POST"])
@login_required
def manual_tracks(sid):
    s = Shipment.query.get_or_404(sid)
    if request.method == "POST":
        desc = request.form.get("description", "").strip()
        if not desc:
            flash("请输入轨迹描述")
            return redirect(url_for("manual_tracks", sid=sid))
        t = ManualTrack(
            shipment_id=s.id,
            happen_time=datetime.strptime(request.form.get("happen_time"), "%Y-%m-%d %H:%M:%S") if request.form.get("happen_time") else datetime.utcnow(),
            location=request.form.get("location", "").strip(),
            description=desc,
            author=current_user.username if current_user.is_authenticated else None
        )
        db.session.add(t)
        db.session.commit()
        flash("已保存手工轨迹")
        return redirect(url_for("manual_tracks", sid=sid))
    return render_template_string("""
    <h3>手工轨迹 - {{s.tracking_number}}</h3>
    <form method="post">
      时间(YYYY-MM-DD HH:MM:SS) <input name="happen_time"><br>
      地点 <input name="location"><br>
      描述 <textarea name="description" rows="4" cols="60"></textarea><br><br>
      <button>添加</button> <a href="{{url_for('shipments')}}">返回</a>
    </form>
    <hr>
    <pre style="white-space:pre-wrap">
    {% for t in s.manual_tracks|sort(attribute='happen_time', reverse=True) %}
    {{ (t.happen_time or t.created_at).strftime('%Y-%m-%d %H:%M:%S') }}  {{ t.location or '' }}
    {{ t.description }}
    ---------------------------
    {% endfor %}
    </pre>
    """, s=s)

# ------------------------------
# 内部轨迹查询（支持代理/客户）
# ------------------------------
@app.route("/track", methods=["GET", "POST"])
@login_required
def track():
    results = {}
    default_text = ""
    message = ""
    agents = CarrierAgent.query.filter_by(is_active=True).order_by(CarrierAgent.name).all()
    carriers_env = CARRIERS
    if request.method == "POST":
        forced_carrier = request.form.get("carrier_id") or None
        agent_id = request.form.get("agent_id") or None
        customer_id = request.form.get("customer_id") or None
        default_text = request.form.get("numbers", "").strip()

        numbers = []
        if default_text:
            numbers = [ln.strip() for ln in default_text.splitlines() if ln.strip()]

        if not numbers:
            q = Shipment.query
            if agent_id:
                q = q.filter(Shipment.agent_id == int(agent_id))
            if customer_id:
                q = q.filter(Shipment.customer_id == int(customer_id))
            numbers = [s.tracking_number for s in q.order_by(Shipment.created_at.desc()).limit(30).all()]
            if not numbers:
                message = "未找到符合条件的运单。"
        else:
            if len(numbers) > 30:
                message = f"输入 {len(numbers)} 条，本次只处理前 30 条。"
                numbers = numbers[:30]

        for n in numbers:
            shipment = Shipment.query.filter_by(tracking_number=n).first()
            if shipment and shipment.agent_tracking_number:
                data = call_gettrack(None, n, agent_id=agent_id or shipment.agent_id)
            else:
                data = {"error": f"未找到对应的 shipment_id（agent_tracking_number）: {n}"}
            if isinstance(data, dict) and data.get("error"):
                results[n] = {"error": data.get("error"), "tracks": None, "raw": data}
            else:
                results[n] = {"error": None, "tracks": format_tracks_from_data(data), "raw": data}

    return render_template_safe("track.html",
                                carriers=carriers_env, agents=agents,
                                customers=Customer.query.order_by(Customer.name).all(),
                                results=results, message=message, default_text=default_text)

# ------------------------------
# 公共查询页面（Web表单）
# ------------------------------
@app.route("/public/track", methods=["GET", "POST"])
def public_track_page():
    results = {}
    default_text = ""
    message = ""
    if request.method == "POST":
        default_text = request.form.get("numbers", "").strip()
        if not default_text:
            message = "请输入运单号"
        else:
            lines = [ln.strip() for ln in default_text.splitlines() if ln.strip()]
            if len(lines) > 30:
                message = f"输入 {len(lines)} 条，本次只处理前 30 条。"
                lines = lines[:30]
            for n in lines:
                s = Shipment.query.filter_by(tracking_number=n).first()
                data = None
                
                # 优先尝试17Track查询（如果有17Track单号）
                if s and s.third_party_tracking_number:
                    data = call_17track(s.third_party_tracking_number)
                
                # 如果没有17Track结果，尝试常规查询
                if not data or (isinstance(data, dict) and data.get("error")):
                    if s and s.agent_id:
                        data = call_gettrack(None, n, agent_id=s.agent_id)
                    elif s and s.carrier_id:
                        data = call_gettrack(s.carrier_id, n, agent_id=None)
                    else:
                        data = call_gettrack(None, n, agent_id=None)
                
                if isinstance(data, dict) and data.get("error"):
                    results[n] = {"error": data.get("error"), "tracks": None, "raw": data}
                else:
                    results[n] = {"error": None, "tracks": format_tracks_from_data(data), "raw": data}

    return render_template_string("""
    <h2>物流轨迹查询</h2>
    <form method="post">
      <textarea name="numbers" rows="6" style="width:600px" placeholder="每行一个单号（最多30条）">{{default_text}}</textarea><br><br>
      <button>查询</button>
    </form>
    {% if message %}<p>{{message}}</p>{% endif %}
    {% if results %}
      <hr><h3>结果</h3>
      <div style="white-space:pre-wrap">
        {% for no, r in results.items() %}
          <h4>{{no}}</h4>
          {% if r.tracks %}{{r.tracks}}{% else %}无轨迹{% endif %}
          <hr>
        {% endfor %}
      </div>
    {% endif %}
    """, results=results, message=message, default_text=default_text)

# ------------------------------
# API
# ------------------------------
@app.route("/api/track/<carrier_id>/<tracking_number>")
def api_track_one(carrier_id, tracking_number):
    data = call_gettrack(carrier_id, tracking_number)
    return app.response_class(json.dumps(data, ensure_ascii=False), mimetype="application/json; charset=utf-8")

@app.route("/api/track_by_agent/<int:agent_id>/<tracking_number>")
def api_track_by_agent(agent_id, tracking_number):
    data = call_gettrack(None, tracking_number, agent_id=agent_id)
    return app.response_class(json.dumps(data, ensure_ascii=False), mimetype="application/json; charset=utf-8")

# ------------------------------
# 17Track API 路由
# ------------------------------
@app.route("/api/17track/<tracking_number>")
def api_17track(tracking_number):
    data = call_17track(tracking_number)
    return app.response_class(json.dumps(data, ensure_ascii=False), mimetype="application/json; charset=utf-8")

# ------------------------------
# 新增路由，渲染前端页面
# ------------------------------
@app.route("/frontend")
def frontend_page():
    return render_template("public_frontend.html")

# ------------------------------
# 新增 JSON API（前端 fetch 调用用这个）
# ------------------------------
@app.route("/public_track", methods=["POST"])
def public_track_json():
    try:
        data = request.get_json() or {}
        order_id = data.get("order_id", "").strip()

        if not order_id:
            return jsonify({"error": "缺少 order_id 参数"}), 400

        s = Shipment.query.filter_by(tracking_number=order_id).first()
        result_data = None
        
        # 优先尝试17Track查询（如果有17Track单号）
        if s and s.third_party_tracking_number:
            result_data = call_17track(s.third_party_tracking_number)
        
        # 如果没有17Track结果，尝试常规查询
        if not result_data or (isinstance(result_data, dict) and result_data.get("error")):
            if s and s.agent_id:
                result_data = call_gettrack(None, order_id, agent_id=s.agent_id)
            elif s and s.carrier_id:
                result_data = call_gettrack(s.carrier_id, order_id, agent_id=None)
            else:
                result_data = call_gettrack(None, order_id, agent_id=None)

        if isinstance(result_data, dict) and result_data.get("error"):
            return jsonify({"order_id": order_id, "error": result_data.get("error"), "tracks": []})
        else:
            return jsonify({"order_id": order_id, "error": None, "tracks": format_tracks_from_data(result_data)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------------------------
# 账单手工导出（保留）
# ------------------------------
@app.route("/invoice", methods=["GET", "POST"])
@login_required
def invoice():
    if request.method == "GET":
        return render_template_safe("invoice.html")
    customer = request.form.get("customer", "").strip()
    bankinfo = request.form.get("bankinfo", "").strip()
    raw = request.form.get("rows", "").strip()
    if not raw:
        flash("请粘贴账单行")
        return redirect(url_for("invoice"))
    lines = [l for l in raw.splitlines() if l.strip()]
    parsed = []
    for ln in lines:
        cols = [c.strip() for c in (ln.split("\t") if "\t" in ln else ln.split(","))]
        parsed.append(cols)
    bio = generate_invoice_xlsx(os.getenv("COMPANY_NAME", "公司名称"),
                                customer or "客户", bankinfo or "", parsed)
    filename = f"invoice_{int(time.time())}.xlsx"
    return send_file(bio, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ------------------------------
# 启动准备
# ------------------------------
def ensure_admin_user():
    try:
        if User.query.count() == 0:
            admin_name = os.getenv("ADMIN_USER", "admin")
            admin_pass = os.getenv("ADMIN_PASS", "123456")
            u = User(username=admin_name, is_admin=True)
            u.set_password(admin_pass)
            db.session.add(u)
            db.session.commit()
            app.logger.info(f"已创建默认管理员账号：{admin_name} / {admin_pass}（请部署后修改）")
    except Exception:
        app.logger.exception("创建默认管理员失败")

# ------------------------------
# 主入口
# ------------------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_sqlite_columns()  # 移除 try-except，让错误冒泡以便调试
        ensure_admin_user()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)

flask_app = app
application = app