# app.py — 复制整个文件覆盖你当前的 app.py
import os
import json
import requests
from flask import Flask, request, render_template_string, redirect, url_for

app = Flask(__name__)

# 优先使用环境变量（在 Render 上推荐设置为环境变量）
APP_TOKEN = os.getenv("APP_TOKEN", "dfaf5c6ba49d58d8c3644671056cfb3b")
APP_KEY = os.getenv("APP_KEY", "4a1756eb968cd85f63b8ab3047e3bebf4a1756eb968cd85f63b8ab3047e3bebf")
API_URL = os.getenv("API_URL", "http://ywsl.rtb56.com/webservice/PublicService.asmx/ServiceInterfaceUTF8")

# 内联 HTML 模板（前端：输入、结果表格、错误提示）
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
      <tr><th style="width:160px">运单号</th><th style="width:220px">简要状态</th><th>原始 API 返回（JSON / 文本）</th></tr>
      {% for num, row in results.items() %}
        <tr>
          <td>{{ num }}</td>
          <td>
            {% if row.status %}
              <div class="{{ 'error' if row.status.startswith('错误') or row.status.startswith('请求出错') else 'status' }}">{{ row.status }}</div>
            {% else %}
              <div class="note">无简要状态</div>
            {% endif %}
          </td>
          <td><pre>{{ row.raw | safe }}</pre></td>
        </tr>
      {% endfor %}
    </table>
  {% endif %}
</body>
</html>
"""

def query_tracking(number: str) -> (str, str):
    """
    查询单个运单，返回 (status_text, raw_pretty_string)
    status_text: 简短状态（例如 '转运中' / '获取跟踪记录成功' / '跟踪号码不能为空' / '错误: ...'）
    raw_pretty_string: 原始 API 返回的 JSON pretty string（中文不转义）或原始文本
    """
    payload = {
        "appToken": APP_TOKEN,
        "appKey": APP_KEY,
        "serviceMethod": "gettrack",
        "paramsJson": json.dumps({"tracking_number": number}, ensure_ascii=False)
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        r = requests.post(API_URL, headers=headers, data=payload, timeout=15)
        # 尝试解析 JSON
        try:
            data = r.json()
            # 尝试从常见字段提取简要状态
            status_candidates = []
            if isinstance(data, dict):
                # 常见字段：cnmessage, track_status_name, track_status_cnname
                for fld in ("cnmessage", "track_status_name", "track_status_cnname", "message"):
                    v = data.get(fld) if isinstance(data, dict) else None
                    if v:
                        status_candidates.append(str(v))
                # data里可能包含 data[0].track_status_name
                inner = data.get("data") if isinstance(data, dict) else None
                if inner and isinstance(inner, list) and len(inner) > 0:
                    first = inner[0]
                    if isinstance(first, dict):
                        for fld in ("track_status_name", "track_status_cnname"):
                            if first.get(fld):
                                status_candidates.append(str(first.get(fld)))
            status_text = status_candidates[0] if status_candidates else (data.get("cnmessage") if isinstance(data, dict) else "")
            pretty = json.dumps(data, ensure_ascii=False, indent=2)
            return (status_text or "查询成功", pretty)
        except Exception:
            # 不是 JSON，返回文本
            text = r.text
            return ("返回非 JSON 文本", text)
    except Exception as e:
        return (f"请求出错: {e}", f"请求出错: {e}")

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
        default_text = numbers_text  # 回显
        if not numbers_text:
            message = "请先输入至少一个运单号（每行一个）"
        else:
            numbers = [n.strip() for n in numbers_text.splitlines() if n.strip()]
            if not numbers:
                message = "未解析到有效单号"
            else:
                if len(numbers) > 30:
                    message = f"您输入 {len(numbers)} 条，本次只处理前 30 条。"
                    numbers = numbers[:30]
                # 逐个查询并保存结果
                for num in numbers:
                    status, raw = query_tracking(num)
                    results[num] = {"status": status, "raw": raw}
    return render_template_string(HTML_TEMPLATE, results=results, message=message, default_text=default_text)

if __name__ == "__main__":
    # 本地调试用 debug=True（部署到 Render 时可关闭或让 Render 管理）
    app.run(host="0.0.0.0", port=5000, debug=True)