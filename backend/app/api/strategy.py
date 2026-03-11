"""选股策略API"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
import os
import json
import pandas as pd
import numpy as np
from pathlib import Path
from functools import lru_cache

router = APIRouter()

# 获取项目根目录的绝对路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
PROCESSED_PATH = str(PROJECT_ROOT / "processed_data")
INDEX_PATH = str(PROJECT_ROOT / "strategy_index")

# 添加内存缓存
_picks_cache = {}


@lru_cache(maxsize=1000)
def get_stock_data_cached(stock_code: str, date: str):
    """
    缓存版本的股票数据读取
    
    Args:
        stock_code: 股票代码
        date: 日期
        
    Returns:
        股票数据字典或None
    """
    try:
        stock_file = f"{PROCESSED_PATH}/{stock_code}.csv"
        df = pd.read_csv(stock_file)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
        
        row = df[df['date'] == date]
        if len(row) > 0:
            return row.iloc[0].to_dict()
        return None
    except Exception:
        return None


def check_b1_condition(row_data: dict) -> bool:
    """检查是否满足B1策略条件"""
    b1_signal = row_data.get('b1_signal', 0)
    return b1_signal == 1


def check_extreme_b1_condition(stock_code: str, row_data: dict, check_b1_first: bool = False) -> bool:
    """
    检查是否满足极致B1条件
    
    Args:
        stock_code: 股票代码
        row_data: 当日数据字典
        check_b1_first: 是否先检查B1条件(用于前N日判断)
        
    Returns:
        是否满足极致B1条件
    """
    # 如果需要先检查B1条件(用于前N日)
    if check_b1_first:
        if not check_b1_condition(row_data):
            return False
    
    # 获取因子数据
    try:
        amplitude = row_data.get('factor_amplitude')
        volume_ratio = row_data.get('factor_volume_ratio')
    except Exception:
        return False
    
    if amplitude is None or volume_ratio is None or pd.isna(amplitude) or pd.isna(volume_ratio):
        return False
    
    # 判断市场分组
    prefix = stock_code[:2]
    if prefix in ['00', '60']:
        # 主板(00/60): 当日振幅>=2.68 且 成交量比率>=0.59
        return amplitude >= 2.68 and volume_ratio >= 0.59
    elif prefix in ['30', '68', '92']:
        # 创业板/科创板/北交所(30/68/92): 当日振幅>=3.46 且 成交量比率>=0.42
        return amplitude >= 3.46 and volume_ratio >= 0.42
    else:
        return False


def get_all_trade_dates(strategy: str = 'B1') -> List[str]:
    """获取所有交易日期(升序)"""
    strategy_dir = f"{INDEX_PATH}/{strategy}"
    if not os.path.exists(strategy_dir):
        return []
    
    dates = []
    for filename in os.listdir(strategy_dir):
        if filename.endswith('.json'):
            date_str = filename.replace('.json', '')
            dates.append(date_str)
    
    return sorted(dates)


def get_consecutive_extreme_b1_days(stock_code: str, date: str, max_days: int = 5) -> int:
    """
    计算截止到前一日,连续极致B1的天数
    
    Args:
        stock_code: 股票代码
        date: 当前日期
        max_days: 最大追溯天数
        
    Returns:
        连续极致B1天数 (0-max_days)
        0: 前一日不是极致B1
        1: 前1日是极致B1(前2日不是)
        2: 前1-2日都是极致B1(前3日不是)
        ...
    """
    try:
        # 获取所有交易日期
        all_dates = get_all_trade_dates()
        if not all_dates:
            return 0
        
        # 找到当前日期的索引
        try:
            curr_idx = all_dates.index(date)
        except ValueError:
            return 0
        
        # 读取股票数据
        stock_file = f"{PROCESSED_PATH}/{stock_code}.csv"
        if not os.path.exists(stock_file):
            return 0
        
        df = pd.read_csv(stock_file)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
        
        consecutive_days = 0
        
        # 从前1日开始向前追溯
        for i in range(1, max_days + 1):
            if curr_idx - i < 0:
                break
            
            prev_date = all_dates[curr_idx - i]
            prev_row = df[df['date'] == prev_date]
            
            if prev_row.empty:
                break
            
            prev_data = prev_row.iloc[0].to_dict()
            
            # 检查前N日是否满足极致B1(需要先检查B1条件)
            if check_extreme_b1_condition(stock_code, prev_data, check_b1_first=True):
                consecutive_days = i
            else:
                break  # 一旦中断就停止
        
        return consecutive_days
        
    except Exception:
        return 0


@router.get("/picks")
async def get_picks(
    date: str = Query(..., description="日期（YYYYMMDD格式）"),
    strategy: str = Query(..., description="策略名称（B1/B2/single_needle）"),
    filter_type: str = Query("all", description="筛选类型（all/extreme_b1）")
):
    """
    获取指定日期和策略的候选池
    
    Args:
        date: 日期（YYYYMMDD格式）
        strategy: 策略名称
        filter_type: 筛选类型（all=全部, extreme_b1=极致B1）
        
    Returns:
        候选池信息
    """
    try:
        # 检查缓存
        cache_key = f"{date}_{strategy}_{filter_type}"
        if cache_key in _picks_cache:
            return _picks_cache[cache_key]
        
        # 读取策略索引文件
        index_file = f"{INDEX_PATH}/{strategy}/{date}.json"
        
        if not os.path.exists(index_file):
            result = {
                "date": date,
                "strategy": strategy,
                "filter_type": filter_type,
                "count": 0,
                "stocks": []
            }
            _picks_cache[cache_key] = result
            return result
        
        with open(index_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 读取每只股票的当日行情和因子数据
        stocks_info = []
        for stock_code in data['stocks']:
            try:
                # 使用缓存版本的数据读取
                row_data = get_stock_data_cached(stock_code, date)
                if row_data is None:
                    continue
                
                # 检查是否满足极致B1条件
                is_extreme_b1 = False
                consecutive_extreme_b1_days = 0
                if strategy == 'B1':
                    is_extreme_b1 = check_extreme_b1_condition(stock_code, row_data, check_b1_first=False)
                    # 如果当日满足极致B1,计算连续天数
                    if is_extreme_b1:
                        consecutive_extreme_b1_days = get_consecutive_extreme_b1_days(stock_code, date)
                
                # 如果filter_type是extreme_b1，只保留满足条件的
                if filter_type == 'extreme_b1' and not is_extreme_b1:
                    continue
                
                # 计算涨跌幅
                change_pct = 0
                if row_data.get('prev_close') and not pd.isna(row_data['prev_close']) and row_data['prev_close'] > 0:
                    change_pct = (row_data['close'] - row_data['prev_close']) / row_data['prev_close'] * 100
                
                stock_info = {
                    "code": stock_code,
                    "close": round(float(row_data['close']), 2),
                    "change_pct": round(float(change_pct), 2),
                    "volume": int(row_data['volumn']),  # 注意：数据库字段是volumn
                    "is_extreme_b1": bool(is_extreme_b1),  # 确保转换为Python bool
                    "consecutive_extreme_b1_days": int(consecutive_extreme_b1_days)  # 连续极致B1天数
                }
                
                # 添加因子数据(用于前端显示)
                if strategy == 'B1':
                    if row_data.get('factor_amplitude') is not None and not pd.isna(row_data['factor_amplitude']):
                        stock_info['factor_amplitude'] = round(float(row_data['factor_amplitude']), 2)
                    if row_data.get('factor_volume_ratio') is not None and not pd.isna(row_data['factor_volume_ratio']):
                        stock_info['factor_volume_ratio'] = round(float(row_data['factor_volume_ratio']), 2)
                
                stocks_info.append(stock_info)
            except Exception as e:
                continue
        
        result = {
            "date": date,
            "strategy": strategy,
            "filter_type": filter_type,
            "count": len(stocks_info),
            "extreme_b1_count": sum(1 for s in stocks_info if s.get('is_extreme_b1', False)),
            "stocks": stocks_info
        }
        
        # 缓存结果
        _picks_cache[cache_key] = result
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stock/kline")
async def get_stock_kline(
    code: str = Query(..., description="股票代码"),
    end_date: str = Query(..., description="截止日期（YYYYMMDD）"),
    limit: int = Query(60, description="K线数量")
):
    """
    获取股票K线数据
    
    Args:
        code: 股票代码
        end_date: 截止日期
        limit: K线数量
        
    Returns:
        K线数据及指标
    """
    try:
        stock_file = f"{PROCESSED_PATH}/{code}.csv"
        
        if not os.path.exists(stock_file):
            raise HTTPException(status_code=404, detail=f"股票 {code} 数据不存在")
        
        df = pd.read_csv(stock_file)
        df['date'] = pd.to_datetime(df['date'])
        
        # 过滤截止日期
        df = df[df['date'] <= pd.to_datetime(end_date, format='%Y%m%d')]
        
        # 取最近limit条
        df = df.tail(limit)
        
        # 转换为前端需要的格式
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # 清理所有NaN和Inf值（转换为None）
        df = df.replace([np.nan, np.inf, -np.inf], None)
        
        # 转换为字典列表
        klines = df.to_dict('records')
        
        # 转换数值类型，并将volumn字段重命名为volume
        for kline in klines:
            # 重命名volumn为volume
            if 'volumn' in kline:
                kline['volume'] = kline['volumn']
                del kline['volumn']
            
            # 处理浮点数字段：NaN/Inf转为None
            for key in ['open', 'high', 'low', 'close', 'ema10_2', 'multi_line', 
                       'ma5', 'ma10', 'kdj_k', 'kdj_d', 'kdj_j', 
                       'macd_dif', 'macd_dea', 'macd_hist', 
                       'wash_short', 'wash_long']:
                if key in kline:
                    if pd.notna(kline[key]):
                        kline[key] = round(float(kline[key]), 2)
                    else:
                        kline[key] = None
            
            # 处理整数字段：NaN/Inf转为0
            for key in ['volume', 'vol_ma5', 'vol_ma60']:
                if key in kline:
                    if pd.notna(kline[key]):
                        kline[key] = int(kline[key])
                    else:
                        kline[key] = 0
        
        return {
            "code": code,
            "count": len(klines),
            "klines": klines
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
