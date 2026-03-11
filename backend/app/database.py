"""
数据库连接和ORM模型

使用 SQLAlchemy 进行数据库操作
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Date, Decimal, BigInteger, SmallInteger, Boolean, Index, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from functools import lru_cache

# 加载环境变量
load_dotenv()

# 数据库连接URL（优先从环境变量读取）
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("⚠️  警告: DATABASE_URL 未设置，使用默认本地数据库")
    DATABASE_URL = "postgresql://localhost:5432/stock_system"

# 创建引擎（支持连接池，针对 Supabase 优化）
engine = create_engine(
    DATABASE_URL,
    pool_size=20,  # 连接池大小
    max_overflow=40,  # 最大溢出连接数
    pool_pre_ping=True,  # 连接前测试（重要！避免连接超时）
    pool_recycle=3600,  # 1小时回收连接
    pool_timeout=30,  # 连接超时时间
    echo=False,  # 生产环境关闭SQL日志
    connect_args={
        'connect_timeout': 10,  # TCP连接超时
    } if 'supabase.co' in DATABASE_URL else {}
)

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ORM基类
Base = declarative_base()


class StockDaily(Base):
    """股票日线数据表"""
    __tablename__ = "stock_daily"
    
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    
    # OHLCV
    open = Column(Decimal(10, 2))
    high = Column(Decimal(10, 2))
    low = Column(Decimal(10, 2))
    close = Column(Decimal(10, 2))
    volume = Column(BigInteger)
    prev_close = Column(Decimal(10, 2))
    
    # 技术指标
    kdj_k = Column(Decimal(10, 2))
    kdj_d = Column(Decimal(10, 2))
    kdj_j = Column(Decimal(10, 2))
    macd_dif = Column(Decimal(10, 4))
    macd_dea = Column(Decimal(10, 4))
    macd_hist = Column(Decimal(10, 4))
    ma5 = Column(Decimal(10, 2))
    ma10 = Column(Decimal(10, 2))
    vol_ma5 = Column(BigInteger)
    vol_ma60 = Column(BigInteger)
    
    # 策略信号
    b1_signal = Column(SmallInteger, default=0)
    b2_signal = Column(SmallInteger, default=0)
    single_needle_signal = Column(SmallInteger, default=0)
    
    # 因子数据
    factor_amplitude = Column(Decimal(10, 2))
    factor_volume_ratio = Column(Decimal(10, 4))
    factor_zhixing_ratio = Column(Decimal(10, 4))
    factor_j_value = Column(Decimal(10, 2))
    
    __table_args__ = (
        Index('idx_code_date', 'stock_code', 'trade_date', unique=True),
        Index('idx_b1_signal', 'trade_date', 'b1_signal'),
        Index('idx_b2_signal', 'trade_date', 'b2_signal'),
    )


class StrategyPick(Base):
    """策略候选池表"""
    __tablename__ = "strategy_picks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy = Column(String(50), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    stock_code = Column(String(10), nullable=False)
    
    close = Column(Decimal(10, 2))
    change_pct = Column(Decimal(10, 2))
    volume = Column(BigInteger)
    is_extreme_b1 = Column(Boolean, default=False)
    consecutive_extreme_b1_days = Column(Integer, default=0)
    
    __table_args__ = (
        Index('idx_strategy_date', 'strategy', 'trade_date'),
        Index('idx_strategy_date_code', 'strategy', 'trade_date', 'stock_code', unique=True),
    )


class LearningCase(Base):
    """学习案例表"""
    __tablename__ = "learning_cases"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy = Column(String(50), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    period = Column(Integer, nullable=False)  # 3/5/10日
    stock_code = Column(String(10), nullable=False)
    future_return = Column(Decimal(10, 4))
    rank_position = Column(Integer)
    
    __table_args__ = (
        Index('idx_strategy_date_period', 'strategy', 'trade_date', 'period'),
        Index('idx_unique_case', 'strategy', 'trade_date', 'period', 'stock_code', unique=True),
    )


class User(Base):
    """用户表（为用户系统预留）"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True)
    phone = Column(String(20), unique=True)
    email = Column(String(100), unique=True)
    wechat_openid = Column(String(100), unique=True)
    password_hash = Column(String(255))
    vip_level = Column(Integer, default=0)
    vip_expire_date = Column(Date)
    created_at = Column(TIMESTAMP, server_default='NOW()')
    updated_at = Column(TIMESTAMP, server_default='NOW()', onupdate='NOW()')
    
    __table_args__ = (
        Index('idx_username', 'username'),
        Index('idx_wechat', 'wechat_openid'),
    )


class BacktestSession(Base):
    """回测会话表（为用户系统预留）"""
    __tablename__ = "backtest_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)  # 外键暂不启用，等用户系统完成后再关联
    session_id = Column(String(50), unique=True, nullable=False)
    start_date = Column(String(8))
    end_date = Column(String(8))
    initial_capital = Column(Decimal(15, 2))
    final_equity = Column(Decimal(15, 2))
    status = Column(String(20), default='running')
    created_at = Column(TIMESTAMP, server_default='NOW()')
    updated_at = Column(TIMESTAMP, server_default='NOW()', onupdate='NOW()')
    
    __table_args__ = (
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_session_id', 'session_id'),
    )


# 依赖注入：获取数据库会话
def get_db():
    """
    获取数据库会话（用于FastAPI依赖注入）
    
    用法：
        @app.get("/api/data")
        def get_data(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 创建所有表
def create_tables():
    """创建所有数据库表"""
    Base.metadata.create_all(bind=engine)
    print("✅ 数据库表创建完成")


if __name__ == "__main__":
    # 测试连接
    print(f"数据库连接: {DATABASE_URL}")
    create_tables()
