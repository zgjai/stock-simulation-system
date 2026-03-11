#!/bin/bash

# A股主观回测系统停止脚本

echo "======================================"
echo "  停止A股主观回测系统"
echo "======================================"
echo ""

# 停止后端 (FastAPI/Uvicorn)
echo "🛑 停止后端服务..."
pkill -f "uvicorn app.main:app"

# 停止前端 (Vite)
echo "🛑 停止前端服务..."
pkill -f "vite"

# 等待进程结束
sleep 2

# 检查是否成功停止
if pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "⚠️  后端服务未完全停止，尝试强制停止..."
    pkill -9 -f "uvicorn app.main:app"
fi

if pgrep -f "vite" > /dev/null; then
    echo "⚠️  前端服务未完全停止，尝试强制停止..."
    pkill -9 -f "vite"
fi

echo ""
echo "✅ 系统已停止"
echo ""
