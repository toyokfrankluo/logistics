# db_reset.py — 强制重置 sqlite 数据库并插入示例数据
import os
from pathlib import Path
import time

# 导入 app 与 db（确保脚本和 app.py 在同一目录）
try:
    import app as app_module
    app = app_module.app
    db = app_module.db
    User = getattr(app_module, "User", None)
    Customer = getattr(app_module, "Customer", None)
    CarrierAgent = getattr(app_module, "CarrierAgent", None)
    Shipment = getattr(app_module, "Shipment", None)
except Exception as e:
    raise SystemExit(f"无法导入 app 模块，请确认在项目根目录并且文件名是 app.py。错误：{e}")

def sqlite_db_path_from_uri(uri: str):
    if not uri:
        return None
    uri = uri.strip()
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "", 1)
    if uri.startswith("sqlite:////"):
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
            time.sleep(0.1)
        else:
            print(f"未发现数据库文件（将创建新的）: {db_file}")
    else:
        print("数据库不是 sqlite 或无法解析其路径，跳过删除步骤，直接执行 db.create_all()")

    # 建表
    print("开始创建表 ...")
    db.create_all()
    print("表创建完成。")

    # 默认 admin
    if User:
        if User.query.count() == 0:
            admin_name = os.getenv("ADMIN_USER", "admin")
            admin_pass = os.getenv("ADMIN_PASS", "123456")
            u = User(username=admin_name, is_admin=True)
            if hasattr(u, "set_password"):
                u.set_password(admin_pass)
            else:
                try:
                    from werkzeug.security import generate_password_hash
                    u.password_hash = generate_password_hash(admin_pass)
                except Exception:
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
            db.session.commit()
            print("已插入示例客户")
            example_customer = c
        else:
            example_customer = Customer.query.first()
            print("已有客户记录，跳过示例客户插入。")
    else:
        example_customer = None
        print("未找到 Customer 模型（跳过）")

    # 示例代理
    if CarrierAgent:
        if not CarrierAgent.query.first():
            a = CarrierAgent(name="示例代理 - RTB56", api_url=os.getenv("API_URL", "http://ywsl.rtb56.com/webservice/PublicService.asmx/ServiceInterfaceUTF8"), username="", password="", app_key=os.getenv("RTB56_KEY", ""), app_token=os.getenv("RTB56_TOKEN", ""))
            db.session.add(a)
            db.session.commit()
            print("已插入示例代理")
            example_agent = a
        else:
            example_agent = CarrierAgent.query.first()
            print("已有代理记录，跳过示例代理插入。")
    else:
        example_agent = None
        print("未找到 CarrierAgent 模型（跳过）")

    # 示例运单
    if Shipment and example_customer:
        if not Shipment.query.first():
            s = Shipment(
                tracking_number="TEST001",
                customer_id=example_customer.id,
                agent_id=example_agent.id if example_agent else None,
                destination="美国",
                channel="空运",
                weight=5.5,
                unit_price=100,
                fee=550,
                status="已录入"
            )
            db.session.add(s)
            db.session.commit()
            print("已插入示例运单 TEST001")
        else:
            print("已有运单，跳过示例插入。")

    print("数据库重置完成。现在可以运行 python app.py 或 flask --app app run 来启动服务。")