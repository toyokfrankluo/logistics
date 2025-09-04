# create_tables.py
from app import app, db

with app.app_context():
    db.create_all()
    print("√ 所有模型对应的表已创建/存在")