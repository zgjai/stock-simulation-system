"""
砖型图指标迁移脚本：
1. 为 stock_daily 表添加 brick_value / brick_body 字段
2. 批量计算所有股票的砖型图历史数据并写入数据库

使用方法：
    cd /Users/zhangguijiang/project/stock/stock_simulation_system
    python backend/scripts/add_brick_indicator.py
"""

import os
import sys
import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from tqdm import tqdm

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "stock.db"

sys.path.insert(0, str(PROJECT_ROOT / "backend" / "scripts"))
from indicators import calc_brick_chart


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    return conn


def migrate_add_columns(conn):
    """为 stock_daily 表添加砖型图字段（如果不存在）"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(stock_daily)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    added = False
    if 'brick_value' not in existing_cols:
        cursor.execute("ALTER TABLE stock_daily ADD COLUMN brick_value REAL")
        print("✅ 已添加字段: brick_value")
        added = True
    if 'brick_body' not in existing_cols:
        cursor.execute("ALTER TABLE stock_daily ADD COLUMN brick_body REAL")
        print("✅ 已添加字段: brick_body")
        added = True

    if not added:
        print("ℹ️  字段已存在，跳过 ALTER TABLE")
    conn.commit()


def calc_and_update_all(conn):
    """读取所有股票数据，计算砖型图，批量更新"""
    cursor = conn.cursor()

    # 获取所有股票代码
    cursor.execute("SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code")
    codes = [row[0] for row in cursor.fetchall()]
    print(f"共 {len(codes)} 只股票需要处理")

    batch_size = 500
    total_updated = 0

    for code in tqdm(codes, desc="计算砖型图"):
        # 读取该股票全部数据
        df = pd.read_sql_query(
            "SELECT id, trade_date, high, low, close FROM stock_daily "
            "WHERE stock_code = ? ORDER BY trade_date ASC",
            conn,
            params=(code,)
        )

        if df.empty:
            continue

        # 计算砖型图
        result = calc_brick_chart(df)
        df['brick_value'] = result['brick_value'].values
        df['brick_body'] = result['brick_body'].values

        # 批量更新
        rows = [
            (
                None if (pd.isna(bv) or np.isinf(bv)) else round(float(bv), 4),
                None if (pd.isna(bb) or np.isinf(bb)) else round(float(bb), 4),
                int(row_id)
            )
            for row_id, bv, bb in zip(df['id'], df['brick_value'], df['brick_body'])
        ]

        cursor.executemany(
            "UPDATE stock_daily SET brick_value=?, brick_body=? WHERE id=?",
            rows
        )
        total_updated += len(rows)

        # 每处理50只股票提交一次
        if total_updated % (50 * batch_size) == 0:
            conn.commit()

    conn.commit()
    print(f"\n✅ 完成！共更新 {total_updated} 条记录")


if __name__ == "__main__":
    print(f"数据库路径: {DB_PATH}")
    if not DB_PATH.exists():
        print("❌ 数据库文件不存在，请先运行迁移脚本")
        sys.exit(1)

    conn = get_conn()
    try:
        print("\n=== 第1步：添加字段 ===")
        migrate_add_columns(conn)

        print("\n=== 第2步：批量计算并写入砖型图数据 ===")
        calc_and_update_all(conn)
    finally:
        conn.close()

    print("\n🎉 砖型图指标数据已全部写入数据库！")
