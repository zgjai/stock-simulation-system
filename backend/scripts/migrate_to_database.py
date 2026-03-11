"""
数据迁移脚本：将CSV/JSON数据导入数据库

使用方法：
    python backend/scripts/migrate_to_database.py

环境变量：
    DATABASE_URL: PostgreSQL连接字符串（从 .env 文件读取）
"""

import os
import sys
import json
import pandas as pd
from pathlib import Path
from tqdm import tqdm
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

# 加载环境变量
PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / '.env')

# 添加项目根目录到路径
sys.path.append(str(PROJECT_ROOT))

# 数据路径
PROCESSED_PATH = PROJECT_ROOT / "processed_data"
INDEX_PATH = PROJECT_ROOT / "strategy_index"
LEARNING_CASES_PATH = PROJECT_ROOT / "learning_cases"

# 数据库连接
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ 错误: DATABASE_URL 环境变量未设置")
    print("\n请在项目根目录创建 .env 文件，并添加：")
    print('DATABASE_URL="postgresql://postgres:[PASSWORD]@db.xxx.supabase.co:5432/postgres"')
    sys.exit(1)


def get_db_connection():
    """获取数据库连接"""
    return psycopg2.connect(DATABASE_URL)


def create_tables(conn):
    """创建数据库表"""
    print("创建数据库表...")
    
    with conn.cursor() as cur:
        # 股票日线数据表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                id BIGSERIAL PRIMARY KEY,
                stock_code VARCHAR(10) NOT NULL,
                trade_date DATE NOT NULL,
                
                open DECIMAL(10, 2),
                high DECIMAL(10, 2),
                low DECIMAL(10, 2),
                close DECIMAL(10, 2),
                volume BIGINT,
                prev_close DECIMAL(10, 2),
                
                kdj_k DECIMAL(10, 2),
                kdj_d DECIMAL(10, 2),
                kdj_j DECIMAL(10, 2),
                macd_dif DECIMAL(10, 4),
                macd_dea DECIMAL(10, 4),
                macd_hist DECIMAL(10, 4),
                ma5 DECIMAL(10, 2),
                ma10 DECIMAL(10, 2),
                vol_ma5 BIGINT,
                vol_ma60 BIGINT,
                
                b1_signal SMALLINT DEFAULT 0,
                b2_signal SMALLINT DEFAULT 0,
                single_needle_signal SMALLINT DEFAULT 0,
                
                factor_amplitude DECIMAL(10, 2),
                factor_volume_ratio DECIMAL(10, 4),
                factor_zhixing_ratio DECIMAL(10, 4),
                factor_j_value DECIMAL(10, 2),
                
                UNIQUE(stock_code, trade_date)
            );
            
            CREATE INDEX IF NOT EXISTS idx_date ON stock_daily(trade_date);
            CREATE INDEX IF NOT EXISTS idx_code_date ON stock_daily(stock_code, trade_date);
            CREATE INDEX IF NOT EXISTS idx_b1_signal ON stock_daily(trade_date, b1_signal) WHERE b1_signal = 1;
            CREATE INDEX IF NOT EXISTS idx_b2_signal ON stock_daily(trade_date, b2_signal) WHERE b2_signal = 1;
        """)
        
        # 策略候选池表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strategy_picks (
                id SERIAL PRIMARY KEY,
                strategy VARCHAR(50) NOT NULL,
                trade_date DATE NOT NULL,
                stock_code VARCHAR(10) NOT NULL,
                
                close DECIMAL(10, 2),
                change_pct DECIMAL(10, 2),
                volume BIGINT,
                is_extreme_b1 BOOLEAN DEFAULT FALSE,
                consecutive_extreme_b1_days INT DEFAULT 0,
                
                UNIQUE(strategy, trade_date, stock_code)
            );
            
            CREATE INDEX IF NOT EXISTS idx_strategy_date ON strategy_picks(strategy, trade_date);
        """)
        
        # 学习案例表
        cur.execute("""
            CREATE TABLE IF NOT EXISTS learning_cases (
                id SERIAL PRIMARY KEY,
                strategy VARCHAR(50) NOT NULL,
                trade_date DATE NOT NULL,
                period INT NOT NULL,
                stock_code VARCHAR(10) NOT NULL,
                future_return DECIMAL(10, 4),
                rank_position INT,
                
                UNIQUE(strategy, trade_date, period, stock_code)
            );
            
            CREATE INDEX IF NOT EXISTS idx_strategy_date_period 
            ON learning_cases(strategy, trade_date, period);
        """)
        
        conn.commit()
    
    print("✅ 表创建完成")


def migrate_stock_daily_data(conn):
    """迁移股票日线数据"""
    print("\n开始迁移股票日线数据...")
    
    csv_files = list(PROCESSED_PATH.glob("*.csv"))
    print(f"找到 {len(csv_files)} 个CSV文件")
    
    batch_size = 1000
    batch_data = []
    
    with conn.cursor() as cur:
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
                        row['date'].date(),
                        row.get('open'),
                        row.get('high'),
                        row.get('low'),
                        row.get('close'),
                        row.get('volumn'),  # 注意字段名
                        row.get('prev_close'),
                        row.get('kdj_k'),
                        row.get('kdj_d'),
                        row.get('kdj_j'),
                        row.get('macd_dif'),
                        row.get('macd_dea'),
                        row.get('macd_hist'),
                        row.get('ma5'),
                        row.get('ma10'),
                        row.get('vol_ma5'),
                        row.get('vol_ma60'),
                        row.get('b1_signal', 0),
                        row.get('b2_signal', 0),
                        row.get('single_needle_signal', 0),
                        row.get('factor_amplitude'),
                        row.get('factor_volume_ratio'),
                        row.get('factor_zhixing_ratio'),
                        row.get('factor_j_value'),
                    ))
                    
                    # 批量插入
                    if len(batch_data) >= batch_size:
                        execute_batch(cur, """
                            INSERT INTO stock_daily (
                                stock_code, trade_date, open, high, low, close, volume, prev_close,
                                kdj_k, kdj_d, kdj_j, macd_dif, macd_dea, macd_hist,
                                ma5, ma10, vol_ma5, vol_ma60,
                                b1_signal, b2_signal, single_needle_signal,
                                factor_amplitude, factor_volume_ratio, factor_zhixing_ratio, factor_j_value
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (stock_code, trade_date) DO NOTHING
                        """, batch_data)
                        conn.commit()
                        batch_data = []
                
            except Exception as e:
                print(f"❌ 处理 {stock_code} 失败: {e}")
                continue
        
        # 插入剩余数据
        if batch_data:
            execute_batch(cur, """
                INSERT INTO stock_daily (
                    stock_code, trade_date, open, high, low, close, volume, prev_close,
                    kdj_k, kdj_d, kdj_j, macd_dif, macd_dea, macd_hist,
                    ma5, ma10, vol_ma5, vol_ma60,
                    b1_signal, b2_signal, single_needle_signal,
                    factor_amplitude, factor_volume_ratio, factor_zhixing_ratio, factor_j_value
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (stock_code, trade_date) DO NOTHING
            """, batch_data)
            conn.commit()
    
    print("✅ 股票日线数据迁移完成")


def migrate_strategy_index(conn):
    """迁移策略索引数据"""
    print("\n开始迁移策略索引...")
    
    strategies = ['B1', 'B2', 'single_needle']
    batch_data = []
    batch_size = 1000
    
    with conn.cursor() as cur:
        for strategy in strategies:
            strategy_dir = INDEX_PATH / strategy
            if not strategy_dir.exists():
                continue
            
            json_files = list(strategy_dir.glob("*.json"))
            print(f"策略 {strategy}: {len(json_files)} 个日期")
            
            for json_file in tqdm(json_files, desc=f"迁移 {strategy}"):
                try:
                    date_str = json_file.stem
                    trade_date = datetime.strptime(date_str, "%Y%m%d").date()
                    
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    for stock_code in data.get('stocks', []):
                        batch_data.append((
                            strategy,
                            trade_date,
                            stock_code,
                            None,  # close (稍后更新)
                            None,  # change_pct
                            None,  # volume
                            False,  # is_extreme_b1
                            0,  # consecutive_extreme_b1_days
                        ))
                        
                        if len(batch_data) >= batch_size:
                            execute_batch(cur, """
                                INSERT INTO strategy_picks (
                                    strategy, trade_date, stock_code, close, change_pct, volume,
                                    is_extreme_b1, consecutive_extreme_b1_days
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (strategy, trade_date, stock_code) DO NOTHING
                            """, batch_data)
                            conn.commit()
                            batch_data = []
                
                except Exception as e:
                    print(f"❌ 处理 {json_file.name} 失败: {e}")
                    continue
        
        # 插入剩余数据
        if batch_data:
            execute_batch(cur, """
                INSERT INTO strategy_picks (
                    strategy, trade_date, stock_code, close, change_pct, volume,
                    is_extreme_b1, consecutive_extreme_b1_days
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (strategy, trade_date, stock_code) DO NOTHING
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
    
    with conn.cursor() as cur:
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
                        trade_date = datetime.strptime(date_str, "%Y%m%d").date()
                        
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        for idx, item in enumerate(data.get('top_stocks', [])):
                            batch_data.append((
                                strategy,
                                trade_date,
                                period,
                                item['code'],
                                item.get('future_return'),
                                idx + 1,  # rank_position
                            ))
                            
                            if len(batch_data) >= batch_size:
                                execute_batch(cur, """
                                    INSERT INTO learning_cases (
                                        strategy, trade_date, period, stock_code, future_return, rank_position
                                    ) VALUES (%s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (strategy, trade_date, period, stock_code) DO NOTHING
                                """, batch_data)
                                conn.commit()
                                batch_data = []
                    
                    except Exception as e:
                        print(f"❌ 处理 {json_file.name} 失败: {e}")
                        continue
        
        # 插入剩余数据
        if batch_data:
            execute_batch(cur, """
                INSERT INTO learning_cases (
                    strategy, trade_date, period, stock_code, future_return, rank_position
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (strategy, trade_date, period, stock_code) DO NOTHING
            """, batch_data)
            conn.commit()
    
    print("✅ 学习案例迁移完成")


def main():
    """主函数"""
    print("="*60)
    print("数据库迁移脚本 - Supabase 版本")
    print("="*60)
    
    # 显示数据库连接信息（隐藏密码）
    masked_url = DATABASE_URL
    if '@' in masked_url:
        parts = masked_url.split('@')
        if ':' in parts[0]:
            user_pass = parts[0].split(':')
            masked_url = f"{user_pass[0]}:***@{parts[1]}"
    
    print(f"数据库: {masked_url}")
    
    # 连接数据库
    try:
        conn = get_db_connection()
        print(f"✅ 数据库连接成功")
    except Exception as e:
        print(f"❌ 数据库连接失败: {e}")
        print("\n常见问题：")
        print("1. 检查 .env 文件中的 DATABASE_URL 是否正确")
        print("2. 确认密码中的特殊字符已正确转义")
        print("3. 检查网络连接（Supabase在海外，可能需要代理）")
        return
    
    try:
        # 创建表
        create_tables(conn)
        
        # 迁移数据
        migrate_stock_daily_data(conn)
        migrate_strategy_index(conn)
        migrate_learning_cases(conn)
        
        # 统计信息
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM stock_daily")
            daily_count = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM strategy_picks")
            picks_count = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM learning_cases")
            cases_count = cur.fetchone()[0]
        
        print("\n" + "="*60)
        print("迁移完成统计")
        print("="*60)
        print(f"股票日线数据: {daily_count:,} 条")
        print(f"策略候选池: {picks_count:,} 条")
        print(f"学习案例: {cases_count:,} 条")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ 迁移过程出错: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
