# app.py — 新版本，直接覆盖旧文件
import os
import json
import requests
from flask import Flask, request, render_template_string, redirect, url_for

app = Flask(__name__)

# 优先使用环境变量（Render 推荐）
APP_TOKEN = os.getenv("APP_TOKEN", "dfaf5c6ba49d58d8c3644671056cfb3b")
APP_KEY = os.getenv("APP_KEY", "4a1756eb968cd85f63b8ab3047e3bebf")
API_URL = os.getenv("API_URL", "http://ywsl.rtb56.com/webservice/PublicService.asmx/ServiceInterfaceUTF8")

# =======================
# 前端模板（支持展开/收起）
# =======================
HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>运单号查询</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    textarea { width: 720px; height: 200px; font-size:14px; }
    .note { color: #666; margin-bottom: 8px; }
    table { border-collapse: collapse; width: 100%; margin-top: 20px; }
    th, td { border: 1px solid #ddd; padding: 8px; vertical-align: top; text-align: left; }
    th { background: #f7f7f7; }
    pre { margin: 0; white-space: pre-wrap; word-wrap: break-word; font-size: 13px; }
    .status { font-weight: bold; color: #2b7a78; }
    .error { color: #b00020; }
    details summary { cursor: pointer; font-weight: bold; color: #0077cc; margin-bottom: 5px; }
  </style>
</head>
<body>
  <h2>运单号查询（每行一个，最多 30 个）</h2>
  <div class="note">支持从 Excel 复制多行粘贴进来；超过 30 行会自动只处理前 30 行。</div>

  <form method="post" action="{{ url_for('track') }}">
    <textarea name="numbers" placeholder="把运单号粘贴在这里（每行一个）">{{ default_text or '' }}</textarea><br><br>
    <button type="submit">查询</button>
  </form>

  {% if message %}
    <p class="note">{{ message }}</p>
  {% endif %}

  {% if results %}
    <h3>查询结果（共 {{ results|length }} 条）：</h3>
    <table>
      <tr><th style="width:160px">运单号</th><th>最新状态 / 详细轨迹</th></tr>
      {% for num, row in results.items() %}
        <tr>
          <td>{{ num }}</td>
          <td>
            {% if row.error %}
              <div class="error">{{ row.error }}</div>
            {% else %}
              <div class="status">{{ row.latest }}</div>
              <details>
                <summary>查看详细轨迹</summary>
                <pre>{{ row.tracks }}</pre>
              </details>
            {% endif %}
          </td>
        </tr>
      {% endfor %}
    </table>
  {% endif %}
</body>
</html>
"""

# =======================
# 格式化函数
# =======================
def format_tracking(data: dict):
    """从API返回的JSON提取轨迹，返回 (最新状态, 全部轨迹字符串)"""
    if not data or "data" not in data or not data["data"]:
        return ("暂无状态", "没有查询到轨迹信息")

    details = data["data"][0].get("details", [])
    if not details:
        return ("暂无状态", "暂无轨迹信息")

    # 最新状态（第一条）
    first = details[0]
    latest = f"{first.get('track_description','')} ({first.get('track_occur_date','')})"

    # 全部轨迹
    lines = []
    for d in details:
        location = d.get("track_location", "")
        desc = d.get("track_description", "")
        time = d.get("track_occur_date", "")
        lines.append(f"{location} — {desc}\n{time}")
    return (latest, "\n".join(lines))

# =======================
# 调用 API
# =======================
def query_tracking(number: str):
    payload = {
        "appToken": APP_TOKEN,
        "appKey": APP_KEY,
        "serviceMethod": "gettrack",
        "paramsJson": json.dumps({"tracking_number": number}, ensure_ascii=False)
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        r = requests.post(API_URL, headers=headers, data=payload, timeout=15)
        data = r.json()
        latest, tracks = format_tracking(data)
        return {"latest": latest, "tracks": tracks, "error": None}
    except Exception as e:
        return {"latest": None, "tracks": None, "error": f"请求出错: {e}"}

# =======================
# 路由
# =======================
@app.route("/", methods=["GET"])
def root():
    return redirect(url_for("track"))

@app.route("/track", methods=["GET", "POST"])
def track():
    results = {}
    message = ""
    default_text = ""
    if request.method == "POST":
        numbers_text = request.form.get("numbers", "").strip()
        default_text = numbers_text
        if not numbers_text:
            message = "请先输入至少一个运单号（每行一个）"
        else:
            numbers = [n.strip() for n in numbers_text.splitlines() if n.strip()]
            if len(numbers) > 30:
                message = f"您输入 {len(numbers)} 条，本次只处理前 30 条。"
                numbers = numbers[:30]
            for num in numbers:
                results[num] = query_tracking(num)
    return render_template_string(HTML_TEMPLATE, results=results, message=message, default_text=default_text)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)