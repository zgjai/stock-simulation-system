"""
砖型策略多因子收益分析脚本

核心目标：在当前选股策略基础上，找到涨幅更高的可能性，并降低下跌风险。

分析的5个因子：
  F1  砖型红/绿柱比例          red_len / green_len（即当日 brick_delta / |昨日 brick_delta|）
  F2  当日股价涨跌幅            close_change_pct
  F3  砖型红柱 / 当日涨跌幅比例  brick_delta / close_change_pct（99分位截断）
  F4  收盘价 / 知行多空线       close / multi_line
  F5  收盘价 / 知行短期趋势线   close / ema10_2

收益目标（双轨）：
  · 实际收盘涨跌幅：未来 1、2、3 个交易日收盘价 vs 当日收盘价的涨跌幅
  · 最大涨幅：未来 1、2、3 个交易日窗口内的最大涨幅（同现有 learning_cases）

使用方法：
    cd /Users/zhangguijiang/project/stock/stock_simulation_system
    python backend/scripts/analyze_multi_factor_return.py --strategy B1
    python backend/scripts/analyze_multi_factor_return.py --strategy B1 --start-date 20200101
    python backend/scripts/analyze_multi_factor_return.py --strategy B1 --test 100
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

MARKET_NAMES = {
    'A': '主板(00/60)',
    'B': '创业板/科创板/北交所(30/68/92)',
}

PERIODS = [1, 2, 3]  # 分析未来1/2/3个交易日


# ──────────────────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────────────────

def get_market(code: str) -> str:
    return 'A' if code[:2] in ['00', '60'] else 'B'


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")
    return conn


def bar(rate: float, max_rate: float, width: int = 24) -> str:
    if max_rate <= 0:
        return '░' * width
    filled = min(int(abs(rate) / max_rate * width), width)
    if rate >= 0:
        return '█' * filled + '░' * (width - filled)
    else:
        return '▒' * filled + '░' * (width - filled)


def pct_tag(val: float) -> str:
    """收益标注"""
    if val >= 3.0:   return '🔴🔴 强势'
    if val >= 1.5:   return '🔴 较强'
    if val >= 0.5:   return '🟡 偏强'
    if val >= -0.5:  return '⚪ 中性'
    if val >= -1.5:  return '🟢 偏弱'
    return              '🟢🟢 弱势'


def down_risk_tag(rate: float) -> str:
    """下跌风险标注"""
    if rate <= 15:  return '✅ 低风险'
    if rate <= 25:  return '⚠️ 中风险'
    return              '❌ 高风险'


def winrate_tag(rate: float) -> str:
    """胜率标注"""
    if rate >= 65:  return '✅ 高胜率'
    if rate >= 50:  return '⚠️ 中胜率'
    return              '❌ 低胜率'


def clip_series(s: pd.Series, lo_pct: float = 1.0, hi_pct: float = 99.0) -> pd.Series:
    """分位数截断，处理极端值"""
    valid = s.dropna()
    if len(valid) < 10:
        return s
    lo = np.percentile(valid, lo_pct)
    hi = np.percentile(valid, hi_pct)
    return s.clip(lo, hi)


# ──────────────────────────────────────────────────────────
#  数据加载
# ──────────────────────────────────────────────────────────

def load_price_cache(conn, codes: List[str]) -> Dict[str, pd.DataFrame]:
    """
    批量加载股价+指标数据，用于：
    1. 当日因子计算（brick_delta, close_change_pct, close/multi_line, close/ema10_2）
    2. 未来N天收益计算（需要后续日期的 close）
    """
    if not codes:
        return {}
    ph = ','.join(['?'] * len(codes))
    sql = f"""
        SELECT stock_code, trade_date,
               close, prev_close,
               brick_value, brick_body,
               ema10_2, multi_line,
               open, high, low
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


# ──────────────────────────────────────────────────────────
#  派生因子计算（5因子 + 未来收益）
# ──────────────────────────────────────────────────────────

def derive_factors_and_returns(stock_df: pd.DataFrame, date_str: str) -> Optional[Dict]:
    """
    从单股 DataFrame 提取指定日期的因子值和未来1/2/3天收益。

    因子定义：
      F1: red_len / green_len
          red_len  = brick_delta(T)   当日动量柱（>0 为红柱）
          green_len= |brick_delta(T-1)| 昨日绿柱（T-1为绿柱时<0，取绝对值）
          策略要求 F1 > brick_ratio（默认0.667），此处记录实际值
      F2: close_change_pct = (close - prev_close) / prev_close * 100
      F3: brick_delta(T) / close_change_pct（99%分位截断后使用）
      F4: close / multi_line
      F5: close / ema10_2

    收益定义：
      ret_close_Nd = (close[T+N] - close[T]) / close[T] * 100  （实际收盘涨跌幅）
      ret_max_Nd   = max(close[T+1..T+N]) / close[T] - 1) * 100 （N日最大涨幅）
    """
    idx_list = stock_df.index[stock_df['trade_date'] == date_str]
    if len(idx_list) == 0:
        return None
    i = idx_list[0]

    # ── 读取当日数据 ──────────────────────────────────────
    close     = stock_df.at[i, 'close']
    prev_close = stock_df.at[i, 'prev_close']
    brick_val  = stock_df.at[i, 'brick_value']
    ema10_2    = stock_df.at[i, 'ema10_2']
    multi_line = stock_df.at[i, 'multi_line']

    if pd.isna(close) or pd.isna(brick_val):
        return None

    close      = float(close)
    brick_val  = float(brick_val)
    ema10_2    = float(ema10_2)  if not pd.isna(ema10_2)    else None
    multi_line = float(multi_line) if not pd.isna(multi_line) else None

    # ── 当日动量柱（brick_delta = 今日砖值 - 昨日砖值）──
    if i == 0:
        return None
    prev_brick = stock_df.at[i - 1, 'brick_value']
    if pd.isna(prev_brick):
        return None
    prev_brick = float(prev_brick)
    brick_delta = brick_val - prev_brick  # 今日动量柱（有符号）

    # 策略要求：今日为红动量柱（brick_delta > 0）
    if brick_delta <= 0:
        return None

    # ── 昨日动量柱（绿柱长度）─────────────────────────────
    if i < 2:
        return None
    prev2_brick = stock_df.at[i - 2, 'brick_value']
    if pd.isna(prev2_brick):
        return None
    prev_delta = prev_brick - float(prev2_brick)
    # 策略要求：昨日为绿动量柱（prev_delta < 0）
    if prev_delta >= 0:
        return None

    red_len   = brick_delta           # 当日红柱长度（正数）
    green_len = abs(prev_delta)       # 昨日绿柱长度（正数）

    # ── F1：红/绿柱比例 ──────────────────────────────────
    f1 = red_len / green_len if green_len > 0 else None

    # ── F6：过去6天（T-2 ~ T-7）红动量柱数量 ─────────────
    # 砖型策略基础条件：T-1为绿柱、T为红柱，两天是确定的；
    # 因此从T-2往前数6天统计历史红柱数量，捕捉短期动量连续性
    # 计算 T-k 的动量柱需要 brick_value[i-k] - brick_value[i-k-1]，
    # k 最大=7 时需要 i-8 ≥ 0，故要求 i >= 8
    f6_red_count = None
    if i >= 8:
        f6_count = 0
        f6_valid = True
        for k in range(2, 8):  # k=2..7，即 T-2 至 T-7
            bv_k   = stock_df.at[i - k,     'brick_value']
            bv_k1  = stock_df.at[i - k - 1, 'brick_value']
            if pd.isna(bv_k) or pd.isna(bv_k1):
                f6_valid = False
                break
            delta_k = float(bv_k) - float(bv_k1)
            if delta_k > 0:
                f6_count += 1
        if f6_valid:
            f6_red_count = f6_count

    # ── F2：当日涨跌幅 ────────────────────────────────────
    if pd.isna(prev_close) or float(prev_close) == 0:
        return None
    f2 = (close - float(prev_close)) / float(prev_close) * 100

    # ── F3：红柱/涨跌幅比例，分涨日/跌日两个子因子 ──────
    # 门槛降至0.2%，避免接近零时的噪音
    # f3_up:   仅当日上涨（f2>0.2%）时有效，= red_len / f2，值越小=每%涨幅动量越强
    # f3_down: 仅当日下跌（f2<-0.2%）时有效，= red_len / abs(f2)，值越大=跌时红柱越强（逆势）
    f3_up   = None
    f3_down = None
    if f2 >= 0.2:
        f3_up   = red_len / f2          # 正值，涨1%时的动量柱强度
    elif f2 <= -0.2:
        f3_down = red_len / abs(f2)     # 正值，跌1%时的红柱逆势强度

    # ── F4：收盘价/知行多空线 ─────────────────────────────
    f4 = close / multi_line if (multi_line is not None and multi_line > 0) else None

    # ── F5：收盘价/知行短期趋势线 ─────────────────────────
    f5 = close / ema10_2 if (ema10_2 is not None and ema10_2 > 0) else None

    # ── 未来N天收益 ───────────────────────────────────────
    returns = {}
    for n in PERIODS:
        future_idx = i + n
        if future_idx >= len(stock_df):
            # 数据不够，跳过
            returns[f'ret_close_{n}d'] = None
            returns[f'ret_max_{n}d']   = None
        else:
            future_close = stock_df.at[future_idx, 'close']
            if pd.isna(future_close) or close == 0:
                returns[f'ret_close_{n}d'] = None
                returns[f'ret_max_{n}d']   = None
            else:
                # 实际收盘涨跌幅
                ret_close = (float(future_close) - close) / close * 100
                # N天内最大涨幅（取 close，不含当日）
                window_closes = [stock_df.at[i + k, 'close']
                                 for k in range(1, n + 1)
                                 if (i + k) < len(stock_df) and not pd.isna(stock_df.at[i + k, 'close'])]
                ret_max = (max(float(c) for c in window_closes) - close) / close * 100 if window_closes else None
                returns[f'ret_close_{n}d'] = round(ret_close, 3)
                returns[f'ret_max_{n}d']   = round(ret_max, 3) if ret_max is not None else None

    result = {
        'f1_brick_ratio':    round(f1, 4)      if f1      is not None else None,
        'f2_change_pct':     round(f2, 3),
        'f3_up':             round(f3_up, 4)   if f3_up   is not None else None,
        'f3_down':           round(f3_down, 4) if f3_down is not None else None,
        'f4_close_multi':    round(f4, 5)      if f4      is not None else None,
        'f5_close_short':    round(f5, 5)      if f5      is not None else None,
        'f6_red_count':      int(f6_red_count) if f6_red_count is not None else None,
        'brick_delta':       round(brick_delta, 4),
        'green_len':         round(green_len, 4),
        'close':             close,
    }
    result.update(returns)
    return result


# ──────────────────────────────────────────────────────────
#  分组统计辅助函数
# ──────────────────────────────────────────────────────────

def group_stats(g: pd.DataFrame, periods: List[int]) -> Dict:
    """对一组样本计算多个收益指标的统计量"""
    stats = {'total': len(g)}
    for n in periods:
        col_c = f'ret_close_{n}d'
        col_m = f'ret_max_{n}d'
        s_c = g[col_c].dropna()
        s_m = g[col_m].dropna()
        if len(s_c) == 0:
            stats[f'n{n}_count']       = 0
            stats[f'n{n}_mean_close']  = None
            stats[f'n{n}_median_close']= None
            stats[f'n{n}_win_rate']    = None
            stats[f'n{n}_down_rate']   = None
            stats[f'n{n}_mean_max']    = None
            stats[f'n{n}_median_max']  = None
            stats[f'n{n}_pct25']       = None
            stats[f'n{n}_pct75']       = None
        else:
            stats[f'n{n}_count']       = int(len(s_c))
            stats[f'n{n}_mean_close']  = round(float(s_c.mean()), 3)
            stats[f'n{n}_median_close']= round(float(s_c.median()), 3)
            stats[f'n{n}_win_rate']    = round(float((s_c > 0).mean() * 100), 1)
            stats[f'n{n}_down_rate']   = round(float((s_c < -1.0).mean() * 100), 1)  # 跌超1%的比例
            stats[f'n{n}_pct25']       = round(float(s_c.quantile(0.25)), 3)
            stats[f'n{n}_pct75']       = round(float(s_c.quantile(0.75)), 3)
            if len(s_m) > 0:
                stats[f'n{n}_mean_max']   = round(float(s_m.mean()), 3)
                stats[f'n{n}_median_max'] = round(float(s_m.median()), 3)
            else:
                stats[f'n{n}_mean_max']   = None
                stats[f'n{n}_median_max'] = None
    return stats


def bin_factor(s: pd.Series, factor_name: str, n_bins: int = 5) -> Tuple[pd.Series, List]:
    """
    将连续因子分成 n_bins 个等频区间，返回分组标签和区间描述。
    对于 F4/F5（close/均线比），1.0 有特殊意义，特别处理。
    """
    valid = s.dropna()
    if len(valid) < n_bins * 10:
        return pd.Series(dtype='object'), []

    # 特殊处理 F4/F5：以 1.0 为分界线
    if factor_name in ('f4_close_multi', 'f5_close_short'):
        bins = [-np.inf, 0.98, 0.99, 1.00, 1.01, 1.02, 1.05, np.inf]
        labels = ['<0.98', '[0.98,0.99)', '[0.99,1.00)',
                  '[1.00,1.01)', '[1.01,1.02)', '[1.02,1.05)', '≥1.05']
        try:
            cut = pd.cut(s, bins=bins, labels=labels, right=False)
            return cut, labels
        except Exception:
            pass

    # 通用：等频分位
    try:
        cut, bin_edges = pd.qcut(valid, q=n_bins, retbins=True, duplicates='drop')
        labels = [f'Q{j+1}({bin_edges[j]:.2f}~{bin_edges[j+1]:.2f})'
                  for j in range(len(bin_edges) - 1)]
        cut_full = pd.qcut(s, q=n_bins, labels=labels, duplicates='drop')
        return cut_full, labels
    except Exception:
        return pd.Series(dtype='object'), []


# ──────────────────────────────────────────────────────────
#  主分析器
# ──────────────────────────────────────────────────────────

class MultiFacReturnAnalyzer:

    def __init__(self,
                 strategy: str = 'B1',
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None,
                 max_dates: Optional[int] = None,
                 brick_ratio: float = 2.0 / 3.0):
        self.strategy   = strategy
        self.start_date = start_date
        self.end_date   = end_date
        self.max_dates  = max_dates
        self.brick_ratio = brick_ratio
        ensure_dir(str(OUTPUT_PATH))

    # ── 数据收集 ──────────────────────────────────────────

    def collect_data(self) -> pd.DataFrame:
        """
        遍历策略索引，取所有满足 brick_ratio 条件的候选股，
        为每条记录计算5个因子 + 未来1/2/3天收益（收盘+最大涨幅）。
        """
        index_dir = INDEX_PATH / self.strategy
        if not index_dir.exists():
            log_message(f"策略索引目录不存在: {index_dir}", 'ERROR')
            return pd.DataFrame()

        fnames = sorted([f for f in os.listdir(index_dir) if f.endswith('.json')])
        if self.start_date:
            fnames = [f for f in fnames if f.replace('.json', '') >= self.start_date]
        if self.end_date:
            fnames = [f for f in fnames if f.replace('.json', '') <= self.end_date]
        if self.max_dates:
            fnames = fnames[:self.max_dates]

        log_message(f"共 {len(fnames)} 个交易日，brick_ratio={self.brick_ratio:.3f}")

        # 预收集所有候选股
        date_candidates: Dict[str, List[str]] = {}
        all_stocks: set = set()
        for fname in fnames:
            date = fname.replace('.json', '')
            idx_file = index_dir / fname
            with open(idx_file) as f:
                idx = json.load(f)
            candidates = idx.get('stocks', [])
            if not candidates:
                continue
            date_candidates[date] = candidates
            all_stocks.update(candidates)

        if not all_stocks:
            log_message("未找到任何候选股", 'ERROR')
            return pd.DataFrame()

        log_message(f"涉及股票 {len(all_stocks)} 只，加载行情数据...")
        conn = get_conn()
        price_cache = load_price_cache(conn, list(all_stocks))
        conn.close()
        log_message(f"行情缓存: {len(price_cache)} 只")

        rows = []
        skipped = 0
        for date, candidates in sorted(date_candidates.items()):
            for code in candidates:
                mkt = get_market(code)
                stock_df = price_cache.get(code)
                if stock_df is None:
                    skipped += 1
                    continue

                factors = derive_factors_and_returns(stock_df, date)
                if factors is None:
                    skipped += 1
                    continue

                # 再次过滤 brick_ratio 条件（策略层面已过滤，此处兜底）
                f1 = factors.get('f1_brick_ratio')
                if f1 is not None and f1 < self.brick_ratio:
                    skipped += 1
                    continue

                rec = {
                    'date':    date,
                    'stock':   code,
                    'market':  mkt,
                    **factors,
                }
                rows.append(rec)

        df = pd.DataFrame(rows)
        log_message(f"样本收集完成: {len(df):,} 条，跳过 {skipped:,} 条")

        # 分位数截断 F3_up 和 F3_down（涨日/跌日分别截断，避免极值干扰）
        for f3_col in ['f3_up', 'f3_down']:
            if f3_col in df.columns and df[f3_col].notna().sum() > 10:
                lo = df[f3_col].quantile(0.01)
                hi = df[f3_col].quantile(0.99)
                df[f3_col] = df[f3_col].clip(lo, hi)
                log_message(f"{f3_col} 分位数截断: [{lo:.2f}, {hi:.2f}]")

        return df

    # ── 单因子分析 ────────────────────────────────────────

    def _build_factor_bins(self, sub: pd.DataFrame) -> Dict:
        """
        动态构建各因子的分箱配置。
        对于样本量过大的尾部区间（≥最大固定边界），自动用等频子分位拆分，
        使每个区间样本量大致均衡（目标：最大区间 ≤ 总样本的 40%）。
        返回：{col: {'name','desc','bins','labels'}}
        """
        n = len(sub)

        def _auto_split_tail(col: str, base_bins: list, base_labels: list,
                             split_last_n: int = 5) -> Tuple[list, list]:
            """
            若最后一个区间样本量 > 总样本40%，对该区间做等频细分。
            split_last_n: 细分成几段
            """
            tail_mask = sub[col] >= base_bins[-2]  # 最后一段的起点
            tail_cnt  = tail_mask.sum()
            if tail_cnt <= n * 0.35 or tail_cnt < split_last_n * 30:
                return base_bins, base_labels
            # 对尾部区间做等频分位
            tail_vals = sub.loc[tail_mask, col].dropna()
            try:
                _, edges = pd.qcut(tail_vals, q=split_last_n, retbins=True, duplicates='drop')
                edges[0]  = base_bins[-2]   # 保证左端点一致
                edges[-1] = base_bins[-1]   # 保证右端点一致（inf）
                new_bins   = base_bins[:-2] + list(edges)
                # 最后一段label用>=
                tail_labels = [f'[{edges[j]:.3f},{edges[j+1]:.3f})' for j in range(len(edges)-2)]
                tail_labels.append(f'≥{edges[-2]:.3f}')
                new_labels = base_labels[:-1] + tail_labels
                return new_bins, new_labels
            except Exception:
                return base_bins, base_labels

        configs = {}

        # F1：砖型红/绿柱比例
        f1_bins   = [0, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 9999]
        f1_labels = ['[0.667,0.8)', '[0.8,1.0)', '[1.0,1.2)',
                     '[1.2,1.5)', '[1.5,2.0)', '[2.0,3.0)', '≥3.0']
        f1_bins, f1_labels = _auto_split_tail('f1_brick_ratio', f1_bins, f1_labels, 5)
        configs['f1_brick_ratio'] = {
            'name': 'F1 砖型红/绿柱比例',
            'desc': '红动量柱长度 / 昨日绿动量柱长度（策略门槛=0.667）',
            'bins': f1_bins, 'labels': f1_labels,
        }

        # F2：当日股价涨跌幅（固定分箱，已经较均匀）
        configs['f2_change_pct'] = {
            'name': 'F2 当日股价涨跌幅',
            'desc': '(close - prev_close) / prev_close × 100',
            'bins':   [-99, -3, -1, 0, 0.5, 1, 2, 3, 4, 5, 99],
            'labels': ['<-3%', '[-3,-1)', '[-1,0)', '[0,0.5)',
                       '[0.5,1)', '[1,2)', '[2,3)', '[3,4)', '[4,5)', '≥5%'],
        }

        # F3_up：仅涨日有效（f2≥0.2%），= red_len/f2，等频5组
        # 含义：值越小=每1%涨幅对应的动量柱越大（涨幅小但动量柱强）
        configs['f3_up'] = {
            'name': 'F3_up 涨日红柱/涨幅比（红柱强度/当日涨幅）',
            'desc': '仅当日上涨(f2≥0.2%)时有效：brick_delta / f2（值越小=单位涨幅动量越强）',
            'bins': None, 'labels': None,  # 动态等频5组
        }

        # F3_down：仅跌日有效（f2≤-0.2%），= red_len/|f2|，等频5组
        # 含义：当日下跌但出现红柱，值越大=跌幅大但红柱更强（逆势动量越强）
        configs['f3_down'] = {
            'name': 'F3_down 跌日红柱/跌幅比（逆势动量强度）',
            'desc': '仅当日下跌(f2≤-0.2%)时有效：brick_delta / |f2|（值越大=跌幅大但红柱更强）',
            'bins': None, 'labels': None,  # 动态等频5组
        }

        # F4：收盘/多空线 — 细分大尾部
        f4_bins   = [-np.inf, 1.00, 1.01, 1.02, 1.03, 1.05, 1.08, 1.12, np.inf]
        f4_labels = ['<1.00', '[1.00,1.01)', '[1.01,1.02)', '[1.02,1.03)',
                     '[1.03,1.05)', '[1.05,1.08)', '[1.08,1.12)', '≥1.12']
        configs['f4_close_multi'] = {
            'name': 'F4 收盘价/知行多空线',
            'desc': 'close / multi_line（1.0=恰好在多空线上，>1=多头区域，策略已过滤<1的情形）',
            'bins': f4_bins, 'labels': f4_labels,
        }

        # F5：收盘/短期趋势线 — 细分大尾部
        f5_bins   = [-np.inf, 0.97, 0.99, 1.00, 1.01, 1.02, 1.04, 1.07, 1.12, np.inf]
        f5_labels = ['<0.97', '[0.97,0.99)', '[0.99,1.00)', '[1.00,1.01)',
                     '[1.01,1.02)', '[1.02,1.04)', '[1.04,1.07)', '[1.07,1.12)', '≥1.12']
        configs['f5_close_short'] = {
            'name': 'F5 收盘价/知行短期趋势线',
            'desc': 'close / ema10_2（1.0=恰好在短期线上，>1=短期多头）',
            'bins': f5_bins, 'labels': f5_labels,
        }

        # F6：过去6天（T-2~T-7）红动量柱数量，0~6 的整数
        configs['f6_red_count'] = {
            'name': 'F6 近6日红柱数量',
            'desc': '信号日往前第2~7个交易日（T-2~T-7）中动量红柱（brick_delta>0）的天数，反映近期动量连续性',
            'bins':   [-0.5, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
            'labels': ['0天', '1天', '2天', '3天', '4天', '5天', '6天'],
        }

        return configs

    def _single_factor_analysis(self, df: pd.DataFrame, market: str) -> Dict:
        """
        对5个因子分别做区间分析：
        - 使用动态分箱，自动细分样本量过大的区间（避免单组>40%总样本）
        - 每个区间输出: 未来1/2/3天均值收益、中位数、胜率、下跌率、最大涨幅
        """
        sub = df[df['market'] == market].copy()
        if len(sub) < 50:
            return {}

        factor_configs = self._build_factor_bins(sub)

        result = {}
        for col, cfg in factor_configs.items():
            s = sub[col].dropna()
            if len(s) < 50:
                result[col] = {'name': cfg['name'], 'desc': cfg['desc'],
                               'total': len(s), 'groups': []}
                continue

            if cfg['bins'] is None:
                # F3_up / F3_down：等频5组
                cut, group_labels = bin_factor(sub[col], col, 5)
            else:
                try:
                    cut = pd.cut(sub[col], bins=cfg['bins'],
                                 labels=cfg['labels'], right=False)
                    group_labels = cfg['labels']
                except Exception:
                    cut, group_labels = bin_factor(sub[col], col, 5)

            if len(group_labels) == 0:
                result[col] = {'name': cfg['name'], 'desc': cfg['desc'],
                               'total': len(s), 'groups': []}
                continue

            sub_with_grp = sub.copy()
            sub_with_grp['_grp'] = cut
            groups = []
            for lbl in group_labels:
                g = sub_with_grp[sub_with_grp['_grp'] == lbl]
                if len(g) < 5:
                    continue
                st = group_stats(g, PERIODS)
                st['label'] = str(lbl)
                groups.append(st)

            result[col] = {
                'name':   cfg['name'],
                'desc':   cfg['desc'],
                'total':  int(len(s)),
                'groups': groups,
            }

        return result

    # ── 多因子联合打分 ────────────────────────────────────

    def _derive_factor_sweet_zones(self, sub: pd.DataFrame) -> Dict:
        """
        从数据中实证推导各因子的"甜区"阈值，用于打分。

        方法：将每个因子分为10等份，计算每段的未来3天均值收益，
        找出高于整体基准的区间作为甜区（得+1），低于基准的区间作为差区（得-1）。

        返回：{col: {'sweet_lo', 'sweet_hi', 'bad_lo', 'bad_hi', 'direction', 'desc'}}
        其中 direction='high'表示高值为甜区，'low'表示低值为甜区，'mid'表示中间值为甜区
        """
        target_col = 'ret_close_3d'
        if target_col not in sub.columns:
            return {}
        baseline = sub[target_col].dropna().mean()

        sweet_zones = {}

        def _find_zone(col: str) -> Optional[Dict]:
            s = sub[[col, target_col]].dropna()
            if len(s) < 100:
                return None
            try:
                s['_decile'] = pd.qcut(s[col], q=10, labels=False, duplicates='drop')
            except Exception:
                return None
            seg = s.groupby('_decile')[target_col].mean()
            if len(seg) < 3:
                return None

            # 找哪些分位段的收益高于基准
            above_base = seg[seg > baseline].index.tolist()
            below_base = seg[seg < baseline - 0.05].index.tolist()  # 明显低于基准

            if not above_base:
                return None

            # 判断方向：高分位得高收益 / 低分位得高收益 / 中间得高收益
            decile_vals = s.groupby('_decile')[col].mean()
            above_mean_decile = float(pd.Series(above_base).mean()) if above_base else 5.0

            # 计算高分位段(7-9)均值 vs 低分位段(0-2)均值
            hi_ret = seg[[i for i in range(7, 10) if i in seg.index]].mean() if any(i in seg.index for i in range(7, 10)) else None
            lo_ret = seg[[i for i in range(0, 3) if i in seg.index]].mean() if any(i in seg.index for i in range(0, 3)) else None

            if hi_ret is None or lo_ret is None:
                return None

            # 判断甜区位置
            if hi_ret > baseline and hi_ret > lo_ret + 0.05:
                direction = 'high'
                # 甜区：高于67分位
                sweet_thr = float(s[col].quantile(0.67))
                bad_thr   = float(s[col].quantile(0.33))
                return {
                    'direction': 'high',
                    'sweet_thr': round(sweet_thr, 4),
                    'bad_thr':   round(bad_thr, 4),
                    'hi_ret':    round(float(hi_ret), 3),
                    'lo_ret':    round(float(lo_ret), 3),
                    'baseline':  round(float(baseline), 3),
                }
            elif lo_ret > baseline and lo_ret > hi_ret + 0.05:
                direction = 'low'
                sweet_thr = float(s[col].quantile(0.33))
                bad_thr   = float(s[col].quantile(0.67))
                return {
                    'direction': 'low',
                    'sweet_thr': round(sweet_thr, 4),
                    'bad_thr':   round(bad_thr, 4),
                    'hi_ret':    round(float(lo_ret), 3),
                    'lo_ret':    round(float(hi_ret), 3),
                    'baseline':  round(float(baseline), 3),
                }
            else:
                # 中间甜区：找收益最高的3个分位段的均值
                mid_deciles = sorted(seg.items(), key=lambda x: x[1], reverse=True)[:3]
                mid_vals = [float(decile_vals[d]) for d, _ in mid_deciles if d in decile_vals]
                if not mid_vals:
                    return None
                sweet_lo = round(min(mid_vals), 4)
                sweet_hi = round(max(mid_vals), 4)
                return {
                    'direction': 'mid',
                    'sweet_lo':  sweet_lo,
                    'sweet_hi':  sweet_hi,
                    'hi_ret':    round(float(seg[[d for d, _ in mid_deciles]].mean()), 3),
                    'lo_ret':    round(float(lo_ret), 3),
                    'baseline':  round(float(baseline), 3),
                }

        for col in ['f1_brick_ratio', 'f2_change_pct', 'f3_up', 'f3_down',
                    'f4_close_multi', 'f5_close_short', 'f6_red_count']:
            if col in sub.columns:
                z = _find_zone(col)
                if z:
                    sweet_zones[col] = z

        return sweet_zones

    def _multi_factor_score(self, df: pd.DataFrame, market: str) -> Dict:
        """
        多因子联合打分模型 v2（实证甜区驱动）：

        【设计思路】
        1. 先从历史数据中找出每个因子的"甜区"（哪个区间未来3天收益最高）
        2. 命中甜区得+1，落在差区得-1，中间区间得0
        3. 5个因子最多得+5分，汇总后按得分分组观察收益差异
        4. 明确告诉你：哪个分数段对应"优先选"/"谨慎对待"

        【与旧版区别】
        旧版用"高值方向"做先验假设，但F4/F5过高（追高）反而有害，
        本版直接用数据实证各因子的甜区，更客观准确。
        """
        sub = df[df['market'] == market].copy()
        if len(sub) < 200:
            return {}

        # 1. 实证推导各因子甜区
        sweet_zones = self._derive_factor_sweet_zones(sub)
        if not sweet_zones:
            return {}

        # 2. 逐因子打分
        score_cols   = []
        score_rules  = []  # 用于报告说明

        FACTOR_NAMES = {
            'f1_brick_ratio':    'F1(红绿比)',
            'f2_change_pct':     'F2(涨跌幅)',
            'f3_up':             'F3_up(涨日红柱/涨幅)',
            'f3_down':           'F3_down(跌日红柱/跌幅)',
            'f4_close_multi':    'F4(收盘/多空线)',
            'f5_close_short':    'F5(收盘/短期线)',
            'f6_red_count':      'F6(近6日红柱数)',
        }

        for col, zone in sweet_zones.items():
            sc_col = f'_sc_{col}'
            sub[sc_col] = 0
            fname = FACTOR_NAMES.get(col, col)

            if zone['direction'] == 'high':
                sub.loc[sub[col].notna() & (sub[col] >= zone['sweet_thr']), sc_col] = 1
                sub.loc[sub[col].notna() & (sub[col] <  zone['bad_thr']),   sc_col] = -1
                rule_desc = (f'{fname}: ≥{zone["sweet_thr"]:.3f} 得+1（甜区，3d均值{zone["hi_ret"]:+.2f}%）'
                             f'，<{zone["bad_thr"]:.3f} 得-1（差区，3d均值{zone["lo_ret"]:+.2f}%）')
            elif zone['direction'] == 'low':
                sub.loc[sub[col].notna() & (sub[col] <= zone['sweet_thr']), sc_col] = 1
                sub.loc[sub[col].notna() & (sub[col] >  zone['bad_thr']),   sc_col] = -1
                rule_desc = (f'{fname}: ≤{zone["sweet_thr"]:.3f} 得+1（甜区，3d均值{zone["hi_ret"]:+.2f}%）'
                             f'，>{zone["bad_thr"]:.3f} 得-1（差区，3d均值{zone["lo_ret"]:+.2f}%）')
            else:  # mid
                sub.loc[sub[col].notna() &
                        (sub[col] >= zone['sweet_lo']) &
                        (sub[col] <= zone['sweet_hi']), sc_col] = 1
                rule_desc = (f'{fname}: [{zone["sweet_lo"]:.3f},{zone["sweet_hi"]:.3f}] 得+1（甜区）'
                             f'，3d均值{zone["hi_ret"]:+.2f}% vs 基准{zone["baseline"]:+.2f}%')

            sub[sc_col] = sub[sc_col].fillna(0)
            score_cols.append(sc_col)
            score_rules.append({'col': col, 'fname': fname, 'rule': rule_desc, 'zone': zone})

        if not score_cols:
            return {}

        # 3. 综合得分
        sub['_total_score'] = sub[score_cols].sum(axis=1)
        max_score = len(score_cols)

        # 4. 按得分分三组：高(≥2)/中(0~1)/低(<0)
        SCORE_GROUPS = [
            (f'优先关注 (≥+2)', sub['_total_score'] >= 2),
            (f'正常对待 (0~+1)', (sub['_total_score'] >= 0) & (sub['_total_score'] < 2)),
            (f'谨慎回避 (<0)',   sub['_total_score'] < 0),
        ]
        groups = []
        for label, mask in SCORE_GROUPS:
            g = sub[mask]
            if len(g) < 5:
                continue
            st = group_stats(g, PERIODS)
            st['label'] = label
            groups.append(st)

        # 5. 逐分值统计（用于精细分组报告）
        score_detail = []
        for sc_val in sorted(sub['_total_score'].unique()):
            g = sub[sub['_total_score'] == sc_val]
            if len(g) < 20:
                continue
            st = group_stats(g, [3])
            st['score'] = int(sc_val)
            st['label'] = f'得分={int(sc_val):+d}'
            score_detail.append(st)

        # 6. 得分分布
        score_dist = sub['_total_score'].value_counts().sort_index().to_dict()
        score_dist = {int(k): int(v) for k, v in score_dist.items()}

        return {
            'total':        int(len(sub)),
            'max_score':    max_score,
            'baseline_3d':  round(float(sub['ret_close_3d'].dropna().mean()), 3),
            'score_rules':  score_rules,
            'score_dist':   score_dist,
            'groups':       groups,
            'score_detail': score_detail,
        }

    # ── 双因子联合分析 ─────────────────────────────────────

    def _dual_factor_analysis(self, df: pd.DataFrame, market: str) -> Dict:
        """
        双因子联合分析 v2：
        1. F1（红绿比） × F2（涨跌幅）
        2. F4（close/multi_line） × F5（close/ema10_2）

        改进：细化分箱，使各交叉格子样本更均匀，
        F4×F5 对 ≥1.05 大区间做等频细分。
        """
        sub = df[df['market'] == market].copy()
        if len(sub) < 100:
            return {}

        result = {}

        def _cross_analysis(col1: str, col2: str,
                            bins1, labels1, bins2, labels2,
                            pair_name: str) -> Dict:
            _sub = sub.copy()
            try:
                _sub['_g1'] = pd.cut(_sub[col1], bins=bins1, labels=labels1, right=False)
                _sub['_g2'] = pd.cut(_sub[col2], bins=bins2, labels=labels2, right=False)
            except Exception:
                return {}
            matrix = []
            for l1 in labels1:
                row = {'label1': l1, 'cells': []}
                for l2 in labels2:
                    g = _sub[(_sub['_g1'] == l1) & (_sub['_g2'] == l2)]
                    if len(g) < 5:
                        row['cells'].append({'label2': l2, 'total': len(g),
                                             'mean_3d': None, 'win_rate_3d': None,
                                             'down_rate_3d': None})
                        continue
                    st = group_stats(g, [3])
                    row['cells'].append({
                        'label2':       l2,
                        'total':        int(len(g)),
                        'mean_3d':      st.get('n3_mean_close'),
                        'win_rate_3d':  st.get('n3_win_rate'),
                        'down_rate_3d': st.get('n3_down_rate'),
                        'mean_max_3d':  st.get('n3_mean_max'),
                    })
                matrix.append(row)
            return {'pair': pair_name, 'labels1': labels1, 'labels2': labels2,
                    'matrix': matrix}

        # ── F1 × F2 ──────────────────────────────────────────────
        # F1 分箱：策略门槛0.667起，细化到3.0为止，3.0以上再等频3段
        f1_sub = sub['f1_brick_ratio'].dropna()
        f1_tail = f1_sub[f1_sub >= 3.0]
        if len(f1_tail) > 3000:
            try:
                _, f1_edges = pd.qcut(f1_tail, q=3, retbins=True, duplicates='drop')
                bins_f1  = [0, 0.8, 1.0, 1.5, 3.0] + list(f1_edges[1:])
                lbl_f1   = ['<0.8', '[0.8,1.0)', '[1.0,1.5)', '[1.5,3.0)'] + \
                           [f'[{f1_edges[j]:.1f},{f1_edges[j+1]:.1f})' for j in range(len(f1_edges)-2)] + \
                           [f'≥{f1_edges[-2]:.1f}']
            except Exception:
                bins_f1 = [0, 0.8, 1.0, 1.5, 3.0, 9999]
                lbl_f1  = ['<0.8', '[0.8,1.0)', '[1.0,1.5)', '[1.5,3.0)', '≥3.0']
        else:
            bins_f1 = [0, 0.8, 1.0, 1.5, 3.0, 9999]
            lbl_f1  = ['<0.8', '[0.8,1.0)', '[1.0,1.5)', '[1.5,3.0)', '≥3.0']

        # F2 分箱：细化中间密集区
        bins_f2 = [-99, -1, 0, 1, 2, 3, 5, 99]
        lbl_f2  = ['<-1%', '[-1,0)', '[0,1)', '[1,2)', '[2,3)', '[3,5)', '≥5%']

        result['f1_x_f2'] = _cross_analysis(
            'f1_brick_ratio', 'f2_change_pct',
            bins_f1, lbl_f1, bins_f2, lbl_f2,
            'F1(红绿比) × F2(涨跌幅)',
        )

        # ── F4 × F5 ──────────────────────────────────────────────
        # 对 F4 ≥1.05 做等频3分，对 F5 ≥1.04 做等频3分
        f4_sub  = sub['f4_close_multi'].dropna()
        f4_tail = f4_sub[f4_sub >= 1.05]
        if len(f4_tail) > 3000:
            try:
                _, f4_edges = pd.qcut(f4_tail, q=3, retbins=True, duplicates='drop')
                bins_f4 = [1.00, 1.01, 1.02, 1.03, 1.05] + list(f4_edges[1:])
                lbl_f4  = ['[1.00,1.01)', '[1.01,1.02)', '[1.02,1.03)', '[1.03,1.05)'] + \
                          [f'[{f4_edges[j]:.4f},{f4_edges[j+1]:.4f})' for j in range(len(f4_edges)-2)] + \
                          [f'≥{f4_edges[-2]:.4f}']
            except Exception:
                bins_f4 = [1.00, 1.01, 1.02, 1.03, 1.05, 1.10, np.inf]
                lbl_f4  = ['[1.00,1.01)', '[1.01,1.02)', '[1.02,1.03)',
                           '[1.03,1.05)', '[1.05,1.10)', '≥1.10']
        else:
            bins_f4 = [1.00, 1.01, 1.02, 1.03, 1.05, 1.10, np.inf]
            lbl_f4  = ['[1.00,1.01)', '[1.01,1.02)', '[1.02,1.03)',
                       '[1.03,1.05)', '[1.05,1.10)', '≥1.10']

        f5_sub  = sub['f5_close_short'].dropna()
        f5_tail = f5_sub[f5_sub >= 1.04]
        if len(f5_tail) > 3000:
            try:
                _, f5_edges = pd.qcut(f5_tail, q=3, retbins=True, duplicates='drop')
                bins_f5 = [0.97, 0.99, 1.00, 1.01, 1.02, 1.04] + list(f5_edges[1:])
                lbl_f5  = ['[0.97,0.99)', '[0.99,1.00)', '[1.00,1.01)',
                           '[1.01,1.02)', '[1.02,1.04)'] + \
                          [f'[{f5_edges[j]:.4f},{f5_edges[j+1]:.4f})' for j in range(len(f5_edges)-2)] + \
                          [f'≥{f5_edges[-2]:.4f}']
            except Exception:
                bins_f5 = [0.97, 0.99, 1.00, 1.01, 1.02, 1.04, 1.08, np.inf]
                lbl_f5  = ['[0.97,0.99)', '[0.99,1.00)', '[1.00,1.01)',
                           '[1.01,1.02)', '[1.02,1.04)', '[1.04,1.08)', '≥1.08']
        else:
            bins_f5 = [0.97, 0.99, 1.00, 1.01, 1.02, 1.04, 1.08, np.inf]
            lbl_f5  = ['[0.97,0.99)', '[0.99,1.00)', '[1.00,1.01)',
                       '[1.01,1.02)', '[1.02,1.04)', '[1.04,1.08)', '≥1.08']

        result['f4_x_f5'] = _cross_analysis(
            'f4_close_multi', 'f5_close_short',
            bins_f4, lbl_f4, bins_f5, lbl_f5,
            'F4(收盘/多空线) × F5(收盘/短期线)',
        )

        return result

    # ── 主运行 ────────────────────────────────────────────

    def run(self) -> Dict:
        log_message('=' * 60)
        log_message(f'多因子收益分析 | 策略:{self.strategy}')
        log_message('=' * 60)

        df = self.collect_data()
        if df.empty:
            log_message('数据为空，分析终止', 'ERROR')
            return {}

        # 基础统计
        total = len(df)
        log_message(f'总样本: {total:,}')
        for col in [f'ret_close_{n}d' for n in PERIODS]:
            v = df[col].dropna()
            log_message(f'  {col}: {len(v):,}条有效，均值={v.mean():.3f}%, 中位={v.median():.3f}%')

        result = {
            'meta': {
                'strategy':   self.strategy,
                'brick_ratio': self.brick_ratio,
                'total':      total,
                'analyzed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'periods':    PERIODS,
            },
            'markets': {},
        }

        for mkt in ['A', 'B']:
            sub = df[df['market'] == mkt]
            log_message(f'  市场 {mkt}({MARKET_NAMES[mkt]}): {len(sub):,} 条')
            if len(sub) < 50:
                continue

            result['markets'][mkt] = {
                'market_name': MARKET_NAMES[mkt],
                'total': int(len(sub)),
                'single_factor': self._single_factor_analysis(df, mkt),
                'multi_factor_score': self._multi_factor_score(df, mkt),
                'dual_factor': self._dual_factor_analysis(df, mkt),
            }

        # 保存 JSON
        suffix = ''
        if self.start_date:
            suffix += f'_from{self.start_date}'
        if self.end_date:
            suffix += f'_to{self.end_date}'
        out_json = OUTPUT_PATH / f'multi_factor_return_{self.strategy}{suffix}.json'
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        log_message(f'JSON 已保存: {out_json}')

        # 生成文本报告
        report = self._build_report(result, df)
        out_txt = OUTPUT_PATH / f'multi_factor_return_{self.strategy}{suffix}_report.txt'
        with open(out_txt, 'w', encoding='utf-8') as f:
            f.write(report)
        log_message(f'报告已保存: {out_txt}')
        print(report)

        return result

    # ── 报告生成 ──────────────────────────────────────────

    def _build_report(self, result: Dict, df: pd.DataFrame) -> str:
        meta   = result['meta']
        lines  = []

        def L(s=''):
            lines.append(s)

        # ── 封面 ──────────────────────────────────────────
        L('=' * 80)
        L('  砖型策略多因子收益分析报告')
        L(f'  策略: {meta["strategy"]}  |  brick_ratio ≥ {meta["brick_ratio"]:.3f}')
        L(f'  生成时间: {meta["analyzed_at"]}')
        L('=' * 80)
        L()
        L('【报告目标】')
        L('  在当前选股策略基础上，通过6个因子区分高收益/低风险候选股：')
        L('  F1 砖型红/绿柱比例  |  F2 当日涨跌幅  |  F3_up 涨日红柱/涨幅  |  F3_down 跌日逆势动量')
        L('  F4 收盘价/知行多空线  |  F5 收盘价/知行短期趋势线  |  F6 近6日红柱数量(T-2~T-7)')
        L()
        L('【收益指标说明】')
        L('  · 实际收盘涨跌幅（ret_closeNd）：买入当日收盘，持有N天后收盘卖出的涨跌幅')
        L('  · 最大涨幅（ret_maxNd）：持有N天内最高收盘价 vs 买入当日收盘')
        L('  · 胜率：实际收盘涨跌幅 > 0 的比例')
        L('  · 下跌率：实际收盘涨跌幅 < -1% 的比例（风险指标）')
        L()

        # ── 全局基准 ──────────────────────────────────────
        L('╔' + '═' * 78 + '╗')
        L('║  全局基准收益统计')
        L('╚' + '═' * 78 + '╝')
        for mkt in ['A', 'B']:
            sub = df[df['market'] == mkt]
            if len(sub) < 10:
                continue
            L(f'  【市场 {mkt} — {MARKET_NAMES[mkt]}】  样本: {len(sub):,}')
            L(f'  {"指标":<16}{"未来1天":>10}{"未来2天":>10}{"未来3天":>10}')
            L(f'  {"─"*16}{"─"*10}{"─"*10}{"─"*10}')
            for label, col_tpl in [
                ('均值收盘涨跌幅',  'ret_close_{n}d'),
                ('中位数收盘涨跌', 'ret_close_{n}d'),
                ('均值最大涨幅',   'ret_max_{n}d'),
                ('胜率(%)',       'ret_close_{n}d'),
                ('下跌率(<%−1%)', 'ret_close_{n}d'),
            ]:
                row = f'  {label:<16}'
                for n in PERIODS:
                    col = col_tpl.format(n=n)
                    s = sub[col].dropna()
                    if len(s) == 0:
                        row += f'{"N/A":>10}'
                        continue
                    if label.startswith('均值收盘'):
                        v = s.mean()
                    elif label.startswith('中位数'):
                        v = s.median()
                    elif label.startswith('均值最大'):
                        v = s.mean()
                    elif label.startswith('胜率'):
                        v = (s > 0).mean() * 100
                    else:  # 下跌率
                        v = (s < -1.0).mean() * 100
                    row += f'{v:>9.2f}%'
                L(row)
            L()

        # ── 逐市场单因子分析 ──────────────────────────────
        for mkt, mkt_data in result['markets'].items():
            mkt_name = mkt_data['market_name']
            mkt_total = mkt_data['total']
            L('╔' + '═' * 78 + '╗')
            L(f'║  Part A  单因子分析  —  市场: {mkt_name}')
            L(f'║  样本: {mkt_total:,}')
            L('╚' + '═' * 78 + '╝')
            L()

            sf = mkt_data.get('single_factor', {})
            for col, fdata in sf.items():
                L(f'  ◆ {fdata["name"]}')
                L(f'    {fdata["desc"]}')
                L(f'    有效样本: {fdata["total"]:,}')
                L()
                groups = fdata.get('groups', [])
                if not groups:
                    L('    样本量不足，跳过')
                    L()
                    continue

                # 表头
                W1, W2, W3 = 18, 7, 9
                hdr = (f'  {"区间":<{W1}}'
                       f'{"样本":>{W2}}'
                       f'{"1d均值":>{W3}}'
                       f'{"2d均值":>{W3}}'
                       f'{"3d均值":>{W3}}'
                       f'{"3d最大":>{W3}}'
                       f'{"3d胜率":>{W3}}'
                       f'{"3d跌率":>{W3}}'
                       f'  {"1d评级":<14}'
                       f'{"3d评级":<14}')
                L(hdr)
                L('  ' + '─' * (W1 + W2 + W3 * 6 + 2 + 14 + 14))

                # 取所有有效格的 3d 均值，计算最大绝对值用于 bar
                all_3d = [g['n3_mean_close'] for g in groups if g.get('n3_mean_close') is not None]
                max_abs = max((abs(v) for v in all_3d), default=1.0)

                for g in groups:
                    lbl = g['label']
                    cnt = g['total']
                    v1  = g.get('n1_mean_close')
                    v2  = g.get('n2_mean_close')
                    v3  = g.get('n3_mean_close')
                    vm  = g.get('n3_mean_max')
                    wr  = g.get('n3_win_rate')
                    dr  = g.get('n3_down_rate')

                    fmt = lambda x: f'{x:+.2f}%' if x is not None else '  N/A '
                    fmtp = lambda x: f'{x:.1f}%' if x is not None else 'N/A'
                    tag1 = pct_tag(v1) if v1 is not None else ''
                    tag3 = pct_tag(v3) if v3 is not None else ''
                    L(f'  {lbl:<{W1}}'
                      f'{cnt:>{W2},}'
                      f'{fmt(v1):>{W3}}'
                      f'{fmt(v2):>{W3}}'
                      f'{fmt(v3):>{W3}}'
                      f'{fmt(vm):>{W3}}'
                      f'{fmtp(wr):>{W3}}'
                      f'{fmtp(dr):>{W3}}'
                      f'  {tag1:<14}'
                      f'{tag3:<14}')
                L()

                # 小结：找最优区间
                best = max(groups, key=lambda g: g.get('n3_mean_close') or -99)
                worst = min(groups, key=lambda g: g.get('n3_mean_close') or 99)
                safest = min((g for g in groups if g.get('n3_down_rate') is not None),
                             key=lambda g: g['n3_down_rate'], default=None)
                v3b = best.get('n3_mean_close')
                v3w = worst.get('n3_mean_close')
                L(f'  ► 关键发现：')
                L(f'    · 最优区间：{best["label"]}  3d均值={fmt(v3b)}，胜率={fmtp(best.get("n3_win_rate"))}')
                L(f'    · 最差区间：{worst["label"]}  3d均值={fmt(v3w)}，下跌率={fmtp(worst.get("n3_down_rate"))}')
                if safest:
                    L(f'    · 最低风险区间：{safest["label"]}  下跌率={fmtp(safest.get("n3_down_rate"))}')
                if v3b is not None and v3w is not None and abs(v3w) > 0.01:
                    spread = abs(v3b - v3w)
                    L(f'    · 因子区分能力：最优-最差 3d收益差 = {spread:.2f}%')
                L()

        # ── 多因子联合打分 ──────────────────────────────────
        for mkt, mkt_data in result['markets'].items():
            mkt_name = mkt_data['market_name']
            L('╔' + '═' * 78 + '╗')
            L(f'║  Part B  多因子联合打分模型  —  市场: {mkt_name}')
            L('╚' + '═' * 78 + '╝')
            L()

            ms = mkt_data.get('multi_factor_score', {})
            if not ms:
                L('  样本量不足，跳过')
                L()
                continue

            baseline = ms.get('baseline_3d', 0)
            max_sc   = ms.get('max_score', 5)

            # ── 打分规则说明 ──────────────────────────────────
            L(f'  ┌─ 打分模型说明 {"─"*56}┐')
            L(f'  │  原理：对每只候选股，逐因子判断其当日值落在哪个区间，')
            L(f'  │        落在"甜区"（历史上该区间3d收益高于整体基准）得+1，')
            L(f'  │        落在"差区"（历史上收益明显低于基准）得-1，中间区得0。')
            L(f'  │  满分：{max_sc}分（{max_sc}个因子全部落在甜区）')
            L(f'  │  整体基准3d均值收益：{baseline:+.2f}%')
            L(f'  └{"─"*68}┘')
            L()

            score_rules = ms.get('score_rules', [])
            if score_rules:
                L(f'  【各因子甜区规则（由历史数据实证推导，非先验假设）】')
                for i, sr in enumerate(score_rules, 1):
                    L(f'  {i}. {sr["rule"]}')
                L()
                L(f'  【实际应用方法】')
                L(f'  ① 今日策略发出候选股列表后，对每只股逐一计算6个因子值')
                L(f'  ② 对照上方规则判断每个因子得分（+1 / 0 / -1）')
                L(f'  ③ 合计总分，按以下分组决策：')
                L(f'     · 总分 ≥ +2  →  "优先关注池"（甜区因子过半，历史收益较高）')
                L(f'     · 总分  0~+1  →  "正常对待"（按策略常规持仓判断）')
                L(f'     · 总分  < 0   →  "谨慎回避"（多个因子处于差区，历史亏损较多）')
                L()
                L(f'  【快速打分示例】')
                L(f'  假设某股当日：F1=1.8, F2=+2.5%(涨日), F3_up=1.4, F4=1.03, F5=1.02, F6=4天')
                L(f'  F2>0.2%→取F3_up，F2<-0.2%→取F3_down，对照规则逐一打分后汇总')
                L()

            # ── 得分分布 ──────────────────────────────────────
            sd = ms.get('score_dist', {})
            if sd:
                L(f'  【历史样本得分分布】')
                score_keys = sorted(sd.keys())
                total_n    = sum(sd.values())
                hdr_row = f'  {"得分":>6}' + ''.join(f'{k:>8}' for k in score_keys)
                cnt_row = f'  {"样本数":>6}' + ''.join(f'{sd[k]:>8,}' for k in score_keys)
                pct_row = f'  {"占比":>6}' + ''.join(
                    f'{sd[k]/total_n*100:>7.1f}%' for k in score_keys)
                L(hdr_row)
                L('  ' + '─' * (6 + 8 * len(score_keys)))
                L(cnt_row)
                L(pct_row)
                L()

            # ── 逐分值收益明细 ────────────────────────────────
            score_detail = ms.get('score_detail', [])
            if score_detail:
                L(f'  【逐分值3d收益明细】')
                fmt  = lambda x: f'{x:+.2f}%' if x is not None else '  N/A '
                fmtp = lambda x: f'{x:.1f}%'  if x is not None else 'N/A'
                L(f'  {"得分":<10}{"样本":>7}{"3d均值":>9}{"3d最大":>9}'
                  f'{"3d胜率":>9}{"3d跌率":>9}  {"vs基准":>9}  {"建议":<10}')
                L('  ' + '─' * (10 + 7 + 9 * 4 + 2 + 9 + 2 + 10))
                for sd_item in score_detail:
                    sc    = sd_item.get('score', 0)
                    cnt   = sd_item.get('total', 0)
                    v3    = sd_item.get('n3_mean_close')
                    vm    = sd_item.get('n3_mean_max')
                    wr    = sd_item.get('n3_win_rate')
                    dr    = sd_item.get('n3_down_rate')
                    diff  = (v3 - baseline) if v3 is not None else None
                    if sc >= 2:
                        advice = '优先关注'
                    elif sc >= 0:
                        advice = '正常对待'
                    else:
                        advice = '谨慎回避'
                    diff_s = f'{diff:+.2f}%' if diff is not None else 'N/A'
                    L(f'  {sd_item["label"]:<10}{cnt:>7,}'
                      f'{fmt(v3):>9}{fmt(vm):>9}'
                      f'{fmtp(wr):>9}{fmtp(dr):>9}'
                      f'  {diff_s:>9}  {advice:<10}')
                L()

            # ── 三组汇总 ──────────────────────────────────────
            groups = ms.get('groups', [])
            if groups:
                L(f'  【三组汇总对比】')
                fmt  = lambda x: f'{x:+.2f}%' if x is not None else '  N/A '
                fmtp = lambda x: f'{x:.1f}%'  if x is not None else 'N/A'
                L(f'  {"分组":<18}{"样本":>7}{"1d均值":>9}{"2d均值":>9}{"3d均值":>9}'
                  f'{"3d最大":>9}{"3d胜率":>9}{"3d跌率":>9}  {"3d评级":<14}')
                L('  ' + '─' * (18 + 7 + 9 * 6 + 2 + 14))
                for g in groups:
                    v3 = g.get('n3_mean_close')
                    L(f'  {g["label"]:<18}{g["total"]:>7,}'
                      f'{fmt(g.get("n1_mean_close")):>9}'
                      f'{fmt(g.get("n2_mean_close")):>9}'
                      f'{fmt(v3):>9}'
                      f'{fmt(g.get("n3_mean_max")):>9}'
                      f'{fmtp(g.get("n3_win_rate")):>9}'
                      f'{fmtp(g.get("n3_down_rate")):>9}'
                      f'  {pct_tag(v3) if v3 is not None else "":<14}')
                L()

                # 结论
                pri = next((g for g in groups if '优先' in g['label']), None)
                cau = next((g for g in groups if '谨慎' in g['label']), None)
                nor = next((g for g in groups if '正常' in g['label']), None)
                L(f'  ► 打分模型结论：')
                if pri and cau:
                    p3  = pri.get('n3_mean_close')
                    c3  = cau.get('n3_mean_close')
                    pdr = pri.get('n3_down_rate')
                    cdr = cau.get('n3_down_rate')
                    if p3 is not None and c3 is not None:
                        L(f'    · 优先关注 vs 谨慎回避  3d收益差: {p3-c3:+.2f}%')
                    if pdr is not None and cdr is not None:
                        L(f'    · 优先关注下跌率={pdr:.1f}%，谨慎回避下跌率={cdr:.1f}%，'
                          f'风险降幅={cdr-pdr:.1f}%')
                if nor:
                    n3 = nor.get('n3_mean_close')
                    if n3 is not None:
                        L(f'    · 正常对待组 3d均值收益: {n3:+.2f}%（基准:{baseline:+.2f}%）')
                L()

        # ── 双因子联合分析 ────────────────────────────────
        for mkt, mkt_data in result['markets'].items():
            mkt_name = mkt_data['market_name']
            L('╔' + '═' * 78 + '╗')
            L(f'║  Part C  双因子联合分析  —  市场: {mkt_name}')
            L(f'║  （F1×F2 和 F4×F5 交叉矩阵，未来3天维度）')
            L('╚' + '═' * 78 + '╝')
            L()

            df_data = mkt_data.get('dual_factor', {})
            for pair_key, pdata in df_data.items():
                if not pdata:
                    continue
                L(f'  ◆ {pdata.get("pair", pair_key)}')
                L()
                L(f'  【未来3天均值收盘涨跌幅矩阵】（格子：均值%，括号内为样本数）')
                labels1 = pdata.get('labels1', [])
                labels2 = pdata.get('labels2', [])
                matrix  = pdata.get('matrix', [])

                # 表头（F2/F5 区间）
                hdr_line = f'  {"F1/F4↓ \\ F2/F5→":<18}'
                for l2 in labels2:
                    hdr_line += f'{l2:>14}'
                L(hdr_line)
                L('  ' + '─' * (18 + 14 * len(labels2)))

                for row in matrix:
                    data_line = f'  {row["label1"]:<18}'
                    for cell in row.get('cells', []):
                        v3 = cell.get('mean_3d')
                        cnt = cell.get('total', 0)
                        if v3 is None or cnt < 5:
                            data_line += f'{"--":>14}'
                        else:
                            cell_str = f'{v3:+.2f}%({cnt})'
                            data_line += f'{cell_str:>14}'
                    L(data_line)
                L()

                # 胜率矩阵
                L(f'  【未来3天胜率矩阵】（格子：胜率%）')
                L(hdr_line.replace('均值收盘涨跌幅矩阵', ''))
                L('  ' + '─' * (18 + 14 * len(labels2)))
                for row in matrix:
                    data_line = f'  {row["label1"]:<18}'
                    for cell in row.get('cells', []):
                        wr = cell.get('win_rate_3d')
                        cnt = cell.get('total', 0)
                        if wr is None or cnt < 5:
                            data_line += f'{"--":>14}'
                        else:
                            wr_str = f'{wr:.1f}%'
                            data_line += f'{wr_str:>14}'
                    L(data_line)
                L()

        # ── 综合操作建议 ──────────────────────────────────
        L('╔' + '═' * 78 + '╗')
        L('║  综合操作建议（基于实证数据动态生成）')
        L('╚' + '═' * 78 + '╝')
        L()
        L('  以下建议均来源于本次历史回测结果，非先验假设：')
        L()

        # 从两个市场各取打分规则和分组数据，动态生成建议
        for mkt, mkt_data in result['markets'].items():
            mkt_name = mkt_data['market_name']
            ms = mkt_data.get('multi_factor_score', {})
            if not ms:
                continue

            L(f'  ◆ 市场 {mkt_name}')
            baseline = ms.get('baseline_3d', 0)
            score_rules = ms.get('score_rules', [])

            # 进攻型：列出"high方向"或"mid方向"中收益最高的规则
            attack_rules = []
            defence_rules = []
            for sr in score_rules:
                z = sr.get('zone', {})
                hi_ret   = z.get('hi_ret', 0) or 0
                lo_ret   = z.get('lo_ret', 0) or 0
                fname    = sr['fname']
                rule     = sr['rule']
                if hi_ret > baseline + 0.3:
                    attack_rules.append((hi_ret, fname, rule))
                if lo_ret < baseline - 0.3:
                    defence_rules.append((lo_ret, fname, rule))

            if attack_rules:
                L(f'  【进攻型：优先选高涨幅候选（甜区3d均值显著高于基准{baseline:+.2f}%）】')
                for hi_ret, fname, rule in sorted(attack_rules, reverse=True):
                    L(f'  · {fname}：{rule}')
                L()

            if defence_rules:
                L(f'  【防守型：回避差区可降低下跌风险】')
                for lo_ret, fname, rule in sorted(defence_rules):
                    L(f'  · {fname}：{rule}')
                L()

            # 打分操作流程
            groups = ms.get('groups', [])
            pri = next((g for g in groups if '优先' in g['label']), None)
            cau = next((g for g in groups if '谨慎' in g['label']), None)
            if pri and cau:
                p3  = pri.get('n3_mean_close')
                pdr = pri.get('n3_down_rate')
                c3  = cau.get('n3_mean_close')
                cdr = cau.get('n3_down_rate')
                L(f'  【每日选股操作流程（打分模型应用）】')
                L(f'  ① 策略触发信号后，计算每只候选股的6个因子当日值')
                L(f'  ② 对照"各因子甜区规则"逐一打分（+1/0/-1），汇总总分')
                L(f'  ③ 分层操作：')
                p3_s  = f'{p3:+.2f}%'  if p3  is not None else 'N/A'
                pdr_s = f'{pdr:.1f}%'  if pdr is not None else 'N/A'
                c3_s  = f'{c3:+.2f}%'  if c3  is not None else 'N/A'
                cdr_s = f'{cdr:.1f}%'  if cdr is not None else 'N/A'
                L(f'     · 总分≥+2 → "优先关注池"（历史3d均值{p3_s}，下跌率{pdr_s}）')
                L(f'     · 总分0~+1 → "正常对待"（按常规策略执行）')
                L(f'     · 总分<0   → "谨慎回避"（历史3d均值{c3_s}，下跌率{cdr_s}）')
                L()
            L()
        L('=' * 80)
        L(f'  报告生成完毕 | 总样本: {meta["total"]:,} | {meta["analyzed_at"]}')
        L('=' * 80)

        return '\n'.join(lines)


# ──────────────────────────────────────────────────────────
#  命令行入口
# ──────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description='砖型策略多因子收益分析')
    p.add_argument('--strategy',    default='B1',  help='策略 (默认B1)')
    p.add_argument('--start-date',  default=None,  help='开始日期 YYYYMMDD')
    p.add_argument('--end-date',    default=None,  help='结束日期 YYYYMMDD')
    p.add_argument('--brick-ratio', type=float, default=2.0/3.0,
                   help='红绿比最低门槛（默认0.667）')
    p.add_argument('--test',        type=int, default=None, metavar='N',
                   help='测试模式：只处理前N个交易日')
    return p.parse_args()


if __name__ == '__main__':
    args = parse_args()
    analyzer = MultiFacReturnAnalyzer(
        strategy=args.strategy,
        start_date=args.start_date,
        end_date=args.end_date,
        max_dates=args.test,
        brick_ratio=args.brick_ratio,
    )
    analyzer.run()
