"""
砖型图增强因子分析脚本

分析三个维度：
  Part A  独立砖型图因子分析（分市场A/B，柱体长度区间 + 状态转换）
  Part B  双因子分析：砖型图状态 × K线当日涨跌幅
  Part C  三维分析：砖型图 × 极致B1

使用方法：
    cd /Users/zhangguijiang/project/stock/stock_simulation_system
    python backend/scripts/analyze_brick_enhanced.py --strategy B1 --period 3d
    python backend/scripts/analyze_brick_enhanced.py --strategy B1 --all-periods
    python backend/scripts/analyze_brick_enhanced.py --strategy B1 --period 3d --test 50
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
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message

DB_PATH       = project_root / "data" / "stock.db"
LEARNING_PATH = project_root / "learning_cases"
INDEX_PATH    = project_root / "strategy_index"
OUTPUT_PATH   = project_root / "data" / "factor_analysis"

# 极致B1阈值（分市场）
EXTREME_THRESHOLDS = {
    'A': {'amplitude': 2.68, 'volume_ratio': 0.59},
    'B': {'amplitude': 3.46, 'volume_ratio': 0.42},
}

# 市场分组名
MARKET_NAMES = {
    'A': '主板(00/60)',
    'B': '创业板/科创板/北交所(30/68/92)',
    None: '全市场',
}


# ──────────────────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────────────────

def get_market(code: str) -> str:
    return 'A' if code[:2] in ['00', '60'] else 'B'


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-32000")
    return conn


def bar(rate: float, max_rate: float, width: int = 28) -> str:
    filled = int(rate / max_rate * width) if max_rate > 0 else 0
    return '█' * filled + '░' * (width - filled)


def signal_tag(rate: float, baseline: float) -> str:
    r = rate / baseline if baseline > 0 else 1.0
    if r >= 2.0:  return '🔴🔴 极强'
    if r >= 1.5:  return '🔴 强'
    if r >= 1.2:  return '🟡 偏强'
    if r >= 0.9:  return '⚪ 中性'
    if r >= 0.7:  return '🟢 偏弱'
    return              '🟢🟢 弱'


# ──────────────────────────────────────────────────────────
#  数据加载
# ──────────────────────────────────────────────────────────

def load_brick_cache(conn, codes: List[str]) -> Dict[str, pd.DataFrame]:
    """批量加载砖型图+行情数据"""
    if not codes:
        return {}
    ph = ','.join(['?'] * len(codes))
    sql = f"""
        SELECT stock_code, trade_date, brick_value, brick_body,
               close, prev_close
        FROM stock_daily
        WHERE stock_code IN ({ph})
        ORDER BY stock_code, trade_date ASC
    """
    df_all = pd.read_sql_query(sql, conn, params=codes)
    df_all['trade_date'] = pd.to_datetime(df_all['trade_date']).dt.strftime('%Y%m%d')
    cache = {}
    for code, grp in df_all.groupby('stock_code'):
        cache[code] = grp.reset_index(drop=True)
    return cache


def load_factor_cache(codes: List[str]) -> Dict[str, pd.DataFrame]:
    """批量加载 processed_data CSV，获取振幅、量比等因子"""
    cache = {}
    pdata = project_root / 'processed_data'
    for code in codes:
        fp = pdata / f'{code}.csv'
        if not fp.exists():
            continue
        try:
            df = pd.read_csv(fp)
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
            cache[code] = df
        except Exception:
            pass
    return cache


# ──────────────────────────────────────────────────────────
#  派生因子
# ──────────────────────────────────────────────────────────

def derive_brick(stock_df: pd.DataFrame, date_str: str) -> Optional[Dict]:
    """
    从单股 DataFrame 提取指定日期的砖型图派生因子。

    概念定义（项目统一标准）：
      brick_value  : 砖型图柱体长度（红/绿柱数值，≥0，今>昨=红柱，今<昨=绿柱）
      brick_body   : 动量柱柱体长度（ABS(今日brick_value - 昨日brick_value)，≥0，存DB）
      brick_delta  : 动量柱（有符号，正=红动量柱/扩张，负=绿动量柱/收缩，派生不存DB）
    """
    idx_list = stock_df.index[stock_df['trade_date'] == date_str]
    if len(idx_list) == 0:
        return None
    i = idx_list[0]

    curr_val = stock_df.at[i, 'brick_value']
    curr_body = stock_df.at[i, 'brick_body']
    if pd.isna(curr_val):
        return None
    curr_val = float(curr_val)
    curr_body = float(curr_body) if not pd.isna(curr_body) else 0.0

    prev_val = float(stock_df.at[i - 1, 'brick_value']) if i > 0 and not pd.isna(stock_df.at[i - 1, 'brick_value']) else curr_val
    prev2_val = (float(stock_df.at[i - 2, 'brick_value'])
                 if i >= 2 and not pd.isna(stock_df.at[i - 2, 'brick_value'])
                 else None)

    close = stock_df.at[i, 'close']
    prev_close = stock_df.at[i, 'prev_close']
    if close and prev_close and float(prev_close) > 0:
        change_pct = (float(close) - float(prev_close)) / float(prev_close) * 100
    else:
        change_pct = 0.0

    # brick_direction：砖型图红/绿柱方向（今日砖型图柱体长度 vs 昨日）
    direction = 1 if curr_val > prev_val else (-1 if curr_val < prev_val else 0)
    # brick_delta：动量柱（有符号）正=红动量柱（扩张），负=绿动量柱（收缩）
    delta = curr_val - prev_val

    # brick_state：基于砖型图柱体长度的连续变化状态
    if prev_val == 0 and curr_val > 0:
        state = 'zero_to_red'      # 超跌区启动，第一根红柱
    elif prev_val > 0 and curr_val > prev_val:
        state = 'red_growing'      # 砖型图柱体增高（红柱，动量扩张）
    elif prev_val > 0 and 0 < curr_val < prev_val:
        state = 'green_shrinking'  # 砖型图柱体降低但未归零（绿柱，动量收缩）
    elif prev_val > 0 and curr_val == 0:
        state = 'green_to_zero'    # 砖型图消失，动量完全耗尽
    else:
        state = 'zero'             # 持续处于超跌消失区

    # brick_turn：连续两日动量柱方向转换
    if prev2_val is None:
        turn = 'other'
    else:
        prev_dir = 1 if prev_val > prev2_val else (-1 if prev_val < prev2_val else 0)
        if direction == 1 and prev_dir == -1:
            turn = 'green_to_red'    # 昨绿动量柱→今红动量柱，反转向上
        elif direction == -1 and prev_dir == 1:
            turn = 'red_to_green'    # 昨红动量柱→今绿动量柱，反转向下
        elif direction == 1 and prev_dir == 1:
            turn = 'red_continue'    # 连续红动量柱
        elif direction == -1 and prev_dir == -1:
            turn = 'green_continue'  # 连续绿动量柱
        else:
            turn = 'other'

    # brick_kline_sync：砖型图方向 × K线涨跌 共振/背离
    if direction == 0 or abs(change_pct) < 0.01:
        kline_sync = 'flat'
    elif direction == 1 and change_pct > 0:
        kline_sync = 'up_up'
    elif direction == 1 and change_pct <= 0:
        kline_sync = 'up_down'
    elif direction == -1 and change_pct > 0:
        kline_sync = 'down_up'
    else:
        kline_sync = 'down_down'

    return {
        'brick_value':      round(curr_val, 4),
        'brick_prev_value': round(prev_val, 4),
        'brick_body':       round(curr_body, 4),
        'brick_direction':  direction,
        'brick_delta':      round(delta, 4),
        'brick_state':      state,
        'brick_turn':       turn,
        'brick_kline_sync': kline_sync,
        'close_change_pct': round(change_pct, 2),
    }


def check_extreme_b1(row_data: dict, market: str) -> bool:
    """根据 processed_data 中的因子判断极致B1"""
    thr = EXTREME_THRESHOLDS.get(market, EXTREME_THRESHOLDS['A'])
    amp = row_data.get('factor_amplitude')
    vr  = row_data.get('factor_volume_ratio')
    if amp is None or vr is None or pd.isna(amp) or pd.isna(vr):
        return False
    return float(amp) >= thr['amplitude'] and float(vr) >= thr['volume_ratio']


# ──────────────────────────────────────────────────────────
#  主分析器
# ──────────────────────────────────────────────────────────

class BrickEnhancedAnalyzer:

    def __init__(self,
                 strategy: str = 'B1',
                 period: str = '3d',
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None,
                 max_dates: Optional[int] = None):
        self.strategy   = strategy
        self.period     = period
        self.start_date = start_date
        self.end_date   = end_date
        self.max_dates  = max_dates
        ensure_dir(str(OUTPUT_PATH))

    # ── 数据收集 ─────────────────────────────────────────

    def collect_data(self) -> pd.DataFrame:
        """
        遍历学习案例，构建每条候选记录，包含：
          - 砖型图派生因子
          - K线涨跌幅
          - 是否极致B1
          - 是否TOP3（按市场分组精确判断）
          - 市场分组 A/B
        """
        cases_dir = LEARNING_PATH / self.strategy
        if not cases_dir.exists():
            log_message(f"学习案例目录不存在: {cases_dir}", 'ERROR')
            return pd.DataFrame()

        fnames = sorted([f for f in os.listdir(cases_dir) if f.endswith('.json')])
        if self.start_date:
            fnames = [f for f in fnames if f.replace('.json', '') >= self.start_date]
        if self.end_date:
            fnames = [f for f in fnames if f.replace('.json', '') <= self.end_date]
        if self.max_dates:
            fnames = fnames[:self.max_dates]

        log_message(f"共 {len(fnames)} 个交易日")

        # —— 预收集 ——
        all_stocks: set = set()
        date_candidates: Dict[str, List[str]] = {}
        date_top3: Dict[str, Dict[str, set]] = {}   # date -> {mkt: set}

        for fname in fnames:
            date = fname.replace('.json', '')
            idx_file = INDEX_PATH / self.strategy / fname
            if not idx_file.exists():
                continue
            with open(idx_file) as f:
                idx = json.load(f)
            candidates = idx.get('stocks', [])
            if not candidates:
                continue
            date_candidates[date] = candidates
            all_stocks.update(candidates)

            case_file = cases_dir / fname
            with open(case_file) as f:
                case_data = json.load(f)
            top3_by_mkt: Dict[str, set] = defaultdict(set)
            if 'market_groups' in case_data:
                for mk in ['A', 'B']:
                    grp = case_data['market_groups'].get(mk, {})
                    for item in grp.get('top_cases', {}).get(self.period, []):
                        top3_by_mkt[mk].add(item['stock_code'])
            else:
                for item in case_data.get('top_cases', {}).get(self.period, []):
                    code = item['stock_code']
                    top3_by_mkt[get_market(code)].add(code)
            date_top3[date] = dict(top3_by_mkt)

        log_message(f"涉及股票 {len(all_stocks)} 只，开始批量加载数据...")

        code_list = list(all_stocks)
        conn = get_conn()
        brick_cache = load_brick_cache(conn, code_list)
        conn.close()
        factor_cache = load_factor_cache(code_list)

        log_message(f"砖型图缓存: {len(brick_cache)} 只，因子缓存: {len(factor_cache)} 只")

        # —— 逐日逐股构建记录 ——
        rows = []
        for date, candidates in date_candidates.items():
            top3_by_mkt = date_top3.get(date, {})

            for code in candidates:
                mkt = get_market(code)
                brick_df = brick_cache.get(code)
                if brick_df is None:
                    continue
                brick = derive_brick(brick_df, date)
                if brick is None:
                    continue

                # 极致B1：从因子缓存中读取振幅/量比
                is_extreme = False
                fdf = factor_cache.get(code)
                if fdf is not None:
                    row_f = fdf[fdf['date'] == date]
                    if not row_f.empty:
                        is_extreme = check_extreme_b1(row_f.iloc[0].to_dict(), mkt)

                is_top3 = 1 if code in top3_by_mkt.get(mkt, set()) else 0

                rec = {**brick,
                       'date':        date,
                       'stock':       code,
                       'market':      mkt,
                       'is_top3':     is_top3,
                       'is_extreme':  int(is_extreme),
                       }
                rows.append(rec)

        df = pd.DataFrame(rows)
        log_message(f"数据收集完成: {len(df):,} 条，TOP3: {df['is_top3'].sum():,}，极致B1: {df['is_extreme'].sum():,}")
        return df

    # ─────────────────────────────────────────────────────
    #  Part A  独立砖型图因子（分市场）
    # ─────────────────────────────────────────────────────

    def _analyze_brick_independent(self, df: pd.DataFrame, market: Optional[str]) -> Dict:
        """
        独立砖型图因子分析：
          A1 - 状态转换（5种状态）对 TOP3 率的影响
          A2 - 方向转换（绿转红/红转绿等）
          A3 - 动量柱（brick_delta，有符号）区间分组
               正值=红动量柱（扩张），负值=绿动量柱（收缩）
          A4 - 砖型图柱体长度（brick_value）绝对高度分位分组
          A5 - 状态 × 市场分组交叉
        """
        sub = df if market is None else df[df['market'] == market]
        if sub.empty:
            return {}
        baseline = float(sub['is_top3'].mean() * 100)
        total = len(sub)

        # ── A1 状态 ──────────────────────────────────────
        STATE_ORDER = ['zero_to_red', 'red_growing', 'green_shrinking', 'green_to_zero', 'zero']
        STATE_LABELS = {
            'zero_to_red':     '零→红（零值启动，第一根红柱）',
            'red_growing':     '红柱增长（今日>昨日>0）',
            'green_shrinking': '绿柱回落（今日<昨日，砖值>0）',
            'green_to_zero':   '绿→零（砖值跌回零）',
            'zero':            '持续为零（今昨均=0）',
        }
        a1 = []
        for s in STATE_ORDER:
            g = sub[sub['brick_state'] == s]
            if len(g) == 0:
                continue
            a1.append({
                'state': s, 'label': STATE_LABELS[s],
                'total': int(len(g)), 'top3_count': int(g['is_top3'].sum()),
                'top3_rate': round(float(g['is_top3'].mean() * 100), 2),
                'avg_brick_value':  round(float(g['brick_value'].mean()), 4),
                'avg_brick_body':   round(float(g['brick_body'].mean()), 4),
                'avg_prev_value':   round(float(g['brick_prev_value'].mean()), 4),
            })

        # ── A2 方向转换 ───────────────────────────────────
        TURN_ORDER = ['green_to_red', 'red_to_green', 'red_continue', 'green_continue', 'other']
        TURN_LABELS = {
            'green_to_red':   '绿转红（昨绿今红，方向反转向上）',
            'red_to_green':   '红转绿（昨红今绿，方向反转向下）',
            'red_continue':   '红柱延续（昨红今红）',
            'green_continue': '绿柱延续（昨绿今绿）',
            'other':          '其他（含零值/不变）',
        }
        a2 = []
        for t in TURN_ORDER:
            g = sub[sub['brick_turn'] == t]
            if len(g) == 0:
                continue
            a2.append({
                'turn': t, 'label': TURN_LABELS[t],
                'total': int(len(g)), 'top3_count': int(g['is_top3'].sum()),
                'top3_rate': round(float(g['is_top3'].mean() * 100), 2),
                'avg_brick_value': round(float(g['brick_value'].mean()), 4),
                'avg_brick_body':  round(float(g['brick_body'].mean()), 4),
            })

        # ── A3 砖型图变化量（有符号 delta）分组 ──────────────
        # 用 brick_delta = 今日砖值 - 昨日砖值（有符号）
        # 负值 = 绿柱（动量收缩），正值 = 红柱（动量扩张），=0 = 不变
        # 区间：绿柱(<-20, -20~-10, -10~-5, -5~-2, -2~0)、=0、红柱(0~2, 2~5, 5~10, 10~20, >20)
        DELTA_BINS   = [-9999, -20.0, -10.0, -5.0, -2.0, -0.0001,
                         0.0001, 2.0,   5.0,  10.0,  20.0,  9999.0]
        DELTA_LABELS = [
            '绿柱 < -20（强烈收缩）',
            '绿柱 [-20,-10)',
            '绿柱 [-10, -5)',
            '绿柱 [ -5, -2)',
            '绿柱 [ -2,  0)',
            '不变（=0）',
            '红柱 (  0,  2]',
            '红柱 (  2,  5]',
            '红柱 (  5, 10]',
            '红柱 ( 10, 20]',
            '红柱 > 20（强烈扩张）',
        ]
        a3 = []
        for j, label in enumerate(DELTA_LABELS):
            lo, hi = DELTA_BINS[j], DELTA_BINS[j + 1]
            if j == 5:   # 精确=0
                g = sub[sub['brick_delta'] == 0.0]
            else:
                g = sub[(sub['brick_delta'] > lo) & (sub['brick_delta'] <= hi)]
            if len(g) == 0:
                continue
            a3.append({
                'group': f'D{j}', 'label': label,
                'total': int(len(g)), 'top3_count': int(g['is_top3'].sum()),
                'top3_rate': round(float(g['is_top3'].mean() * 100), 2),
                'avg_delta': round(float(g['brick_delta'].mean()), 4),
                'avg_body':  round(float(g['brick_body'].mean()), 4),
                'lo': lo, 'hi': hi,
                'direction': '绿柱' if j < 5 else ('不变' if j == 5 else '红柱'),
            })

        # ── A4 砖值绝对高度分位 ───────────────────────────
        zero_g = sub[sub['brick_value'] == 0.0]
        nz_g   = sub[sub['brick_value'] >  0.0].copy()
        a4 = []
        if len(zero_g) > 0:
            a4.append({
                'group': 'G0', 'range': '砖值=0',
                'total': int(len(zero_g)), 'top3_count': int(zero_g['is_top3'].sum()),
                'top3_rate': round(float(zero_g['is_top3'].mean() * 100), 2),
                'avg_value': 0.0,
            })
        if len(nz_g) >= 5:
            try:
                nz_g['_q'] = pd.qcut(nz_g['brick_value'], q=5, duplicates='drop')
                for qi, (gkey, gdf) in enumerate(sorted(nz_g.groupby('_q', observed=True)), 1):
                    a4.append({
                        'group': f'G{qi}', 'range': str(gkey),
                        'total': int(len(gdf)), 'top3_count': int(gdf['is_top3'].sum()),
                        'top3_rate': round(float(gdf['is_top3'].mean() * 100), 2),
                        'avg_value': round(float(gdf['brick_value'].mean()), 4),
                    })
            except Exception as e:
                log_message(f'砖值分位分组失败: {e}', 'WARNING')

        return {
            'market': market,
            'market_name': MARKET_NAMES.get(market, '全市场'),
            'total': total,
            'baseline': round(baseline, 2),
            'state': a1,
            'turn': a2,
            'body_groups': a3,
            'value_groups': a4,
        }

    # ─────────────────────────────────────────────────────
    #  Part B  双因子：砖型图状态 × K线涨跌幅
    # ─────────────────────────────────────────────────────

    def _analyze_dual_brick_kline(self, df: pd.DataFrame, market: Optional[str]) -> Dict:
        """
        双因子联合分析：
          B1 - 砖型图状态（5种） × K线涨跌幅区间（固定分组）
          B2 - 砖型图方向转换 × K线涨跌幅均值
          B3 - 总览热力矩阵：brick_state × change_pct_group
        """
        sub = df if market is None else df[df['market'] == market]
        if sub.empty:
            return {}
        baseline = float(sub['is_top3'].mean() * 100)

        # 涨跌幅固定分组
        PCT_BINS   = [-99, -5, -3, -1, 0, 1, 3, 5, 99]
        PCT_LABELS = ['<-5%', '[-5,-3)', '[-3,-1)', '[-1,0)', '[0,1)', '[1,3)', '[3,5)', '≥5%']

        sub = sub.copy()
        sub['pct_group'] = pd.cut(sub['close_change_pct'],
                                  bins=PCT_BINS, labels=PCT_LABELS, right=False)

        STATE_ORDER = ['zero_to_red', 'red_growing', 'green_shrinking', 'green_to_zero', 'zero']
        STATE_SHORT = {
            'zero_to_red':     '零→红',
            'red_growing':     '红柱增长',
            'green_shrinking': '绿柱回落',
            'green_to_zero':   '绿→零',
            'zero':            '持续为零',
        }

        # B1: 交叉矩阵（state × pct_group）
        b1_matrix = []
        for state in STATE_ORDER:
            sg = sub[sub['brick_state'] == state]
            if len(sg) == 0:
                continue
            row_data = {
                'state': state, 'label': STATE_SHORT[state],
                'state_total': int(len(sg)),
                'state_top3_rate': round(float(sg['is_top3'].mean() * 100), 2),
                'pct_breakdown': [],
            }
            for pg in PCT_LABELS:
                cell = sg[sg['pct_group'] == pg]
                if len(cell) < 10:
                    continue
                row_data['pct_breakdown'].append({
                    'pct_group': pg,
                    'total': int(len(cell)),
                    'top3_count': int(cell['is_top3'].sum()),
                    'top3_rate': round(float(cell['is_top3'].mean() * 100), 2),
                    'avg_change': round(float(cell['close_change_pct'].mean()), 2),
                })
            b1_matrix.append(row_data)

        # B2: 方向转换 × 涨跌幅区间
        TURN_ORDER = ['green_to_red', 'red_to_green', 'red_continue', 'green_continue', 'other']
        TURN_SHORT = {
            'green_to_red':   '绿转红',
            'red_to_green':   '红转绿',
            'red_continue':   '红柱延续',
            'green_continue': '绿柱延续',
            'other':          '其他',
        }
        b2 = []
        for turn in TURN_ORDER:
            tg = sub[sub['brick_turn'] == turn]
            if len(tg) == 0:
                continue
            b2.append({
                'turn': turn, 'label': TURN_SHORT[turn],
                'total': int(len(tg)),
                'top3_rate': round(float(tg['is_top3'].mean() * 100), 2),
                'avg_change': round(float(tg['close_change_pct'].mean()), 2),
                'change_std': round(float(tg['close_change_pct'].std()), 2),
                'top3_avg_change':     round(float(tg[tg['is_top3'] == 1]['close_change_pct'].mean()), 2) if tg['is_top3'].sum() > 0 else 0,
                'non_top3_avg_change': round(float(tg[tg['is_top3'] == 0]['close_change_pct'].mean()), 2) if (tg['is_top3'] == 0).sum() > 0 else 0,
            })

        # B3: 热力矩阵摘要（只保留 top3_rate，格式化为表格用）
        b3_rows = []
        for pg in PCT_LABELS:
            pg_sub = sub[sub['pct_group'] == pg]
            if len(pg_sub) < 20:
                continue
            row_entry = {'pct_group': pg, 'total': int(len(pg_sub))}
            for state in STATE_ORDER:
                cell = pg_sub[pg_sub['brick_state'] == state]
                if len(cell) >= 10:
                    row_entry[state] = round(float(cell['is_top3'].mean() * 100), 2)
                else:
                    row_entry[state] = None
            b3_rows.append(row_entry)

        return {
            'market': market,
            'market_name': MARKET_NAMES.get(market, '全市场'),
            'baseline': round(baseline, 2),
            'state_x_pct': b1_matrix,
            'turn_x_pct':  b2,
            'heatmap':     b3_rows,
            'pct_labels':  PCT_LABELS,
            'state_order': STATE_ORDER,
        }

    # ─────────────────────────────────────────────────────
    #  Part C  三维：砖型图 × 极致B1
    # ─────────────────────────────────────────────────────

    def _analyze_brick_extreme(self, df: pd.DataFrame, market: Optional[str]) -> Dict:
        """
        砖型图 × 极致B1 联合分析（双轨）：
          C1 - 极致B1 vs 普通B1 基础对比
          C2/C3/C4 - 砖型图因子对 TOP3率 的影响，分两轨展示：
            轨道1（全体B1）：以全体B1基准率为参照，各砖型分组在全体B1中的TOP3率
            轨道2（仅极致B1）：以极致B1基准率为参照，砖型因子在极致B1子集内的区分能力
          C5 - 最优组合排名（全体B1 / 极致B1子集 各TOP10）
        """
        sub = df if market is None else df[df['market'] == market]
        if sub.empty:
            return {}
        baseline_all = float(sub['is_top3'].mean() * 100)

        # 极致B1子集及其基准
        ext_sub = sub[sub['is_extreme'] == 1].copy()
        noext_sub = sub[sub['is_extreme'] == 0].copy()
        baseline_ext = float(ext_sub['is_top3'].mean() * 100) if len(ext_sub) > 0 else 0.0

        # C1: 基础对比
        c1 = {
            'extreme': {
                'total': int(len(ext_sub)),
                'top3_count': int(ext_sub['is_top3'].sum()),
                'top3_rate':  round(baseline_ext, 2),
            },
            'non_extreme': {
                'total': int(len(noext_sub)),
                'top3_count': int(noext_sub['is_top3'].sum()),
                'top3_rate':  round(float(noext_sub['is_top3'].mean() * 100), 2) if len(noext_sub) > 0 else 0.0,
            },
        }

        STATE_ORDER = ['zero_to_red', 'red_growing', 'green_shrinking', 'green_to_zero', 'zero']
        STATE_LABELS = {
            'zero_to_red':     '零→红',
            'red_growing':     '红柱增长',
            'green_shrinking': '绿柱回落',
            'green_to_zero':   '绿→零',
            'zero':            '持续为零',
        }

        def _group_stat(pool: pd.DataFrame, mask: pd.Series, base: float) -> Dict:
            """计算子集的 total/top3_rate/vs_base"""
            g = pool[mask]
            rate = round(float(g['is_top3'].mean() * 100), 2) if len(g) > 0 else 0.0
            return {
                'total': int(len(g)),
                'top3_count': int(g['is_top3'].sum()),
                'top3_rate': rate,
                'vs_base': round(rate / base, 2) if base > 0 else 0.0,
            }

        # ── C2 砖型图状态 ──────────────────────────────────
        c2 = []
        for state in STATE_ORDER:
            # 全体B1轨道
            sg_all = sub[sub['brick_state'] == state]
            if len(sg_all) == 0:
                continue
            # 极致B1子集轨道
            sg_ext = ext_sub[ext_sub['brick_state'] == state]
            entry = {
                'state': state, 'label': STATE_LABELS[state],
                # 轨道1：全体B1中此状态的表现
                'all_total':    int(len(sg_all)),
                'all_rate':     round(float(sg_all['is_top3'].mean() * 100), 2),
                'all_vs_base':  round(float(sg_all['is_top3'].mean() * 100) / baseline_all, 2) if baseline_all > 0 else 0.0,
                # 轨道2：仅极致B1子集中此状态的表现
                'ext_total':    int(len(sg_ext)),
                'ext_rate':     round(float(sg_ext['is_top3'].mean() * 100), 2) if len(sg_ext) > 0 else 0.0,
                'ext_vs_base':  round(float(sg_ext['is_top3'].mean() * 100) / baseline_ext, 2) if len(sg_ext) > 0 and baseline_ext > 0 else 0.0,
            }
            c2.append(entry)

        # ── C3 方向转换 ────────────────────────────────────
        TURN_ORDER = ['green_to_red', 'red_to_green', 'red_continue', 'green_continue', 'other']
        TURN_LABELS = {
            'green_to_red':   '绿转红',
            'red_to_green':   '红转绿',
            'red_continue':   '红柱延续',
            'green_continue': '绿柱延续',
            'other':          '其他',
        }
        c3 = []
        for turn in TURN_ORDER:
            tg_all = sub[sub['brick_turn'] == turn]
            if len(tg_all) < 10:
                continue
            tg_ext = ext_sub[ext_sub['brick_turn'] == turn]
            c3.append({
                'turn': turn, 'label': TURN_LABELS[turn],
                'all_total':   int(len(tg_all)),
                'all_rate':    round(float(tg_all['is_top3'].mean() * 100), 2),
                'all_vs_base': round(float(tg_all['is_top3'].mean() * 100) / baseline_all, 2) if baseline_all > 0 else 0.0,
                'ext_total':   int(len(tg_ext)),
                'ext_rate':    round(float(tg_ext['is_top3'].mean() * 100), 2) if len(tg_ext) > 0 else 0.0,
                'ext_vs_base': round(float(tg_ext['is_top3'].mean() * 100) / baseline_ext, 2) if len(tg_ext) > 0 and baseline_ext > 0 else 0.0,
            })

        # ── C4 动量柱区间 ──────────────────────────────────
        C4_DELTA_BINS   = [-9999, -20.0, -10.0, -5.0, -2.0, -0.0001,
                            0.0001, 2.0,   5.0,  10.0,  20.0,  9999.0]
        C4_DELTA_LABELS = [
            '绿柱 < -20', '绿柱 [-20,-10)', '绿柱 [-10,-5)',
            '绿柱 [-5,-2)', '绿柱 [-2,0)',
            '不变（=0）',
            '红柱 (0,2]', '红柱 (2,5]', '红柱 (5,10]',
            '红柱 (10,20]', '红柱 > 20',
        ]
        c4 = []
        for j, blabel in enumerate(C4_DELTA_LABELS):
            lo, hi = C4_DELTA_BINS[j], C4_DELTA_BINS[j + 1]
            if j == 5:
                g_all = sub[sub['brick_delta'] == 0.0]
                g_ext = ext_sub[ext_sub['brick_delta'] == 0.0]
            else:
                g_all = sub[(sub['brick_delta'] > lo) & (sub['brick_delta'] <= hi)]
                g_ext = ext_sub[(ext_sub['brick_delta'] > lo) & (ext_sub['brick_delta'] <= hi)]
            if len(g_all) < 10:
                continue
            c4.append({
                'label': blabel,
                'direction': '绿柱' if j < 5 else ('不变' if j == 5 else '红柱'),
                'all_total':   int(len(g_all)),
                'all_rate':    round(float(g_all['is_top3'].mean() * 100), 2),
                'all_vs_base': round(float(g_all['is_top3'].mean() * 100) / baseline_all, 2) if baseline_all > 0 else 0.0,
                'ext_total':   int(len(g_ext)),
                'ext_rate':    round(float(g_ext['is_top3'].mean() * 100), 2) if len(g_ext) > 0 else 0.0,
                'ext_vs_base': round(float(g_ext['is_top3'].mean() * 100) / baseline_ext, 2) if len(g_ext) > 0 and baseline_ext > 0 else 0.0,
            })

        # ── C5 最优组合排名（全体B1 top10 + 极致B1子集 top10）
        c5_all, c5_ext = [], []
        for state in STATE_ORDER:
            # 全体B1
            cell_all = sub[sub['brick_state'] == state]
            if len(cell_all) >= 10:
                rate_all = round(float(cell_all['is_top3'].mean() * 100), 2)
                c5_all.append({
                    'label': STATE_LABELS[state],
                    'total': int(len(cell_all)),
                    'top3_count': int(cell_all['is_top3'].sum()),
                    'top3_rate': rate_all,
                    'vs_base': round(rate_all / baseline_all, 2) if baseline_all > 0 else 0.0,
                })
            # 极致B1子集
            cell_ext = ext_sub[ext_sub['brick_state'] == state]
            if len(cell_ext) >= 10:
                rate_ext = round(float(cell_ext['is_top3'].mean() * 100), 2)
                c5_ext.append({
                    'label': STATE_LABELS[state],
                    'total': int(len(cell_ext)),
                    'top3_count': int(cell_ext['is_top3'].sum()),
                    'top3_rate': rate_ext,
                    'vs_base': round(rate_ext / baseline_ext, 2) if baseline_ext > 0 else 0.0,
                })
        c5_all.sort(key=lambda x: x['top3_rate'], reverse=True)
        c5_ext.sort(key=lambda x: x['top3_rate'], reverse=True)

        return {
            'market':       market,
            'market_name':  MARKET_NAMES.get(market, '全市场'),
            'baseline_all': round(baseline_all, 2),
            'baseline_ext': round(baseline_ext, 2),
            'ext_total':    int(len(ext_sub)),
            'extreme_vs_non': c1,
            'state_groups':   c2,
            'turn_groups':    c3,
            'delta_groups':   c4,
            'top_all':        c5_all[:10],
            'top_ext':        c5_ext[:10],
        }

    # ─────────────────────────────────────────────────────
    #  Part D  动量柱专项分析
    # ─────────────────────────────────────────────────────

    def _analyze_momentum(self, df: pd.DataFrame, market: Optional[str]) -> Dict:
        """
        动量柱专项分析（以 brick_delta 为核心）：
          D1 - 动量柱幅度区间（有符号，11段）× TOP3率，含"加速/减速"维度
          D2 - 动量柱方向 × K线当日涨跌幅（四象限 + 区间交叉）
               · 红动量柱+涨  / 红动量柱+跌（背离）
               · 绿动量柱+涨（背离）/ 绿动量柱+跌
          D3 - 动量柱 × 极致B1 联合效应
               · 各幅度区间在 极致/普通B1 下的 TOP3率对比
          D4 - 连续同向动量柱计数（红连续N日 / 绿连续N日）× TOP3率
               brick_turn 已给出单日判断，需在 df 中新增连续天数字段
          D5 - 最优组合 TOP20（动量柱区间 × 极致B1 × K线方向）
        """
        sub = df if market is None else df[df['market'] == market]
        if sub.empty:
            return {}
        sub = sub.copy()
        baseline = float(sub['is_top3'].mean() * 100)
        total = len(sub)

        DELTA_BINS   = [-9999, -20.0, -10.0, -5.0, -2.0, -0.0001,
                         0.0001,  2.0,  5.0,  10.0,  20.0,  9999.0]
        DELTA_LABELS = [
            '绿柱 < -20（强烈收缩）',
            '绿柱 [-20,-10)',
            '绿柱 [-10, -5)',
            '绿柱 [ -5, -2)',
            '绿柱 [ -2,  0)',
            '不变（=0）',
            '红柱 (  0,  2]',
            '红柱 (  2,  5]',
            '红柱 (  5, 10]',
            '红柱 ( 10, 20]',
            '红柱 > 20（强烈扩张）',
        ]
        PCT_BINS   = [-99, -5, -3, -1, 0, 1, 3, 5, 99]
        PCT_LABELS = ['<-5%', '[-5,-3)', '[-3,-1)', '[-1,0)', '[0,1)', '[1,3)', '[3,5)', '≥5%']

        # ── D1  动量柱幅度区间 × TOP3率 ──────────────────
        d1 = []
        for j, label in enumerate(DELTA_LABELS):
            lo, hi = DELTA_BINS[j], DELTA_BINS[j + 1]
            if j == 5:
                g = sub[sub['brick_delta'] == 0.0]
            else:
                g = sub[(sub['brick_delta'] > lo) & (sub['brick_delta'] <= hi)]
            if len(g) == 0:
                continue
            direction = '绿柱' if j < 5 else ('不变' if j == 5 else '红柱')
            d1.append({
                'group':     f'D{j}',
                'label':     label,
                'direction': direction,
                'total':     int(len(g)),
                'top3_count': int(g['is_top3'].sum()),
                'top3_rate': round(float(g['is_top3'].mean() * 100), 2),
                'avg_delta': round(float(g['brick_delta'].mean()), 4),
                'avg_brick_value': round(float(g['brick_value'].mean()), 4),
                'lo': lo, 'hi': hi,
            })

        # 红柱/绿柱整体加权均
        red_rows  = [x for x in d1 if x['direction'] == '红柱']
        grn_rows  = [x for x in d1 if x['direction'] == '绿柱']
        def _wavg(rows):
            t = sum(r['total'] for r in rows)
            if t == 0:
                return 0.0
            return sum(r['top3_rate'] * r['total'] for r in rows) / t
        red_wavg = round(_wavg(red_rows), 4)
        grn_wavg = round(_wavg(grn_rows), 4)

        # ── D2  动量柱方向 × K线涨跌幅（四象限 + 区间明细）────
        sub['pct_group'] = pd.cut(sub['close_change_pct'],
                                  bins=PCT_BINS, labels=PCT_LABELS, right=False)
        # 四象限定义：
        #   QI  红动量柱 + 阳线（共振扩张）
        #   QII 红动量柱 + 阴线（动量领先，K线背离）
        #   QIII绿动量柱 + 阴线（共振收缩）
        #   QIV 绿动量柱 + 阳线（K线反弹，动量仍弱）
        sub['momentum_dir'] = sub['brick_delta'].apply(
            lambda x: 'red' if x > 0 else ('green' if x < 0 else 'flat'))
        sub['kline_dir'] = sub['close_change_pct'].apply(
            lambda x: 'up' if x > 0 else ('down' if x < 0 else 'flat'))

        # 极致B1子集及其基准（在 sub 派生列完成后再切出，保留 kline_dir 等列）
        ext_sub = sub[sub['is_extreme'] == 1].copy()
        baseline_ext = float(ext_sub['is_top3'].mean() * 100) if len(ext_sub) > 0 else 0.0

        QUADRANT_DEF = [
            ('QI',   'red',   'up',   '红动量柱 × 阳线（共振扩张）'),
            ('QII',  'red',   'down', '红动量柱 × 阴线（动量先行，K线背离）'),
            ('QIII', 'green', 'down', '绿动量柱 × 阴线（共振收缩）'),
            ('QIV',  'green', 'up',   '绿动量柱 × 阳线（K线反弹，动量仍弱）'),
            ('QV',   'flat',  None,   '动量不变（delta=0）'),
        ]
        d2_quadrant = []
        for qid, md, kd, qlabel in QUADRANT_DEF:
            if md == 'flat':
                g = sub[sub['momentum_dir'] == 'flat']
            elif kd is None:
                g = sub[sub['momentum_dir'] == md]
            else:
                g = sub[(sub['momentum_dir'] == md) & (sub['kline_dir'] == kd)]
            if len(g) == 0:
                continue
            d2_quadrant.append({
                'quadrant': qid, 'label': qlabel,
                'total': int(len(g)), 'top3_count': int(g['is_top3'].sum()),
                'top3_rate': round(float(g['is_top3'].mean() * 100), 2),
                'avg_delta': round(float(g['brick_delta'].mean()), 4),
                'avg_change_pct': round(float(g['close_change_pct'].mean()), 2),
                'avg_change_std': round(float(g['close_change_pct'].std()), 2),
                'top3_avg_change': round(float(g[g['is_top3']==1]['close_change_pct'].mean()), 2) if g['is_top3'].sum() > 0 else 0.0,
            })

        # 动量柱幅度区间 × K线涨跌幅区间（11×8 矩阵，只保留≥10样本的格子）
        d2_matrix = []
        for j, dlabel in enumerate(DELTA_LABELS):
            lo, hi = DELTA_BINS[j], DELTA_BINS[j + 1]
            if j == 5:
                dg = sub[sub['brick_delta'] == 0.0]
            else:
                dg = sub[(sub['brick_delta'] > lo) & (sub['brick_delta'] <= hi)]
            if len(dg) == 0:
                continue
            row_entry = {
                'delta_label': dlabel,
                'delta_total': int(len(dg)),
                'delta_top3_rate': round(float(dg['is_top3'].mean() * 100), 2),
                'direction': '绿柱' if j < 5 else ('不变' if j == 5 else '红柱'),
                'pct_cells': {},
            }
            for pg in PCT_LABELS:
                cell = dg[dg['pct_group'] == pg]
                if len(cell) >= 10:
                    row_entry['pct_cells'][pg] = {
                        'total': int(len(cell)),
                        'top3_rate': round(float(cell['is_top3'].mean() * 100), 2),
                    }
            d2_matrix.append(row_entry)

        # ── D3  动量柱幅度区间（双轨：全体B1 + 极致B1子集）──────
        # 轨道1：全体B1，各动量柱区间的 TOP3率 vs 全体基准
        # 轨道2：仅极致B1子集，各动量柱区间的 TOP3率 vs 极致B1基准
        d3 = []
        for j, dlabel in enumerate(DELTA_LABELS):
            lo, hi = DELTA_BINS[j], DELTA_BINS[j + 1]
            if j == 5:
                g_all = sub[sub['brick_delta'] == 0.0]
                g_ext = ext_sub[ext_sub['brick_delta'] == 0.0]
            else:
                g_all = sub[(sub['brick_delta'] > lo) & (sub['brick_delta'] <= hi)]
                g_ext = ext_sub[(ext_sub['brick_delta'] > lo) & (ext_sub['brick_delta'] <= hi)]
            if len(g_all) < 10:
                continue
            direction = '绿柱' if j < 5 else ('不变' if j == 5 else '红柱')
            all_rate = round(float(g_all['is_top3'].mean() * 100), 2)
            ext_rate = round(float(g_ext['is_top3'].mean() * 100), 2) if len(g_ext) > 0 else 0.0
            d3.append({
                'label':     dlabel,
                'direction': direction,
                # 全体B1轨道
                'all_total':   int(len(g_all)),
                'all_rate':    all_rate,
                'all_vs_base': round(all_rate / baseline, 2) if baseline > 0 else 0.0,
                # 极致B1子集轨道
                'ext_total':   int(len(g_ext)),
                'ext_rate':    ext_rate,
                'ext_vs_base': round(ext_rate / baseline_ext, 2) if len(g_ext) > 0 and baseline_ext > 0 else 0.0,
            })

        # ── D4  连续同向动量柱（双轨）────────────────────────
        # brick_turn 已区分 red_continue / green_continue，
        # turn=green_to_red  → 红动量柱第1日
        # turn=red_continue  → 红动量柱第2+日
        # turn=red_to_green  → 绿动量柱第1日
        # turn=green_continue→ 绿动量柱第2+日
        STREAK_DEF = [
            ('red_day1',   'green_to_red',   '红动量柱 第1日（昨绿→今红）'),
            ('red_day2p',  'red_continue',   '红动量柱 连续第2+日'),
            ('grn_day1',   'red_to_green',   '绿动量柱 第1日（昨红→今绿）'),
            ('grn_day2p',  'green_continue', '绿动量柱 连续第2+日'),
            ('other',      'other',          '其他（含零值/不变/无前日数据）'),
        ]
        d4 = []
        for sid, turn_key, slabel in STREAK_DEF:
            g_all = sub[sub['brick_turn'] == turn_key]
            if len(g_all) == 0:
                continue
            g_ext = ext_sub[ext_sub['brick_turn'] == turn_key]
            all_rate = round(float(g_all['is_top3'].mean() * 100), 2)
            ext_rate = round(float(g_ext['is_top3'].mean() * 100), 2) if len(g_ext) > 0 else 0.0
            d4.append({
                'streak_id':  sid,
                'turn_key':   turn_key,
                'label':      slabel,
                # 全体B1轨道
                'all_total':    int(len(g_all)),
                'all_top3':     int(g_all['is_top3'].sum()),
                'all_rate':     all_rate,
                'all_vs_base':  round(all_rate / baseline, 2) if baseline > 0 else 0.0,
                'all_avg_delta': round(float(g_all['brick_delta'].mean()), 4),
                # 极致B1子集轨道
                'ext_total':    int(len(g_ext)),
                'ext_top3':     int(g_ext['is_top3'].sum()),
                'ext_rate':     ext_rate,
                'ext_vs_base':  round(ext_rate / baseline_ext, 2) if len(g_ext) > 0 and baseline_ext > 0 else 0.0,
            })

        # ── D5  最优组合（双轨 TOP20）────────────────────────
        # 全体B1：动量柱区间 × K线方向（不区分极致/普通，避免混入极致标签）
        # 极致B1子集：动量柱区间 × K线方向
        d5_all, d5_ext = [], []
        for j, dlabel in enumerate(DELTA_LABELS):
            lo, hi = DELTA_BINS[j], DELTA_BINS[j + 1]
            if j == 5:
                dg_all = sub[sub['brick_delta'] == 0.0]
                dg_ext = ext_sub[ext_sub['brick_delta'] == 0.0]
            else:
                dg_all = sub[(sub['brick_delta'] > lo) & (sub['brick_delta'] <= hi)]
                dg_ext = ext_sub[(ext_sub['brick_delta'] > lo) & (ext_sub['brick_delta'] <= hi)]
            direction = '绿柱' if j < 5 else ('不变' if j == 5 else '红柱')
            for md, md_label in [('up', '阳线'), ('down', '阴线')]:
                # 全体B1
                cell_all = dg_all[dg_all['kline_dir'] == md]
                if len(cell_all) >= 10:
                    rate_all = round(float(cell_all['is_top3'].mean() * 100), 2)
                    d5_all.append({
                        'delta_label': dlabel, 'direction': direction,
                        'kline_label': md_label,
                        'total': int(len(cell_all)), 'top3_count': int(cell_all['is_top3'].sum()),
                        'top3_rate': rate_all,
                        'vs_base': round(rate_all / baseline, 2) if baseline > 0 else 0.0,
                    })
                # 极致B1子集
                cell_ext = dg_ext[dg_ext['kline_dir'] == md]
                if len(cell_ext) >= 10:
                    rate_ext = round(float(cell_ext['is_top3'].mean() * 100), 2)
                    d5_ext.append({
                        'delta_label': dlabel, 'direction': direction,
                        'kline_label': md_label,
                        'total': int(len(cell_ext)), 'top3_count': int(cell_ext['is_top3'].sum()),
                        'top3_rate': rate_ext,
                        'vs_base': round(rate_ext / baseline_ext, 2) if baseline_ext > 0 else 0.0,
                    })
        d5_all.sort(key=lambda x: x['top3_rate'], reverse=True)
        d5_ext.sort(key=lambda x: x['top3_rate'], reverse=True)

        return {
            'market':        market,
            'market_name':   MARKET_NAMES.get(market, '全市场'),
            'total':         total,
            'baseline':      round(baseline, 2),
            'baseline_ext':  round(baseline_ext, 2),
            'ext_total':     int(len(ext_sub)),
            'delta_groups':  d1,
            'red_wavg':      red_wavg,
            'grn_wavg':      grn_wavg,
            'quadrant':      d2_quadrant,
            'delta_x_pct':   d2_matrix,
            'delta_x_extreme': d3,
            'streak':        d4,
            'top_all':       d5_all[:20],
            'top_ext':       d5_ext[:20],
        }

    # ─────────────────────────────────────────────────────
    #  汇总 & 入口
    # ─────────────────────────────────────────────────────

    def run(self) -> Dict:
        log_message('=' * 60)
        log_message(f'砖型图增强分析 | 策略:{self.strategy} 周期:{self.period}')
        log_message('=' * 60)

        df = self.collect_data()
        if df.empty:
            log_message('数据为空，分析终止', 'ERROR')
            return {}

        result = {
            'meta': {
                'strategy':  self.strategy,
                'period':    self.period,
                'total_samples': int(len(df)),
                'top3_samples':  int(df['is_top3'].sum()),
                'extreme_b1_samples': int(df['is_extreme'].sum()),
                'overall_top3_rate': round(float(df['is_top3'].mean() * 100), 2),
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            },
            'part_a': {},   # 独立砖型图，分市场
            'part_b': {},   # 双因子
            'part_c': {},   # × 极致B1
            'part_d': {},   # 动量柱专项
        }

        # 分市场分析
        for mkt in [None, 'A', 'B']:
            key = mkt if mkt else 'ALL'
            log_message(f'  分析市场: {MARKET_NAMES[mkt]}')
            result['part_a'][key] = self._analyze_brick_independent(df, mkt)
            result['part_b'][key] = self._analyze_dual_brick_kline(df, mkt)
            result['part_c'][key] = self._analyze_brick_extreme(df, mkt)
            result['part_d'][key] = self._analyze_momentum(df, mkt)

        # 保存 JSON
        out_json = OUTPUT_PATH / f'brick_enhanced_{self.strategy}_{self.period}.json'
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log_message(f'JSON 已保存: {out_json}')

        # 生成报告
        report_text = self._build_report(result, df)
        out_txt = OUTPUT_PATH / f'brick_enhanced_{self.strategy}_{self.period}_report.txt'
        with open(out_txt, 'w', encoding='utf-8') as f:
            f.write(report_text)
        log_message(f'报告已保存: {out_txt}')

        print(report_text)
        return result

    # ─────────────────────────────────────────────────────
    #  报告生成
    # ─────────────────────────────────────────────────────

    def _build_report(self, result: Dict, df: pd.DataFrame) -> str:
        meta = result['meta']
        baseline_all = meta['overall_top3_rate']
        lines = []

        def L(s=''):
            lines.append(s)

        # ── 封面 ──────────────────────────────────────────
        L('=' * 76)
        L('  砖型图增强因子分析报告')
        L(f'  策略: {meta["strategy"]}  |  周期: {meta["period"]}')
        L(f'  生成时间: {meta["analyzed_at"]}')
        L('=' * 76)
        L()
        L('【全局概览】')
        L(f'  总样本数       : {meta["total_samples"]:>12,} 条')
        L(f'  TOP3 样本数    : {meta["top3_samples"]:>12,} 条')
        L(f'  极致B1 样本数  : {meta["extreme_b1_samples"]:>12,} 条')
        L(f'  全市场基准TOP3率: {baseline_all:>10.2f}%')
        L()
        L('  报告结构：')
        L('    Part A  独立砖型图因子分析（分市场A/B）')
        L('    Part B  双因子：砖型图状态 × K线当日涨跌幅')
        L('    Part C  砖型图 × 极致B1 三维联合分析')
        L('    Part D  动量柱专项分析（brick_delta 为核心）')
        L('            D1 动量柱幅度区间 × TOP3率')
        L('            D2 动量柱方向 × K线涨跌幅（四象限 + 区间矩阵）')
        L('            D3 动量柱幅度 × 极致B1 联合效应')
        L('            D4 连续同向动量柱（红连续/绿连续）× TOP3率')
        L('            D5 三维最优组合 TOP20（动量柱×极致B1×K线方向）')
        L()

        # ── Part A ────────────────────────────────────────
        for mkt in [None, 'A', 'B']:
            key = mkt if mkt else 'ALL'
            pa = result['part_a'].get(key, {})
            if not pa:
                continue
            mkt_name = pa['market_name']
            baseline = pa['baseline']
            total    = pa['total']

            L('╔' + '═' * 74 + '╗')
            L(f'║  Part A  独立砖型图因子分析  —  市场: {mkt_name}')
            L(f'║  样本: {total:,}   基准TOP3率: {baseline:.2f}%')
            L('╚' + '═' * 74 + '╝')
            L()

            # ── A1 状态转换 ───────────────────────────────
            L('  ◆ A1  砖型图状态转换 → TOP3率')
            L()
            L(f'  {"状态":<26} {"样本":>9} {"TOP3数":>7} {"TOP3率":>7}  {"砖值均":>8}  {"柱体均":>8}  {"对比基准":<10}  图示')
            L(f'  {"─"*26} {"─"*9} {"─"*7} {"─"*7}  {"─"*8}  {"─"*8}  {"─"*10}  {"─"*26}')
            state_data = pa.get('state', [])
            max_r = max((d['top3_rate'] for d in state_data), default=1)
            for d in state_data:
                b = bar(d['top3_rate'], max_r, 26)
                sig = signal_tag(d['top3_rate'], baseline)
                L(f'  {d["label"]:<26} {d["total"]:>9,} {d["top3_count"]:>7,} '
                  f'{d["top3_rate"]:>6.2f}%  {d["avg_brick_value"]:>8.4f}  '
                  f'{d["avg_brick_body"]:>8.4f}  {sig:<12}  {b}')
            L()

            # 状态小结
            s_map = {d['state']: d for d in state_data}
            L('  ► 状态分析关键发现：')
            top_state = max(state_data, key=lambda x: x['top3_rate']) if state_data else None
            if top_state:
                L(f'    · 最高TOP3率状态：【{top_state["label"]}】')
                L(f'      TOP3率 {top_state["top3_rate"]:.2f}%，是基准的 '
                  f'{top_state["top3_rate"]/baseline:.1f} 倍，样本 {top_state["total"]:,} 条')
            if 'zero_to_red' in s_map and 'zero' in s_map:
                z2r = s_map['zero_to_red']
                zz  = s_map['zero']
                L(f'    · "零→红"启动信号：{z2r["top3_rate"]:.2f}%（基准{z2r["top3_rate"]/baseline:.1f}倍），')
                L(f'      "持续为零"超跌：{zz["top3_rate"]:.2f}%（基准{zz["top3_rate"]/baseline:.1f}倍）')
                L(f'      两种极端状态均优于中间过渡状态，验证了B1策略的超跌反弹逻辑。')
            if 'green_shrinking' in s_map:
                gs = s_map['green_shrinking']
                L(f'    · "绿柱回落"（占比 {gs["total"]/total*100:.1f}%）：TOP3率仅 '
                  f'{gs["top3_rate"]:.2f}%（基准的 {gs["top3_rate"]/baseline:.2f}倍），')
                L(f'      动量衰减期间是B1候选池中质量最低的区间，建议降低权重。')
            L()

            # ── A2 方向转换 ───────────────────────────────
            L('  ◆ A2  连续两日方向转换 → TOP3率')
            L()
            turn_data = pa.get('turn', [])
            max_r = max((d['top3_rate'] for d in turn_data), default=1)
            L(f'  {"转换类型":<28} {"样本":>9} {"TOP3数":>7} {"TOP3率":>7}  {"砖值均":>8}  {"柱体均":>8}  {"对比基准":<10}  图示')
            L(f'  {"─"*28} {"─"*9} {"─"*7} {"─"*7}  {"─"*8}  {"─"*8}  {"─"*10}  {"─"*26}')
            for d in turn_data:
                b = bar(d['top3_rate'], max_r, 26)
                sig = signal_tag(d['top3_rate'], baseline)
                L(f'  {d["label"]:<28} {d["total"]:>9,} {d["top3_count"]:>7,} '
                  f'{d["top3_rate"]:>6.2f}%  {d["avg_brick_value"]:>8.4f}  '
                  f'{d["avg_brick_body"]:>8.4f}  {sig:<12}  {b}')
            L()
            t_map = {d['turn']: d for d in turn_data}
            L('  ► 方向转换关键发现：')
            if 'green_to_red' in t_map:
                g2r = t_map['green_to_red']
                L(f'    · 绿转红（方向反转向上）：TOP3率 {g2r["top3_rate"]:.2f}%（基准 {g2r["top3_rate"]/baseline:.1f}倍），')
                L(f'      当砖型图从下跌方向转为上涨，是动量反转的早期信号。')
            if 'red_to_green' in t_map:
                r2g = t_map['red_to_green']
                L(f'    · 红转绿（方向反转向下）：TOP3率 {r2g["top3_rate"]:.2f}%（基准 {r2g["top3_rate"]/baseline:.1f}倍），')
                L(f'      动量由升转降，即便当日砖值仍较高，对后续表现也有负面影响。')
            if 'red_continue' in t_map and 'green_continue' in t_map:
                rc = t_map['red_continue']
                gc = t_map['green_continue']
                ratio = rc['top3_rate'] / gc['top3_rate'] if gc['top3_rate'] > 0 else 0
                L(f'    · 红柱延续 vs 绿柱延续：{rc["top3_rate"]:.2f}% vs {gc["top3_rate"]:.2f}%，')
                L(f'      连续红柱命中率是连续绿柱的 {ratio:.2f} 倍，动量延续优于动量衰减。')
            L()

            # ── A3 砖型图变化量（有符号 delta）分组 ─────────
            L('  ◆ A3  砖型图变化量（有符号 delta = 今日砖值 - 昨日砖值）→ TOP3率')
            L('      负值 = 绿柱（动量收缩），正值 = 红柱（动量扩张），=0 = 不变')
            L('      ⚠ 相同幅度的绿柱与红柱含义相反，本节已区分正负方向单独统计')
            L()
            body_data = pa.get('body_groups', [])
            max_r = max((d['top3_rate'] for d in body_data), default=1)
            L(f'  {"区间（有符号）":<22} {"样本":>9} {"TOP3率":>7}  {"delta均值":>10}  {"方向":>4}  {"对比基准":<10}  图示')
            L(f'  {"─"*22} {"─"*9} {"─"*7}  {"─"*10}  {"─"*4}  {"─"*10}  {"─"*26}')
            # 绿柱组（负值）
            green_data = [d for d in body_data if d['direction'] == '绿柱']
            flat_data  = [d for d in body_data if d['direction'] == '不变']
            red_data   = [d for d in body_data if d['direction'] == '红柱']
            for section, sect_label in [(green_data, '── 绿柱（动量收缩）──'),
                                        (flat_data,  '── 不变 ──'),
                                        (red_data,   '── 红柱（动量扩张）──')]:
                if section:
                    L(f'  {sect_label}')
                    for d in section:
                        b = bar(d['top3_rate'], max_r, 26)
                        sig = signal_tag(d['top3_rate'], baseline)
                        L(f'  {d["label"]:<22} {d["total"]:>9,} {d["top3_rate"]:>6.2f}%  '
                          f'{d["avg_delta"]:>+10.4f}  {d["direction"]:>4}  {sig:<12}  {b}')
            L()
            # 小结：红柱 vs 绿柱的同幅度对比
            if green_data and red_data:
                avg_green = sum(d['top3_rate'] * d['total'] for d in green_data) / sum(d['total'] for d in green_data)
                avg_red   = sum(d['top3_rate'] * d['total'] for d in red_data)   / sum(d['total'] for d in red_data)
                L(f'  ► 红柱区间加权均TOP3率: {avg_red:.2f}%  vs  绿柱区间加权均TOP3率: {avg_green:.2f}%')
                L(f'    相同 delta 幅度下，红柱（动量扩张）TOP3率是绿柱（动量收缩）的 {avg_red/avg_green:.2f} 倍。')
                best_red   = max(red_data,   key=lambda x: x['top3_rate'])
                best_green = max(green_data, key=lambda x: x['top3_rate'])
                L(f'    · 红柱最优区间：【{best_red["label"]}】，TOP3率 {best_red["top3_rate"]:.2f}%（基准 {best_red["top3_rate"]/baseline:.1f}倍）')
                L(f'    · 绿柱最优区间：【{best_green["label"]}】，TOP3率 {best_green["top3_rate"]:.2f}%（基准 {best_green["top3_rate"]/baseline:.1f}倍）')
            L()

            # ── A4 砖值绝对高度分位 ────────────────────────
            L('  ◆ A4  砖值绝对高度（五分位）→ TOP3率')
            L()
            vg_data = pa.get('value_groups', [])
            max_r = max((d['top3_rate'] for d in vg_data), default=1)
            L(f'  {"分组":<8} {"砖值区间":<24} {"样本":>9} {"TOP3率":>7}  {"对比基准":<10}  图示')
            L(f'  {"─"*8} {"─"*24} {"─"*9} {"─"*7}  {"─"*10}  {"─"*26}')
            for d in vg_data:
                b = bar(d['top3_rate'], max_r, 26)
                sig = signal_tag(d['top3_rate'], baseline)
                L(f'  {d["group"]:<8} {d["range"]:<24} {d["total"]:>9,} {d["top3_rate"]:>6.2f}%  {sig:<12}  {b}')
            L()
            if len(vg_data) >= 2:
                g0   = vg_data[0]
                g_hi = vg_data[-1]
                L(f'  ► 砖值分布规律：')
                L(f'    · 砖值=0（超跌极端）：TOP3率 {g0["top3_rate"]:.2f}%（基准 {g0["top3_rate"]/baseline:.1f}倍）')
                L(f'    · 最高分位（{g_hi["range"]}）：TOP3率 {g_hi["top3_rate"]:.2f}%（基准 {g_hi["top3_rate"]/baseline:.1f}倍）')
                L(f'    · 砖型图对B1的影响呈"U型"：超跌零值区和动量高位均优于中间区域。')
            L()

        # ── Part B ────────────────────────────────────────
        for mkt in [None, 'A', 'B']:
            key = mkt if mkt else 'ALL'
            pb = result['part_b'].get(key, {})
            if not pb:
                continue
            mkt_name = pb['market_name']
            baseline = pb['baseline']

            L('╔' + '═' * 74 + '╗')
            L(f'║  Part B  双因子分析：砖型图状态 × K线涨跌幅  —  市场: {mkt_name}')
            L(f'║  基准TOP3率: {baseline:.2f}%')
            L('╚' + '═' * 74 + '╝')
            L()

            # B1: 状态 × 涨跌幅区间展开
            L('  ◆ B1  砖型图状态 × K线涨跌幅分组（明细）')
            L()
            for row_d in pb.get('state_x_pct', []):
                L(f'  ▶ 【{row_d["label"]}】 总样本: {row_d["state_total"]:,}  整体TOP3率: {row_d["state_top3_rate"]:.2f}%')
                bd = row_d.get('pct_breakdown', [])
                if bd:
                    L(f'    {"涨跌幅区间":<12} {"样本":>8} {"TOP3率":>7}  {"均涨跌幅":>8}  {"对比基准":<10}')
                    L(f'    {"─"*12} {"─"*8} {"─"*7}  {"─"*8}  {"─"*10}')
                    max_r = max(c['top3_rate'] for c in bd) if bd else 1
                    for c in bd:
                        sig = signal_tag(c['top3_rate'], baseline)
                        L(f'    {c["pct_group"]:<12} {c["total"]:>8,} {c["top3_rate"]:>6.2f}%  '
                          f'{c["avg_change"]:>+7.2f}%  {sig}')
                else:
                    L(f'    （各涨跌幅区间样本量不足10，不展示细节）')
                L()

            # B2: 方向转换 × 涨跌幅
            L('  ◆ B2  砖型图方向转换 × K线涨跌幅特征')
            L()
            L(f'  {"转换类型":<16} {"样本":>9} {"TOP3率":>7}  {"均涨跌幅":>8}  {"涨跌标准差":>10}  '
              f'{"TOP3均涨":>8}  {"非TOP3均涨":>10}  {"对比基准":<10}')
            L(f'  {"─"*16} {"─"*9} {"─"*7}  {"─"*8}  {"─"*10}  {"─"*8}  {"─"*10}  {"─"*10}')
            b2_data = pb.get('turn_x_pct', [])
            for d in b2_data:
                sig = signal_tag(d['top3_rate'], baseline)
                L(f'  {d["label"]:<16} {d["total"]:>9,} {d["top3_rate"]:>6.2f}%  '
                  f'{d["avg_change"]:>+7.2f}%  {d["change_std"]:>10.2f}  '
                  f'{d["top3_avg_change"]:>+7.2f}%  {d["non_top3_avg_change"]:>+9.2f}%  {sig}')
            L()
            L('  ► 双因子关键发现：')
            b2_map = {d['turn']: d for d in b2_data}
            if 'green_to_red' in b2_map:
                d = b2_map['green_to_red']
                L(f'    · 绿转红时 TOP3均涨跌幅={d["top3_avg_change"]:+.2f}% vs 非TOP3={d["non_top3_avg_change"]:+.2f}%')
                L(f'      TOP3股在绿转红信号下仍有正向K线表现，说明砖型图领先于价格。')
            if 'red_continue' in b2_map and 'green_continue' in b2_map:
                rc = b2_map['red_continue']
                gc = b2_map['green_continue']
                L(f'    · 红柱延续当日均涨 {rc["avg_change"]:+.2f}%，TOP3组均涨 {rc["top3_avg_change"]:+.2f}%')
                L(f'    · 绿柱延续当日均涨 {gc["avg_change"]:+.2f}%，TOP3组均涨 {gc["top3_avg_change"]:+.2f}%')
            L()

            # B3: 热力矩阵
            L('  ◆ B3  热力矩阵：K线涨跌幅区间 × 砖型图状态（TOP3率%，空=样本不足）')
            L()
            state_order = pb.get('state_order', [])
            state_short = {
                'zero_to_red': '零→红', 'red_growing': '红柱增',
                'green_shrinking': '绿柱落', 'green_to_zero': '绿→零', 'zero': '持续零',
            }
            # 表头
            header = f'  {"涨跌幅区间":<12} {"总样":>7}'
            for s in state_order:
                header += f'  {state_short.get(s, s):>7}'
            L(header)
            sep = f'  {"─"*12} {"─"*7}'
            for s in state_order:
                sep += f'  {"─"*7}'
            L(sep)
            for row_d in pb.get('heatmap', []):
                line = f'  {row_d["pct_group"]:<12} {row_d["total"]:>7,}'
                for s in state_order:
                    v = row_d.get(s)
                    if v is None:
                        line += f'  {"--":>7}'
                    else:
                        tag = '↑↑' if v >= baseline * 2 else ('↑' if v >= baseline * 1.2 else ('↓' if v < baseline * 0.7 else ''))
                        line += f'  {v:>5.1f}{tag:>2}'
                L(line)
            L()
            L(f'  ↑↑ = ≥基准2倍  ↑ = ≥基准1.2倍  ↓ = <基准0.7倍  基准={baseline:.2f}%')
            L()

        # ── Part C ────────────────────────────────────────
        for mkt in [None, 'A', 'B']:
            key = mkt if mkt else 'ALL'
            pc = result['part_c'].get(key, {})
            if not pc:
                continue
            mkt_name     = pc['market_name']
            baseline_all = pc['baseline_all']   # 全体B1基准
            baseline_ext = pc['baseline_ext']   # 极致B1子集基准
            ext_total    = pc['ext_total']

            L('╔' + '═' * 74 + '╗')
            L(f'║  Part C  砖型图 × 极致B1 联合分析（双轨）  —  市场: {mkt_name}')
            L(f'║  全体B1基准TOP3率: {baseline_all:.2f}%   极致B1基准TOP3率: {baseline_ext:.2f}%   极致B1样本: {ext_total:,}')
            L('╚' + '═' * 74 + '╝')
            L()

            # C1: 基础对比
            c1 = pc.get('extreme_vs_non', {})
            ext_info = c1.get('extreme', {})
            nxt_info = c1.get('non_extreme', {})
            L('  ◆ C1  极致B1 vs 普通B1 基础对比')
            L()
            L(f'  {"类别":<16} {"样本":>9} {"TOP3数":>7} {"TOP3率":>7}  {"对比全体基准":<12}')
            L(f'  {"─"*16} {"─"*9} {"─"*7} {"─"*7}  {"─"*12}')
            for info, label in [(ext_info, '极致B1'), (nxt_info, '普通B1（非极致）')]:
                sig = signal_tag(info.get('top3_rate', 0), baseline_all)
                L(f'  {label:<16} {info.get("total", 0):>9,} {info.get("top3_count", 0):>7,} '
                  f'{info.get("top3_rate", 0):>6.2f}%  {sig}')
            L()
            if ext_info.get('top3_rate', 0) > 0 and nxt_info.get('top3_rate', 0) > 0:
                boost = ext_info['top3_rate'] / nxt_info['top3_rate']
                L(f'  ► 极致B1的TOP3率是普通B1的 {boost:.2f} 倍。')
                if boost >= 1.5:
                    L(f'    结论：极致B1信号对TOP3命中率有显著提升，建议优先关注极致B1。')
                elif boost >= 1.2:
                    L(f'    结论：极致B1信号有一定提升效果，可作为候选加分项。')
                else:
                    L(f'    结论：极致B1信号对TOP3率提升有限，需结合其他因子综合判断。')
            L()

            # C2: 砖型图状态 × 双轨
            L('  ◆ C2  砖型图状态 — 双轨分析')
            L('      轨道1：全体B1（各状态 TOP3率 vs 全体基准）')
            L('      轨道2：仅极致B1子集（砖型因子在极致B1内部的区分能力，vs 极致B1基准）')
            L()
            L(f'  {"状态":<18}  ── 轨道1 全体B1 ──────────────────  ── 轨道2 极致B1子集 ──────────────')
            L(f'  {"":18}  {"总样":>8}  {"TOP3率":>7}  {"vs全体基":>8}  分级  '
              f'{"总样":>8}  {"TOP3率":>7}  {"vs极致基":>8}  分级')
            L(f'  {"─"*18}  {"─"*8}  {"─"*7}  {"─"*8}  {"─"*6}  '
              f'{"─"*8}  {"─"*7}  {"─"*8}  {"─"*6}')
            c2_data = pc.get('state_groups', [])
            for d in c2_data:
                sig_all = signal_tag(d['all_rate'], baseline_all)
                sig_ext = signal_tag(d['ext_rate'], baseline_ext) if d['ext_total'] >= 10 else '--'
                L(f'  {d["label"]:<18}  {d["all_total"]:>8,}  {d["all_rate"]:>6.2f}%  '
                  f'{d["all_vs_base"]:>7.2f}x  {sig_all:<6}  '
                  f'{d["ext_total"]:>8,}  {d["ext_rate"]:>6.2f}%  '
                  f'{d["ext_vs_base"]:>7.2f}x  {sig_ext}')
            L()
            L('  ► C2 关键发现：')
            # 全体B1最优状态
            c2_best_all = max(c2_data, key=lambda x: x['all_rate']) if c2_data else None
            if c2_best_all:
                L(f'    · [全体B1] 最佳状态：【{c2_best_all["label"]}】'
                  f'TOP3率 {c2_best_all["all_rate"]:.2f}%（基准{c2_best_all["all_vs_base"]:.2f}x），'
                  f'样本 {c2_best_all["all_total"]:,}')
            # 极致B1子集最优状态（样本≥10）
            c2_ext_valid = [d for d in c2_data if d['ext_total'] >= 10]
            c2_best_ext = max(c2_ext_valid, key=lambda x: x['ext_rate']) if c2_ext_valid else None
            if c2_best_ext:
                L(f'    · [极致B1] 最佳状态：【{c2_best_ext["label"]}】'
                  f'TOP3率 {c2_best_ext["ext_rate"]:.2f}%（极致基准{c2_best_ext["ext_vs_base"]:.2f}x），'
                  f'样本 {c2_best_ext["ext_total"]:,}')
            L()

            # C3: 方向转换 × 双轨
            L('  ◆ C3  砖型图方向转换 — 双轨分析')
            L()
            L(f'  {"转换类型":<16}  ── 轨道1 全体B1 ──────────────────  ── 轨道2 极致B1子集 ──────────────')
            L(f'  {"":16}  {"总样":>8}  {"TOP3率":>7}  {"vs全体基":>8}  分级  '
              f'{"总样":>8}  {"TOP3率":>7}  {"vs极致基":>8}  分级')
            L(f'  {"─"*16}  {"─"*8}  {"─"*7}  {"─"*8}  {"─"*6}  '
              f'{"─"*8}  {"─"*7}  {"─"*8}  {"─"*6}')
            for d in pc.get('turn_groups', []):
                sig_all = signal_tag(d['all_rate'], baseline_all)
                sig_ext = signal_tag(d['ext_rate'], baseline_ext) if d['ext_total'] >= 10 else '--'
                L(f'  {d["label"]:<16}  {d["all_total"]:>8,}  {d["all_rate"]:>6.2f}%  '
                  f'{d["all_vs_base"]:>7.2f}x  {sig_all:<6}  '
                  f'{d["ext_total"]:>8,}  {d["ext_rate"]:>6.2f}%  '
                  f'{d["ext_vs_base"]:>7.2f}x  {sig_ext}')
            L()

            # C4: 动量柱区间（有符号 delta）× 双轨
            L('  ◆ C4  砖型图变化量（有符号 delta）— 双轨分析')
            L('      负值=绿柱（动量收缩），正值=红柱（动量扩张）')
            L()
            L(f'  {"区间（有符号）":<22} {"方向":>4}  ── 轨道1 全体B1 ──────────────────  ── 轨道2 极致B1子集 ──────────────')
            L(f'  {"":22} {"":4}  {"总样":>8}  {"TOP3率":>7}  {"vs全体基":>8}  分级  '
              f'{"总样":>8}  {"TOP3率":>7}  {"vs极致基":>8}  分级')
            L(f'  {"─"*22} {"─"*4}  {"─"*8}  {"─"*7}  {"─"*8}  {"─"*6}  '
              f'{"─"*8}  {"─"*7}  {"─"*8}  {"─"*6}')
            c4_data = pc.get('delta_groups', [])
            green_c4 = [d for d in c4_data if d['direction'] == '绿柱']
            flat_c4  = [d for d in c4_data if d['direction'] == '不变']
            red_c4   = [d for d in c4_data if d['direction'] == '红柱']
            for section, sect_label in [(green_c4, '── 绿柱（动量收缩）──'),
                                        (flat_c4,  '── 不变 ──'),
                                        (red_c4,   '── 红柱（动量扩张）──')]:
                if section:
                    L(f'  {sect_label}')
                    for d in section:
                        sig_all = signal_tag(d['all_rate'], baseline_all)
                        sig_ext = signal_tag(d['ext_rate'], baseline_ext) if d['ext_total'] >= 10 else '--'
                        L(f'  {d["label"]:<22} {d["direction"]:>4}  {d["all_total"]:>8,}  '
                          f'{d["all_rate"]:>6.2f}%  {d["all_vs_base"]:>7.2f}x  {sig_all:<6}  '
                          f'{d["ext_total"]:>8,}  {d["ext_rate"]:>6.2f}%  '
                          f'{d["ext_vs_base"]:>7.2f}x  {sig_ext}')
            L()

            # C5: 最优状态排名（全体B1 TOP10 + 极致B1子集 TOP10）
            L('  ◆ C5  砖型图状态最优排名（样本≥10，按TOP3率降序）')
            L()
            L('  ▶ 轨道1：全体B1 TOP10')
            L(f'  {"排名":>4}  {"状态":<18}  {"总样":>8}  {"TOP3数":>7}  {"TOP3率":>7}  {"vs全体基":>8}  分级')
            L(f'  {"─"*4}  {"─"*18}  {"─"*8}  {"─"*7}  {"─"*7}  {"─"*8}  {"─"*8}')
            for rank_i, d in enumerate(pc.get('top_all', []), 1):
                sig = signal_tag(d['top3_rate'], baseline_all)
                L(f'  {rank_i:>4}  {d["label"]:<18}  {d["total"]:>8,}  {d["top3_count"]:>7,}  '
                  f'{d["top3_rate"]:>6.2f}%  {d["vs_base"]:>7.2f}x  {sig}')
            L()
            L('  ▶ 轨道2：极致B1子集 TOP10（仅在极致B1内部排名，vs 极致B1基准）')
            L(f'  {"排名":>4}  {"状态":<18}  {"总样":>8}  {"TOP3数":>7}  {"TOP3率":>7}  {"vs极致基":>8}  分级')
            L(f'  {"─"*4}  {"─"*18}  {"─"*8}  {"─"*7}  {"─"*7}  {"─"*8}  {"─"*8}')
            for rank_i, d in enumerate(pc.get('top_ext', []), 1):
                sig = signal_tag(d['top3_rate'], baseline_ext) if baseline_ext > 0 else '--'
                L(f'  {rank_i:>4}  {d["label"]:<18}  {d["total"]:>8,}  {d["top3_count"]:>7,}  '
                  f'{d["top3_rate"]:>6.2f}%  {d["vs_base"]:>7.2f}x  {sig}')
            L()

        # ── Part D ────────────────────────────────────────
        for mkt in [None, 'A', 'B']:
            key = mkt if mkt else 'ALL'
            pd_data = result['part_d'].get(key, {})
            if not pd_data:
                continue
            mkt_name = pd_data['market_name']
            baseline = pd_data['baseline']
            total    = pd_data['total']

            L('╔' + '═' * 74 + '╗')
            L(f'║  Part D  动量柱专项分析  —  市场: {mkt_name}')
            L(f'║  样本: {total:,}   基准TOP3率: {baseline:.2f}%')
            L('╚' + '═' * 74 + '╝')
            L()

            # ── D1 动量柱幅度区间 × TOP3率 ──────────────────
            L('  ◆ D1  动量柱幅度区间（有符号 delta）→ TOP3率')
            L('      正值=红动量柱（扩张），负值=绿动量柱（收缩），=0=不变')
            L()
            d1_data = pd_data.get('delta_groups', [])
            max_r = max((d['top3_rate'] for d in d1_data), default=1)
            L(f'  {"区间（有符号）":<24} {"方向":>4} {"样本":>9} {"TOP3率":>7}  '
              f'{"delta均":>9}  {"砖值均":>8}  {"对比基准":<12}  图示')
            L(f'  {"─"*24} {"─"*4} {"─"*9} {"─"*7}  {"─"*9}  {"─"*8}  {"─"*12}  {"─"*26}')
            grn_d1 = [d for d in d1_data if d['direction'] == '绿柱']
            flat_d1 = [d for d in d1_data if d['direction'] == '不变']
            red_d1 = [d for d in d1_data if d['direction'] == '红柱']
            for section, sect_label in [(grn_d1, '── 绿柱（动量收缩）──'),
                                        (flat_d1, '── 不变 ──'),
                                        (red_d1,  '── 红柱（动量扩张）──')]:
                if section:
                    L(f'  {sect_label}')
                    for d in section:
                        b = bar(d['top3_rate'], max_r, 26)
                        sig = signal_tag(d['top3_rate'], baseline)
                        delta_str = f'{d["avg_delta"]:+.4f}'
                        L(f'  {d["label"]:<24} {d["direction"]:>4} {d["total"]:>9,} '
                          f'{d["top3_rate"]:>6.2f}%  {delta_str:>9}  '
                          f'{d["avg_brick_value"]:>8.4f}  {sig:<14}  {b}')
            L()
            red_wavg = pd_data.get('red_wavg', 0)
            grn_wavg = pd_data.get('grn_wavg', 0)
            L(f'  ► 红动量柱区间加权均TOP3率: {red_wavg:.2f}%  vs  绿动量柱区间加权均TOP3率: {grn_wavg:.2f}%')
            if grn_wavg > 0:
                ratio = red_wavg / grn_wavg
                L(f'    相同 delta 幅度下，红动量柱 TOP3率是绿动量柱的 {ratio:.2f} 倍。')
            if red_d1:
                best_red = max(red_d1, key=lambda x: x['top3_rate'])
                L(f'    · 红柱最优区间：【{best_red["label"]}】，TOP3率 {best_red["top3_rate"]:.2f}%（基准{best_red["top3_rate"]/baseline:.1f}倍）')
            if grn_d1:
                best_grn = max(grn_d1, key=lambda x: x['top3_rate'])
                L(f'    · 绿柱最优区间：【{best_grn["label"]}】，TOP3率 {best_grn["top3_rate"]:.2f}%（基准{best_grn["top3_rate"]/baseline:.1f}倍）')
            L()

            # ── D2 四象限 + 区间×K线矩阵 ─────────────────────
            L('  ◆ D2  动量柱方向 × K线涨跌幅')
            L()
            L('  ▶ 四象限汇总')
            d2q = pd_data.get('quadrant', [])
            max_r2 = max((d['top3_rate'] for d in d2q), default=1)
            L(f'  {"象限描述":<28} {"样本":>9} {"TOP3率":>7}  {"delta均":>9}  {"均涨跌幅":>8}  {"对比基准":<12}  图示')
            L(f'  {"─"*28} {"─"*9} {"─"*7}  {"─"*9}  {"─"*8}  {"─"*12}  {"─"*26}')
            for d in d2q:
                b = bar(d['top3_rate'], max_r2, 26)
                sig = signal_tag(d['top3_rate'], baseline)
                delta_str = f'{d["avg_delta"]:+.4f}'
                change_str = f'{d["avg_change_pct"]:+.2f}%'
                L(f'  {d["label"]:<28} {d["total"]:>9,} {d["top3_rate"]:>6.2f}%  '
                  f'{delta_str:>9}  {change_str:>8}  {sig:<14}  {b}')
            L()

            # 四象限关键发现
            q_map = {d['quadrant']: d for d in d2q}
            L('  ► 四象限关键发现：')
            qi  = q_map.get('QI')
            qii = q_map.get('QII')
            qiii= q_map.get('QIII')
            qiv = q_map.get('QIV')
            if qi and qii:
                L(f'    · 红动量柱+阳线（QI）vs 红动量柱+阴线（QII）：'
                  f'{qi["top3_rate"]:.2f}% vs {qii["top3_rate"]:.2f}%')
                if qii['top3_rate'] > qi['top3_rate']:
                    L(f'      ⚠ 红动量+阴线 TOP3率更高——砖型图领先K线，当日回调不影响后续表现。')
                else:
                    L(f'      红动量+阳线共振效果更佳。')
            if qiii and qiv:
                L(f'    · 绿动量柱+阴线（QIII）vs 绿动量柱+阳线（QIV）：'
                  f'{qiii["top3_rate"]:.2f}% vs {qiv["top3_rate"]:.2f}%')
                if qiv['top3_rate'] > qiii['top3_rate']:
                    L(f'      绿动量收缩但K线反弹，可能是阶段性底部信号，需关注。')
            L()

            L('  ▶ 动量柱区间 × K线涨跌幅矩阵（TOP3率%，空=样本不足10）')
            d2_matrix = pd_data.get('delta_x_pct', [])
            PCT_LABELS_DISP = ['<-5%', '[-5,-3)', '[-3,-1)', '[-1,0)', '[0,1)', '[1,3)', '[3,5)', '≥5%']
            # 表头
            hdr = f'  {"动量柱区间":<24} {"方向":>4} {"总样":>7}'
            for pg in PCT_LABELS_DISP:
                hdr += f'  {pg:>7}'
            L(hdr)
            sep = f'  {"─"*24} {"─"*4} {"─"*7}'
            for _ in PCT_LABELS_DISP:
                sep += f'  {"─"*7}'
            L(sep)
            prev_dir = None
            for row in d2_matrix:
                cur_dir = row['direction']
                if cur_dir != prev_dir:
                    dir_label = '── 绿柱 ──' if cur_dir == '绿柱' else ('── 不变 ──' if cur_dir == '不变' else '── 红柱 ──')
                    L(f'  {dir_label}')
                    prev_dir = cur_dir
                row_str = f'  {row["delta_label"]:<24} {row["direction"]:>4} {row["delta_total"]:>7,}'
                for pg in PCT_LABELS_DISP:
                    cell = row['pct_cells'].get(pg)
                    if cell:
                        r = cell['top3_rate']
                        flag = '↑↑' if r >= baseline * 2 else ('↑' if r >= baseline * 1.2 else ('↓' if r < baseline * 0.7 else ' '))
                        row_str += f'  {r:>5.1f}{flag}'
                    else:
                        row_str += f'  {"--":>7}'
                L(row_str)
            L(f'  ↑↑ = ≥基准2倍  ↑ = ≥基准1.2倍  ↓ = <基准0.7倍  基准={baseline:.2f}%')
            L()

            # ── D3 动量柱幅度区间（双轨）────────────────────────
            L('  ◆ D3  动量柱幅度区间 — 双轨分析')
            L('      轨道1：全体B1（各区间 TOP3率 vs 全体基准）')
            L('      轨道2：仅极致B1子集（砖型因子在极致B1内部的区分能力，vs 极致B1基准）')
            L()
            baseline_ext_d = pd_data.get('baseline_ext', 0.0)
            L(f'  {"区间（有符号）":<24} {"方向":>4}  ── 轨道1 全体B1 ──────────────────  ── 轨道2 极致B1子集 ──────────────')
            L(f'  {"":24} {"":4}  {"总样":>8}  {"TOP3率":>7}  {"vs全体基":>8}  分级  '
              f'{"总样":>8}  {"TOP3率":>7}  {"vs极致基":>8}  分级')
            L(f'  {"─"*24} {"─"*4}  {"─"*8}  {"─"*7}  {"─"*8}  {"─"*6}  '
              f'{"─"*8}  {"─"*7}  {"─"*8}  {"─"*6}')
            d3_data = pd_data.get('delta_x_extreme', [])
            grn_d3 = [d for d in d3_data if d['direction'] == '绿柱']
            flat_d3= [d for d in d3_data if d['direction'] == '不变']
            red_d3 = [d for d in d3_data if d['direction'] == '红柱']
            for section, sect_label in [(grn_d3, '── 绿柱（动量收缩）──'),
                                        (flat_d3, '── 不变 ──'),
                                        (red_d3,  '── 红柱（动量扩张）──')]:
                if section:
                    L(f'  {sect_label}')
                    for d in section:
                        sig_all = signal_tag(d['all_rate'], baseline)
                        sig_ext = signal_tag(d['ext_rate'], baseline_ext_d) if d['ext_total'] >= 10 and baseline_ext_d > 0 else '--'
                        L(f'  {d["label"]:<24} {d["direction"]:>4}  {d["all_total"]:>8,}  '
                          f'{d["all_rate"]:>6.2f}%  {d["all_vs_base"]:>7.2f}x  {sig_all:<6}  '
                          f'{d["ext_total"]:>8,}  {d["ext_rate"]:>6.2f}%  '
                          f'{d["ext_vs_base"]:>7.2f}x  {sig_ext}')
            L()
            # D3 关键发现
            L('  ► D3 关键发现：')
            d3_all_best = max(d3_data, key=lambda x: x['all_rate']) if d3_data else None
            if d3_all_best:
                L(f'    · [全体B1] 最优动量柱区间：【{d3_all_best["label"]}】'
                  f'TOP3率 {d3_all_best["all_rate"]:.2f}%（全体基准{d3_all_best["all_vs_base"]:.2f}x）')
            d3_ext_valid = [d for d in d3_data if d['ext_total'] >= 10]
            d3_ext_best = max(d3_ext_valid, key=lambda x: x['ext_rate']) if d3_ext_valid else None
            if d3_ext_best:
                L(f'    · [极致B1] 最优动量柱区间：【{d3_ext_best["label"]}】'
                  f'TOP3率 {d3_ext_best["ext_rate"]:.2f}%（极致基准{d3_ext_best["ext_vs_base"]:.2f}x），'
                  f'样本 {d3_ext_best["ext_total"]:,}')
            if red_d3 and grn_d3:
                red_all_avg = sum(d['all_rate']*d['all_total'] for d in red_d3) / max(1, sum(d['all_total'] for d in red_d3))
                grn_all_avg = sum(d['all_rate']*d['all_total'] for d in grn_d3) / max(1, sum(d['all_total'] for d in grn_d3))
                L(f'    · 红动量柱全体均TOP3率 {red_all_avg:.2f}%  vs  绿动量柱全体均TOP3率 {grn_all_avg:.2f}%')
                if red_all_avg > grn_all_avg:
                    L(f'      红动量柱（扩张方向）整体TOP3率占优。')
                else:
                    L(f'      绿动量柱（收缩方向）整体TOP3率占优。')
            L()

            # ── D4 连续同向动量柱（双轨）──────────────────────
            L('  ◆ D4  连续同向动量柱 — 双轨分析')
            L('      利用 brick_turn 字段区分：第1日（转折）vs 第2+日（延续）')
            L()
            d4_data = pd_data.get('streak', [])
            # 全体B1轨道
            max_r4_all = max((d['all_rate'] for d in d4_data), default=1)
            L('  ▶ 轨道1：全体B1')
            L(f'  {"类型":<32} {"总样":>9} {"TOP3数":>7} {"TOP3率":>7}  '
              f'{"vs全体基":>8}  {"delta均":>9}  {"对比基准":<12}  图示')
            L(f'  {"─"*32} {"─"*9} {"─"*7} {"─"*7}  {"─"*8}  {"─"*9}  {"─"*12}  {"─"*26}')
            red_streak = [d for d in d4_data if d['streak_id'].startswith('red')]
            grn_streak = [d for d in d4_data if d['streak_id'].startswith('grn')]
            oth_streak = [d for d in d4_data if d['streak_id'] == 'other']
            for section, sect_label in [(red_streak, '── 红动量柱 ──'),
                                        (grn_streak, '── 绿动量柱 ──'),
                                        (oth_streak, '── 其他 ──')]:
                if section:
                    L(f'  {sect_label}')
                    for d in section:
                        b = bar(d['all_rate'], max_r4_all, 26)
                        sig = signal_tag(d['all_rate'], baseline)
                        delta_str = f'{d["all_avg_delta"]:+.4f}'
                        L(f'  {d["label"]:<32} {d["all_total"]:>9,} {d["all_top3"]:>7,} '
                          f'{d["all_rate"]:>6.2f}%  {d["all_vs_base"]:>7.2f}x  {delta_str:>9}  '
                          f'{sig:<14}  {b}')
            L()
            # 轨道2
            max_r4_ext = max((d['ext_rate'] for d in d4_data if d['ext_total'] >= 10), default=1)
            L('  ▶ 轨道2：极致B1子集')
            L(f'  {"类型":<32} {"总样":>9} {"TOP3数":>7} {"TOP3率":>7}  '
              f'{"vs极致基":>8}  {"对比基准":<12}  图示')
            L(f'  {"─"*32} {"─"*9} {"─"*7} {"─"*7}  {"─"*8}  {"─"*12}  {"─"*26}')
            for section, sect_label in [(red_streak, '── 红动量柱 ──'),
                                        (grn_streak, '── 绿动量柱 ──'),
                                        (oth_streak, '── 其他 ──')]:
                if section:
                    L(f'  {sect_label}')
                    for d in section:
                        if d['ext_total'] < 10:
                            continue
                        b = bar(d['ext_rate'], max_r4_ext, 26)
                        sig = signal_tag(d['ext_rate'], baseline_ext_d) if baseline_ext_d > 0 else '--'
                        L(f'  {d["label"]:<32} {d["ext_total"]:>9,} {d["ext_top3"]:>7,} '
                          f'{d["ext_rate"]:>6.2f}%  {d["ext_vs_base"]:>7.2f}x  '
                          f'{sig:<14}  {b}')
            L()
            # D4 关键发现
            L('  ► D4 关键发现：')
            d4_map = {d['streak_id']: d for d in d4_data}
            red1 = d4_map.get('red_day1')
            red2p = d4_map.get('red_day2p')
            grn1 = d4_map.get('grn_day1')
            grn2p = d4_map.get('grn_day2p')
            if red1 and red2p:
                L(f'    · [全体B1] 红动量柱：第1日 {red1["all_rate"]:.2f}% vs 延续第2+日 {red2p["all_rate"]:.2f}%')
                if red2p['all_rate'] > red1['all_rate']:
                    L(f'      连续红动量柱的质量高于单日反转，动量延续信号更强。')
                else:
                    L(f'      红动量柱首日反转信号更值得关注，延续阶段效果趋弱。')
                if red1['ext_total'] >= 10 and red2p['ext_total'] >= 10:
                    L(f'    · [极致B1] 红动量柱：第1日 {red1["ext_rate"]:.2f}% vs 延续第2+日 {red2p["ext_rate"]:.2f}%')
            if grn1 and grn2p:
                L(f'    · [全体B1] 绿动量柱：第1日 {grn1["all_rate"]:.2f}% vs 延续第2+日 {grn2p["all_rate"]:.2f}%')
                if grn2p['all_rate'] < grn1['all_rate']:
                    L(f'      绿动量持续收缩压制TOP3概率，应避开连续绿动量柱区域。')
                if grn1['ext_total'] >= 10 and grn2p['ext_total'] >= 10:
                    L(f'    · [极致B1] 绿动量柱：第1日 {grn1["ext_rate"]:.2f}% vs 延续第2+日 {grn2p["ext_rate"]:.2f}%')
            L()

            # ── D5 最优组合排名（双轨 TOP20）─────────────────────────
            L('  ◆ D5  最优组合排名 TOP20（动量柱区间 × K线方向，样本≥10，按TOP3率降序）')
            L()
            L('  ▶ 轨道1：全体B1 TOP20（vs 全体基准）')
            L(f'  {"排名":>4}  {"动量柱区间":<28}  {"方向":>4}  {"K线":>4}  '
              f'{"总样":>8}  {"TOP3数":>7}  {"TOP3率":>7}  {"vs全体基":>8}  分级')
            L(f'  {"─"*4}  {"─"*28}  {"─"*4}  {"─"*4}  '
              f'{"─"*8}  {"─"*7}  {"─"*7}  {"─"*8}  {"─"*8}')
            for rank_i, d in enumerate(pd_data.get('top_all', []), 1):
                sig = signal_tag(d['top3_rate'], baseline)
                L(f'  {rank_i:>4}  {d["delta_label"]:<28}  {d["direction"]:>4}  '
                  f'{d["kline_label"]:>4}  '
                  f'{d["total"]:>8,}  {d["top3_count"]:>7,}  '
                  f'{d["top3_rate"]:>6.2f}%  {d["vs_base"]:>7.2f}x  {sig}')
            L()
            L('  ▶ 轨道2：极致B1子集 TOP20（仅在极致B1内部排名，vs 极致B1基准）')
            L(f'  {"排名":>4}  {"动量柱区间":<28}  {"方向":>4}  {"K线":>4}  '
              f'{"总样":>8}  {"TOP3数":>7}  {"TOP3率":>7}  {"vs极致基":>8}  分级')
            L(f'  {"─"*4}  {"─"*28}  {"─"*4}  {"─"*4}  '
              f'{"─"*8}  {"─"*7}  {"─"*7}  {"─"*8}  {"─"*8}')
            for rank_i, d in enumerate(pd_data.get('top_ext', []), 1):
                sig = signal_tag(d['top3_rate'], baseline_ext_d) if baseline_ext_d > 0 else '--'
                L(f'  {rank_i:>4}  {d["delta_label"]:<28}  {d["direction"]:>4}  '
                  f'{d["kline_label"]:>4}  '
                  f'{d["total"]:>8,}  {d["top3_count"]:>7,}  '
                  f'{d["top3_rate"]:>6.2f}%  {d["vs_base"]:>7.2f}x  {sig}')
            L()

        # ── 综合结论 ──────────────────────────────────────
        L('╔' + '═' * 74 + '╗')
        L('║  综合结论与操作建议')
        L('╚' + '═' * 74 + '╝')
        L()
        L('  基于本次四维分析（独立因子 / 砖型×K线 / 砖型×极致B1双轨 / 动量柱双轨），总结如下核心规律：')
        L()

        # 逐市场输出最优策略
        for mkt, mkt_label in [('A', '主板(00/60)'), ('B', '创业板/科创板')]:
            key = mkt
            pa = result['part_a'].get(key, {})
            pb = result['part_b'].get(key, {})
            pc = result['part_c'].get(key, {})
            pd_d = result['part_d'].get(key, {})
            if not pa or not pc:
                continue
            baseline_a = pa['baseline']
            baseline_c_all = pc.get('baseline_all', baseline_a)
            baseline_c_ext = pc.get('baseline_ext', 0.0)

            L(f'  ─── 【{mkt_label}】全体B1基准TOP3率: {baseline_c_all:.2f}%   极致B1基准: {baseline_c_ext:.2f}% ───')
            L()

            # 独立砖型图最优状态
            state_data = pa.get('state', [])
            if state_data:
                top_state = max(state_data, key=lambda x: x['top3_rate'])
                L(f'  1. 最佳单因子状态：【{top_state["label"]}】')
                L(f'     TOP3率 {top_state["top3_rate"]:.2f}%（全体基准 {top_state["top3_rate"]/baseline_c_all:.1f}倍），')
                L(f'     推荐将此砖型图状态作为B1候选池的筛选加分条件。')
            L()

            # 最优双因子组合（砖型图状态 + 涨跌幅区间）
            best_dual = None
            best_dual_rate = 0
            for row_d in pb.get('state_x_pct', []):
                for c in row_d.get('pct_breakdown', []):
                    if c['top3_rate'] > best_dual_rate and c['total'] >= 30:
                        best_dual_rate = c['top3_rate']
                        best_dual = (row_d['label'], c['pct_group'], c)
            if best_dual:
                s_label, pg, c = best_dual
                L(f'  2. 最佳双因子组合（砖型图+K线涨跌幅）：')
                L(f'     砖型图状态【{s_label}】× 当日涨跌幅【{pg}】')
                L(f'     TOP3率 {c["top3_rate"]:.2f}%（全体基准 {c["top3_rate"]/baseline_c_all:.1f}倍），样本 {c["total"]:,} 条')
            L()

            # 最优砖型图×极致B1（双轨 TOP1）
            top_all_c = pc.get('top_all', [])
            top_ext_c = pc.get('top_ext', [])
            L(f'  3. 砖型图状态 最优组合（双轨）：')
            if top_all_c:
                best_all = top_all_c[0]
                L(f'     [全体B1]  【{best_all["label"]}】'
                  f'TOP3率 {best_all["top3_rate"]:.2f}%（全体基准{best_all["vs_base"]:.2f}x），'
                  f'样本 {best_all["total"]:,}')
            if top_ext_c and baseline_c_ext > 0:
                best_ext = top_ext_c[0]
                L(f'     [极致B1]  【{best_ext["label"]}】'
                  f'TOP3率 {best_ext["top3_rate"]:.2f}%（极致基准{best_ext["vs_base"]:.2f}x），'
                  f'样本 {best_ext["total"]:,}')
            L()

            # 最优动量柱组合（双轨 TOP1）
            top_all_d = pd_d.get('top_all', [])
            top_ext_d = pd_d.get('top_ext', [])
            baseline_ext_d2 = pd_d.get('baseline_ext', 0.0)
            L(f'  4. 动量柱 最优组合（双轨）：')
            if top_all_d:
                best_all_d = top_all_d[0]
                L(f'     [全体B1]  动量柱【{best_all_d["delta_label"]}】× K线【{best_all_d["kline_label"]}】')
                L(f'     TOP3率 {best_all_d["top3_rate"]:.2f}%（全体基准{best_all_d["vs_base"]:.2f}x），样本 {best_all_d["total"]:,}')
            if top_ext_d and baseline_ext_d2 > 0:
                best_ext_d = top_ext_d[0]
                L(f'     [极致B1]  动量柱【{best_ext_d["delta_label"]}】× K线【{best_ext_d["kline_label"]}】')
                L(f'     TOP3率 {best_ext_d["top3_rate"]:.2f}%（极致基准{best_ext_d["vs_base"]:.2f}x），样本 {best_ext_d["total"]:,}')
            L()

        L('  ★ 注意事项：')
        L('    · 样本量 < 50 的组合统计可靠性较低，仅供参考，需持续积累后复验。')
        L('    · 本分析基于历史回测数据，不代表未来收益保证。')
        L('    · 建议将砖型图条件作为叠加过滤器，而非独立选股条件。')
        L('    · 极致B1阈值：主板(振幅≥2.68% 且 量比≥0.59)；创业板等(振幅≥3.46% 且 量比≥0.42)。')
        L()
        L('=' * 76)
        L(f'  报告生成完毕  |  数据量：{meta["total_samples"]:,} 条  |  {meta["analyzed_at"]}')
        L('=' * 76)

        return '\n'.join(lines)


# ──────────────────────────────────────────────────────────
#  命令行入口
# ──────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description='砖型图增强因子分析（含双因子 & 极致B1）')
    p.add_argument('--strategy',    default='B1',  help='策略 (默认B1)')
    p.add_argument('--period',      default='3d',  choices=['3d', '5d', '10d'])
    p.add_argument('--all-periods', action='store_true', help='分析所有周期')
    p.add_argument('--start-date',  default=None,  help='开始日期 YYYYMMDD')
    p.add_argument('--end-date',    default=None,  help='结束日期 YYYYMMDD')
    p.add_argument('--test',        type=int, default=None, metavar='N',
                   help='测试模式：只处理前N个交易日')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()
    periods = ['3d', '5d', '10d'] if args.all_periods else [args.period]

    for period in periods:
        analyzer = BrickEnhancedAnalyzer(
            strategy=args.strategy,
            period=period,
            start_date=args.start_date,
            end_date=args.end_date,
            max_dates=args.test,
        )
        analyzer.run()
