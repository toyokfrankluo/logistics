# wsgi.py —— 专门给 Flask CLI 找入口用
# 只做一件事：从 app.py 里把 flask_app 暴露出来

from app import flask_app as app, db  # app = Flask 实例；db 只是为了将来在 shell 里能直接用

# 可选：本文件也支持直接运行（不是必须）
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)