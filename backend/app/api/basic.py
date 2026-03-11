"""基础查询API"""
from fastapi import APIRouter, HTTPException
from typing import List
import os
import json
import pandas as pd
from datetime import datetime

router = APIRouter()

# 数据路径（从配置读取）
PROCESSED_PATH = "processed_data"
INDEX_PATH = "strategy_index"


@router.get("/trade-dates")
async def get_trade_dates():
    """
    获取所有交易日列表
    
    Returns:
        交易日列表（YYYYMMDD格式）
    """
    try:
        # 从任一股票文件中提取交易日
        sample_files = [f for f in os.listdir(PROCESSED_PATH) if f.endswith('.csv')]
        if not sample_files:
            raise HTTPException(status_code=500, detail="没有找到处理后的数据文件")
        
        sample_file = f"{PROCESSED_PATH}/{sample_files[0]}"
        df = pd.read_csv(sample_file, usecols=['date'])
        dates = pd.to_datetime(df['date']).dt.strftime('%Y%m%d').tolist()
        
        return {
            "dates": dates,
            "count": len(dates),
            "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies")
async def get_strategies():
    """
    获取策略列表
    
    Returns:
        策略列表
    """
    return {
        "strategies": [
            {"id": "B1", "name": "B1选股", "description": "低位+窄幅+量温和+多头支撑"},
            {"id": "B2", "name": "B2选股", "description": "两日联动：打底+起爆"},
            {"id": "brick", "name": "砖型选股", "description": "砖型动量柱绿转红+知行多头+收盘高于多空线"},
            {"id": "single_needle", "name": "单针选股", "description": "高位双针后转弱"}
        ]
    }


@router.get("/stock/list")
async def get_stock_list():
    """
    获取所有股票列表
    
    Returns:
        股票代码列表
    """
    try:
        files = [f.replace('.csv', '') for f in os.listdir(PROCESSED_PATH) if f.endswith('.csv')]
        return {
            "stocks": sorted(files),
            "count": len(files)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
