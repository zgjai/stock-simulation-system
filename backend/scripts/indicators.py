"""技术指标计算模块"""
import pandas as pd
import numpy as np
from typing import Tuple


def calc_ma(series: pd.Series, period: int) -> pd.Series:
    """
    移动平均线
    
    Args:
        series: 数据序列
        period: 周期
        
    Returns:
        MA序列
    """
    return series.rolling(window=period, min_periods=1).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """
    指数移动平均线
    
    Args:
        series: 数据序列
        period: 周期
        
    Returns:
        EMA序列
    """
    return series.ewm(span=period, adjust=False).mean()


def calc_zhixing_short(df: pd.DataFrame) -> pd.Series:
    """
    知行短期趋势线 = EMA(EMA(C,10),10)
    
    Args:
        df: 包含收盘价的DataFrame
        
    Returns:
        知行短期趋势线序列
    """
    ema1 = calc_ema(df['close'], 10)
    ema2 = calc_ema(ema1, 10)
    return ema2


def calc_zhixing_multi(df: pd.DataFrame) -> pd.Series:
    """
    知行多空线 = (MA14+MA28+MA57+MA114)/4
    
    Args:
        df: 包含收盘价的DataFrame
        
    Returns:
        知行多空线序列
    """
    ma14 = calc_ma(df['close'], 14)
    ma28 = calc_ma(df['close'], 28)
    ma57 = calc_ma(df['close'], 57)
    ma114 = calc_ma(df['close'], 114)
    
    # 数据不足114日时，可能有NaN
    multi_line = (ma14 + ma28 + ma57 + ma114) / 4
    return multi_line


def calc_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    KDJ指标
    
    Args:
        df: 包含OHLC的DataFrame
        n: RSV周期
        m1: K值平滑周期
        m2: D值平滑周期
        
    Returns:
        (rsv, k, d, j): KDJ四个序列
    """
    low_n = df['low'].rolling(window=n, min_periods=1).min()
    high_n = df['high'].rolling(window=n, min_periods=1).max()
    
    # RSV = (C - LLV(L,N)) / (HHV(H,N) - LLV(L,N)) * 100
    denominator = high_n - low_n
    rsv = np.where(
        denominator > 0,
        (df['close'] - low_n) / denominator * 100,
        50  # 分母为0时默认50
    )
    rsv = pd.Series(rsv, index=df.index)
    
    # K = EMA(RSV, m1)
    k = rsv.ewm(span=m1, adjust=False).mean()
    
    # D = EMA(K, m2)
    d = k.ewm(span=m2, adjust=False).mean()
    
    # J = 3K - 2D
    j = 3 * k - 2 * d
    
    return rsv, k, d, j


def calc_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD指标
    
    Args:
        df: 包含收盘价的DataFrame
        fast: 快线周期
        slow: 慢线周期
        signal: 信号线周期
        
    Returns:
        (dif, dea, hist): MACD三个序列
    """
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2  # 柱状图
    
    return dif, dea, hist


def calc_wash_line(df: pd.DataFrame, period: int) -> pd.Series:
    """
    洗盘线 = 100 * (C - LLV(L,N)) / (HHV(C,N) - LLV(L,N))
    分母为0时记为0
    
    Args:
        df: 包含OHLC的DataFrame
        period: 周期
        
    Returns:
        洗盘线序列
    """
    llv = df['low'].rolling(window=period, min_periods=1).min()
    hhv = df['close'].rolling(window=period, min_periods=1).max()
    
    denominator = hhv - llv
    wash = np.where(
        denominator > 0,
        100 * (df['close'] - llv) / denominator,
        0
    )
    
    return pd.Series(wash, index=df.index)


def calc_single_needle(df: pd.DataFrame, period: int) -> pd.Series:
    """
    单针指标 = 100 * (C - LLV(L,N)) / (HHV(C,N) - LLV(L,N))
    分母为0时返回NaN（用于后续过滤）
    
    Args:
        df: 包含OHLC的DataFrame
        period: 周期
        
    Returns:
        单针指标序列
    """
    llv = df['low'].rolling(window=period, min_periods=1).min()
    hhv = df['close'].rolling(window=period, min_periods=1).max()
    
    denominator = hhv - llv
    # 分母为0时返回NaN，不是0
    single_needle = (df['close'] - llv) / denominator * 100
    
    return single_needle


def calc_brick_chart(df: pd.DataFrame) -> dict:
    """
    砖型图指标计算

    ── 概念定义 ──────────────────────────────────────────────
    砖型图：
        由红柱和绿柱组成的动量指标。
        今日砖值 > 昨日砖值 → 红柱（动量上升）
        今日砖值 < 昨日砖值 → 绿柱（动量下降）
        砖值 = 0 表示指标消失（极深超跌区）

    砖型图柱体长度（字段: brick_value）：
        即红柱或绿柱本身的数值，反映当日动量的绝对高度。
        公式：砖型图 = IF(VAR6A>4, VAR6A-4, 0)  （≥0）

    动量柱（派生字段: brick_delta = brick_value - REF(brick_value,1)）：
        今日砖型图柱体长度 - 昨日砖型图柱体长度，有符号。
        正数（红动量柱）：今日砖值高于昨日，动量在扩张
        负数（绿动量柱）：今日砖值低于昨日，动量在收缩
        注意：动量柱不存储在数据库，在分析脚本中实时派生。

    动量柱柱体长度（字段: brick_body）：
        = ABS(今日砖值 - 昨日砖值)，即红/绿动量柱的数值（≥0）。
        反映当日砖型图的变化幅度，但不含方向信息。
        若需区分扩张/收缩，请使用有符号的 brick_delta。

    ── 公式 ──────────────────────────────────────────────────
    VAR1A = (HHV(HIGH,4)-CLOSE)/(HHV(HIGH,4)-LLV(LOW,4))*100-90
    VAR2A = SMA(VAR1A,4,1)+100
    VAR3A = (CLOSE-LLV(LOW,4))/(HHV(HIGH,4)-LLV(LOW,4))*100
    VAR4A = SMA(VAR3A,6,1)
    VAR5A = SMA(VAR4A,6,1)+100
    VAR6A = VAR5A - VAR2A
    砖型图柱体长度(brick_value) = IF(VAR6A>4, VAR6A-4, 0)
    动量柱柱体长度(brick_body)  = ABS(brick_value - REF(brick_value,1))

    Returns:
        dict: 包含 brick_value（砖型图柱体长度）、brick_body（动量柱柱体长度）两列
    """
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    
    # HHV/LLV：4日最高/最低
    hhv4 = high.rolling(window=4, min_periods=1).max()
    llv4 = low.rolling(window=4, min_periods=1).min()
    
    denom4 = hhv4 - llv4
    
    # VAR1A
    var1a = np.where(denom4 > 0, (hhv4 - close) / denom4 * 100 - 90, -90)
    var1a = pd.Series(var1a, index=df.index)
    
    # VAR2A = SMA(VAR1A,4,1)+100  (东财SMA: SMA(X,N,M)=X*M/N + SMA[-1]*(N-M)/N)
    var2a = var1a.ewm(alpha=1/4, adjust=False).mean() + 100
    
    # VAR3A
    var3a = np.where(denom4 > 0, (close - llv4) / denom4 * 100, 50)
    var3a = pd.Series(var3a, index=df.index)
    
    # VAR4A = SMA(VAR3A,6,1)
    var4a = var3a.ewm(alpha=1/6, adjust=False).mean()
    
    # VAR5A = SMA(VAR4A,6,1)+100
    var5a = var4a.ewm(alpha=1/6, adjust=False).mean() + 100
    
    # VAR6A = VAR5A - VAR2A
    var6a = var5a - var2a
    
    # 砖型图柱体长度(brick_value) = IF(VAR6A>4, VAR6A-4, 0)
    brick = np.where(var6a > 4, var6a - 4, 0)
    brick = pd.Series(brick, index=df.index)

    # 动量柱柱体长度(brick_body) = ABS(brick_value - REF(brick_value,1))
    # 注意：此为绝对值，不含方向。若需方向，用 brick_value - brick_value.shift(1) 即 brick_delta。
    brick_body = (brick - brick.shift(1)).abs()
    brick_body = brick_body.fillna(0)
    
    return {
        'brick_value': brick.round(4),
        'brick_body': brick_body.round(4),
    }


def add_all_indicators(df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
    """
    为DataFrame添加所有技术指标列
    
    Args:
        df: 原始OHLCV数据
        stock_code: 股票代码（用于识别板块）
        
    Returns:
        添加了指标列的DataFrame
    """
    from utils import get_limit_ratio, calc_limit_price
    
    # 确保数据按日期排序
    df = df.sort_values('date').reset_index(drop=True)
    
    # 前一日收盘价
    df['prev_close'] = df['close'].shift(1)
    
    # 涨跌停价
    limit_ratio = get_limit_ratio(stock_code)
    df['limit_up'] = df['prev_close'].apply(
        lambda x: calc_limit_price(x, limit_ratio, 1)
    )
    df['limit_down'] = df['prev_close'].apply(
        lambda x: calc_limit_price(x, limit_ratio, -1)
    )
    
    # 主图指标
    df['ema10_1'] = calc_ema(df['close'], 10)
    df['ema10_2'] = calc_ema(df['ema10_1'], 10)  # 知行短期
    df['multi_line'] = calc_zhixing_multi(df)  # 知行多空
    df['ma5'] = calc_ma(df['close'], 5)
    df['ma10'] = calc_ma(df['close'], 10)
    
    # 副图指标
    df['vol_ma5'] = calc_ma(df['volumn'], 5)
    df['vol_ma60'] = calc_ma(df['volumn'], 60)
    
    rsv, k, d, j = calc_kdj(df)
    df['kdj_rsv'] = rsv
    df['kdj_k'] = k
    df['kdj_d'] = d
    df['kdj_j'] = j
    
    dif, dea, hist = calc_macd(df)
    df['macd_dif'] = dif
    df['macd_dea'] = dea
    df['macd_hist'] = hist
    
    # 洗盘线（固定参数 N1=3, N2=21）
    df['wash_short'] = calc_wash_line(df, period=3)
    df['wash_long'] = calc_wash_line(df, period=21)
    
    # 单针指标（用于策略计算）
    df['single_needle_short'] = calc_single_needle(df, period=3)
    df['single_needle_long'] = calc_single_needle(df, period=21)
    
    # 砖型图指标
    brick_result = calc_brick_chart(df)
    df['brick_value'] = brick_result['brick_value']
    df['brick_body'] = brick_result['brick_body']
    
    # 可交易标记（有成交量即可交易）
    df['can_trade'] = (df['volumn'] > 0).astype(int)
    
    return df
