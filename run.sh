#!/bin/bash
# ==========================================
# run.sh - 一键运行 Flask 项目的脚本
# 功能：
# 1. 自动进入项目目录
# 2. 自动激活虚拟环境
# 3. 自动杀掉 5000 端口的旧进程
# 4. 自动初始化数据库（如果没有）
# 5. 自动启动 Flask
# ==========================================

# 进入项目目录
cd ~/Desktop/logistics-starter || exit

# 激活虚拟环境
source .venv/bin/activate

# 杀掉占用 5000 端口的进程
echo ">>> 检查并清理 5000 端口..."
lsof -ti:5000 | xargs kill -9 2>/dev/null
echo ">>> 5000 端口已释放"

# 检查数据库是否存在
if [ ! -f "instance/logistics.db" ]; then
    echo ">>> 数据库不存在，正在初始化..."
    python init_db.py
    echo ">>> 数据库已初始化完成"
fi

# 启动 Flask
echo ">>> 正在启动 Flask 应用..."
python app.py