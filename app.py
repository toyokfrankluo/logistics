import os
import requests
import datetime
from flask import Flask, request, render_template, jsonify

app = Flask(__name__, template_folder="templates")

def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# 从环境变量读取 API 配置（部署时在 Render 上配置）
API_URL = os.getenv("API_URL")           # e.g. https://api.forwarder.com/track
API_METHOD = os.getenv("API_METHOD", "GET").upper()  # GET or POST
API_PARAM = os.getenv("API_PARAM", "hbl")            # 参数名, e.g. hbl, waybill
API_KEY_NAME = os.getenv("API_KEY_NAME", "")         # 可选：把 api key 放在 query/header
API_KEY = os.getenv("API_KEY", "")
API_KEY_IN = os.getenv("API_KEY_IN", "query")        # "query" 或 "header"

def call_forwarder_api(tracking_no):
    """如果环境变量有正确配置，就去调用真实 API；否则返回示例数据（demo）。"""
    if not API_URL:
        # demo fallback
        return {
            "status": "DEMO - 未配置真实 API",
            "last_update": now(),
            "history": [
                {"time": now(), "event": f"示例轨迹：收到查询请求，单号 {tracking_no}"},
                {"time": now(), "event": "示例轨迹：货物装船"},
                {"time": now(), "event": "示例轨迹：货物在海上运输"}
            ],
            "raw": {}
        }

    try:
        if API_METHOD == "GET":
            params = {API_PARAM: tracking_no}
            if API_KEY and API_KEY_IN == "query" and API_KEY_NAME:
                params[API_KEY_NAME] = API_KEY
            headers = {}
            if API_KEY and API_KEY_IN == "header" and API_KEY_NAME:
                headers[API_KEY_NAME] = API_KEY
            resp = requests.get(API_URL, params=params, headers=headers, timeout=20)
        else:  # POST
            data = {API_PARAM: tracking_no}
            if API_KEY and API_KEY_IN == "body" and API_KEY_NAME:
                data[API_KEY_NAME] = API_KEY
            headers = {}
            if API_KEY and API_KEY_IN == "header" and API_KEY_NAME:
                headers[API_KEY_NAME] = API_KEY
            resp = requests.post(API_URL, json=data, headers=headers, timeout=20)

        resp.raise_for_status()
        j = resp.json()

        # 尝试规范化常见字段
        status = j.get("status") or j.get("current_status") or j.get("result") or "未知"
        history = j.get("history") or j.get("events") or j.get("tracks") or j.get("data") or []
        # 如果 history 是字符串，尝试包装
        if isinstance(history, str):
            history = [{"time": now(), "event": history}]
        return {
            "status": status,
            "last_update": now(),
            "history": history,
            "raw": j
        }
    except Exception as e:
        return {
            "status": "调用 API 出错",
            "last_update": now(),
            "history": [{"time": now(), "event": f"错误：{str(e)}"}],
            "raw": {}
        }


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/track", methods=["POST"])
def track():
    tracking_no = request.form.get("hbl", "").strip()
    if not tracking_no:
        return {"error": "缺少单号 hbl"}, 400
    result = call_forwarder_api(tracking_no)
    # 如果前端以 AJAX 请求 JSON，可返回 JSON；这里我们返回渲染模板
    return render_template("result.html", tracking_no=tracking_no, result=result)


# 简单的 JSON 接口，方便调试或外部调用
@app.route("/api/track", methods=["GET"])
def api_track():
    tracking_no = request.args.get("hbl", "").strip()
    if not tracking_no:
        return jsonify({"error": "缺少参数 hbl"}), 400
    return jsonify(call_forwarder_api(tracking_no))


if __name__ == "__main__":
    # 本地测试时用 host="0.0.0.0" 可让局域网设备访问
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)