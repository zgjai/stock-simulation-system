"""选股策略计算模块"""
import pandas as pd
import numpy as np


def check_b1_strategy(df: pd.DataFrame) -> pd.Series:
    """
    B1策略：单日基础筛选
    目标：筛出"低位 + 窄幅 + 多头支撑"的股票（已移除量能条件）
    
    Args:
        df: 包含所有指标的DataFrame
        
    Returns:
        每日是否符合策略的0/1标记
    """
    signals = pd.Series(0, index=df.index)
    
    for i in range(1, len(df)):
        row = df.iloc[i]
        
        # 条件1: J值低位
        if pd.isna(row['kdj_j']) or row['kdj_j'] > 16:
            continue
        
        # 条件2: 窄幅波动（OR关系）
        prev_close = df.iloc[i-1]['close']
        if prev_close <= 0:
            continue
            
        daily_chg = (row['close'] - prev_close) / prev_close * 100
        oc_chg = (row['close'] - row['open']) / prev_close * 100
        
        if not ((-2.5 <= daily_chg <= 2.5) or (-2.5 <= oc_chg <= 2.5)):
            continue
        
        # 条件3: 振幅温和
        amplitude = (row['high'] - row['low']) / prev_close * 100
        if amplitude > 7:
            continue
        
        # 条件4: 多头趋势（数据不足则False）
        if pd.isna(row['ema10_2']) or pd.isna(row['multi_line']):
            continue
        if row['ema10_2'] < row['multi_line']:
            continue
        
        # 【已移除】条件5: 量能温和（过去30日不含当日）
        # 原条件: 当日成交量 ≤ 过去30日最大成交量的一半
        # 移除原因: 优化策略，去除成交量筛选条件
        # start_idx = max(0, i - 30)
        # hist_30d = df.iloc[start_idx:i]
        # if len(hist_30d) == 0:
        #     continue
        # max_vol_30d = hist_30d['volumn'].max()
        # if row['volumn'] > max_vol_30d * 0.5:
        #     continue
        
        # 全部通过
        signals.iloc[i] = 1
    
    return signals


def check_b2_strategy(df: pd.DataFrame) -> pd.Series:
    """
    B2策略：两日联动（打底+起爆）
    目标：先筛"第一日打底"，再要求"第二日起爆"
    
    Args:
        df: 包含所有指标的DataFrame
        
    Returns:
        每日是否符合策略的0/1标记
    """
    signals = pd.Series(0, index=df.index)
    
    for i in range(2, len(df)):
        t_minus_1 = df.iloc[i-1]
        t = df.iloc[i]
        t_minus_2_close = df.iloc[i-2]['close']
        
        if t_minus_2_close <= 0:
            continue
        
        # === T-1日打底条件 ===
        # 1) J值低位
        if pd.isna(t_minus_1['kdj_j']) or t_minus_1['kdj_j'] > 21:
            continue
        
        # 2) 窄幅波动
        daily_chg = (t_minus_1['close'] - t_minus_2_close) / t_minus_2_close * 100
        oc_chg = (t_minus_1['close'] - t_minus_1['open']) / t_minus_2_close * 100
        if not ((-2.5 <= daily_chg <= 2.5) or (-2.5 <= oc_chg <= 2.5)):
            continue
        
        # 3) 振幅温和
        amplitude = (t_minus_1['high'] - t_minus_1['low']) / t_minus_2_close * 100
        if amplitude > 7:
            continue
        
        # 4) 多头趋势
        if pd.isna(t_minus_1['ema10_2']) or pd.isna(t_minus_1['multi_line']):
            continue
        if t_minus_1['ema10_2'] < t_minus_1['multi_line']:
            continue
        
        # 【已移除】5) 量能温和
        # 原条件: 当日成交量 ≤ 过去30日最大成交量的一半
        # 移除原因: 优化策略，去除成交量筛选条件
        
        # === T日起爆条件 ===
        t_minus_1_close = t_minus_1['close']
        
        if t_minus_1_close <= 0:
            continue
        
        # 1) 强势上涨
        t_daily_chg = (t['close'] - t_minus_1_close) / t_minus_1_close * 100
        if t_daily_chg < 4:
            continue
        
        # 2) 放量
        if t['volumn'] < t_minus_1['volumn'] * 1.618:
            continue
        
        # 3) J不超买
        if pd.isna(t['kdj_j']) or t['kdj_j'] > 80:
            continue
        
        # 4) 上影线短
        upper_shadow = t['high'] - max(t['close'], t['open'])
        body = abs(t['close'] - t['open'])
        
        if body == 0:  # 十字星
            if upper_shadow > 0.001:  # 要求极短
                continue
        else:
            if upper_shadow >= body / 3:
                continue
        
        # 全部通过
        signals.iloc[i] = 1
    
    return signals


def check_single_needle_strategy(df: pd.DataFrame) -> pd.Series:
    """
    单针策略：两日/三日模式+趋势过滤
    目标：识别"高位双针后转弱"的形态，且趋势仍为多头
    
    Args:
        df: 包含所有指标的DataFrame
        
    Returns:
        每日是否符合策略的0/1标记
    """
    signals = pd.Series(0, index=df.index)
    
    for i in range(2, len(df)):
        row = df.iloc[i]
        
        # 先检查趋势过滤（性能优化）
        if pd.isna(row['ema10_2']) or pd.isna(row['multi_line']):
            continue
        if row['ema10_2'] <= row['multi_line']:
            continue
        
        # 检查分母为0（排除）
        if pd.isna(row['single_needle_short']) or pd.isna(row['single_needle_long']):
            continue
        
        # === 两日模式 ===
        if i >= 1:
            t_minus_1 = df.iloc[i-1]
            
            # T-1: 高位双针
            cond1 = (not pd.isna(t_minus_1['single_needle_short']) and 
                     t_minus_1['single_needle_short'] > 95 and
                     not pd.isna(t_minus_1['single_needle_long']) and
                     t_minus_1['single_needle_long'] > 95)
            
            # T: 降针
            cond2 = (row['single_needle_short'] <= 30 and 
                     row['single_needle_long'] >= 85)
            
            # T: 缩量
            cond3 = row['volumn'] < t_minus_1['volumn']
            
            if cond1 and cond2 and cond3:
                signals.iloc[i] = 1
                continue
        
        # === 三日模式 ===
        if i >= 2:
            t_minus_2 = df.iloc[i-2]
            t_minus_1 = df.iloc[i-1]
            
            # T-2: 高位双针
            cond1 = (not pd.isna(t_minus_2['single_needle_short']) and
                     t_minus_2['single_needle_short'] > 95 and
                     not pd.isna(t_minus_2['single_needle_long']) and
                     t_minus_2['single_needle_long'] > 95)
            
            # T-1和T: 连续降针
            cond2 = (not pd.isna(t_minus_1['single_needle_short']) and
                     t_minus_1['single_needle_short'] <= 30 and
                     not pd.isna(t_minus_1['single_needle_long']) and
                     t_minus_1['single_needle_long'] >= 85)
            
            cond3 = (row['single_needle_short'] <= 30 and 
                     row['single_needle_long'] >= 85)
            
            # T-1和T: 连续缩量
            cond4 = t_minus_1['volumn'] < t_minus_2['volumn']
            cond5 = row['volumn'] < t_minus_2['volumn']
            
            if cond1 and cond2 and cond3 and cond4 and cond5:
                signals.iloc[i] = 1
    
    return signals


def check_brick_strategy(df: pd.DataFrame, brick_ratio: float = 0.667) -> pd.Series:
    """
    砖型选股策略（brick）
    条件：
    1. 砖型图动量柱由绿转红，且红动量柱长度 > 绿动量柱长度 × brick_ratio
    2. 知行短期趋势线(ema10_2) > 知行多空线(multi_line)
    3. 当日收盘价 > 知行多空线(multi_line)

    动量柱方向判断：
        brick_delta(i) = brick_value(i) - brick_value(i-1)
        brick_delta > 0 → 红动量柱（动量扩张）
        brick_delta < 0 → 绿动量柱（动量收缩）
        brick_delta = 0 → 无方向，不计入

    由绿转红：T-1日为绿动量柱（brick_delta(T-1) < 0），T日为红动量柱（brick_delta(T) > 0）
    红柱长度（ABS值）> 绿柱长度（ABS值）× brick_ratio

    Args:
        df: 包含所有指标的DataFrame（必须包含 brick_value, ema10_2, multi_line, close）
        brick_ratio: 红柱长度需超过绿柱长度的比例，默认 2/3

    Returns:
        每日是否符合策略的0/1标记
    """
    signals = pd.Series(0, index=df.index)

    for i in range(2, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i - 1]
        prev2_row = df.iloc[i - 2]

        # --- 基础字段完整性检查 ---
        if pd.isna(row['brick_value']) or pd.isna(prev_row['brick_value']) or pd.isna(prev2_row['brick_value']):
            continue
        if pd.isna(row['ema10_2']) or pd.isna(row['multi_line']):
            continue
        if pd.isna(row['close']):
            continue

        # --- 计算动量柱方向和长度 ---
        # 当日动量柱 delta（T）
        today_delta = float(row['brick_value']) - float(prev_row['brick_value'])
        # 前一日动量柱 delta（T-1）
        prev_delta = float(prev_row['brick_value']) - float(prev2_row['brick_value'])

        # 条件1：由绿转红（T-1为绿柱，T为红柱）
        if prev_delta >= 0:   # T-1不是绿柱（必须严格小于0才算绿柱）
            continue
        if today_delta <= 0:  # T不是红柱（必须严格大于0才算红柱）
            continue

        red_len = today_delta          # 红柱长度（正数）
        green_len = abs(prev_delta)    # 绿柱长度（取绝对值）

        # 红柱长度 > 绿柱长度 × brick_ratio
        if red_len <= green_len * brick_ratio:
            continue

        # 条件2：知行短期趋势线 > 知行多空线
        if float(row['ema10_2']) <= float(row['multi_line']):
            continue

        # 条件3：当日收盘价 > 知行多空线
        if float(row['close']) <= float(row['multi_line']):
            continue

        # 全部通过
        signals.iloc[i] = 1

    return signals


def add_strategy_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    为DataFrame添加所有策略信号列
    
    Args:
        df: 包含所有指标的DataFrame
        
    Returns:
        添加了策略信号列的DataFrame
    """
    df['b1_signal'] = check_b1_strategy(df)
    df['b2_signal'] = check_b2_strategy(df)
    df['single_needle_signal'] = check_single_needle_strategy(df)
    df['brick_signal'] = check_brick_strategy(df)
    
    return df
