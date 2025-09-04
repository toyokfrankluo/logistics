from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "welcome to my logistics"  # 修正1：补全了字符串的引号

if __name__ == "__main__":            # 修正2：在if后加了空格
    app.run(debug=True)               # 修正3：将 == 改为 =，并确保缩进