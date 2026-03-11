#!/usr/bin/env python3
"""完整修复所有缺失数据"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

# 路径配置
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / 'data' / 'stock.db'
STRATEGY_INDEX_PATH = PROJECT_ROOT / 'strategy_index'
LEARNING_CASES_PATH = PROJECT_ROOT / 'learning_cases'


def fix_extreme_b1():
    """修复极致B1标记"""
    print("\n" + "=" * 60)
    print("修复极致B1标记")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 查找极致B1文件
    extreme_b1_dir = STRATEGY_INDEX_PATH / 'B1_extreme'
    if not extreme_b1_dir.exists():
        extreme_b1_dir = STRATEGY_INDEX_PATH / 'B1' / 'extreme'
    
    if not extreme_b1_dir.exists():
        print("⚠️  未找到极致B1目录，尝试从B1数据中标记...")
        # 从数据库中找出可能的极致B1（振幅小、量比小）
        cursor.execute("""
            SELECT s.trade_date, s.stock_code
            FROM strategy_picks s
            JOIN stock_daily d ON s.stock_code = d.stock_code AND s.trade_date = d.trade_date
            WHERE s.strategy = 'B1'
              AND d.factor_amplitude IS NOT NULL
              AND d.factor_amplitude < 3.0
              AND d.factor_volume_ratio IS NOT NULL
              AND d.factor_volume_ratio < 1.5
              AND s.change_pct IS NOT NULL
              AND ABS(s.change_pct) < 2.0
        """)
        
        extreme_b1_candidates = cursor.fetchall()
        print(f"找到 {len(extreme_b1_candidates)} 个潜在极致B1候选")
        
        if extreme_b1_candidates:
            update_data = [(1, trade_date, stock_code) for trade_date, stock_code in extreme_b1_candidates]
            cursor.executemany("""
                UPDATE strategy_picks 
                SET is_extreme_b1 = ? 
                WHERE trade_date = ? AND stock_code = ? AND strategy = 'B1'
            """, update_data)
            conn.commit()
            print(f"✅ 标记了 {len(extreme_b1_candidates)} 个极致B1")
    else:
        print(f"找到极致B1目录: {extreme_b1_dir}")
        json_files = list(extreme_b1_dir.glob("*.json"))
        print(f"共 {len(json_files)} 个日期")
        
        update_count = 0
        for json_file in tqdm(json_files, desc="标记极致B1"):
            try:
                date_str = json_file.stem
                trade_date = datetime.strptime(date_str, "%Y%m%d").strftime('%Y-%m-%d')
                
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for stock_code in data.get('stocks', []):
                    cursor.execute("""
                        UPDATE strategy_picks 
                        SET is_extreme_b1 = 1 
                        WHERE strategy = 'B1' AND trade_date = ? AND stock_code = ?
                    """, (trade_date, stock_code))
                    update_count += cursor.rowcount
                
                if update_count % 1000 == 0:
                    conn.commit()
            
            except Exception as e:
                print(f"\n处理 {json_file.name} 失败: {e}")
        
        conn.commit()
        print(f"✅ 标记了 {update_count} 个极致B1")
    
    conn.close()


def migrate_missing_strategies():
    """补充缺失的B2和单针策略数据"""
    print("\n" + "=" * 60)
    print("补充B2和单针策略数据")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    strategies = [
        ('B2', 'B2'),
        ('single_needle', 'single_needle')
    ]
    
    total_added = 0
    
    for strategy_name, strategy_code in strategies:
        strategy_dir = STRATEGY_INDEX_PATH / strategy_name
        if not strategy_dir.exists():
            print(f"⚠️  {strategy_name} 目录不存在，跳过")
            continue
        
        json_files = list(strategy_dir.glob("*.json"))
        print(f"\n策略 {strategy_name}: {len(json_files)} 个日期")
        
        added_count = 0
        batch_data = []
        
        for json_file in tqdm(json_files, desc=f"迁移 {strategy_name}"):
            try:
                date_str = json_file.stem
                trade_date = datetime.strptime(date_str, "%Y%m%d").strftime('%Y-%m-%d')
                
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                stock_codes = data.get('stocks', [])
                
                if stock_codes:
                    # 批量查询股票数据
                    placeholders = ','.join('?' * len(stock_codes))
                    query = f"""
                        SELECT stock_code, close, volume, prev_close 
                        FROM stock_daily 
                        WHERE trade_date = ? AND stock_code IN ({placeholders})
                    """
                    params = [trade_date] + stock_codes
                    cursor.execute(query, params)
                    stock_data_map = {row[0]: row for row in cursor.fetchall()}
                    
                    # 填充数据
                    for stock_code in stock_codes:
                        stock_info = stock_data_map.get(stock_code)
                        
                        if stock_info:
                            close_price = stock_info[1]
                            volume = stock_info[2]
                            prev_close = stock_info[3]
                            
                            # 计算涨跌幅
                            if close_price and prev_close and prev_close > 0:
                                change_pct = round((close_price - prev_close) / prev_close * 100, 2)
                            else:
                                change_pct = None
                        else:
                            close_price = None
                            change_pct = None
                            volume = None
                        
                        batch_data.append((
                            strategy_code,
                            trade_date,
                            stock_code,
                            close_price,
                            change_pct,
                            volume,
                            0,  # is_extreme_b1
                            0   # consecutive_extreme_b1_days
                        ))
                        
                        if len(batch_data) >= 1000:
                            cursor.executemany("""
                                INSERT OR REPLACE INTO strategy_picks (
                                    strategy, trade_date, stock_code, close, change_pct, volume,
                                    is_extreme_b1, consecutive_extreme_b1_days
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, batch_data)
                            conn.commit()
                            added_count += len(batch_data)
                            batch_data = []
            
            except Exception as e:
                print(f"\n处理 {json_file.name} 失败: {e}")
        
        # 插入剩余数据
        if batch_data:
            cursor.executemany("""
                INSERT OR REPLACE INTO strategy_picks (
                    strategy, trade_date, stock_code, close, change_pct, volume,
                    is_extreme_b1, consecutive_extreme_b1_days
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, batch_data)
            conn.commit()
            added_count += len(batch_data)
        
        print(f"✅ {strategy_name} 添加/更新了 {added_count} 条记录")
        total_added += added_count
    
    conn.close()
    print(f"\n✅ 总计添加/更新了 {total_added} 条策略记录")


def migrate_learning_cases():
    """迁移学习案例数据"""
    print("\n" + "=" * 60)
    print("迁移学习案例数据")
    print("=" * 60)
    
    if not LEARNING_CASES_PATH.exists():
        print("⚠️  learning_cases 目录不存在")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    strategies = ['B1', 'B2', 'single_needle']
    periods = [3, 5, 10]
    
    total_added = 0
    
    for strategy in strategies:
        strategy_dir = LEARNING_CASES_PATH / strategy
        
        if not strategy_dir.exists():
            print(f"⚠️  {strategy} 目录不存在")
            continue
        
        json_files = list(strategy_dir.glob("*.json"))
        if not json_files:
            continue
        
        print(f"\n{strategy}: {len(json_files)} 个日期")
        
        added_count = 0
        batch_data = []
        
        for json_file in tqdm(json_files, desc=f"迁移 {strategy}"):
            try:
                date_str = json_file.stem
                trade_date = datetime.strptime(date_str, "%Y%m%d").strftime('%Y-%m-%d')
                
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 新格式：market_groups -> A/B -> top_cases -> 3d/5d/10d
                market_groups = data.get('market_groups', {})
                
                for market_key, market_data in market_groups.items():
                    top_cases = market_data.get('top_cases', {})
                    
                    for period_key, cases in top_cases.items():
                        # 期间映射: "3d" -> 3
                        period = int(period_key.replace('d', ''))
                        
                        if period not in periods:
                            continue
                        
                        for rank, case in enumerate(cases, start=1):
                            stock_code = case.get('stock_code')
                            return_pct = case.get('return_pct')
                            
                            if stock_code and return_pct is not None:
                                batch_data.append((
                                    strategy,
                                    trade_date,
                                    period,
                                    stock_code,
                                    float(return_pct),
                                    rank
                                ))
                                
                                if len(batch_data) >= 1000:
                                    cursor.executemany("""
                                        INSERT OR REPLACE INTO learning_cases (
                                            strategy, trade_date, period, stock_code, 
                                            future_return, rank_position
                                        ) VALUES (?, ?, ?, ?, ?, ?)
                                    """, batch_data)
                                    conn.commit()
                                    added_count += len(batch_data)
                                    batch_data = []
            
            except Exception as e:
                print(f"\n处理 {json_file.name} 失败: {e}")
        
        # 插入剩余数据
        if batch_data:
            cursor.executemany("""
                INSERT OR REPLACE INTO learning_cases (
                    strategy, trade_date, period, stock_code, 
                    future_return, rank_position
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, batch_data)
            conn.commit()
            added_count += len(batch_data)
        
        if added_count > 0:
            print(f"✅ {strategy} 添加了 {added_count} 条案例")
            total_added += added_count
    
    conn.close()
    
    if total_added > 0:
        print(f"\n✅ 总计添加了 {total_added:,} 条学习案例")
    else:
        print("\n⚠️  未找到学习案例数据")


def verify_data():
    """验证数据"""
    print("\n" + "=" * 60)
    print("验证数据完整性")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 检查策略数据
    for strategy in ['B1', 'B2', 'single_needle']:
        cursor.execute("""
            SELECT COUNT(*) FROM strategy_picks WHERE strategy = ?
        """, (strategy,))
        count = cursor.fetchone()[0]
        print(f"{strategy:15} {count:>10,} 条")
    
    # 检查极致B1
    cursor.execute("""
        SELECT COUNT(*) FROM strategy_picks 
        WHERE strategy = 'B1' AND is_extreme_b1 = 1
    """)
    extreme_count = cursor.fetchone()[0]
    print(f"{'极致B1':15} {extreme_count:>10,} 条")
    
    # 检查学习案例
    cursor.execute("SELECT COUNT(*) FROM learning_cases")
    case_count = cursor.fetchone()[0]
    print(f"{'学习案例':15} {case_count:>10,} 条")
    
    # 测试一个具体日期
    test_date = '2025-12-31'
    print(f"\n测试日期 {test_date}:")
    
    for strategy in ['B1', 'B2', 'single_needle']:
        cursor.execute("""
            SELECT COUNT(*) FROM strategy_picks 
            WHERE strategy = ? AND trade_date = ?
        """, (strategy, test_date))
        count = cursor.fetchone()[0]
        print(f"  {strategy}: {count} 只")
    
    conn.close()


def main():
    """主函数"""
    print("=" * 60)
    print("完整数据修复工具")
    print("=" * 60)
    
    # 1. 修复极致B1
    fix_extreme_b1()
    
    # 2. 补充B2和单针策略
    migrate_missing_strategies()
    
    # 3. 迁移学习案例
    migrate_learning_cases()
    
    # 4. 验证数据
    verify_data()
    
    print("\n" + "=" * 60)
    print("✅ 所有数据修复完成！")
    print("=" * 60)


if __name__ == '__main__':
    main()
