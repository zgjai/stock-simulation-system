"""
数据库连接和ORM模型 - SQLite 版本

使用本地 SQLite 数据库
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, Date, Numeric, BigInteger, SmallInteger, Boolean, Index, TIMESTAMP, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 数据库文件路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "stock.db"

# 确保 data 目录存在
DB_PATH.parent.mkdir(exist_ok=True)

# 数据库连接URL
DATABASE_URL = f"sqlite:///{DB_PATH}"

# 创建引擎（SQLite 配置）
engine = create_engine(
    DATABASE_URL,
    connect_args={
        'check_same_thread': False,  # 允许多线程访问
        'timeout': 30,  # 锁超时时间（秒）
    },
    pool_size=5,  # 连接池大小
    max_overflow=10,
    pool_pre_ping=True,
    echo=False  # 生产环境关闭SQL日志
)

# 启用 WAL 模式和性能优化
with engine.connect() as conn:
    conn.execute(text("PRAGMA journal_mode=WAL"))  # WAL 模式（提升并发）
    conn.execute(text("PRAGMA synchronous=NORMAL"))  # 平衡性能和安全
    conn.execute(text("PRAGMA cache_size=-64000"))  # 64MB 缓存
    conn.execute(text("PRAGMA temp_store=MEMORY"))  # 临时表在内存
    conn.commit()

# 会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ORM基类
Base = declarative_base()


class StockDaily(Base):
    """股票日线数据表"""
    __tablename__ = "stock_daily"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    
    # OHLCV
    open = Column(Numeric(10, 2))
    high = Column(Numeric(10, 2))
    low = Column(Numeric(10, 2))
    close = Column(Numeric(10, 2))
    volume = Column(BigInteger)
    prev_close = Column(Numeric(10, 2))
    amount = Column(Numeric(18, 2))
    
    # 技术指标
    ma5 = Column(Numeric(10, 2))
    ma10 = Column(Numeric(10, 2))
    vol_ma5 = Column(BigInteger)
    vol_ma60 = Column(BigInteger)
    kdj_k = Column(Numeric(10, 2))
    kdj_d = Column(Numeric(10, 2))
    kdj_j = Column(Numeric(10, 2))
    macd_dif = Column(Numeric(10, 4))
    macd_dea = Column(Numeric(10, 4))
    macd_hist = Column(Numeric(10, 4))
    
    # 知行和单针指标
    ema10_2 = Column(Numeric(10, 2))  # 知行短期趋势线
    multi_line = Column(Numeric(10, 2))  # 知行多空线
    wash_short = Column(Numeric(10, 2))  # 单针短期
    wash_long = Column(Numeric(10, 2))  # 单针长期
    
    # 策略信号
    b1_signal = Column(SmallInteger, default=0)
    b2_signal = Column(SmallInteger, default=0)
    single_needle_signal = Column(SmallInteger, default=0)
    brick_signal = Column(SmallInteger, default=0)  # 砖型选股信号
    
    # 砖型图指标
    # 概念说明：
    #   砖型图          : 由红柱/绿柱构成的动量指标（今日>昨日=红柱，今日<昨日=绿柱，=0为超跌消失区）
    #   砖型图柱体长度   : brick_value，红柱或绿柱本身的数值（≥0），反映当日动量绝对高度
    #   动量柱          : brick_delta（派生，不存DB）= brick_value - REF(brick_value,1)，有符号
    #                     正数=红动量柱（动量扩张），负数=绿动量柱（动量收缩）
    #   动量柱柱体长度   : brick_body，= ABS(brick_delta)，反映变化幅度，不含方向
    brick_value = Column(Numeric(10, 4))   # 砖型图柱体长度（红/绿柱数值，≥0）
    brick_body  = Column(Numeric(10, 4))   # 动量柱柱体长度（ABS(今日brick_value - 昨日brick_value)，≥0）
    
    # 关键因子
    factor_amplitude = Column(Numeric(10, 2))
    factor_volume_ratio = Column(Numeric(10, 4))
    factor_j_value = Column(Numeric(10, 2))
    
    __table_args__ = (
        Index('idx_code_date', 'stock_code', 'trade_date', unique=True),
        Index('idx_date_b1', 'trade_date', 'b1_signal'),
        Index('idx_date_b2', 'trade_date', 'b2_signal'),
        Index('idx_date_brick', 'trade_date', 'brick_signal'),
    )


class StrategyPick(Base):
    """策略候选池表"""
    __tablename__ = "strategy_picks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy = Column(String(50), nullable=False, index=True)
    trade_date = Column(Date, nullable=False, index=True)
    stock_code = Column(String(10), nullable=False)
    
    close = Column(Numeric(10, 2))
    change_pct = Column(Numeric(10, 2))
    volume = Column(BigInteger)
    is_extreme_b1 = Column(Boolean, default=False)
    consecutive_extreme_b1_days = Column(Integer, default=0)
    
    # 关键因子（用于极致B1筛选）
    factor_amplitude = Column(Numeric(10, 2))
    factor_volume_ratio = Column(Numeric(10, 4))
    
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
    period = Column(Integer, nullable=False)
    stock_code = Column(String(10), nullable=False)
    future_return = Column(Numeric(10, 4))
    rank_position = Column(Integer)
    
    __table_args__ = (
        Index('idx_strategy_date_period', 'strategy', 'trade_date', 'period'),
        Index('idx_unique_case', 'strategy', 'trade_date', 'period', 'stock_code', unique=True),
    )


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True)
    phone = Column(String(20), unique=True)
    email = Column(String(100), unique=True)
    wechat_openid = Column(String(100), unique=True)
    password_hash = Column(String(255))
    vip_level = Column(Integer, default=0)
    vip_expire_date = Column(Date)
    created_at = Column(TIMESTAMP)
    updated_at = Column(TIMESTAMP)
    
    __table_args__ = (
        Index('idx_username', 'username'),
        Index('idx_wechat', 'wechat_openid'),
    )


class BacktestSession(Base):
    """回测会话表"""
    __tablename__ = "backtest_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer)  # 暂不设置外键
    session_id = Column(String(50), unique=True, nullable=False)
    start_date = Column(String(8))
    end_date = Column(String(8))
    current_date = Column(String(8))
    initial_capital = Column(Numeric(15, 2))
    final_equity = Column(Numeric(15, 2))
    cash = Column(Numeric(15, 2))
    status = Column(String(20), default='running')
    strategy = Column(String(50))
    slippage = Column(Numeric(10, 4))
    commission_rate = Column(Numeric(10, 4))
    created_at = Column(TIMESTAMP)
    updated_at = Column(TIMESTAMP)
    
    __table_args__ = (
        Index('idx_user_created', 'user_id', 'created_at'),
        Index('idx_session_id', 'session_id'),
        Index('idx_status', 'status'),
    )


class BacktestPosition(Base):
    """回测持仓表"""
    __tablename__ = "backtest_positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(50), nullable=False, index=True)
    stock_code = Column(String(10), nullable=False)
    shares = Column(Integer)
    cost_price = Column(Numeric(10, 2))
    buy_date = Column(String(8))
    buy_trade_days = Column(Integer)
    status = Column(String(20), default='holding')  # holding/sold
    
    __table_args__ = (
        Index('idx_session_code', 'session_id', 'stock_code'),
        Index('idx_session_status', 'session_id', 'status'),
    )


class BacktestTrade(Base):
    """回测交易记录表"""
    __tablename__ = "backtest_trades"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(50), nullable=False, index=True)
    trade_date = Column(String(8), nullable=False)
    stock_code = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)  # buy/sell
    shares = Column(Integer)
    price = Column(Numeric(10, 2))
    amount = Column(Numeric(15, 2))
    commission = Column(Numeric(15, 2))
    profit = Column(Numeric(15, 2))
    profit_rate = Column(Numeric(10, 4))
    created_at = Column(TIMESTAMP)
    
    __table_args__ = (
        Index('idx_session_date', 'session_id', 'trade_date'),
    )


# 依赖注入：获取数据库会话
def get_db():
    """
    获取数据库会话（用于FastAPI依赖注入）
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
    print(f"✅ 数据库表创建完成: {DB_PATH}")
    print(f"📊 数据库大小: {DB_PATH.stat().st_size / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    # 测试连接
    print(f"数据库路径: {DB_PATH}")
    create_tables()
