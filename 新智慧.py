import requests
import json
import os
from datetime import datetime

# NextSLS API 配置
API_URL = "http://xmsdwl.nextsls.com/api/v5/shipment/get_tracking?access_token=68ba8cafd79d3149ba75b30e68ba8caf743809607"
API_KEY = "eyJhcHBfY29kZSI6Inhtc2R3bCIsInRva2VuIjoiNjhiYThjYWZkNzlkMzE0OWJhNzViMzBlNjhiYThjYWY3NDM4MDk2MDcifQ=="
API_TOKEN = "68ba8cafd79d3149ba75b30e68ba8caf743809607"  # 替换为您的实际API令牌

# 测试用的运单ID列表 - 请替换为实际的系统运单号
SHIPMENT_IDS = [
    "XM2509097098",  # 示例运单号1
    "FBA191489QLY",  # 示例运单号2
    "FBA190YH5S0X",  # 示例运单号3
]

def test_shipment_tracking():
    """测试通过 shipment_id 获取物流轨迹"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN}"
    }
    
    print("🚀 开始测试 NextSLS 物流轨迹抓取")
    print("=" * 60)
    
    for shipment_id in SHIPMENT_IDS:
        print(f"\n📦 查询运单号: {shipment_id}")
        
        # 构建请求数据
        payload = {
            "shipment": {
                "shipment_id": shipment_id,
                "language": "zh"
            }
        }
        
        try:
            # 发送请求
            response = requests.post(API_URL, json=payload, headers=headers, timeout=15)
            response.encoding = "utf-8"
            
            # 检查响应状态
            if response.status_code != 200:
                print(f"❌ 请求失败，状态码: {response.status_code}")
                continue
            
            # 解析响应数据
            data = response.json()
            
            if data.get("status") != 1:
                print(f"❌ API返回错误: {data.get('info', '未知错误')}")
                continue
            
            # 提取轨迹信息
            shipment_data = data.get("data", {}).get("shipment", {})
            tracking_number = shipment_data.get("tracking_number", "未知")
            status = shipment_data.get("status", "未知")
            traces = shipment_data.get("traces", [])
            
            print(f"✅ 转单号: {tracking_number}, 状态: {status}")
            
            if not traces:
                print("  暂无轨迹信息")
                continue
            
            print("  轨迹信息:")
            for trace in traces:
                timestamp = trace.get("time", 0)
                if isinstance(timestamp, (int, float)):
                    date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    date = str(timestamp)
                
                location = trace.get("location", "")
                info = trace.get("info", "")
                
                print(f"  ⏰ {date} | 📍 {location} | 📝 {info}")
                
        except Exception as e:
            print(f"❌ 请求异常: {str(e)}")
    
    print("\n" + "=" * 60)
    print("✅ 测试完成")

if __name__ == "__main__":
    # 运行测试
    test_shipment_tracking()