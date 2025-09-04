# db_init.py — 初始化数据库并插入示例客户/代理
from app import db, Customer, CarrierAgent, Shipment, app

with app.app_context():
    db.create_all()
    # 插入示例客户
    if not Customer.query.first():
        c = Customer(name="示例客户 - 张三", bank_info="开户行: 招商银行\n户名: 深圳市星睿国际物流有限公司\n账号: 62148xxxxxxx")
        db.session.add(c)
    # 插入示例代理
    if not CarrierAgent.query.first():
        a = CarrierAgent(name="示例代理 - RTB56", api_url="", username="", password="")
        db.session.add(a)
    db.session.commit()
    print("数据库初始化完成：表已创建，示例客户与代理（如无）已插入。")