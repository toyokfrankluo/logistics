import requests
import json
from datetime import datetime

def test_nextsls(client_reference):
    url = "http://xmsdwl.nextsls.com/api/v5/shipment/get_tracking"

    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer 68ba8cafd79d3149ba75b30e68ba8caf743809607"
    }

    payload = {
        "access_token": "68ba8cafd79d3149ba75b30e68ba8caf743809607",
        "shipment": {
            "shipment_id": "",
            "client_reference": client_reference,  # ✅ 这里直接用客户单号
            "tracking_number": "",
            "parcel_number": "",
            "waybill_number": "",
            "language": "zh"
        }
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    print("=== API 原始返回 (nextsls) ===", resp.text)

    try:
        data = resp.json()
    except Exception:
        return None, "返回不是 JSON"

    if data.get("status") != 1:
        return None, data.get("info", "接口调用失败")

    traces = data.get("data", {}).get("shipment", {}).get("traces", [])
    tracks = []
    for t in traces:
        ts = t.get("time")
        if isinstance(ts, int):
            ts = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        tracks.append({
            "time": ts,
            "location": t.get("location", ""),
            "description": t.get("info", "")
        })
    return tracks, None


if __name__ == "__main__":
    # 在这里填一个你在 nextsls 下单时的 客户单号
    tracks, err = test_nextsls("FBA190YH5S0X")
    if err:
        print("错误:", err)
    else:
        for tr in tracks:
            print(tr)