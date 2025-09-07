#!/bin/bash
# ==========================================
# run.sh - 一键运行 Flask 项目的脚本
# 功能：
# 1. 自动进入项目目录
# 2. 自动激活虚拟环境
# 3. 自动杀掉 5000 端口的旧进程
# 4. 自动初始化/补全数据库
# 5. 自动启动 Flask
# ==========================================

set -e  # 出错立即退出

# 项目路径
PROJECT_DIR=~/Desktop/logistics-starter

# 进入项目目录
cd "$PROJECT_DIR" || exit 1

# 激活虚拟环境
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> 激活虚拟环境..."
source .venv/bin/activate

# 杀掉占用 5000 端口的进程
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> 检查并清理 5000 端口..."
lsof -ti:5000 | xargs kill -9 2>/dev/null || true
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> 5000 端口已释放"

# 初始化/补全数据库（不管存不存在，都会运行一次）
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> 检查数据库并补全缺失表/字段..."
python init_db.py
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> 数据库检查完成"

# 启动 Flask
echo "[$(date '+%Y-%m-%d %H:%M:%S')] >>> 正在启动 Flask 应用..."
exec python app.py