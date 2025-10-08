import os
import time
import schedule
import requests
import json
from datetime import datetime, timedelta
from flask import Flask
from models import db, Shipment, CarrierAgent

def create_app():
    app = Flask(__name__)
    
    # 配置数据库
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    return app

def fetch_tracking_from_api(agent, tracking_number):
    """
    从您的 views.py 中复制 fetch_tracking_from_api 函数到这里
    注意：需要复制完整的函数代码
    """
    # 这里需要复制您 views.py 中的完整 fetch_tracking_from_api 函数
    # 由于代码较长，建议直接从 views.py 复制过来
    pass

def sync_tracking_to_supabase(shipment, tracks):
    """
    从您的 views.py 中复制 sync_tracking_to_supabase 函数到这里
    """
    # 这里需要复制您 views.py 中的完整 sync_tracking_to_supabase 函数
    pass

def auto_refresh_tracking():
    """自动刷新物流轨迹"""
    print(f"🕒 [{datetime.now()}] 开始自动刷新物流轨迹...")
    
    app = create_app()
    
    with app.app_context():
        try:
            # 获取最近7天内有更新的运单
            seven_days_ago = datetime.now() - timedelta(days=7)
            shipments = Shipment.query.filter(
                Shipment.agent_id.isnot(None),
                Shipment.created_at >= seven_days_ago
            ).all()
            
            updated_count = 0
            total_count = len(shipments)
            
            print(f"📦 需要刷新 {total_count} 个运单")
            
            for shipment in shipments:
                try:
                    agent = CarrierAgent.query.get(shipment.agent_id)
                    if agent and agent.supports_api:
                        # 调用轨迹API
                        tracks, error = fetch_tracking_from_api(agent, shipment.tracking_number)
                        
                        if tracks and not error:
                            # 同步到Supabase
                            success_count, fail_count = sync_tracking_to_supabase(shipment, tracks)
                            
                            if success_count > 0:
                                updated_count += 1
                                print(f"✅ 自动更新: {shipment.tracking_number} (+{success_count}条)")
                            
                            # 避免请求过于频繁
                            time.sleep(1)
                            
                except Exception as e:
                    print(f"🔥 自动更新失败 {shipment.tracking_number}: {str(e)}")
            
            print(f"🎯 自动刷新完成: 更新 {updated_count}/{total_count} 个运单")
            
        except Exception as e:
            print(f"💥 自动刷新过程出错: {str(e)}")

def run_scheduler():
    """运行定时任务"""
    # 每30分钟执行一次
    schedule.every(30).minutes.do(auto_refresh_tracking)
    
    # 启动时立即执行一次
    auto_refresh_tracking()
    
    print("⏰ 物流轨迹自动刷新服务已启动 (每30分钟执行一次)")
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # 每分钟检查一次

if __name__ == "__main__":
    run_scheduler()