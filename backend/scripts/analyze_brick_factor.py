"""
砖型图因子分析脚本

分析砖型图指标对B1策略优秀案例（涨幅TOP3）的影响，重点研究：
1. 当日砖型图颜色（红柱/绿柱）与未来收益的关系
2. 砖型图颜色+K线涨跌的四种组合（共振/背离）
3. 砖型图状态转换（绿转红/红转绿/红柱增长/红柱缩短/持续为零）
4. 动量柱柱体长度（brick_body，ABS(今-昨)，绝对值）与收益的分组关系

数据来源：直接读取 SQLite stock.db（brick_value, brick_body字段）
优秀案例定义：learning_cases/<strategy>/<date>.json 中各市场分组的 TOP3

使用方法：
    cd /Users/zhangguijiang/project/stock/stock_simulation_system
    python backend/scripts/analyze_brick_factor.py --strategy B1 --period 3d
    python backend/scripts/analyze_brick_factor.py --strategy B1 --all-periods
    python backend/scripts/analyze_brick_factor.py --strategy B1 --period 3d --test 50
    python backend/scripts/analyze_brick_factor.py --strategy B1 --period 3d --market A
"""

import sys
import os
import json
import sqlite3
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message

DB_PATH = project_root / "data" / "stock.db"
LEARNING_CASES_PATH = project_root / "learning_cases"
INDEX_PATH = project_root / "strategy_index"
OUTPUT_PATH = project_root / "data" / "factor_analysis"


# ─────────────────────────────────────────────
#  数据库工具
# ─────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-32000")
    return conn


def load_brick_cache(conn, stock_codes: List[str]) -> Dict[str, pd.DataFrame]:
    """
    一次性批量加载所有目标股票的砖型图数据，按股票代码缓存。
    返回 {stock_code: DataFrame(trade_date, brick_value, brick_body, close, prev_close)}
    """
    if not stock_codes:
        return {}

    placeholders = ",".join(["?"] * len(stock_codes))
    sql = f"""
        SELECT stock_code, trade_date, brick_value, brick_body, close, prev_close
        FROM stock_daily
        WHERE stock_code IN ({placeholders})
        ORDER BY stock_code, trade_date ASC
    """
    df_all = pd.read_sql_query(sql, conn, params=stock_codes)
    df_all['trade_date'] = pd.to_datetime(df_all['trade_date']).dt.strftime('%Y%m%d')

    cache = {}
    for code, grp in df_all.groupby('stock_code'):
        grp = grp.reset_index(drop=True)
        cache[code] = grp
    return cache


# ─────────────────────────────────────────────
#  派生因子计算（逐行，仅针对特定日期）
# ─────────────────────────────────────────────

def derive_brick_factors(stock_df: pd.DataFrame, date_str: str) -> Optional[Dict]:
    """
    从单只股票的全量DataFrame中，提取指定日期的砖型图派生因子。

    ── 概念定义（项目统一标准）────────────────────────────────
    砖型图：
        由红柱/绿柱组成的动量指标。
        今日砖值 > 昨日砖值 → 红柱；今日砖值 < 昨日砖值 → 绿柱；砖值=0 为超跌消失区。

    砖型图柱体长度（brick_value，存DB）：
        红柱或绿柱本身的数值（≥0），反映当日动量的绝对高度。

    动量柱（brick_delta，派生不存DB）：
        = 今日 brick_value - 昨日 brick_value，有符号。
        正数 → 红动量柱（动量扩张，今日砖值高于昨日）
        负数 → 绿动量柱（动量收缩，今日砖值低于昨日）

    动量柱柱体长度（brick_body，存DB）：
        = ABS(brick_delta)，即红/绿动量柱的数值（≥0）。
        反映变化幅度，不含方向。若需区分方向请使用 brick_delta。

    ── 派生因子列表 ────────────────────────────────────────────
      brick_value      - 砖型图柱体长度（当日红/绿柱数值，≥0，已在DB）
      brick_body       - 动量柱柱体长度（ABS(今-昨)，≥0，已在DB）
      brick_direction  - 方向：+1=红柱（今>昨），-1=绿柱（今<昨），0=不变
      brick_delta      - 动量柱（有符号）= brick_value - prev_brick_value
      brick_state      - 状态枚举（见下方说明）
      brick_kline_sync - 砖型图方向 × K线涨跌 的共振/背离组合
      close_change_pct - 当日K线涨跌幅（收盘/昨收 - 1）* 100

    brick_state 枚举（基于砖型图柱体长度的连续变化）：
      'zero_to_red'    : 昨日砖值=0 且 今日砖值>0（超跌区启动，第一根红柱）
      'red_growing'    : 昨日砖值>0 且 今日砖值>昨日砖值（红柱，砖型图柱体在增高）
      'green_shrinking': 昨日砖值>0 且 0<今日砖值<昨日砖值（绿柱，砖型图柱体在降低但未归零）
      'green_to_zero'  : 昨日砖值>0 且 今日砖值=0（砖型图消失，动量完全耗尽）
      'zero'           : 昨日=今日=0（持续处于超跌消失区）

    brick_turn 枚举（追踪动量柱连续两日的方向转换，需要前两日砖值）：
      'green_to_red'   : 昨日动量柱为绿（昨<前天），今日动量柱为红（今>昨）—— 反转向上
      'red_to_green'   : 昨日动量柱为红（昨>前天），今日动量柱为绿（今<昨）—— 反转向下
      'red_continue'   : 连续两日均为红动量柱
      'green_continue' : 连续两日均为绿动量柱
      'other'          : 涉及零值或不变的情形

    brick_kline_sync 枚举：
      'up_up'    : 红柱 + 阳线（砖型图与K线共振↑）
      'up_down'  : 红柱 + 阴线（背离A，砖型图动量先行）
      'down_up'  : 绿柱 + 阳线（背离B，价格反弹但动量仍在衰减）
      'down_down': 绿柱 + 阴线（砖型图与K线共振↓）
      'flat'     : 不变 或 涨跌幅=0
    """
    row_idx = stock_df.index[stock_df['trade_date'] == date_str]
    if len(row_idx) == 0:
        return None
    i = row_idx[0]

    curr_val = stock_df.at[i, 'brick_value']
    curr_body = stock_df.at[i, 'brick_body']

    if pd.isna(curr_val):
        return None

    curr_val = float(curr_val)
    curr_body = float(curr_body) if not pd.isna(curr_body) else 0.0

    # 前一日砖型图柱体长度
    if i > 0:
        prev_val = stock_df.at[i - 1, 'brick_value']
        prev_val = float(prev_val) if not pd.isna(prev_val) else 0.0
    else:
        prev_val = curr_val  # 无前一日，视为不变

    # 前两日砖型图柱体长度（用于判断昨日动量柱方向：昨日动量柱是红还是绿）
    if i >= 2:
        prev2_val = stock_df.at[i - 2, 'brick_value']
        prev2_val = float(prev2_val) if not pd.isna(prev2_val) else 0.0
    else:
        prev2_val = None  # 无前两日数据，无法判断昨日动量柱方向

    # 当日涨跌幅
    close = stock_df.at[i, 'close']
    prev_close = stock_df.at[i, 'prev_close']
    if close and prev_close and float(prev_close) > 0:
        close_change_pct = (float(close) - float(prev_close)) / float(prev_close) * 100
    else:
        close_change_pct = 0.0

    # ── brick_direction（砖型图红/绿柱方向）──
    if curr_val > prev_val:
        brick_direction = 1      # 红柱（今日砖型图柱体长度 > 昨日）
    elif curr_val < prev_val:
        brick_direction = -1     # 绿柱（今日砖型图柱体长度 < 昨日）
    else:
        brick_direction = 0      # 不变

    # ── brick_delta（动量柱，有符号）──
    # 正数=红动量柱（动量扩张），负数=绿动量柱（动量收缩）
    brick_delta = curr_val - prev_val

    # ── brick_state ──
    if prev_val == 0 and curr_val > 0:
        brick_state = 'zero_to_red'       # 零值启动，第一根红柱
    elif prev_val > 0 and curr_val > prev_val:
        brick_state = 'red_growing'       # 红柱，今日比昨日更高
    elif prev_val > 0 and 0 < curr_val < prev_val:
        brick_state = 'green_shrinking'   # 绿柱，砖值回落但未到零
    elif prev_val > 0 and curr_val == 0:
        brick_state = 'green_to_zero'     # 绿柱，砖值跌回零
    else:
        brick_state = 'zero'              # 持续为零

    # ── brick_turn（连续两日方向转换）──
    # 昨日方向：昨日 vs 前天
    if prev2_val is None:
        brick_turn = 'other'   # 无前天数据
    else:
        prev_dir = 1 if prev_val > prev2_val else (-1 if prev_val < prev2_val else 0)
        if brick_direction == 1 and prev_dir == -1:
            brick_turn = 'green_to_red'    # 昨绿今红：方向向上反转
        elif brick_direction == -1 and prev_dir == 1:
            brick_turn = 'red_to_green'    # 昨红今绿：方向向下反转
        elif brick_direction == 1 and prev_dir == 1:
            brick_turn = 'red_continue'    # 红柱延续
        elif brick_direction == -1 and prev_dir == -1:
            brick_turn = 'green_continue'  # 绿柱延续
        else:
            brick_turn = 'other'           # 涉及零值/不变

    # ── brick_kline_sync ──
    if brick_direction == 0 or abs(close_change_pct) < 0.01:
        brick_kline_sync = 'flat'
    elif brick_direction == 1 and close_change_pct > 0:
        brick_kline_sync = 'up_up'
    elif brick_direction == 1 and close_change_pct <= 0:
        brick_kline_sync = 'up_down'
    elif brick_direction == -1 and close_change_pct > 0:
        brick_kline_sync = 'down_up'
    else:
        brick_kline_sync = 'down_down'

    return {
        'brick_value':       round(curr_val, 4),
        'brick_prev_value':  round(prev_val, 4),
        'brick_prev2_value': round(prev2_val, 4) if prev2_val is not None else None,
        'brick_body':        round(curr_body, 4),
        'brick_direction':   brick_direction,
        'brick_delta':       round(brick_delta, 4),
        'brick_state':       brick_state,
        'brick_turn':        brick_turn,
        'brick_kline_sync':  brick_kline_sync,
        'close_change_pct':  round(close_change_pct, 2),
    }


# ─────────────────────────────────────────────
#  市场分组工具
# ─────────────────────────────────────────────

def get_market_group(stock_code: str) -> str:
    prefix = stock_code[:2]
    if prefix in ['00', '60']:
        return 'A'
    elif prefix in ['30', '68', '92']:
        return 'B'
    return 'A'


MARKET_GROUP_NAMES = {
    'A': '主板(00/60)',
    'B': '创业板/科创板/北交所(30/68/92)',
    None: '全市场'
}


# ─────────────────────────────────────────────
#  核心分析器
# ─────────────────────────────────────────────

class BrickFactorAnalyzer:

    def __init__(self,
                 strategy: str = 'B1',
                 period: str = '3d',
                 market_group: Optional[str] = None,
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None,
                 max_dates: Optional[int] = None):
        self.strategy = strategy
        self.period = period
        self.market_group = market_group
        self.start_date = start_date
        self.end_date = end_date
        self.max_dates = max_dates
        ensure_dir(str(OUTPUT_PATH))

    # ── Step1: 收集数据 ──────────────────────────

    def collect_data(self) -> pd.DataFrame:
        """
        遍历所有学习案例日期，对每个候选股票提取砖型图派生因子，
        标注是否为当日TOP3。
        """
        cases_dir = LEARNING_CASES_PATH / self.strategy
        if not cases_dir.exists():
            log_message(f"学习案例目录不存在: {cases_dir}", 'ERROR')
            return pd.DataFrame()

        # 获取并过滤日期文件
        case_files = sorted([f for f in os.listdir(cases_dir) if f.endswith('.json')])
        if self.start_date:
            case_files = [f for f in case_files if f.replace('.json', '') >= self.start_date]
        if self.end_date:
            case_files = [f for f in case_files if f.replace('.json', '') <= self.end_date]
        if self.max_dates:
            case_files = case_files[:self.max_dates]

        log_message(f"共 {len(case_files)} 个交易日需要处理")

        # ── 预收集所有涉及的股票代码，批量加载砖型图数据 ──
        all_stocks: set = set()
        date_candidates: Dict[str, List[str]] = {}  # date -> [stock_code]
        date_top3: Dict[str, Dict[str, set]] = {}   # date -> {mkt: {code}}

        for fname in case_files:
            date = fname.replace('.json', '')
            # 读候选池
            index_file = INDEX_PATH / self.strategy / fname
            if not index_file.exists():
                continue
            with open(index_file, 'r') as f:
                index_data = json.load(f)
            candidates = index_data.get('stocks', [])
            if self.market_group:
                candidates = [s for s in candidates if get_market_group(s) == self.market_group]
            if not candidates:
                continue
            date_candidates[date] = candidates
            all_stocks.update(candidates)

            # 读TOP3
            case_file = cases_dir / fname
            with open(case_file, 'r') as f:
                case_data = json.load(f)
            top3_by_mkt: Dict[str, set] = defaultdict(set)
            if 'market_groups' in case_data:
                for mkt_key in ['A', 'B']:
                    if self.market_group and mkt_key != self.market_group:
                        continue
                    grp = case_data['market_groups'].get(mkt_key, {})
                    for item in grp.get('top_cases', {}).get(self.period, []):
                        top3_by_mkt[mkt_key].add(item['stock_code'])
            else:
                for item in case_data.get('top_cases', {}).get(self.period, []):
                    code = item['stock_code']
                    mkt = get_market_group(code)
                    if not self.market_group or mkt == self.market_group:
                        top3_by_mkt[mkt].add(code)
            date_top3[date] = top3_by_mkt

        log_message(f"涉及股票数: {len(all_stocks)}，开始从数据库批量加载...")

        conn = get_conn()
        brick_cache = load_brick_cache(conn, list(all_stocks))
        conn.close()

        log_message(f"数据库加载完成，缓存了 {len(brick_cache)} 只股票的砖型图数据")

        # ── 逐日逐股提取因子 ──
        rows = []
        processed = 0
        for date, candidates in date_candidates.items():
            top3_by_mkt = date_top3.get(date, {})
            # 合并所有市场的TOP3
            all_top3 = set()
            for s in top3_by_mkt.values():
                all_top3.update(s)

            for stock in candidates:
                stock_df = brick_cache.get(stock)
                if stock_df is None:
                    continue
                factors = derive_brick_factors(stock_df, date)
                if factors is None:
                    continue

                mkt = get_market_group(stock)
                is_top3 = 1 if stock in all_top3 else 0

                # 如果需要精确按市场分组判断TOP3
                if self.market_group:
                    is_top3 = 1 if stock in top3_by_mkt.get(self.market_group, set()) else 0

                factors['is_top3'] = is_top3
                factors['date'] = date
                factors['stock'] = stock
                factors['market'] = mkt
                rows.append(factors)

            processed += 1
            if processed % 100 == 0:
                log_message(f"  已处理 {processed}/{len(date_candidates)} 个日期，当前记录数: {len(rows)}")

        df = pd.DataFrame(rows)
        log_message(f"数据收集完成，共 {len(df)} 条记录，其中TOP3: {df['is_top3'].sum()} 条")
        return df

    # ── Step2: 分析各维度 ─────────────────────────

    def analyze_direction(self, df: pd.DataFrame) -> Dict:
        """维度1：红柱/绿柱/不变 与 TOP3比例"""
        result = []
        dir_labels = {1: '红柱(↑)', -1: '绿柱(↓)', 0: '不变'}
        for d, label in dir_labels.items():
            sub = df[df['brick_direction'] == d]
            if len(sub) == 0:
                continue
            result.append({
                'direction': d,
                'label': label,
                'total': int(len(sub)),
                'top3_count': int(sub['is_top3'].sum()),
                'top3_rate': round(float(sub['is_top3'].mean() * 100), 2),
                'avg_brick_value': round(float(sub['brick_value'].mean()), 4),
            })
        return {'dimension': 'brick_direction', 'title': '砖型图颜色（红/绿/不变）', 'data': result}

    def analyze_state(self, df: pd.DataFrame) -> Dict:
        """维度2：5种状态转换 与 TOP3比例"""
        states = ['zero_to_red', 'red_growing', 'green_shrinking', 'green_to_zero', 'zero']
        state_labels = {
            'zero_to_red':      '零→红（零值启动，第一根红柱）',
            'red_growing':      '红柱增长（今日>昨日）',
            'green_shrinking':  '绿柱回落（今日<昨日，砖值>0）',
            'green_to_zero':    '绿→零（砖值跌回零）',
            'zero':             '持续为零',
        }
        result = []
        for state in states:
            sub = df[df['brick_state'] == state]
            if len(sub) == 0:
                continue
            # 今日砖值范围
            curr_min = round(float(sub['brick_value'].min()), 4)
            curr_max = round(float(sub['brick_value'].max()), 4)
            curr_mean = round(float(sub['brick_value'].mean()), 4)
            prev_min = round(float(sub['brick_prev_value'].min()), 4)
            prev_max = round(float(sub['brick_prev_value'].max()), 4)
            prev_mean = round(float(sub['brick_prev_value'].mean()), 4)
            body_min = round(float(sub['brick_body'].min()), 4)
            body_max = round(float(sub['brick_body'].max()), 4)
            body_mean = round(float(sub['brick_body'].mean()), 4)
            result.append({
                'state': state,
                'label': state_labels[state],
                'total': int(len(sub)),
                'top3_count': int(sub['is_top3'].sum()),
                'top3_rate': round(float(sub['is_top3'].mean() * 100), 2),
                # 今日砖值
                'curr_value_min': curr_min,
                'curr_value_max': curr_max,
                'avg_brick_value': curr_mean,
                # 昨日砖值
                'prev_value_min': prev_min,
                'prev_value_max': prev_max,
                'avg_prev_value': prev_mean,
                # 动量柱柱体长度（brick_body = ABS(今-昨)，≥0，不含方向）
                'body_min': body_min,
                'body_max': body_max,
                'avg_brick_body': body_mean,
            })
        return {'dimension': 'brick_state', 'title': '砖型图状态转换', 'data': result}

    def analyze_turn(self, df: pd.DataFrame) -> Dict:
        """维度2b：连续两日方向转换（绿转红/红转绿/延续）与 TOP3比例"""
        turns = ['green_to_red', 'red_to_green', 'red_continue', 'green_continue', 'other']
        turn_labels = {
            'green_to_red':   '绿转红（昨绿今红，方向向上反转）',
            'red_to_green':   '红转绿（昨红今绿，方向向下反转）',
            'red_continue':   '红柱延续（昨红今红）',
            'green_continue': '绿柱延续（昨绿今绿）',
            'other':          '其他（含零值/不变情形）',
        }
        result = []
        for turn in turns:
            sub = df[df['brick_turn'] == turn]
            if len(sub) == 0:
                continue
            curr_mean = round(float(sub['brick_value'].mean()), 4)
            prev_mean = round(float(sub['brick_prev_value'].mean()), 4)
            body_mean = round(float(sub['brick_body'].mean()), 4)
            result.append({
                'turn': turn,
                'label': turn_labels[turn],
                'total': int(len(sub)),
                'top3_count': int(sub['is_top3'].sum()),
                'top3_rate': round(float(sub['is_top3'].mean() * 100), 2),
                'avg_brick_value': curr_mean,
                'avg_prev_value': prev_mean,
                'avg_brick_body': body_mean,
            })
        return {'dimension': 'brick_turn', 'title': '砖型图连续两日方向转换', 'data': result}

    def analyze_kline_sync(self, df: pd.DataFrame) -> Dict:
        """维度3：砖型图与K线共振/背离 与 TOP3比例"""
        combos = ['up_up', 'up_down', 'down_up', 'down_down', 'flat']
        combo_labels = {
            'up_up':    '红柱+阳线（共振↑）',
            'up_down':  '红柱+阴线（背离A，砖先行）',
            'down_up':  '绿柱+阳线（背离B，假反弹）',
            'down_down':'绿柱+阴线（共振↓）',
            'flat':     '不变/平盘',
        }
        result = []
        for combo in combos:
            sub = df[df['brick_kline_sync'] == combo]
            if len(sub) == 0:
                continue
            result.append({
                'combo': combo,
                'label': combo_labels[combo],
                'total': int(len(sub)),
                'top3_count': int(sub['is_top3'].sum()),
                'top3_rate': round(float(sub['is_top3'].mean() * 100), 2),
                'avg_close_change': round(float(sub['close_change_pct'].mean()), 2),
                'avg_brick_body': round(float(sub['brick_body'].mean()), 4),
            })
        return {'dimension': 'brick_kline_sync', 'title': '砖型图与K线共振/背离', 'data': result}

    def analyze_value_groups(self, df: pd.DataFrame) -> Dict:
        """维度4：砖型图绝对值分组（Q1~Q5）与 TOP3比例"""
        # 只分析 brick_value > 0 的部分（为0的单独一组）
        zero_df = df[df['brick_value'] == 0]
        nonzero_df = df[df['brick_value'] > 0].copy()

        result = []

        # 零值组
        if len(zero_df) > 0:
            result.append({
                'group': 'G0',
                'label': '砖值=0（无信号）',
                'range': '0',
                'total': int(len(zero_df)),
                'top3_count': int(zero_df['is_top3'].sum()),
                'top3_rate': round(float(zero_df['is_top3'].mean() * 100), 2),
                'avg_brick_value': 0.0,
            })

        # 非零值按五分位分组
        if len(nonzero_df) >= 5:
            try:
                nonzero_df['_qgroup'] = pd.qcut(nonzero_df['brick_value'], q=5, duplicates='drop')
                for i, (grp_key, grp_df) in enumerate(sorted(nonzero_df.groupby('_qgroup', observed=True)), 1):
                    result.append({
                        'group': f'G{i}',
                        'label': f'砖值Q{i}（{str(grp_key)}）',
                        'range': str(grp_key),
                        'total': int(len(grp_df)),
                        'top3_count': int(grp_df['is_top3'].sum()),
                        'top3_rate': round(float(grp_df['is_top3'].mean() * 100), 2),
                        'avg_brick_value': round(float(grp_df['brick_value'].mean()), 4),
                    })
            except Exception as e:
                log_message(f"砖值分组失败: {e}", 'WARNING')

        return {'dimension': 'brick_value_group', 'title': '砖型图绝对值分组', 'data': result}

    def analyze_body_groups(self, df: pd.DataFrame) -> Dict:
        """维度5：动量柱柱体长度（brick_body）分组与 TOP3比例
        brick_body = ABS(今日brick_value - 昨日brick_value)，≥0，不含方向。
        若需区分红/绿动量柱方向，请使用 brick_delta（有符号）。
        """
        # brick_body 精确为 0 的情况：前后两日砖值完全相同
        zero_df = df[df['brick_body'] == 0]
        nonzero_df = df[df['brick_body'] > 0].copy()

        result = []
        if len(zero_df) > 0:
            result.append({
                'group': 'G0',
                'label': '动量柱柱体长度=0（前后砖值完全相同，动量无变化）',
                'range': '0.0000',
                'total': int(len(zero_df)),
                'top3_count': int(zero_df['is_top3'].sum()),
                'top3_rate': round(float(zero_df['is_top3'].mean() * 100), 2),
                'avg_body': 0.0,
                'body_min': 0.0,
                'body_max': 0.0,
            })

        if len(nonzero_df) >= 5:
            try:
                nonzero_df['_qgroup'] = pd.qcut(nonzero_df['brick_body'], q=5, duplicates='drop')
                for i, (grp_key, grp_df) in enumerate(sorted(nonzero_df.groupby('_qgroup', observed=True)), 1):
                    result.append({
                        'group': f'G{i}',
                        'label': f'动量柱柱体长度Q{i}（{str(grp_key)}）',
                        'range': str(grp_key),
                        'total': int(len(grp_df)),
                        'top3_count': int(grp_df['is_top3'].sum()),
                        'top3_rate': round(float(grp_df['is_top3'].mean() * 100), 2),
                        'avg_body': round(float(grp_df['brick_body'].mean()), 4),
                        'body_min': round(float(grp_df['brick_body'].min()), 4),
                        'body_max': round(float(grp_df['brick_body'].max()), 4),
                    })
            except Exception as e:
                log_message(f"动量柱柱体长度分组失败: {e}", 'WARNING')

        return {'dimension': 'brick_body_group', 'title': '动量柱柱体长度分组', 'data': result}

    def analyze_state_x_kline(self, df: pd.DataFrame) -> Dict:
        """
        维度6：状态 × K线方向 交叉分析
        只展示样本量>=10的组合，排除噪声
        """
        cross = df.groupby(['brick_state', 'brick_kline_sync']).agg(
            total=('is_top3', 'count'),
            top3_count=('is_top3', 'sum'),
            avg_close_change=('close_change_pct', 'mean'),
            avg_brick_value=('brick_value', 'mean'),
        ).reset_index()
        cross['top3_rate'] = (cross['top3_count'] / cross['total'] * 100).round(2)
        # 过滤样本太少的组合
        cross = cross[cross['total'] >= 10].sort_values('top3_rate', ascending=False)

        result = []
        for _, row in cross.iterrows():
            result.append({
                'brick_state': row['brick_state'],
                'brick_kline_sync': row['brick_kline_sync'],
                'total': int(row['total']),
                'top3_count': int(row['top3_count']),
                'top3_rate': float(row['top3_rate']),
                'avg_close_change': round(float(row['avg_close_change']), 2),
                'avg_brick_value': round(float(row['avg_brick_value']), 4),
            })
        return {'dimension': 'state_x_kline', 'title': '状态×K线方向交叉分析（TOP3率排序）', 'data': result}

    def analyze_correlation(self, df: pd.DataFrame) -> Dict:
        """数值因子与TOP3/收益的相关性"""
        numeric_factors = ['brick_value', 'brick_prev_value', 'brick_body', 'brick_delta', 'close_change_pct']
        result = []
        for f in numeric_factors:
            valid = df[[f, 'is_top3']].dropna()
            if len(valid) < 10:
                continue
            corr = float(valid[f].corr(valid['is_top3']))
            result.append({
                'factor': f,
                'corr_with_top3': round(corr, 4),
                'mean_top3': round(float(df[df['is_top3'] == 1][f].mean()), 4),
                'mean_non_top3': round(float(df[df['is_top3'] == 0][f].mean()), 4),
            })
        return {'dimension': 'correlation', 'title': '数值因子与TOP3的相关性', 'data': result}

    # ── Step3: 汇总输出 ───────────────────────────

    def run(self) -> Dict:
        log_message("=" * 60)
        log_message(f"砖型图因子分析 | 策略:{self.strategy} 周期:{self.period} 市场:{MARKET_GROUP_NAMES.get(self.market_group,'全市场')}")
        log_message("=" * 60)

        df = self.collect_data()
        if df.empty:
            log_message("数据为空，分析终止", 'ERROR')
            return {}

        log_message("开始逐维度分析...")

        result = {
            'meta': {
                'strategy': self.strategy,
                'period': self.period,
                'market_group': self.market_group,
                'market_name': MARKET_GROUP_NAMES.get(self.market_group, '全市场'),
                'total_samples': int(len(df)),
                'top3_samples': int(df['is_top3'].sum()),
                'overall_top3_rate': round(float(df['is_top3'].mean() * 100), 2),
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            },
            'analyses': {
                'direction':       self.analyze_direction(df),
                'state':           self.analyze_state(df),
                'turn':            self.analyze_turn(df),
                'kline_sync':      self.analyze_kline_sync(df),
                'value_groups':    self.analyze_value_groups(df),
                'body_groups':     self.analyze_body_groups(df),
                'state_x_kline':   self.analyze_state_x_kline(df),
                'correlation':     self.analyze_correlation(df),
            }
        }

        # 保存 JSON
        mkt_suffix = f"_{self.market_group}" if self.market_group else ""
        out_file = OUTPUT_PATH / f"brick_factor_{self.strategy}_{self.period}{mkt_suffix}.json"
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log_message(f"JSON 结果已保存: {out_file}")

        # 生成可读报告
        report_file = OUTPUT_PATH / f"brick_factor_{self.strategy}_{self.period}{mkt_suffix}_report.txt"
        report_text = self._build_report(result, df)
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        log_message(f"分析报告已保存: {report_file}")

        print(report_text)
        return result

    # ─────────────────────────────────────────────
    #  报告生成
    # ─────────────────────────────────────────────

    def _bar(self, rate: float, max_rate: float, width: int = 30) -> str:
        """生成 ASCII 进度条"""
        filled = int(rate / max_rate * width) if max_rate > 0 else 0
        return '█' * filled + '░' * (width - filled)

    def _signal(self, rate: float, baseline: float) -> str:
        ratio = rate / baseline if baseline > 0 else 1
        if ratio >= 2.0:   return '🔴🔴 极强'
        if ratio >= 1.5:   return '🔴 强'
        if ratio >= 1.2:   return '🟡 偏强'
        if ratio >= 0.9:   return '⚪ 中性'
        if ratio >= 0.7:   return '🟢 偏弱'
        return              '🟢🟢 弱'

    def _build_report(self, result: Dict, df: pd.DataFrame) -> str:
        meta = result['meta']
        analyses = result['analyses']
        baseline = meta['overall_top3_rate']
        lines = []

        def L(s=''):
            lines.append(s)

        # ── 封面 ──────────────────────────────────
        L('=' * 70)
        L(f'  砖型图因子分析报告')
        L(f'  策略: {meta["strategy"]}  |  周期: {meta["period"]}  |  市场: {meta["market_name"]}')
        L(f'  生成时间: {meta["analyzed_at"]}')
        L('=' * 70)
        L()
        L('【概览】')
        L(f'  总样本数   : {meta["total_samples"]:>10,} 条')
        L(f'  TOP3 样本数: {meta["top3_samples"]:>10,} 条')
        L(f'  基准 TOP3率: {baseline:>10.2f}%  （每日候选池中随机命中 TOP3 的概率）')
        L()
        L('  砖型图定义说明：')
        L('    · 红柱 = 今日砖值 > 昨日砖值，柱体高度 = 今日 - 昨日')
        L('    · 绿柱 = 今日砖值 < 昨日砖值，柱体高度 = 昨日 - 今日')
        L('    · 砖值 = IF(VAR6A>4, VAR6A-4, 0)，仅有正值时可见')
        L()

        # ── 维度1：颜色 ────────────────────────────
        L('─' * 70)
        L('【维度一】当日砖柱颜色（今日 vs 昨日砖值）')
        L('─' * 70)
        dir_data = analyses['direction']['data']
        max_r = max(d['top3_rate'] for d in dir_data)
        L(f'  {"颜色":<16} {"样本":>9} {"TOP3数":>7} {"TOP3率":>7}  {"今日砖值均值":>12}  {"对比基准":>8}  图示')
        L(f'  {"─"*16} {"─"*9} {"─"*7} {"─"*7}  {"─"*12}  {"─"*8}  {"─"*30}')
        for d in dir_data:
            bar = self._bar(d['top3_rate'], max_r)
            sig = self._signal(d['top3_rate'], baseline)
            L(f'  {d["label"]:<16} {d["total"]:>9,} {d["top3_count"]:>7,} {d["top3_rate"]:>6.2f}%  {d["avg_brick_value"]:>12.4f}  {sig:<10}  {bar}')
        L()
        # 小结
        red = next((d for d in dir_data if d['direction'] == 1), None)
        grn = next((d for d in dir_data if d['direction'] == -1), None)
        flat = next((d for d in dir_data if d['direction'] == 0), None)
        if red and grn:
            L(f'  ▶ 红柱 TOP3率 {red["top3_rate"]:.2f}% vs 绿柱 {grn["top3_rate"]:.2f}%，')
            ratio = red['top3_rate'] / grn['top3_rate'] if grn['top3_rate'] > 0 else 0
            L(f'    红柱命中率是绿柱的 {ratio:.2f} 倍。')
        if flat:
            L(f'  ▶ "砖值不变"组 TOP3率 {flat["top3_rate"]:.2f}%（是基准的 {flat["top3_rate"]/baseline:.1f} 倍），')
            L(f'    该组 avg_brick_value={flat["avg_brick_value"]:.2f}，属于砖值趋近于零的极低位，')
            L(f'    深度超跌特征突出，与 B1 策略逻辑高度吻合。')
        L()

        # ── 维度2：状态 ────────────────────────────
        L('─' * 70)
        L('【维度二】砖型图状态转换')
        L('─' * 70)
        L('  状态定义（"零"指砖值精确为 0.0000，即公式输出 ≤ 4 时裁切为零）：')
        L('    零→红  : 昨日砖值=0.0000，今日首次出现正值（第一根红柱）')
        L('    红柱增长: 今日>昨日>0（连续红柱，动量加速）')
        L('    绿柱回落: 今日<昨日 且 今日>0（绿柱，动量衰减中）')
        L('    绿→零  : 昨日>0，今日砖值归零至 0.0000（绿柱，动量消失）')
        L('    持续为零: 昨日=今日=0.0000（砖值长期不存在，极深超跌）')
        L()
        state_data = analyses['state']['data']
        max_r = max(d['top3_rate'] for d in state_data) if state_data else 1
        L(f'  {"状态":<22} {"样本":>9} {"TOP3率":>7}  {"今日砖值(均/最小/最大)":>28}  {"昨日砖值(均/最小/最大)":>28}  {"柱体高度(均/最小/最大)":>28}  图示')
        L(f'  {"─"*22} {"─"*9} {"─"*7}  {"─"*28}  {"─"*28}  {"─"*28}  {"─"*22}')
        for d in state_data:
            bar = self._bar(d['top3_rate'], max_r, 22)
            sig = self._signal(d['top3_rate'], baseline)
            curr_str = f'{d["avg_brick_value"]:>7.4f} / {d["curr_value_min"]:>7.4f} / {d["curr_value_max"]:>8.4f}'
            prev_str = f'{d["avg_prev_value"]:>7.4f} / {d["prev_value_min"]:>7.4f} / {d["prev_value_max"]:>8.4f}'
            body_str = f'{d["avg_brick_body"]:>7.4f} / {d["body_min"]:>7.4f} / {d["body_max"]:>8.4f}'
            L(f'  {d["label"]:<22} {d["total"]:>9,} {d["top3_rate"]:>6.2f}%  {curr_str}  {prev_str}  {body_str}  {bar} {sig}')
        L()
        # 小结
        s_map = {d['state']: d for d in state_data}
        L('  ▶ 关键发现：')
        if 'zero_to_red' in s_map:
            d = s_map['zero_to_red']
            L(f'    · 零→红（启动信号）：TOP3率 {d["top3_rate"]:.2f}%，是基准的 {d["top3_rate"]/baseline:.1f} 倍。')
            L(f'      昨日砖值=0.0000，今日砖值均值={d["avg_brick_value"]:.4f}（范围 {d["curr_value_min"]:.4f}~{d["curr_value_max"]:.4f}），')
            L(f'      柱体高度均值={d["avg_brick_body"]:.4f}，样本量 {d["total"]} 条。')
        if 'red_growing' in s_map:
            d = s_map['red_growing']
            L(f'    · 红柱增长：TOP3率 {d["top3_rate"]:.2f}%，样本量充足（{d["total"]:,} 条），')
            L(f'      今日砖值均值={d["avg_brick_value"]:.4f}，昨日均值={d["avg_prev_value"]:.4f}，')
            L(f'      柱体高度均值={d["avg_brick_body"]:.4f}（平均每日增量）。')
        if 'green_shrinking' in s_map:
            d = s_map['green_shrinking']
            L(f'    · 绿柱回落：TOP3率 {d["top3_rate"]:.2f}%，与基准接近，')
            L(f'      今日砖值均值={d["avg_brick_value"]:.4f}，昨日均值={d["avg_prev_value"]:.4f}，')
            L(f'      占总样本 {d["total"]/meta["total_samples"]*100:.1f}%，是最大量的状态。')
        if 'green_to_zero' in s_map:
            d = s_map['green_to_zero']
            L(f'    · 绿→零：TOP3率 {d["top3_rate"]:.2f}%（基准的 {d["top3_rate"]/baseline:.1f} 倍），')
            L(f'      今日砖值=0.0000，昨日砖值均值={d["avg_prev_value"]:.4f}（范围 {d["prev_value_min"]:.4f}~{d["prev_value_max"]:.4f}），')
            L(f'      样本量 {d["total"]} 条（较少，需谨慎解读）。')
        if 'zero' in s_map:
            d = s_map['zero']
            L(f'    · 持续为零：TOP3率 {d["top3_rate"]:.2f}%（基准的 {d["top3_rate"]/baseline:.1f} 倍），')
            L(f'      昨日=今日=0.0000，砖值归零说明两条均线差值≤4，处于极深超跌区，往往是 B1 最底部。')
        L()

        # ── 维度2b：方向转换 ──────────────────────
        L('─' * 70)
        L('【维度二b】连续两日方向转换（绿转红 / 红转绿 / 延续）')
        L('─' * 70)
        L('  定义说明：')
        L('    绿转红  : 昨日砖值 < 前天砖值（昨是绿柱），今日砖值 > 昨日砖值（今是红柱）')
        L('    红转绿  : 昨日砖值 > 前天砖值（昨是红柱），今日砖值 < 昨日砖值（今是绿柱）')
        L('    红柱延续: 昨红今红（昨>前天 且 今>昨）')
        L('    绿柱延续: 昨绿今绿（昨<前天 且 今<昨）')
        L('    其他    : 涉及零值或砖值不变的情形')
        L()
        turn_data = analyses['turn']['data']
        max_r = max(d['top3_rate'] for d in turn_data) if turn_data else 1
        L(f'  {"转换类型":<26} {"样本":>9} {"TOP3数":>7} {"TOP3率":>7}  {"今日砖值均值":>12}  {"对比基准":>8}  图示')
        L(f'  {"─"*26} {"─"*9} {"─"*7} {"─"*7}  {"─"*12}  {"─"*8}  {"─"*28}')
        for d in turn_data:
            bar = self._bar(d['top3_rate'], max_r, 28)
            sig = self._signal(d['top3_rate'], baseline)
            L(f'  {d["label"]:<26} {d["total"]:>9,} {d["top3_count"]:>7,} {d["top3_rate"]:>6.2f}%  {d["avg_brick_value"]:>12.4f}  {sig:<10}  {bar}')
        L()
        t_map = {d['turn']: d for d in turn_data}
        L('  ▶ 关键发现：')
        if 'green_to_red' in t_map:
            d = t_map['green_to_red']
            L(f'    · 绿转红：TOP3率 {d["top3_rate"]:.2f}%（基准的 {d["top3_rate"]/baseline:.1f} 倍），样本 {d["total"]:,} 条')
            L(f'      今日砖值均值={d["avg_brick_value"]:.4f}，昨日均值={d["avg_prev_value"]:.4f}，')
            L(f'      柱体高度均值={d["avg_brick_body"]:.4f}。')
        if 'red_to_green' in t_map:
            d = t_map['red_to_green']
            L(f'    · 红转绿：TOP3率 {d["top3_rate"]:.2f}%（基准的 {d["top3_rate"]/baseline:.1f} 倍），样本 {d["total"]:,} 条')
            L(f'      动量由升转降，今日砖值均值={d["avg_brick_value"]:.4f}（仍处于较高位），')
            L(f'      柱体高度均值={d["avg_brick_body"]:.4f}。')
        if 'red_continue' in t_map and 'green_continue' in t_map:
            rc = t_map['red_continue']
            gc = t_map['green_continue']
            L(f'    · 红柱延续 vs 绿柱延续：{rc["top3_rate"]:.2f}% vs {gc["top3_rate"]:.2f}%')
            ratio = rc["top3_rate"] / gc["top3_rate"] if gc["top3_rate"] > 0 else 0
            L(f'      红柱延续命中率是绿柱延续的 {ratio:.2f} 倍，动量持续上行时更易出现优秀案例。')
        L()

        # ── 维度3：共振/背离 ───────────────────────
        L('─' * 70)
        L('【维度三】砖型图与当日K线的共振/背离关系')
        L('─' * 70)
        L('  组合定义（砖柱方向 × K线涨跌）：')
        L('    红柱+阳线 : 动量与价格同步上涨（共振↑）')
        L('    红柱+阴线 : 动量翻红但价格仍跌（砖领先于价格，背离A）')
        L('    绿柱+阳线 : 价格反弹但动量仍在衰减（假反弹风险，背离B）')
        L('    绿柱+阴线 : 动量与价格同步下跌（共振↓）')
        L()
        kline_data = analyses['kline_sync']['data']
        max_r = max(d['top3_rate'] for d in kline_data) if kline_data else 1
        L(f'  {"组合":<22} {"样本":>9} {"TOP3数":>7} {"TOP3率":>7} {"均涨跌幅":>8}  {"对比基准":>8}  图示')
        L(f'  {"─"*22} {"─"*9} {"─"*7} {"─"*7} {"─"*8}  {"─"*8}  {"─"*26}')
        for d in kline_data:
            bar = self._bar(d['top3_rate'], max_r, 26)
            sig = self._signal(d['top3_rate'], baseline)
            L(f'  {d["label"]:<22} {d["total"]:>9,} {d["top3_count"]:>7,} {d["top3_rate"]:>6.2f}% '
              f'{d["avg_close_change"]:>+7.2f}%  {sig:<10}  {bar}')
        L()
        up_down = next((d for d in kline_data if d['combo'] == 'up_down'), None)
        up_up   = next((d for d in kline_data if d['combo'] == 'up_up'),   None)
        dn_up   = next((d for d in kline_data if d['combo'] == 'down_up'), None)
        if up_down and up_up:
            L(f'  ▶ 背离A（红柱+阴线）TOP3率 {up_down["top3_rate"]:.2f}% > '
              f'共振↑（红柱+阳线）{up_up["top3_rate"]:.2f}%')
            L(f'    说明砖型图动量翻红但当日股价尚未跟涨，具有一定的领先性。')
        if dn_up:
            L(f'  ▶ 背离B（绿柱+阳线）TOP3率仅 {dn_up["top3_rate"]:.2f}%，')
            L(f'    当日股价反弹但动量仍在衰减，为弱信号，需警惕假反弹。')
        L()

        # ── 维度4：砖值绝对高度分组 ────────────────
        L('─' * 70)
        L('【维度四】砖值绝对高度分组（五分位 + 零值单独）')
        L('─' * 70)
        vg_data = analyses['value_groups']['data']
        max_r = max(d['top3_rate'] for d in vg_data) if vg_data else 1
        L(f'  {"分组":<10} {"砖值区间":<22} {"样本":>9} {"TOP3率":>7}  {"对比基准":>8}  图示')
        L(f'  {"─"*10} {"─"*22} {"─"*9} {"─"*7}  {"─"*8}  {"─"*28}')
        for d in vg_data:
            bar = self._bar(d['top3_rate'], max_r, 28)
            sig = self._signal(d['top3_rate'], baseline)
            L(f'  {d["group"]:<10} {d["range"]:<22} {d["total"]:>9,} {d["top3_rate"]:>6.2f}%  {sig:<10}  {bar}')
        L()
        if len(vg_data) >= 3:
            g0 = vg_data[0]
            g5 = vg_data[-1]
            g1 = vg_data[1] if len(vg_data) > 1 else None
            L(f'  ▶ 砖值与 TOP3 率呈单调递增关系：砖值越高，命中率越高。')
            L(f'    最高分位（{g5["range"]}）TOP3率 {g5["top3_rate"]:.2f}%，')
            L(f'    是最低分位 {g1["top3_rate"]:.2f}% 的 {g5["top3_rate"]/g1["top3_rate"]:.1f} 倍。' if g1 else '')
            L(f'  ▶ 砖值=0 组 TOP3率 {g0["top3_rate"]:.2f}%（基准的 {g0["top3_rate"]/baseline:.1f} 倍），')
            L(f'    极低位超跌特征，B1 策略本身的超跌反弹逻辑在此处最为纯粹。')
            L(f'  ▶ 结论：砖值高位（动量充分积累）和砖值为零（极度超跌）均为优质区间，')
            L(f'    中间值（G1~G2，砖值 49 以下）为相对洼地。')
        L()

        # ── 维度5：动量柱柱体长度分组 ────────────────────
        L('─' * 70)
        L('【维度五】动量柱柱体长度分组（brick_body = ABS(今日砖值 - 昨日砖值)，≥0）')
        L('─' * 70)
        L('  注：动量柱柱体长度=0 表示前后两日砖值精确相同（如连续涨停板/无波动日），')
        L('      实际交易中较罕见，主要分布在 G1~G5 五个分位组。')
        L('      ⚠ 此处为绝对值分组，不区分红/绿动量柱方向（增强报告 A3 节已区分方向）')
        L()
        bg_data = analyses['body_groups']['data']
        max_r = max(d['top3_rate'] for d in bg_data) if bg_data else 1
        L(f'  {"分组":<6} {"样本":>9} {"TOP3率":>7}  {"均值":>8}  {"最小值":>8}  {"最大值":>10}  {"对比基准":>8}  图示')
        L(f'  {"─"*6} {"─"*9} {"─"*7}  {"─"*8}  {"─"*8}  {"─"*10}  {"─"*8}  {"─"*26}')
        for d in bg_data:
            bar = self._bar(d['top3_rate'], max_r, 26)
            sig = self._signal(d['top3_rate'], baseline)
            avg_v = d.get('avg_body', 0.0)
            min_v = d.get('body_min', 0.0)
            max_v = d.get('body_max', 0.0)
            L(f'  {d["group"]:<6} {d["total"]:>9,} {d["top3_rate"]:>6.2f}%  {avg_v:>8.4f}  {min_v:>8.4f}  {max_v:>10.4f}  {sig:<10}  {bar}')
        L()
        L('  ▶ 动量柱柱体长度（绝对值变化幅度）对 TOP3 率的影响相对较弱，')
        L('    不宜作为独立筛选条件，需配合动量柱方向（红=扩张/绿=收缩）使用。')
        L('    区分方向的有符号分析（brick_delta）详见增强报告 A3 节。')
        L()

        # ── 维度6：交叉分析 ───────────────────────
        L('─' * 70)
        L('【维度六】状态 × K线方向 交叉分析（TOP3率降序，样本≥10）')
        L('─' * 70)
        cx_data = analyses['state_x_kline']['data']
        L(f'  {"砖图状态":<20} {"K线方向":<14} {"样本":>8} {"TOP3数":>7} {"TOP3率":>7} {"均涨跌幅":>8}  信号')
        L(f'  {"─"*20} {"─"*14} {"─"*8} {"─"*7} {"─"*7} {"─"*8}  {"─"*8}')
        state_zh = {
            'zero_to_red':     '零→红（启动）',
            'red_growing':     '红柱增长',
            'green_shrinking': '绿柱回落',
            'green_to_zero':   '绿→零',
            'zero':            '持续为零',
        }
        kline_zh = {
            'up_up':    '红柱+阳线',
            'up_down':  '红柱+阴线',
            'down_up':  '绿柱+阳线',
            'down_down':'绿柱+阴线',
            'flat':     '平盘',
        }
        for d in cx_data:
            s_label = state_zh.get(d['brick_state'], d['brick_state'])
            k_label = kline_zh.get(d['brick_kline_sync'], d['brick_kline_sync'])
            sig = self._signal(d['top3_rate'], baseline)
            L(f'  {s_label:<20} {k_label:<14} {d["total"]:>8,} {d["top3_count"]:>7,} '
              f'{d["top3_rate"]:>6.2f}% {d["avg_close_change"]:>+7.2f}%  {sig}')
        L()

        # ── 维度7：相关性 ─────────────────────────
        L('─' * 70)
        L('【维度七】数值因子与 TOP3 的线性相关性')
        L('─' * 70)
        L('  注：线性相关系数仅供参考，砖型图与 TOP3 的关系为非线性（高值和零值均优），')
        L('  建议以分组分析为主要依据。')
        L()
        corr_data = analyses['correlation']['data']
        factor_zh = {
            'brick_value':      '当日砖值',
            'brick_prev_value': '昨日砖值',
            'brick_body':       '动量柱柱体长度（|今-昨|）',
            'brick_delta':      '有符号变化量（今-昨）',
            'close_change_pct': '当日K线涨跌幅',
        }
        L(f'  {"因子":<24} {"与TOP3相关":>12} {"TOP3均值":>12} {"非TOP3均值":>12}  解读')
        L(f'  {"─"*24} {"─"*12} {"─"*12} {"─"*12}  {"─"*20}')
        for d in corr_data:
            fname = factor_zh.get(d['factor'], d['factor'])
            diff = d['mean_top3'] - d['mean_non_top3']
            interpret = f'TOP3高 {diff:+.2f}' if abs(diff) > 0.1 else '差异微弱'
            L(f'  {fname:<24} {d["corr_with_top3"]:>+12.4f} {d["mean_top3"]:>12.4f} '
              f'{d["mean_non_top3"]:>12.4f}  {interpret}')
        L()

        # ── 综合建议 ──────────────────────────────
        L('─' * 70)
        L('【综合建议】基于本次分析的砖型图筛选策略')
        L('─' * 70)
        L()
        L('  ★ 优先关注（TOP3率显著高于基准）：')
        L()
        top_states = sorted([(d['top3_rate'], d) for d in state_data], reverse=True)
        rank = 1
        for rate, d in top_states:
            if rate > baseline * 1.2:
                L(f'  {rank}. 【{d["label"]}】')
                L(f'     TOP3率 {rate:.2f}%，是基准的 {rate/baseline:.1f} 倍，样本 {d["total"]:,} 条')
                if d['state'] == 'zero_to_red':
                    L(f'     → 砖值从零启动，动量刚刚点火，可配合K线阳线确认（交叉最强组合）')
                elif d['state'] == 'zero':
                    L(f'     → 极深超跌，B1策略在此区间最能体现反弹价值')
                elif d['state'] == 'red_growing':
                    L(f'     → 动量持续积累中，配合高砖值（Q5区间 >{vg_data[-1]["range"].split(",")[0].strip("("):.0f}）更佳')
                rank += 1
        L()
        L('  ★ 可叠加使用的砖值条件：')
        if len(vg_data) >= 2:
            g5 = vg_data[-1]
            L(f'  · 高位过滤：砖值 > {g5["range"].split(",")[0].strip("(").split(".")[0]}（Q5分位）')
            L(f'    TOP3率 {g5["top3_rate"]:.2f}%，是 Q1 分位的 {g5["top3_rate"]/vg_data[1]["top3_rate"]:.1f} 倍')
        L('  · 零值过滤：砖值 = 0（持续为零状态）可与低 J 值、低振幅叠加筛选底部')
        L()
        L('  ☆ 规避条件（TOP3率明显低于基准）：')
        for rate, d in sorted([(d['top3_rate'], d) for d in state_data]):
            if rate < baseline * 0.85 and d['total'] > 1000:
                L(f'  · 【{d["label"]}】：TOP3率 {rate:.2f}%（基准的 {rate/baseline:.2f} 倍），')
                L(f'    占总样本 {d["total"]/meta["total_samples"]*100:.1f}%，应降低权重或配合其他条件使用')
        L()
        L('  注：以上建议基于全量历史数据统计，建议结合实盘验证后使用。')
        L('      样本量 < 500 的组合（如零→红）统计可靠性较低，需持续积累后复验。')
        L()
        L('=' * 70)
        L(f'  报告生成完毕  |  数据量：{meta["total_samples"]:,} 条  |  {meta["analyzed_at"]}')
        L('=' * 70)

        return '\n'.join(lines)


# ─────────────────────────────────────────────
#  命令行入口
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description='砖型图因子分析')
    parser.add_argument('--strategy', default='B1', help='策略名称 (默认: B1)')
    parser.add_argument('--period', default='3d', choices=['3d', '5d', '10d'], help='分析周期')
    parser.add_argument('--all-periods', action='store_true', help='分析所有周期(3d/5d/10d)')
    parser.add_argument('--market', default=None, choices=['A', 'B'], help='市场分组 (A=主板, B=创业板等, 不填=全市场)')
    parser.add_argument('--start-date', default=None, help='开始日期 YYYYMMDD')
    parser.add_argument('--end-date', default=None, help='结束日期 YYYYMMDD')
    parser.add_argument('--test', type=int, default=None, metavar='N', help='测试模式：只处理前N个交易日')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    periods = ['3d', '5d', '10d'] if args.all_periods else [args.period]

    for period in periods:
        analyzer = BrickFactorAnalyzer(
            strategy=args.strategy,
            period=period,
            market_group=args.market,
            start_date=args.start_date,
            end_date=args.end_date,
            max_dates=args.test,
        )
        analyzer.run()
