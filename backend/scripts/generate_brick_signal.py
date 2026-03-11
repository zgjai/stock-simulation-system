"""
砖型选股信号 - 存量数据清洗脚本（数据库版）

功能：
1. 为 stock_daily 表新增 brick_signal 字段（若不存在）
2. 直接从数据库读取 brick_value / ema10_2 / multi_line / close，计算 brick_signal
3. 将砖型选股候选池写入 strategy_picks 表（strategy='brick'）
4. 生成 strategy_index/brick/*.json 索引文件

用法：
    cd /Users/zhangguijiang/project/stock/stock_simulation_system
    python backend/scripts/generate_brick_signal.py

注意：brick_ratio 默认 2/3（0.667），该脚本以此为基准构建候选池。
前端查询时可通过 ?brick_ratio=X 参数实时过滤，无需重新跑脚本。
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from tqdm import tqdm

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent

# 路径配置
INDEX_PATH = PROJECT_ROOT / "strategy_index" / "brick"
DB_PATH    = PROJECT_ROOT / "data" / "stock.db"

# 默认 brick_ratio（2/3），用于基准候选池入库
DEFAULT_BRICK_RATIO = 2.0 / 3.0


# ──────────────────────────────────────────────
# 数据库工具
# ──────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-128000")  # 128MB 缓存
    return conn


def ensure_brick_signal_column(conn):
    """确保 stock_daily 表有 brick_signal 列"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(stock_daily)")
    cols = [row[1] for row in cursor.fetchall()]

    # 若存在旧的 b3_signal 列，将其数据迁移到 brick_signal
    if 'b3_signal' in cols and 'brick_signal' not in cols:
        print("检测到旧列 b3_signal，迁移数据到 brick_signal ...")
        cursor.execute("ALTER TABLE stock_daily ADD COLUMN brick_signal INTEGER DEFAULT 0")
        cursor.execute("UPDATE stock_daily SET brick_signal = b3_signal")
        conn.commit()
        print("✅ 数据迁移完成（b3_signal → brick_signal）")
    elif 'brick_signal' not in cols:
        print("新增 brick_signal 列...")
        cursor.execute("ALTER TABLE stock_daily ADD COLUMN brick_signal INTEGER DEFAULT 0")
        conn.commit()
        print("✅ brick_signal 列已创建")
    else:
        print("brick_signal 列已存在")

    # 确保索引存在
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_date_brick ON stock_daily(trade_date, brick_signal)")
    conn.commit()


def ensure_strategy_picks_columns(conn):
    """确保 strategy_picks 表有 factor_amplitude / factor_volume_ratio 列"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(strategy_picks)")
    cols = [row[1] for row in cursor.fetchall()]
    for col, col_type in [('factor_amplitude', 'REAL'), ('factor_volume_ratio', 'REAL')]:
        if col not in cols:
            cursor.execute(f"ALTER TABLE strategy_picks ADD COLUMN {col} {col_type}")
    conn.commit()


# ──────────────────────────────────────────────
# 砖型选股信号计算（基于数据库数据）
# ──────────────────────────────────────────────

def compute_brick_signal_for_stock(rows: list, brick_ratio: float) -> list:
    """
    给定一只股票的按日期排序记录列表，计算砖型选股信号。

    rows 列结构：(stock_code, trade_date, brick_value, ema10_2, multi_line, close,
                  prev_close, volume, factor_amplitude, factor_volume_ratio)

    返回满足条件的行列表（brick_signal=1）。

    条件：
    1. 砖型动量柱由绿转红：T-1日 delta < 0，T日 delta > 0
    2. 红柱长度 > 绿柱长度 × brick_ratio
    3. ema10_2 > multi_line（知行短期趋势线 > 知行多空线）
    4. close > multi_line（收盘价 > 知行多空线）
    """
    signals = []
    n = len(rows)
    for i in range(2, n):
        r     = rows[i]
        prev  = rows[i - 1]
        prev2 = rows[i - 2]

        bv       = r[2]
        bv_prev  = prev[2]
        bv_prev2 = prev2[2]
        ema10_2  = r[3]
        multi_line = r[4]
        close    = r[5]

        # 字段完整性
        if any(v is None for v in [bv, bv_prev, bv_prev2, ema10_2, multi_line, close]):
            continue

        today_delta = float(bv) - float(bv_prev)
        prev_delta  = float(bv_prev) - float(bv_prev2)

        # 条件1：绿转红
        if prev_delta >= 0 or today_delta <= 0:
            continue

        red_len   = today_delta
        green_len = abs(prev_delta)

        # 条件2：比例
        if red_len <= green_len * brick_ratio:
            continue

        # 条件3：多头趋势
        if float(ema10_2) <= float(multi_line):
            continue

        # 条件4：收盘价高于多空线
        if float(close) <= float(multi_line):
            continue

        signals.append(r)

    return signals


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def update_stock_daily_brick_signal(conn):
    """从数据库批量计算并写入 brick_signal"""
    print("\n[1/3] 从数据库计算并写入 brick_signal ...")

    cursor = conn.cursor()

    # 先清零（避免重复计算产生脏数据）
    print("  清零旧 brick_signal 数据...")
    cursor.execute("UPDATE stock_daily SET brick_signal=0")
    conn.commit()

    # 获取所有股票代码
    cursor.execute("SELECT DISTINCT stock_code FROM stock_daily ORDER BY stock_code")
    stock_codes = [r[0] for r in cursor.fetchall()]
    print(f"  共 {len(stock_codes)} 只股票")

    brick_rows_all = []
    batch_updates  = []
    batch_size     = 10000
    updated_total  = 0

    for stock_code in tqdm(stock_codes, desc="  计算进度"):
        cursor.execute("""
            SELECT stock_code, trade_date, brick_value, ema10_2, multi_line, close,
                   prev_close, volume, factor_amplitude, factor_volume_ratio
            FROM stock_daily
            WHERE stock_code = ?
            ORDER BY trade_date ASC
        """, (stock_code,))
        rows = cursor.fetchall()

        if len(rows) < 3:
            continue

        hit_rows = compute_brick_signal_for_stock(rows, DEFAULT_BRICK_RATIO)

        for r in hit_rows:
            batch_updates.append((1, r[0], r[1]))  # (brick_signal, stock_code, trade_date)
            brick_rows_all.append(r)

        if len(batch_updates) >= batch_size:
            cursor.executemany(
                "UPDATE stock_daily SET brick_signal=? WHERE stock_code=? AND trade_date=?",
                batch_updates
            )
            conn.commit()
            updated_total += len(batch_updates)
            batch_updates = []

    if batch_updates:
        cursor.executemany(
            "UPDATE stock_daily SET brick_signal=? WHERE stock_code=? AND trade_date=?",
            batch_updates
        )
        conn.commit()
        updated_total += len(batch_updates)

    print(f"  ✅ 砖型选股信号条数: {len(brick_rows_all):,}，数据库更新 {updated_total:,} 行")
    return brick_rows_all


def build_strategy_picks_brick(conn, brick_rows_all: list):
    """将砖型选股候选池写入 strategy_picks 表（strategy='brick'）"""
    print("\n[2/3] 生成 strategy_picks（brick）...")

    cursor = conn.cursor()

    # 迁移旧的 B3 数据 → brick（如果存在）
    cursor.execute("SELECT COUNT(*) FROM strategy_picks WHERE strategy='B3'")
    old_count = cursor.fetchone()[0]
    if old_count > 0:
        print(f"  迁移旧 strategy='B3' 数据（{old_count:,} 条）→ strategy='brick' ...")
        cursor.execute("UPDATE strategy_picks SET strategy='brick' WHERE strategy='B3'")
        conn.commit()
        print("  ✅ 旧数据迁移完成")

    # 删除并重建 brick 候选池
    cursor.execute("DELETE FROM strategy_picks WHERE strategy='brick'")
    conn.commit()

    batch = []
    for r in tqdm(brick_rows_all, desc="  写入候选池"):
        stock_code, trade_date = r[0], r[1]
        close, prev_close, volume = r[5], r[6], r[7]
        fa, fvr = r[8], r[9]

        if prev_close and float(prev_close) > 0 and close:
            change_pct = round((float(close) - float(prev_close)) / float(prev_close) * 100, 2)
        else:
            change_pct = None

        batch.append((
            'brick',
            trade_date,
            stock_code,
            close,
            change_pct,
            volume,
            0,   # is_extreme_b1
            0,   # consecutive_extreme_b1_days
            fa,
            fvr,
        ))

        if len(batch) >= 5000:
            cursor.executemany("""
                INSERT OR IGNORE INTO strategy_picks
                  (strategy, trade_date, stock_code, close, change_pct, volume,
                   is_extreme_b1, consecutive_extreme_b1_days, factor_amplitude, factor_volume_ratio)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, batch)
            conn.commit()
            batch = []

    if batch:
        cursor.executemany("""
            INSERT OR IGNORE INTO strategy_picks
              (strategy, trade_date, stock_code, close, change_pct, volume,
               is_extreme_b1, consecutive_extreme_b1_days, factor_amplitude, factor_volume_ratio)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, batch)
        conn.commit()

    cursor.execute("SELECT COUNT(*) FROM strategy_picks WHERE strategy='brick'")
    cnt = cursor.fetchone()[0]
    print(f"  ✅ strategy_picks brick 共 {cnt:,} 条")


def build_index_files(conn):
    """生成 strategy_index/brick/*.json 索引文件"""
    print("\n[3/3] 生成索引文件 strategy_index/brick/ ...")

    INDEX_PATH.mkdir(parents=True, exist_ok=True)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT trade_date, stock_code FROM strategy_picks
        WHERE strategy='brick'
        ORDER BY trade_date, stock_code
    """)
    rows = cursor.fetchall()

    # 按日期分组
    date_map: dict = {}
    for trade_date, stock_code in rows:
        if hasattr(trade_date, 'strftime'):
            date_str = trade_date.strftime('%Y%m%d')
        else:
            date_str = str(trade_date).replace('-', '')
        if date_str not in date_map:
            date_map[date_str] = []
        date_map[date_str].append(stock_code)

    for date_str, stocks in tqdm(date_map.items(), desc="  写入JSON"):
        idx_file = INDEX_PATH / f"{date_str}.json"
        data = {
            "date": date_str,
            "strategy": "brick",
            "stocks": sorted(stocks),
            "count": len(stocks)
        }
        with open(idx_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 共生成 {len(date_map)} 个索引文件")


def main():
    print("=" * 60)
    print("砖型选股 - 存量数据清洗（数据库版）")
    print(f"  数据库: {DB_PATH}")
    print(f"  默认比例门槛: {DEFAULT_BRICK_RATIO:.3f}（2/3）")
    print("=" * 60)

    if not DB_PATH.exists():
        print(f"❌ 数据库不存在: {DB_PATH}")
        sys.exit(1)

    conn = get_conn()
    try:
        ensure_brick_signal_column(conn)
        ensure_strategy_picks_columns(conn)
        brick_rows_all = update_stock_daily_brick_signal(conn)
        build_strategy_picks_brick(conn, brick_rows_all)
        build_index_files(conn)

        print("\n" + "=" * 60)
        print("✅ 砖型选股存量数据清洗完成！")
        print("=" * 60)
    except Exception as e:
        import traceback
        print(f"\n❌ 出错: {e}")
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    main()
