#!/bin/bash

# A股主观回测系统重启脚本

echo "======================================"
echo "  重启A股主观回测系统"
echo "======================================"
echo ""

# 停止现有服务
echo "🛑 停止现有服务..."
pkill -f "uvicorn app.main:app"
pkill -f "vite"
sleep 2

# 清理可能残留的进程
pkill -9 -f "uvicorn app.main:app" 2>/dev/null
pkill -9 -f "vite" 2>/dev/null

echo "✅ 现有服务已停止"
echo ""

# 创建日志目录
mkdir -p logs

# 重新启动后端
echo "📦 启动后端服务 (http://127.0.0.1:8000)"
cd backend
# 使用系统Python（兼容conda环境）
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > ../logs/backend.log 2>&1 &
BACKEND_PID=$!
cd ..
echo "   后端进程ID: $BACKEND_PID"

# 等待后端启动
echo "   等待后端启动..."
for i in {1..10}; do
    curl -s http://127.0.0.1:8000/health > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "   ✅ 后端已就绪"
        break
    fi
    sleep 1
    echo -n "."
done
echo ""

# 重新启动前端
echo "🎨 启动前端服务 (http://localhost:5173)"
cd frontend
nohup npm run dev > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo "   前端进程ID: $FRONTEND_PID"

# 等待前端启动
echo "   等待前端启动..."
sleep 3

echo ""
echo "======================================"
echo "✅ 系统重启成功！"
echo "======================================"
echo ""
echo "📍 访问地址: http://localhost:5173"
echo "📍 API文档:  http://127.0.0.1:8000/docs"
echo ""
echo "💡 查看日志:"
echo "  后端日志: tail -f logs/backend.log"
echo "  前端日志: tail -f logs/frontend.log"
echo ""
echo "💡 测试API:"
echo "  curl http://127.0.0.1:8000/health"
echo ""
