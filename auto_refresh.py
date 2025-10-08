import os
import time
import schedule
import requests
import json
from datetime import datetime, timedelta
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 简化的自动刷新版本，避免复杂的依赖关系
def auto_refresh_tracking():
    """自动刷新物流轨迹 - 简化版本"""
    print(f"🕒 [{datetime.now()}] 开始自动刷新物流轨迹...")
    
    try:
        # 直接从环境变量获取数据库连接
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            print("❌ 未找到数据库连接配置")
            return
        
        # 创建数据库连接
        engine = create_engine(database_url)
        Session = sessionmaker(bind=engine)
        session = Session()
        
        # 获取最近7天内有代理的运单
        seven_days_ago = datetime.now() - timedelta(days=7)
        
        # 执行SQL查询（避免复杂的ORM依赖）
        result = session.execute(f"""
            SELECT s.id, s.tracking_number, s.agent_id, a.name as agent_name, 
                   a.api_url, a.app_token, a.app_key, a.supports_api
            FROM shipment s
            LEFT JOIN carrier_agent a ON s.agent_id = a.id
            WHERE s.agent_id IS NOT NULL 
            AND s.created_at >= '{seven_days_ago}'
            AND a.supports_api = true
        """)
        
        shipments = result.fetchall()
        updated_count = 0
        total_count = len(shipments)
        
        print(f"📦 找到 {total_count} 个需要刷新的运单")
        
        # 从环境变量获取Supabase配置
        supabase_url = os.environ.get('SUPABASE_URL')
        supabase_key = os.environ.get('SUPABASE_KEY')
        
        for shipment in shipments:
            try:
                tracking_number = shipment.tracking_number
                agent_api_url = shipment.api_url
                agent_app_token = shipment.app_token
                agent_app_key = shipment.app_key
                
                print(f"🔍 处理运单: {tracking_number}")
                
                # 调用轨迹API（简化版本）
                tracks = fetch_tracking_simple(agent_api_url, agent_app_token, agent_app_key, tracking_number)
                
                if tracks:
                    # 同步到Supabase
                    success_count = sync_to_supabase_simple(supabase_url, supabase_key, tracking_number, tracks)
                    
                    if success_count > 0:
                        updated_count += 1
                        print(f"✅ 自动更新成功: {tracking_number} (+{success_count}条)")
                    
                    # 避免请求过于频繁
                    time.sleep(2)
                else:
                    print(f"⚠️ 无轨迹数据: {tracking_number}")
                    
            except Exception as e:
                print(f"🔥 自动更新失败 {tracking_number}: {str(e)}")
        
        session.close()
        print(f"🎯 自动刷新完成: 成功更新 {updated_count}/{total_count} 个运单")
        
    except Exception as e:
        print(f"💥 自动刷新过程出错: {str(e)}")

def fetch_tracking_simple(api_url, app_token, app_key, tracking_number):
    """简化的轨迹获取函数"""
    try:
        # 根据不同的API类型调用
        if "rtb56.com" in api_url or "txfba.com" in api_url:
            payload = {
                "appToken": app_token,
                "appKey": app_key,
                "serviceMethod": "gettrack",
                "paramsJson": json.dumps({"tracking_number": tracking_number})
            }
            
            resp = requests.post(api_url, data=payload, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("data"):
                    tracks = []
                    details = data["data"][0].get("details", [])
                    for d in details:
                        tracks.append({
                            "time": d.get("track_occur_date"),
                            "location": d.get("track_location"),
                            "description": d.get("track_description")
                        })
                    return tracks
        # 可以添加其他API类型的处理
        
        return None
        
    except Exception as e:
        print(f"❌ 获取轨迹失败 {tracking_number}: {str(e)}")
        return None

def sync_to_supabase_simple(supabase_url, supabase_key, tracking_number, tracks):
    """简化的Supabase同步函数"""
    if not supabase_url or not supabase_key:
        print("❌ Supabase配置缺失")
        return 0
    
    success_count = 0
    
    for track in tracks:
        try:
            track_data = {
                "tracking_number": tracking_number,
                "event_time": track.get('time', datetime.now().isoformat()),
                "location": track.get('location', ''),
                "description": track.get('description', '')
            }
            
            response = requests.post(
                f"{supabase_url}/rest/v1/shipment_tracking_details",
                headers={
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                    "apikey": supabase_key,
                    "Prefer": "return=minimal"
                },
                data=json.dumps(track_data),
                timeout=10
            )
            
            if response.status_code in [200, 201, 204]:
                success_count += 1
                
        except Exception as e:
            print(f"❌ 同步轨迹失败: {str(e)}")
    
    return success_count

def run_scheduler():
    """运行定时任务"""
    print("🚀 启动物流轨迹自动刷新服务...")
    
    # 每30分钟执行一次
    schedule.every(30).minutes.do(auto_refresh_tracking)
    
    # 启动时立即执行一次
    print("🔄 首次执行自动刷新...")
    auto_refresh_tracking()
    
    print("⏰ 自动刷新服务已启动，每30分钟执行一次")
    
    # 保持程序运行
    while True:
        schedule.run_pending()
        time.sleep(60)  # 每分钟检查一次

if __name__ == "__main__":
    run_scheduler()