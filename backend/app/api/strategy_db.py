"""
选股策略API - 数据库版本

重构说明：
1. 所有文件读取改为数据库查询
2. 使用 Repository 模式分离业务逻辑
3. 添加依赖注入获取数据库会话
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories import StockRepository, StrategyRepository

router = APIRouter()


@router.get("/picks")
async def get_picks(
    date: str = Query(..., description="日期（YYYYMMDD格式）"),
    strategy: str = Query(..., description="策略名称（B1/B2/single_needle）"),
    filter_type: str = Query("all", description="筛选类型（all/extreme_b1）"),
    db: Session = Depends(get_db)
):
    """
    获取指定日期和策略的候选池（从数据库读取）
    
    性能优化：
    - 单次数据库查询获取所有候选股票
    - 无需遍历文件系统
    - 支持索引优化
    """
    try:
        # 解析日期
        trade_date = datetime.strptime(date, "%Y%m%d").date()
        
        # 从数据库获取候选池
        stocks = StrategyRepository.get_picks_by_date(
            db=db,
            strategy=strategy,
            trade_date=trade_date,
            filter_type=filter_type
        )
        
        return {
            "date": date,
            "strategy": strategy,
            "filter_type": filter_type,
            "count": len(stocks),
            "extreme_b1_count": sum(1 for s in stocks if s.get('is_extreme_b1', False)),
            "stocks": stocks
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock/kline")
async def get_stock_kline(
    code: str = Query(..., description="股票代码"),
    end_date: str = Query(..., description="截止日期（YYYYMMDD）"),
    limit: int = Query(60, description="K线数量"),
    db: Session = Depends(get_db)
):
    """
    获取股票K线数据（从数据库读取）
    
    性能优化：
    - 单次SQL查询 + ORDER BY + LIMIT
    - 利用索引：(stock_code, trade_date)
    - 避免加载整个CSV文件
    """
    try:
        # 解析日期
        trade_date = datetime.strptime(end_date, "%Y%m%d").date()
        
        # 从数据库获取K线
        klines = StockRepository.get_stock_kline(
            db=db,
            stock_code=code,
            end_date=trade_date,
            limit=limit
        )
        
        if not klines:
            raise HTTPException(status_code=404, detail=f"股票 {code} 数据不存在")
        
        return {
            "code": code,
            "count": len(klines),
            "klines": klines
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trade-dates")
async def get_trade_dates(
    strategy: str = Query("B1", description="策略名称"),
    db: Session = Depends(get_db)
):
    """
    获取所有交易日期（从数据库读取）
    
    性能优化：
    - DISTINCT + ORDER BY 查询
    - 利用索引
    """
    try:
        dates = StrategyRepository.get_all_trade_dates(db=db, strategy=strategy)
        
        return {
            "strategy": strategy,
            "count": len(dates),
            "dates": dates
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
