"""基础工具函数"""
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd
from datetime import datetime
from typing import Tuple, Set
import os


def get_limit_ratio(stock_code: str) -> Decimal:
    """
    根据股票代码获取涨跌停比例
    
    Args:
        stock_code: 股票代码（6位）
        
    Returns:
        涨跌停比例（Decimal类型）
    """
    prefix = stock_code[:2]
    if prefix in ['00', '60']:  # 主板
        return Decimal('0.10')
    elif prefix in ['30', '68']:  # 创业板/科创板
        return Decimal('0.20')
    elif prefix == '92':  # 北交所
        return Decimal('0.30')
    return Decimal('0.10')  # 默认


def calc_limit_price(prev_close: float, limit_ratio: Decimal, direction: int) -> float:
    """
    计算涨跌停价（精确到分）
    
    Args:
        prev_close: 前一日收盘价
        limit_ratio: 涨跌停比例
        direction: 1=涨停, -1=跌停
        
    Returns:
        涨跌停价格
    """
    if pd.isna(prev_close) or prev_close <= 0:
        return float('nan')
    
    price = Decimal(str(prev_close)) * (Decimal('1') + direction * limit_ratio)
    return float(price.quantize(Decimal('0.01'), ROUND_HALF_UP))


def detect_anomaly(row: pd.Series) -> Tuple[bool, str]:
    """
    检测数据异常
    
    Args:
        row: DataFrame的一行数据
        
    Returns:
        (is_anomaly, reason): 是否异常及原因
    """
    # 1. 检查价格合法性
    if row['close'] < 0.01:
        return True, "收盘价<0.01"
    
    if row['high'] < row['low']:
        return True, "最高价<最低价"
    
    if not (row['low'] <= row['close'] <= row['high']):
        return True, "收盘价不在[最低,最高]区间"
    
    if not (row['low'] <= row['open'] <= row['high']):
        return True, "开盘价不在[最低,最高]区间"
    
    # 2. 检查涨跌幅（需要前一日收盘价）
    if 'prev_close' in row and pd.notna(row['prev_close']) and row['prev_close'] > 0:
        daily_change = abs((row['close'] - row['prev_close']) / row['prev_close'])
        if daily_change > 0.5:  # 50%
            return True, f"单日涨跌幅>{daily_change:.2%}"
    
    # 3. 检查成交量
    if row['volumn'] == 0 and (row['high'] != row['low']):
        return True, "成交量=0但有价格波动"
    
    return False, ""


def load_trade_calendar(path: str = 'data/trade_calendar.csv') -> Set[str]:
    """
    加载交易日历
    
    Args:
        path: 交易日历文件路径
        
    Returns:
        交易日集合（YYYYMMDD格式）
    """
    if not os.path.exists(path):
        print(f"⚠ 交易日历文件不存在: {path}")
        return set()
    
    df = pd.read_csv(path)
    return set(df[df['is_trading_day'] == 1]['date'].astype(str))


def get_stock_code_from_filename(filename: str) -> str:
    """
    从文件名中提取股票代码
    
    Args:
        filename: 文件名，如 price_000001.csv
        
    Returns:
        股票代码，如 000001
    """
    # 去掉扩展名
    name = filename.replace('.csv', '')
    # 提取 price_ 后面的部分
    if name.startswith('price_'):
        return name[6:]
    return name


def format_date(date_str: str) -> str:
    """
    格式化日期为YYYYMMDD
    
    Args:
        date_str: 日期字符串
        
    Returns:
        YYYYMMDD格式的日期
    """
    try:
        dt = pd.to_datetime(date_str)
        return dt.strftime('%Y%m%d')
    except:
        return date_str


def ensure_dir(path: str):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def log_message(msg: str, level: str = 'INFO'):
    """
    输出日志消息
    
    Args:
        msg: 消息内容
        level: 日志级别（INFO/WARNING/ERROR）
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    prefix = {
        'INFO': '✓',
        'WARNING': '⚠',
        'ERROR': '✗'
    }.get(level, 'ℹ')
    
    print(f"[{timestamp}] {prefix} {msg}")
