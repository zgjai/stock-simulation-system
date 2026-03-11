"""
数据迁移脚本：将CSV/JSON数据导入 SQLite 数据库

使用方法：
    python backend/scripts/migrate_to_sqlite.py
    
特点：
    - 本地 SQLite 数据库
    - 快速迁移（10-20分钟）
    - 支持断点续传
"""

import os
import sys
import json
import pandas as pd
from pathlib import Path
from tqdm import tqdm
from datetime import datetime
import sqlite3

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

# 数据路径
PROCESSED_PATH = PROJECT_ROOT / "processed_data"
INDEX_PATH = PROJECT_ROOT / "strategy_index"
LEARNING_CASES_PATH = PROJECT_ROOT / "learning_cases"
DB_PATH = PROJECT_ROOT / "data" / "stock.db"

# 确保 data 目录存在
DB_PATH.parent.mkdir(exist_ok=True)


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    # 启用 WAL 模式
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64MB缓存
    return conn


def create_tables(conn):
    """创建数据库表"""
    print("创建数据库表...")
    
    cursor = conn.cursor()
    
    # 股票日线数据表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            prev_close REAL,
            amount REAL,
            
            ma5 REAL,
            ma10 REAL,
            vol_ma5 INTEGER,
            vol_ma60 INTEGER,
            kdj_k REAL,
            kdj_d REAL,
            kdj_j REAL,
            macd_dif REAL,
            macd_dea REAL,
            macd_hist REAL,
            
            b1_signal INTEGER DEFAULT 0,
            b2_signal INTEGER DEFAULT 0,
            single_needle_signal INTEGER DEFAULT 0,
            
            factor_amplitude REAL,
            factor_volume_ratio REAL,
            factor_j_value REAL,
            
            UNIQUE(stock_code, trade_date)
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_date ON stock_daily(stock_code, trade_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON stock_daily(trade_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_date_b1 ON stock_daily(trade_date, b1_signal)")
    
    # 策略候选池表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL,
            trade_date DATE NOT NULL,
            stock_code TEXT NOT NULL,
            
            close REAL,
            change_pct REAL,
            volume INTEGER,
            is_extreme_b1 INTEGER DEFAULT 0,
            consecutive_extreme_b1_days INTEGER DEFAULT 0,
            
            UNIQUE(strategy, trade_date, stock_code)
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_date ON strategy_picks(strategy, trade_date)")
    
    # 学习案例表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy TEXT NOT NULL,
            trade_date DATE NOT NULL,
            period INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            future_return REAL,
            rank_position INTEGER,
            
            UNIQUE(strategy, trade_date, period, stock_code)
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_date_period ON learning_cases(strategy, trade_date, period)")
    
    conn.commit()
    print("✅ 表创建完成")


def migrate_stock_daily_data(conn):
    """迁移股票日线数据"""
    print("\n开始迁移股票日线数据...")
    
    csv_files = list(PROCESSED_PATH.glob("*.csv"))
    print(f"找到 {len(csv_files)} 个CSV文件")
    
    batch_size = 1000
    batch_data = []
    
    cursor = conn.cursor()
    
    for csv_file in tqdm(csv_files, desc="迁移进度"):
        stock_code = csv_file.stem
        
        try:
            df = pd.read_csv(csv_file)
            df['date'] = pd.to_datetime(df['date'])
            
            # 清理NaN和Inf
            df = df.replace([float('inf'), float('-inf')], None)
            df = df.where(pd.notna(df), None)
            
            for _, row in df.iterrows():
                batch_data.append((
                    stock_code,
                    row['date'].strftime('%Y-%m-%d'),
                    row.get('open'),
                    row.get('high'),
                    row.get('low'),
                    row.get('close'),
                    int(row.get('volumn')) if pd.notna(row.get('volumn')) else None,
                    row.get('prev_close'),
                    row.get('amount'),
                    row.get('ma5'),
                    row.get('ma10'),
                    int(row.get('vol_ma5')) if pd.notna(row.get('vol_ma5')) else None,
                    int(row.get('vol_ma60')) if pd.notna(row.get('vol_ma60')) else None,
                    row.get('kdj_k'),
                    row.get('kdj_d'),
                    row.get('kdj_j'),
                    row.get('macd_dif'),
                    row.get('macd_dea'),
                    row.get('macd_hist'),
                    int(row.get('b1_signal', 0)),
                    int(row.get('b2_signal', 0)),
                    int(row.get('single_needle_signal', 0)),
                    row.get('factor_amplitude'),
                    row.get('factor_volume_ratio'),
                    row.get('factor_j_value'),
                ))
                
                # 批量插入
                if len(batch_data) >= batch_size:
                    cursor.executemany("""
                        INSERT OR IGNORE INTO stock_daily (
                            stock_code, trade_date, open, high, low, close, volume, prev_close, amount,
                            ma5, ma10, vol_ma5, vol_ma60,
                            kdj_k, kdj_d, kdj_j, macd_dif, macd_dea, macd_hist,
                            b1_signal, b2_signal, single_needle_signal,
                            factor_amplitude, factor_volume_ratio, factor_j_value
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch_data)
                    conn.commit()
                    batch_data = []
        
        except Exception as e:
            print(f"\n❌ 处理 {stock_code} 失败: {e}")
            continue
    
    # 插入剩余数据
    if batch_data:
        cursor.executemany("""
            INSERT OR IGNORE INTO stock_daily (
                stock_code, trade_date, open, high, low, close, volume, prev_close, amount,
                ma5, ma10, vol_ma5, vol_ma60,
                kdj_k, kdj_d, kdj_j, macd_dif, macd_dea, macd_hist,
                b1_signal, b2_signal, single_needle_signal,
                factor_amplitude, factor_volume_ratio, factor_j_value
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch_data)
        conn.commit()
    
    print("✅ 股票日线数据迁移完成")


def migrate_strategy_index(conn):
    """迁移策略索引数据"""
    print("\n开始迁移策略索引...")
    
    strategies = ['B1', 'B2', 'single_needle']
    batch_data = []
    batch_size = 1000
    
    cursor = conn.cursor()
    
    for strategy in strategies:
        strategy_dir = INDEX_PATH / strategy
        if not strategy_dir.exists():
            continue
        
        json_files = list(strategy_dir.glob("*.json"))
        print(f"策略 {strategy}: {len(json_files)} 个日期")
        
        for json_file in tqdm(json_files, desc=f"迁移 {strategy}"):
            try:
                date_str = json_file.stem
                trade_date = datetime.strptime(date_str, "%Y%m%d").strftime('%Y-%m-%d')
                
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # 获取该日期的所有股票数据（用于填充候选池字段）
                stock_codes = data.get('stocks', [])
                if stock_codes:
                    # 批量查询股票数据
                    placeholders = ','.join('?' * len(stock_codes))
                    query = f"""
                        SELECT stock_code, close, volume 
                        FROM stock_daily 
                        WHERE trade_date = ? AND stock_code IN ({placeholders})
                    """
                    params = [trade_date] + stock_codes
                    cursor.execute(query, params)
                    stock_data_map = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
                    
                    # 填充候选池数据
                    for stock_code in stock_codes:
                        stock_info = stock_data_map.get(stock_code, (None, None))
                        close_price = stock_info[0]
                        volume = stock_info[1]
                        
                        # 计算涨跌幅（需要prev_close）
                        if close_price:
                            cursor.execute("""
                                SELECT prev_close FROM stock_daily 
                                WHERE stock_code = ? AND trade_date = ?
                            """, (stock_code, trade_date))
                            result = cursor.fetchone()
                            prev_close = result[0] if result else None
                            
                            if prev_close and prev_close > 0:
                                change_pct = round((close_price - prev_close) / prev_close * 100, 2)
                            else:
                                change_pct = None
                        else:
                            change_pct = None
                        
                        batch_data.append((
                            strategy,
                            trade_date,
                            stock_code,
                            close_price,
                            change_pct,
                            volume,
                            0,  # is_extreme_b1
                            0   # consecutive_extreme_b1_days
                        ))
                        
                        if len(batch_data) >= batch_size:
                            cursor.executemany("""
                                INSERT OR IGNORE INTO strategy_picks (
                                    strategy, trade_date, stock_code, close, change_pct, volume,
                                    is_extreme_b1, consecutive_extreme_b1_days
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, batch_data)
                            conn.commit()
                            batch_data = []
            
            except Exception as e:
                print(f"\n❌ 处理 {json_file.name} 失败: {e}")
                continue
    
    # 插入剩余数据
    if batch_data:
        cursor.executemany("""
            INSERT OR IGNORE INTO strategy_picks (
                strategy, trade_date, stock_code, close, change_pct, volume,
                is_extreme_b1, consecutive_extreme_b1_days
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, batch_data)
        conn.commit()
    
    print("✅ 策略索引迁移完成")


def migrate_learning_cases(conn):
    """迁移学习案例数据"""
    print("\n开始迁移学习案例...")
    
    if not LEARNING_CASES_PATH.exists():
        print("⚠️  learning_cases 目录不存在，跳过")
        return
    
    strategies = ['B1', 'B2', 'single_needle']
    periods = [3, 5, 10]
    batch_data = []
    batch_size = 1000
    
    cursor = conn.cursor()
    
    for strategy in strategies:
        for period in periods:
            strategy_dir = LEARNING_CASES_PATH / strategy / f"{period}d"
            if not strategy_dir.exists():
                continue
            
            json_files = list(strategy_dir.glob("*.json"))
            print(f"策略 {strategy} {period}日: {len(json_files)} 个日期")
            
            for json_file in tqdm(json_files, desc=f"迁移 {strategy} {period}d"):
                try:
                    date_str = json_file.stem
                    trade_date = datetime.strptime(date_str, "%Y%m%d").strftime('%Y-%m-%d')
                    
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    for idx, item in enumerate(data.get('top_stocks', [])):
                        batch_data.append((
                            strategy,
                            trade_date,
                            period,
                            item['code'],
                            item.get('future_return'),
                            idx + 1,
                        ))
                        
                        if len(batch_data) >= batch_size:
                            cursor.executemany("""
                                INSERT OR IGNORE INTO learning_cases (
                                    strategy, trade_date, period, stock_code, future_return, rank_position
                                ) VALUES (?, ?, ?, ?, ?, ?)
                            """, batch_data)
                            conn.commit()
                            batch_data = []
                
                except Exception as e:
                    print(f"\n❌ 处理 {json_file.name} 失败: {e}")
                    continue
    
    # 插入剩余数据
    if batch_data:
        cursor.executemany("""
            INSERT OR IGNORE INTO learning_cases (
                strategy, trade_date, period, stock_code, future_return, rank_position
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, batch_data)
        conn.commit()
    
    print("✅ 学习案例迁移完成")


def main():
    """主函数"""
    print("="*60)
    print("SQLite 数据库迁移脚本")
    print("="*60)
    print(f"数据库路径: {DB_PATH}")
    
    # 连接数据库
    try:
        conn = get_db_connection()
        print("✅ 数据库连接成功")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        return
    
    try:
        # 创建表
        create_tables(conn)
        
        # 迁移数据
        migrate_stock_daily_data(conn)
        migrate_strategy_index(conn)
        migrate_learning_cases(conn)
        
        # 统计信息
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM stock_daily")
        daily_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM strategy_picks")
        picks_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM learning_cases")
        cases_count = cursor.fetchone()[0]
        
        # 数据库大小
        db_size_mb = DB_PATH.stat().st_size / 1024 / 1024
        
        print("\n" + "="*60)
        print("迁移完成统计")
        print("="*60)
        print(f"股票日线数据: {daily_count:,} 条")
        print(f"策略候选池: {picks_count:,} 条")
        print(f"学习案例: {cases_count:,} 条")
        print(f"数据库大小: {db_size_mb:.2f} MB")
        print("="*60)
        
        # 优化数据库
        print("\n优化数据库...")
        cursor.execute("VACUUM")
        cursor.execute("ANALYZE")
        conn.commit()
        print("✅ 数据库优化完成")
        
    except Exception as e:
        print(f"\n❌ 迁移过程出错: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
