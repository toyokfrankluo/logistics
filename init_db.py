# init_db.py - PostgreSQL 数据库初始化脚本
import os
import sys
from app import app, db, User, Shipment

def init_database():
    """初始化数据库表结构"""
    print("🚀 开始初始化数据库...")
    print(f"📊 数据库URL: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    with app.app_context():
        try:
            # 创建所有表
            print("🛠️ 正在创建数据库表...")
            db.create_all()
            print("✅ 数据库表创建成功！")
            
            # 检查并修复表结构（针对PostgreSQL）
            print("🔧 检查表结构完整性...")
            try:
                # 尝试查询一个包含所有字段的记录
                test_shipment = Shipment.query.first()
                if test_shipment:
                    # 如果查询成功，说明表结构完整
                    print("✅ 表结构完整")
                else:
                    print("ℹ️ 表为空，但结构完整")
            except Exception as e:
                print(f"⚠️ 表结构可能不完整: {e}")
                print("🔄 重新创建表结构...")
                # 删除并重新创建所有表
                db.drop_all()
                db.create_all()
                print("✅ 表结构重新创建成功")
            
            # 创建默认管理员用户
            print("👤 检查默认用户...")
            if User.query.count() == 0:
                admin_name = os.getenv("ADMIN_USER", "admin")
                admin_pass = os.getenv("ADMIN_PASS", "123456")
                u = User(username=admin_name, is_admin=True)
                u.set_password(admin_pass)
                db.session.add(u)
                db.session.commit()
                print(f"✅ 已创建默认管理员：{admin_name}/{admin_pass}")
            else:
                print("ℹ️ 用户已存在，跳过创建")
                
        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            import traceback
            traceback.print_exc()
            # 如果是表已存在的错误，可以忽略
            if "already exists" not in str(e) and "relation" not in str(e):
                raise

if __name__ == "__main__":
    init_database()