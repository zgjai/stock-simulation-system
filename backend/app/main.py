"""FastAPI主应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yaml
from pathlib import Path

# 加载配置
config_path = Path(__file__).parent.parent.parent / 'config.yaml'
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# 创建FastAPI应用
app = FastAPI(
    title="股票回测系统 API",
    description="A股主观回测模拟系统后端API",
    version="1.0.0"
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 导入路由
from app.api import basic, strategy, backtest
# 导入数据库版本API（v2版本）
from app.api import strategy_v2, backtest_v2

app.include_router(basic.router, prefix="/api", tags=["基础查询"])

# 旧版API（文件读取）
app.include_router(strategy.router, prefix="/api/v1", tags=["选股策略-文件版"])
app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["回测管理-文件版"])

# 新版API（数据库查询）⭐ 推荐使用
app.include_router(strategy_v2.router, prefix="/api", tags=["选股策略-数据库版"])
app.include_router(backtest_v2.router, prefix="/api/backtest", tags=["回测管理-数据库版"])


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "股票回测系统 API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    
    host = config['api']['host']
    port = config['api']['port']
    
    print(f"\n{'='*60}")
    print(f"股票回测系统 API 启动中...")
    print(f"地址: http://{host}:{port}")
    print(f"文档: http://{host}:{port}/docs")
    print(f"{'='*60}\n")
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True
    )
