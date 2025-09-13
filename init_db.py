# init_db.py - PostgreSQL 数据库初始化脚本
import os
from app import app, db, User

def init_database():
    """初始化数据库表结构"""
    with app.app_context():
        try:
            # 创建所有表
            db.create_all()
            print("✅ 数据库表创建成功！")
            
            # 创建默认管理员用户
            if User.query.count() == 0:
                admin_name = os.getenv("ADMIN_USER", "admin")
                admin_pass = os.getenv("ADMIN_PASS", "123456")
                u = User(username=admin_name, is_admin=True)
                u.set_password(admin_pass)
                db.session.add(u)
                db.session.commit()
                print(f"✅ 已创建默认管理员：{admin_name}/{admin_pass}")
                
        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            # 如果是表已存在的错误，可以忽略
            if "already exists" not in str(e) and "relation" not in str(e):
                raise

if __name__ == "__main__":
    init_database()