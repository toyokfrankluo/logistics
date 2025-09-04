from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from models import db, Customer, Agent, Order

def init_admin(app):
    admin = Admin(app, name="物流后台", template_mode="bootstrap4")

    # 注册模型
    admin.add_view(ModelView(Customer, db.session, name="客户管理"))
    admin.add_view(ModelView(Agent, db.session, name="代理管理"))
    admin.add_view(ModelView(Order, db.session, name="订单管理"))

    return admin