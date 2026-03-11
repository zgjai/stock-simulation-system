#!/bin/bash

# SQLite 数据库迁移 - 一键脚本
# 使用方法：./migrate_sqlite.sh

set -e  # 遇到错误立即退出

echo "============================================================"
echo "SQLite 数据库迁移 - 一键脚本"
echo "============================================================"

# 检查 Python 版本
PYTHON_CMD="python3"
if ! command -v $PYTHON_CMD &> /dev/null; then
    PYTHON_CMD="python"
fi

echo "使用 Python: $($PYTHON_CMD --version)"

# 第一步：安装依赖
echo ""
echo "【1/3】安装依赖..."
cd backend
$PYTHON_CMD -m pip install -q sqlalchemy==2.0.23 tqdm==4.66.1
echo "✅ 依赖安装完成"

# 第二步：创建数据库表
echo ""
echo "【2/3】创建数据库表..."
cd ..
$PYTHON_CMD -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from backend.app.database_sqlite import create_tables
create_tables()
"
echo "✅ 数据库表创建完成"

# 第三步：数据迁移
echo ""
echo "【3/3】开始数据迁移（预计 10-20 分钟）..."
$PYTHON_CMD backend/scripts/migrate_to_sqlite.py

echo ""
echo "============================================================"
echo "🎉 迁移完成！"
echo "============================================================"
echo ""
echo "下一步："
echo "  1. 启动后端: cd backend && uvicorn app.main:app --reload --port 8000"
echo "  2. 启动前端: cd frontend && npm run dev"
echo "  3. 测试API: curl http://localhost:8000/api/picks?date=20251231&strategy=B1"
echo "  4. 查看数据库: sqlite3 data/stock.db"
echo ""
echo "⚠️ 重要修复说明："
echo "  - 已修复回测 session_id 丢失问题"
echo "  - 已修复 API 404 路由问题"
echo "  - 已修复 Vue ElCheckbox 警告"
echo "  - 已配置 Vite 代理转发"
echo ""
