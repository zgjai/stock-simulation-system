"""
修复极致B1因子数据脚本
功能：
1. 为 strategy_picks 表添加 factor_amplitude 和 factor_volume_ratio 字段
2. 从 stock_daily 表更新因子数据
3. 重新计算 is_extreme_b1 标记
"""
import sqlite3
import sys
from pathlib import Path
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "stock.db"


def check_extreme_b1(stock_code, amplitude, volume_ratio):
    """检查是否满足极致B1条件"""
    if amplitude is None or volume_ratio is None:
        return False
    
    prefix = stock_code[:2]
    if prefix in ['00', '60']:
        # 主板: 振幅>=2.68 且 量比>=0.59
        return amplitude >= 2.68 and volume_ratio >= 0.59
    elif prefix in ['30', '68', '92']:
        # 创业板/科创板/北交所: 振幅>=3.46 且 量比>=0.42
        return amplitude >= 3.46 and volume_ratio >= 0.42
    return False


def main():
    if not DB_PATH.exists():
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return
    
    print(f"📊 数据库路径: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    print("\n" + "="*60)
    print("步骤1: 添加缺失字段")
    print("="*60)
    
    # 检查字段是否存在
    cursor.execute("PRAGMA table_info(strategy_picks)")
    columns = [row[1] for row in cursor.fetchall()]
    
    fields_to_add = []
    if 'factor_amplitude' not in columns:
        fields_to_add.append(('factor_amplitude', 'REAL'))
    if 'factor_volume_ratio' not in columns:
        fields_to_add.append(('factor_volume_ratio', 'REAL'))
    
    if fields_to_add:
        for field_name, field_type in fields_to_add:
            try:
                cursor.execute(f"ALTER TABLE strategy_picks ADD COLUMN {field_name} {field_type}")
                print(f"✅ 添加字段: {field_name}")
            except sqlite3.OperationalError as e:
                print(f"⚠️  字段已存在: {field_name}")
        conn.commit()
    else:
        print("✅ 所有字段已存在")
    
    print("\n" + "="*60)
    print("步骤2: 更新因子数据")
    print("="*60)
    
    # 查询所有策略候选记录
    cursor.execute("""
        SELECT DISTINCT strategy, trade_date, stock_code 
        FROM strategy_picks
        ORDER BY trade_date DESC
    """)
    picks = cursor.fetchall()
    
    print(f"📌 找到 {len(picks)} 条候选记录")
    
    # 批量更新
    batch_updates = []
    no_data_count = 0
    
    print("\n⏳ 正在从 stock_daily 读取因子数据...")
    for strategy, trade_date, stock_code in tqdm(picks, desc="处理进度"):
        # 从 stock_daily 读取因子数据
        cursor.execute("""
            SELECT factor_amplitude, factor_volume_ratio
            FROM stock_daily
            WHERE stock_code = ? AND trade_date = ?
        """, (stock_code, trade_date))
        
        result = cursor.fetchone()
        if result and result[0] is not None and result[1] is not None:
            amplitude, volume_ratio = result
            is_extreme_b1 = check_extreme_b1(stock_code, amplitude, volume_ratio)
            
            batch_updates.append((
                amplitude,
                volume_ratio,
                int(is_extreme_b1),
                stock_code,
                trade_date
            ))
        else:
            no_data_count += 1
    
    print(f"\n⚠️  无因子数据的记录: {no_data_count}")
    print(f"✅ 可更新的记录: {len(batch_updates)}")
    
    if batch_updates:
        print("\n⏳ 批量更新数据库...")
        cursor.executemany("""
            UPDATE strategy_picks
            SET factor_amplitude = ?,
                factor_volume_ratio = ?,
                is_extreme_b1 = ?
            WHERE stock_code = ? AND trade_date = ?
        """, batch_updates)
        
        conn.commit()
        print(f"✅ 成功更新 {len(batch_updates)} 条记录")
    
    print("\n" + "="*60)
    print("步骤3: 统计极致B1数据")
    print("="*60)
    
    # 按策略统计
    cursor.execute("""
        SELECT strategy, 
               COUNT(*) as total,
               SUM(CASE WHEN is_extreme_b1 = 1 THEN 1 ELSE 0 END) as extreme_count
        FROM strategy_picks
        GROUP BY strategy
        ORDER BY strategy
    """)
    
    stats = cursor.fetchall()
    for strategy_name, total, extreme_count in stats:
        extreme_pct = (extreme_count / total * 100) if total > 0 else 0
        print(f"\n策略: {strategy_name}")
        print(f"  总候选数: {total:,}")
        print(f"  极致B1数: {extreme_count:,}")
        print(f"  极致B1占比: {extreme_pct:.2f}%")
    
    # 验证数据完整性
    print("\n" + "="*60)
    print("步骤4: 验证数据完整性")
    print("="*60)
    
    cursor.execute("""
        SELECT COUNT(*) 
        FROM strategy_picks 
        WHERE factor_amplitude IS NULL OR factor_volume_ratio IS NULL
    """)
    null_count = cursor.fetchone()[0]
    
    if null_count > 0:
        print(f"⚠️  仍有 {null_count} 条记录的因子数据为空")
    else:
        print("✅ 所有记录的因子数据完整")
    
    conn.close()
    print("\n" + "="*60)
    print("🎉 修复完成！")
    print("="*60)
    print("\n💡 下一步: 重启后端服务，刷新前端页面验证")


if __name__ == "__main__":
    main()
