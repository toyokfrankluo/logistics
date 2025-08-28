import requests
import json
import datetime

# 示例：货代 API 信息（以后可以放到 config.json 里）
API_URL = "http://8.135.12.215:5001/api/tracking"
APPKEY = "70a0d7015bd5d5950c4753665ac5872c"
HBL_LIST = ["SX02468"]  # 这里放你要查询的单号，可以多个

# 结果保存
result = {}

for hbl in HBL_LIST:
    try:
        res = requests.get(API_URL, params={"hbl": hbl, "appkey": APPKEY})
        data = res.json()
        result[hbl] = {
            "status": data.get("status", "未知"),
            "last_update": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "history": data.get("history", [])
        }
    except Exception as e:
        result[hbl] = {"error": str(e)}

# 写入文件（供网页查询）
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("抓取完成，结果已写入 data.json")