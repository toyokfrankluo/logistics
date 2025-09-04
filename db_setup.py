# db_reset.py
"""
强制重置数据库（删除 sqlite 文件 -> 重建表 -> 插入示例数据 + 管理员账号）
请在项目根目录（含 app.py）下运行：
    source .venv/bin/activate
    python db_reset.py
"""

import os
import importlib
from pathlib import Path

# 导入 Flask app 与 db
# 注意：这里假设你的主模块名为 app.py（module name = "app"）
try:
    import app as app_module
    app = app_module.app
    db = app_module.db
except Exception as e:
    raise SystemExit(f"无法导入 app 模块，请确认在项目根目录并且文件名是 app.py。错误：{e}")

# 解析 sqlite 文件路径（支持 sqlite:///relative.db & sqlite:////absolute/path.db）
def sqlite_db_path_from_uri(uri: str):
    if not uri:
        return None
    uri = uri.strip()
    if uri.startswith("sqlite:///"):
        # relative or absolute without extra slash
        return uri.replace("sqlite:///", "", 1)
    if uri.startswith("sqlite:////"):
        # absolute with 4 slashes
        return uri.replace("sqlite:////", "/", 1)
    return None

with app.app_context():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    db_path = sqlite_db_path_from_uri(uri)
    if db_path:
        db_file = Path(db_path)
        if db_file.exists():
            print(f"删除旧数据库文件: {db_file}")
            db_file.unlink()
        else:
            print(f"未发现数据库文件（将创建新的）: {db_file}")
    else:
        print("数据库不是 sqlite 或无法解析其路径，跳过删除步骤，直接执行 db.create_all()")

    # 建表
    print("开始创建表 ...")
    db.create_all()
    print("表创建完成。")

    # 通过反射安全获取模型类（兼容 Agent / CarrierAgent 命名差异）
    User = getattr(app_module, "User", None)
    Customer = getattr(app_module, "Customer", None)
    CarrierAgent = getattr(app_module, "CarrierAgent", None)
    Agent = getattr(app_module, "Agent", None)
    Shipment = getattr(app_module, "Shipment", None)

    # 插入默认 admin（admin/admin）
    if User:
        if User.query.count() == 0:
            admin_name = os.getenv("ADMIN_USER", "admin")
            admin_pass = os.getenv("ADMIN_PASS", "admin")
            u = User(username=admin_name, is_admin=True)
            # 有些实现使用 set_password 方法
            if hasattr(u, "set_password"):
                u.set_password(admin_pass)
            else:
                # 直接写入 password_hash（尝试使用 werkzeug）
                from werkzeug.security import generate_password_hash
                try:
                    u.password_hash = generate_password_hash(admin_pass)
                except Exception:
                    # 如果模型使用 plain password 字段 fallback
                    if hasattr(u, "password"):
                        u.password = admin_pass
            db.session.add(u)
            db.session.commit()
            print(f"已创建管理员账号: {admin_name} / {admin_pass}")
        else:
            print("已有用户存在，跳过创建 admin。")
    else:
        print("未在 app.py 中找到 User 模型，跳过创建 admin。")

    # 示例客户
    if Customer:
        if not Customer.query.first():
            c = Customer(name="示例客户 - 张三", bank_info="开户行: 招商银行\n户名: 深圳市星睿国际物流有限公司\n账号: 62148xxxxxxx")
            db.session.add(c)
            print("已插入示例客户")
        else:
            print("已有客户记录，跳过示例客户插入。")
    else:
        print("未找到 Customer 模型（跳过）")

    # 示例代理（CarrierAgent 或 Agent）
    AgentModel = CarrierAgent or Agent
    if AgentModel:
        if not AgentModel.query.first():
            a = AgentModel(name="示例代理 - RTB56", api_url="", username="", password="")
            db.session.add(a)
            print("已插入示例代理")
        else:
            print("已有代理记录，跳过示例代理插入。")
    else:
        print("未找到 CarrierAgent / Agent 模型（跳过）")

    db.session.commit()
    print("数据库重置完成。现在可以运行 python app.py 或者 flask run 来启动服务。")