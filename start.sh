#!/bin/bash

# A股主观回测系统启动脚本

echo "======================================"
echo "  A股主观回测模拟系统"
echo "======================================"
echo ""

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到Python3，请先安装Python 3.8+"
    exit 1
fi

# 检查Node环境
if ! command -v node &> /dev/null; then
    echo "❌ 错误: 未找到Node.js，请先安装Node.js 18+"
    exit 1
fi

# 检查后端依赖（使用系统Python，兼容conda环境）
if [ ! -d "backend/venv" ]; then
    echo "⚠️  未找到Python虚拟环境"
    echo "💡 使用系统Python环境（支持conda）"
fi

# 检查必要的Python包
echo "🔍 检查Python依赖..."
python3 -c "import fastapi, uvicorn, sqlalchemy" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  缺少必要的Python包，请安装:"
    echo "   pip install fastapi uvicorn sqlalchemy"
    read -p "是否继续启动? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ Python依赖完整"
fi

# 检查前端依赖
if [ ! -d "frontend/node_modules" ]; then
    echo "⚠️  未找到Node依赖，正在安装..."
    cd frontend
    npm install
    cd ..
    echo "✅ Node依赖安装完成"
else
    echo "✅ Node依赖已存在"
fi

# 检查数据库文件
if [ ! -f "data/stock.db" ]; then
    echo ""
    echo "⚠️  警告: 未找到SQLite数据库文件"
    echo "请先运行数据迁移脚本:"
    echo "  ./migrate_sqlite.sh"
    echo ""
    read -p "是否继续启动系统? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ 数据库文件存在"
fi

echo ""
echo "🚀 正在启动系统..."
echo ""

# 创建日志目录
mkdir -p logs

# 启动后端
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

# 启动前端
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
echo "✅ 系统启动成功！"
echo "======================================"
echo ""
echo "📍 访问地址: http://localhost:5173"
echo "📍 API文档:  http://127.0.0.1:8000/docs"
echo ""
echo "💡 查看日志:"
echo "  后端日志: tail -f logs/backend.log"
echo "  前端日志: tail -f logs/frontend.log"
echo ""
echo "💡 查看运行状态:"
echo "  ps aux | grep uvicorn"
echo "  ps aux | grep vite"
echo ""
echo "🛑 停止系统:"
echo "  ./stop.sh"
echo ""
echo "🔧 快速重启:"
echo "  ./restart.sh"
echo ""
