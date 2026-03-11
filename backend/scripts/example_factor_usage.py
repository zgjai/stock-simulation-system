"""因子数据使用示例脚本"""
import sys
import os
import pandas as pd
import json
from pathlib import Path

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)


def example1_filter_by_amplitude():
    """示例1：筛选低振幅股票"""
    print("\n" + "="*60)
    print("示例1：筛选某日B1策略中振幅<3%的股票")
    print("="*60)
    
    date = '20250120'  # 指定日期
    
    # 读取B1策略候选池
    index_file = f'strategy_index/B1/{date}.json'
    if not os.path.exists(index_file):
        print(f"索引文件不存在: {index_file}")
        return
    
    with open(index_file, 'r') as f:
        data = json.load(f)
        candidates = data['stocks']
    
    print(f"\nB1策略候选池共有 {len(candidates)} 只股票")
    
    # 筛选低振幅股票
    low_amp_stocks = []
    for stock in candidates[:10]:  # 只看前10个示例
        csv_file = f'processed_data/{stock}.csv'
        if not os.path.exists(csv_file):
            continue
            
        df = pd.read_csv(csv_file)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
        row = df[df['date'] == date]
        
        if not row.empty:
            amp = row.iloc[0]['factor_amplitude']
            close = row.iloc[0]['close']
            if amp < 3.0:
                low_amp_stocks.append({
                    'stock': stock,
                    'amplitude': amp,
                    'close': close
                })
    
    print(f"\n振幅<3%的股票（前10个候选中）:")
    for item in low_amp_stocks:
        print(f"  {item['stock']}: 振幅={item['amplitude']:.2f}%, 收盘={item['close']:.2f}")


def example2_analyze_top5_factors():
    """示例2：分析优秀案例的因子特征"""
    print("\n" + "="*60)
    print("示例2：分析某日优秀案例的因子特征")
    print("="*60)
    
    date = '20250120'
    
    # 读取学习案例
    case_file = f'learning_cases/B1/{date}.json'
    if not os.path.exists(case_file):
        print(f"学习案例文件不存在: {case_file}")
        return
    
    with open(case_file, 'r') as f:
        learning_case = json.load(f)
    
    # 获取3日涨幅TOP5
    top5_cases = learning_case['top_cases']['3d']
    if not top5_cases:
        print("没有找到优秀案例")
        return
    
    print(f"\n{date} 的3日涨幅TOP5股票:")
    
    factor_data = []
    for i, case in enumerate(top5_cases, 1):
        stock = case['stock_code']
        return_pct = case['return_pct']
        
        # 读取因子数据
        csv_file = f'processed_data/{stock}.csv'
        if not os.path.exists(csv_file):
            continue
        
        df = pd.read_csv(csv_file)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
        row = df[df['date'] == date]
        
        if not row.empty:
            print(f"\nTOP{i}: {stock} (3日涨幅: {return_pct:.2f}%)")
            print(f"  振幅: {row.iloc[0]['factor_amplitude']:.2f}%")
            print(f"  成交量比率: {row.iloc[0]['factor_volume_ratio']:.2f}")
            print(f"  J值: {row.iloc[0]['factor_j_value']:.2f}")
            print(f"  知行比率: {row.iloc[0]['factor_wash_ratio']:.4f}")
            print(f"  K线实体比例: {row.iloc[0]['factor_body_ratio']:.4f}")
            print(f"  收盘价位置: {row.iloc[0]['factor_close_position']:.4f}")
            
            factor_data.append({
                'stock': stock,
                'return': return_pct,
                'amplitude': row.iloc[0]['factor_amplitude'],
                'volume_ratio': row.iloc[0]['factor_volume_ratio'],
                'j_value': row.iloc[0]['factor_j_value'],
                'wash_ratio': row.iloc[0]['factor_wash_ratio'],
            })
    
    # 计算平均值
    if factor_data:
        df_factors = pd.DataFrame(factor_data)
        print("\n" + "-"*60)
        print("TOP5平均因子特征:")
        print(f"  平均振幅: {df_factors['amplitude'].mean():.2f}%")
        print(f"  平均成交量比率: {df_factors['volume_ratio'].mean():.2f}")
        print(f"  平均J值: {df_factors['j_value'].mean():.2f}")
        print(f"  平均知行比率: {df_factors['wash_ratio'].mean():.4f}")


def example3_factor_statistics():
    """示例3：单个股票的因子统计"""
    print("\n" + "="*60)
    print("示例3：查看单个股票的因子统计信息")
    print("="*60)
    
    stock = '000001'
    csv_file = f'processed_data/{stock}.csv'
    
    if not os.path.exists(csv_file):
        print(f"股票数据不存在: {csv_file}")
        return
    
    df = pd.read_csv(csv_file)
    factor_cols = [col for col in df.columns if col.startswith('factor_')]
    
    print(f"\n股票 {stock} 的因子统计信息:")
    print(df[factor_cols].describe().round(2).to_string())
    
    # 最近5天的因子数据
    print(f"\n最近5天的因子数据:")
    recent = df[['date', 'close'] + factor_cols].tail(5)
    print(recent.to_string(index=False))


def example4_compare_groups():
    """示例4：对比高低振幅股票的特征"""
    print("\n" + "="*60)
    print("示例4：对比高低振幅股票的其他因子特征")
    print("="*60)
    
    stock = '000001'
    csv_file = f'processed_data/{stock}.csv'
    
    if not os.path.exists(csv_file):
        print(f"股票数据不存在: {csv_file}")
        return
    
    df = pd.read_csv(csv_file)
    
    # 过滤掉NaN值
    df = df.dropna(subset=['factor_amplitude', 'factor_volume_ratio', 'factor_j_value'])
    
    # 按振幅分组
    low_amp = df[df['factor_amplitude'] < 3.0]
    high_amp = df[df['factor_amplitude'] >= 7.0]
    
    print(f"\n股票 {stock}:")
    print(f"低振幅(<3%)天数: {len(low_amp)} 天")
    print(f"高振幅(>=7%)天数: {len(high_amp)} 天")
    
    if len(low_amp) > 0 and len(high_amp) > 0:
        print("\n低振幅组的平均特征:")
        print(f"  平均成交量比率: {low_amp['factor_volume_ratio'].mean():.2f}")
        print(f"  平均J值: {low_amp['factor_j_value'].mean():.2f}")
        print(f"  平均K线实体比例: {low_amp['factor_body_ratio'].mean():.4f}")
        
        print("\n高振幅组的平均特征:")
        print(f"  平均成交量比率: {high_amp['factor_volume_ratio'].mean():.2f}")
        print(f"  平均J值: {high_amp['factor_j_value'].mean():.2f}")
        print(f"  平均K线实体比例: {high_amp['factor_body_ratio'].mean():.4f}")


def main():
    """主函数"""
    print("\n" + "="*60)
    print("因子数据使用示例")
    print("="*60)
    
    # 运行所有示例
    try:
        example1_filter_by_amplitude()
    except Exception as e:
        print(f"\n示例1执行失败: {str(e)}")
    
    try:
        example2_analyze_top5_factors()
    except Exception as e:
        print(f"\n示例2执行失败: {str(e)}")
    
    try:
        example3_factor_statistics()
    except Exception as e:
        print(f"\n示例3执行失败: {str(e)}")
    
    try:
        example4_compare_groups()
    except Exception as e:
        print(f"\n示例4执行失败: {str(e)}")
    
    print("\n" + "="*60)
    print("示例运行完成！")
    print("="*60)
    print("\n更多用法请参考: 因子数据快速使用指南.md")


if __name__ == '__main__':
    main()
