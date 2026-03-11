"""测试单个股票的指标和策略计算"""
import sys
import os
import pandas as pd
from pathlib import Path

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from indicators import add_all_indicators
from strategies import add_strategy_signals
from utils import detect_anomaly, get_stock_code_from_filename


def test_stock(stock_code='000001'):
    """
    测试单个股票
    
    Args:
        stock_code: 股票代码
    """
    print(f"\n{'='*60}")
    print(f"测试股票: {stock_code}")
    print(f"{'='*60}\n")
    
    # 1. 读取原始数据
    input_file = f'origin_data/price_{stock_code}.csv'
    try:
        df = pd.read_csv(input_file)
    except FileNotFoundError:
        print(f"✗ 文件不存在: {input_file}")
        return None
    
    # 重命名列（适配原始数据格式）
    df.rename(columns={
        'timetag': 'date',
    }, inplace=True)
    
    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
    df = df.sort_values('date').reset_index(drop=True)
    
    print(f"✓ 读取数据: {len(df)}条记录")
    print(f"  时间范围: {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}\n")
    
    # 2. 检测异常数据
    anomaly_count = 0
    anomaly_list = []
    
    # 先计算prev_close用于异常检测
    df['prev_close'] = df['close'].shift(1)
    
    for idx, row in df.iterrows():
        is_anomaly, reason = detect_anomaly(row)
        if is_anomaly:
            anomaly_count += 1
            anomaly_list.append((row['date'].strftime('%Y-%m-%d'), reason))
            if anomaly_count <= 5:  # 只显示前5条
                print(f"⚠ 异常: {row['date'].strftime('%Y-%m-%d')} - {reason}")
    
    if anomaly_count == 0:
        print("✓ 无异常数据\n")
    else:
        print(f"\n⚠ 共检测到 {anomaly_count} 条异常数据\n")
    
    # 3. 计算指标
    print("计算技术指标...")
    df = add_all_indicators(df, stock_code)
    print("✓ 指标计算完成\n")
    
    # 4. 计算策略
    print("计算选股策略...")
    df = add_strategy_signals(df)
    print("✓ 策略计算完成\n")
    
    # 5. 统计结果
    b1_count = df['b1_signal'].sum()
    b2_count = df['b2_signal'].sum()
    sn_count = df['single_needle_signal'].sum()
    
    print(f"{'策略统计':-^60}")
    print(f"B1策略触发: {b1_count}次 ({b1_count/len(df)*100:.2f}%)")
    print(f"B2策略触发: {b2_count}次 ({b2_count/len(df)*100:.2f}%)")
    print(f"单针策略触发: {sn_count}次 ({sn_count/len(df)*100:.2f}%)")
    print(f"{'-'*60}\n")
    
    # 6. 显示最近的信号
    print(f"{'最近10个交易日的策略信号':-^60}")
    recent = df.tail(10)[['date', 'close', 'kdj_j', 'b1_signal', 'b2_signal', 'single_needle_signal']].copy()
    recent['date'] = recent['date'].dt.strftime('%Y-%m-%d')
    recent['close'] = recent['close'].round(2)
    recent['kdj_j'] = recent['kdj_j'].round(2)
    print(recent.to_string(index=False))
    print(f"{'-'*60}\n")
    
    # 7. 显示部分指标值（验证正确性）
    print(f"{'最近5日指标值（用于通达信对比）':-^60}")
    cols = ['date', 'close', 'ema10_2', 'multi_line', 'kdj_k', 'kdj_d', 'kdj_j', 'macd_dif']
    display_df = df.tail(5)[cols].copy()
    display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d')
    for col in ['close', 'ema10_2', 'multi_line', 'kdj_k', 'kdj_d', 'kdj_j', 'macd_dif']:
        if col in display_df.columns:
            display_df[col] = display_df[col].round(2)
    print(display_df.to_string(index=False))
    print(f"{'-'*60}\n")
    
    return df


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='测试单个股票的指标和策略计算')
    parser.add_argument('--code', type=str, default='000001', help='股票代码')
    args = parser.parse_args()
    
    # 测试股票
    df = test_stock(args.code)
    
    if df is not None:
        print("\n✅ 测试完成！")
        print("\n下一步：")
        print("1. 对比通达信的指标值，验证计算正确性")
        print("2. 手工验证几个策略信号日，确认逻辑正确")
        print("3. 运行批量预处理: python preprocess_all.py\n")
