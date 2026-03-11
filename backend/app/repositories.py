"""
数据访问层 - Repository 模式

封装所有数据库查询逻辑，提供缓存优化
"""

from typing import List, Dict, Optional
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from functools import lru_cache
import redis
import json

from app.database import StockDaily, StrategyPick, LearningCase

# Redis缓存（可选，用于高并发场景）
REDIS_ENABLED = False
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    redis_client.ping()
    REDIS_ENABLED = True
except:
    redis_client = None


class StockRepository:
    """股票数据仓库"""
    
    @staticmethod
    def get_stock_by_date(db: Session, stock_code: str, trade_date: date) -> Optional[Dict]:
        """
        获取指定日期的股票数据
        
        Args:
            db: 数据库会话
            stock_code: 股票代码
            trade_date: 交易日期
            
        Returns:
            股票数据字典 or None
        """
        # 尝试从Redis缓存读取
        if REDIS_ENABLED:
            cache_key = f"stock:{stock_code}:{trade_date}"
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        
        # 数据库查询
        row = db.query(StockDaily).filter(
            and_(
                StockDaily.stock_code == stock_code,
                StockDaily.trade_date == trade_date
            )
        ).first()
        
        if not row:
            return None
        
        # 转换为字典
        data = {
            'stock_code': row.stock_code,
            'date': row.trade_date.strftime('%Y%m%d'),
            'open': float(row.open) if row.open else None,
            'high': float(row.high) if row.high else None,
            'low': float(row.low) if row.low else None,
            'close': float(row.close) if row.close else None,
            'volume': int(row.volume) if row.volume else 0,
            'prev_close': float(row.prev_close) if row.prev_close else None,
            'kdj_k': float(row.kdj_k) if row.kdj_k else None,
            'kdj_d': float(row.kdj_d) if row.kdj_d else None,
            'kdj_j': float(row.kdj_j) if row.kdj_j else None,
            'macd_dif': float(row.macd_dif) if row.macd_dif else None,
            'macd_dea': float(row.macd_dea) if row.macd_dea else None,
            'macd_hist': float(row.macd_hist) if row.macd_hist else None,
            'ma5': float(row.ma5) if row.ma5 else None,
            'ma10': float(row.ma10) if row.ma10 else None,
            'vol_ma5': int(row.vol_ma5) if row.vol_ma5 else 0,
            'vol_ma60': int(row.vol_ma60) if row.vol_ma60 else 0,
            'b1_signal': row.b1_signal,
            'b2_signal': row.b2_signal,
            'single_needle_signal': row.single_needle_signal,
            'factor_amplitude': float(row.factor_amplitude) if row.factor_amplitude else None,
            'factor_volume_ratio': float(row.factor_volume_ratio) if row.factor_volume_ratio else None,
        }
        
        # 写入Redis缓存（过期时间1小时）
        if REDIS_ENABLED:
            redis_client.setex(cache_key, 3600, json.dumps(data))
        
        return data
    
    @staticmethod
    def get_stock_kline(db: Session, stock_code: str, end_date: date, limit: int = 60) -> List[Dict]:
        """
        获取K线数据
        
        Args:
            db: 数据库会话
            stock_code: 股票代码
            end_date: 截止日期
            limit: 返回条数
            
        Returns:
            K线数据列表
        """
        rows = db.query(StockDaily).filter(
            and_(
                StockDaily.stock_code == stock_code,
                StockDaily.trade_date <= end_date
            )
        ).order_by(StockDaily.trade_date.desc()).limit(limit).all()
        
        # 反转顺序（从旧到新）
        rows = list(reversed(rows))
        
        klines = []
        for row in rows:
            klines.append({
                'date': row.trade_date.strftime('%Y-%m-%d'),
                'open': float(row.open) if row.open else None,
                'high': float(row.high) if row.high else None,
                'low': float(row.low) if row.low else None,
                'close': float(row.close) if row.close else None,
                'volume': int(row.volume) if row.volume else 0,
                'kdj_k': float(row.kdj_k) if row.kdj_k else None,
                'kdj_d': float(row.kdj_d) if row.kdj_d else None,
                'kdj_j': float(row.kdj_j) if row.kdj_j else None,
                'macd_dif': float(row.macd_dif) if row.macd_dif else None,
                'macd_dea': float(row.macd_dea) if row.macd_dea else None,
                'macd_hist': float(row.macd_hist) if row.macd_hist else None,
                'vol_ma5': int(row.vol_ma5) if row.vol_ma5 else 0,
                'vol_ma60': int(row.vol_ma60) if row.vol_ma60 else 0,
                'b1_signal': row.b1_signal,
                'b2_signal': row.b2_signal,
            })
        
        return klines


class StrategyRepository:
    """策略数据仓库"""
    
    @staticmethod
    def get_picks_by_date(db: Session, strategy: str, trade_date: date, 
                          filter_type: str = 'all') -> List[Dict]:
        """
        获取指定日期的候选池
        
        Args:
            db: 数据库会话
            strategy: 策略名称
            trade_date: 交易日期
            filter_type: 筛选类型（all/extreme_b1）
            
        Returns:
            候选股票列表
        """
        query = db.query(
            StrategyPick.stock_code,
            StrategyPick.close,
            StrategyPick.change_pct,
            StrategyPick.volume,
            StrategyPick.is_extreme_b1,
            StrategyPick.consecutive_extreme_b1_days
        ).filter(
            and_(
                StrategyPick.strategy == strategy,
                StrategyPick.trade_date == trade_date
            )
        )
        
        # 筛选极致B1
        if filter_type == 'extreme_b1':
            query = query.filter(StrategyPick.is_extreme_b1 == True)
        
        rows = query.all()
        
        stocks = []
        for row in rows:
            stocks.append({
                'code': row.stock_code,
                'close': float(row.close) if row.close else None,
                'change_pct': float(row.change_pct) if row.change_pct else None,
                'volume': int(row.volume) if row.volume else 0,
                'is_extreme_b1': row.is_extreme_b1,
                'consecutive_extreme_b1_days': row.consecutive_extreme_b1_days,
            })
        
        return stocks
    
    @staticmethod
    def get_all_trade_dates(db: Session, strategy: str = 'B1') -> List[str]:
        """
        获取所有交易日期
        
        Args:
            db: 数据库会话
            strategy: 策略名称
            
        Returns:
            日期列表（YYYYMMDD格式）
        """
        rows = db.query(StrategyPick.trade_date).filter(
            StrategyPick.strategy == strategy
        ).distinct().order_by(StrategyPick.trade_date).all()
        
        return [row.trade_date.strftime('%Y%m%d') for row in rows]


class LearningCaseRepository:
    """学习案例仓库"""
    
    @staticmethod
    def get_top_cases(db: Session, strategy: str, trade_date: date, 
                      period: int, limit: int = 5) -> List[Dict]:
        """
        获取学习案例TOP股票
        
        Args:
            db: 数据库会话
            strategy: 策略名称
            trade_date: 交易日期
            period: 周期（3/5/10）
            limit: 返回数量
            
        Returns:
            TOP股票列表
        """
        rows = db.query(LearningCase).filter(
            and_(
                LearningCase.strategy == strategy,
                LearningCase.trade_date == trade_date,
                LearningCase.period == period
            )
        ).order_by(LearningCase.rank_position).limit(limit).all()
        
        cases = []
        for row in rows:
            cases.append({
                'code': row.stock_code,
                'future_return': float(row.future_return) if row.future_return else None,
                'rank': row.rank_position,
            })
        
        return cases


# 导出
__all__ = [
    'StockRepository',
    'StrategyRepository', 
    'LearningCaseRepository',
]
