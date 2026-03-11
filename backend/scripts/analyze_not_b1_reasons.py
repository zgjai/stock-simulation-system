"""不符合B1原因分析 - 深度分析导致不符合B1的具体因子"""
import sys
import os
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message


class NotB1ReasonsAnalyzer:
    """不符合B1原因分析器"""
    
    def __init__(self, 
                 processed_path='processed_data',
                 learning_cases_path='learning_cases',
                 index_path='strategy_index',
                 output_path='data/factor_analysis',
                 strategy='B1',
                 period='3d',
                 market_group=None,
                 start_date=None,
                 end_date=None):
        self.processed_path = processed_path
        self.learning_cases_path = learning_cases_path
        self.index_path = index_path
        self.output_path = output_path
        self.strategy = strategy
        self.period = period
        self.market_group = market_group
        self.start_date = start_date
        self.end_date = end_date
        
        ensure_dir(self.output_path)
        
        # 市场分组名称
        self.market_group_names = {
            'A': '主板(00/60)',
            'B': '创业板/科创板/北交所(30/68/92)',
            None: '全市场'
        }
        
        # B1策略条件阈值（已移除量能条件）
        self.b1_thresholds = {
            'j_value': 16,              # J值 ≤ 16
            'amplitude': 7.0,           # 振幅 ≤ 7%
            'change_pct': 2.5,          # 涨跌幅 [-2.5%, 2.5%]
            'open_close_change': 2.5    # 开收幅度 [-2.5%, 2.5%]
            # 注意: 量能条件已从B1策略中移除
        }
        
        # 极致B1阈值配置
        self.extreme_b1_thresholds = {
            'A': {'amplitude': 2.68, 'volume_ratio': 0.59},  # 主板
            'B': {'amplitude': 3.46, 'volume_ratio': 0.42}   # 创业板等
        }
        
        # 性能优化: 缓存股票数据
        self.stock_data_cache = {}
        self.cache_hits = 0
        self.cache_misses = 0
    
    def get_stock_market_group(self, stock_code: str) -> str:
        """获取股票的市场分组"""
        prefix = stock_code[:2]
        if prefix in ['00', '60']:
            return 'A'
        elif prefix in ['30', '68', '92']:
            return 'B'
        else:
            return 'A'
    
    def check_b1_condition(self, row: pd.Series) -> bool:
        """检查是否满足B1策略条件 - 直接使用b1_signal字段"""
        b1_signal = row.get('b1_signal', 0)
        return b1_signal == 1
    
    def check_extreme_b1_condition(self, row: pd.Series, market_group: str, check_b1_first: bool = False) -> bool:
        """检查是否满足极致B1条件"""
        if check_b1_first:
            if not self.check_b1_condition(row):
                return False
        
        amplitude = row.get('factor_amplitude', None)
        volume_ratio = row.get('factor_volume_ratio', None)
        
        if pd.isna(amplitude) or pd.isna(volume_ratio):
            return False
        
        thresholds = self.extreme_b1_thresholds.get(market_group, self.extreme_b1_thresholds['A'])
        return amplitude >= thresholds['amplitude'] and volume_ratio >= thresholds['volume_ratio']
    
    def analyze_not_b1_reasons(self, row: pd.Series) -> Dict:
        """
        分析不符合B1的具体原因
        
        B1策略的4个条件（已移除量能条件）:
        1. J值低位: J ≤ 16
        2. 窄幅波动: 涨跌幅在 [-2.5%, 2.5%]
        3. 振幅温和: 振幅 ≤ 7%
        4. 多头趋势: EMA10_2 > multi_line
        
        Returns:
            {
                'not_b1_by_j': bool,           # 因J值导致不符合
                'not_b1_by_amplitude': bool,   # 因振幅导致不符合
                'not_b1_by_change': bool,      # 因涨跌幅导致不符合
                'j_value': float,
                'amplitude': float,
                'change_pct': float,
                'j_interval': str,             # J值所在区间
                'amplitude_interval': str,     # 振幅所在区间
                'change_interval': str         # 涨跌幅所在区间
            }
        """
        # 获取因子值
        j_value = row.get('kdj_j', np.nan)
        amplitude = row.get('factor_amplitude', np.nan)
        change_pct = row.get('factor_close_change_prev', np.nan)
        open_close_change = row.get('factor_close_change_open', np.nan)
        ema10_2 = row.get('ema10_2', np.nan)
        multi_line = row.get('multi_line', np.nan)
        # 注意: 量能条件已从B1策略中移除，不再判断
        
        # 判断各条件是否符合
        j_pass = not pd.isna(j_value) and j_value <= self.b1_thresholds['j_value']
        amplitude_pass = not pd.isna(amplitude) and amplitude <= self.b1_thresholds['amplitude']
        change_pass = not pd.isna(change_pct) and abs(change_pct) <= self.b1_thresholds['change_pct']
        trend_pass = not pd.isna(ema10_2) and not pd.isna(multi_line) and ema10_2 > multi_line
        
        # 判断不符合的原因 (可能有多个原因)
        not_b1_by_j = not j_pass
        not_b1_by_amplitude = not amplitude_pass
        not_b1_by_change = not change_pass
        not_b1_by_trend = not trend_pass
        
        # 对各因子进行区间划分
        # J值区间
        if pd.isna(j_value):
            j_interval = 'unknown'
        elif j_value <= 16:
            j_interval = 'pass'  # 符合条件
        elif j_value <= 30:
            j_interval = '16-30'  # 轻微超标
        elif j_value <= 50:
            j_interval = '30-50'  # 中度超标
        elif j_value <= 80:
            j_interval = '50-80'  # 高位区
        else:
            j_interval = '>80'    # 超买区
        
        # 振幅区间
        if pd.isna(amplitude):
            amplitude_interval = 'unknown'
        elif amplitude <= 7:
            amplitude_interval = 'pass'  # 符合条件
        elif amplitude <= 9:
            amplitude_interval = '7-9'   # 轻微超标
        elif amplitude <= 12:
            amplitude_interval = '9-12'  # 中度波动
        else:
            amplitude_interval = '>12'   # 高波动
        
        # 涨跌幅区间
        if pd.isna(change_pct):
            change_interval = 'unknown'
        elif abs(change_pct) <= 2.5:
            change_interval = 'pass'     # 符合条件
        elif change_pct < -5:
            change_interval = '<-5'      # 深跌
        elif change_pct < -2.5:
            change_interval = '-5~-2.5'  # 中跌
        elif change_pct > 7:
            change_interval = '>7'       # 大涨
        elif change_pct > 5:
            change_interval = '5-7'      # 中涨
        else:
            change_interval = '2.5-5'    # 小涨
        
        return {
            'not_b1_by_j': not_b1_by_j,
            'not_b1_by_amplitude': not_b1_by_amplitude,
            'not_b1_by_change': not_b1_by_change,
            'not_b1_by_trend': not_b1_by_trend,
            # 注意: 移除了 not_b1_by_volume 字段
            'j_value': float(j_value) if not pd.isna(j_value) else None,
            'amplitude': float(amplitude) if not pd.isna(amplitude) else None,
            'change_pct': float(change_pct) if not pd.isna(change_pct) else None,
            'j_interval': j_interval,
            'amplitude_interval': amplitude_interval,
            'change_interval': change_interval
        }
    
    def get_prev_trading_date(self, date: str, all_dates: List[str]) -> str:
        """获取前一个交易日"""
        try:
            idx = all_dates.index(date)
            if idx > 0:
                return all_dates[idx - 1]
        except ValueError:
            pass
        return None
    
    def load_stock_data(self, stock_code: str) -> pd.DataFrame:
        """加载股票数据 (带缓存优化)"""
        if stock_code in self.stock_data_cache:
            self.cache_hits += 1
            return self.stock_data_cache[stock_code]
        
        self.cache_misses += 1
        csv_file = f'{self.processed_path}/{stock_code}.csv'
        if not os.path.exists(csv_file):
            return None
        
        df = pd.read_csv(csv_file)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
        
        # 缓存数据
        self.stock_data_cache[stock_code] = df
        return df
    
    def collect_not_b1_data(self) -> pd.DataFrame:
        """收集前一日不符合B1的数据，包含具体原因分析"""
        market_name = self.market_group_names.get(self.market_group, '全市场')
        log_message(f"开始收集前一日不符合B1的数据 (周期={self.period}, 市场={market_name})...")
        
        # 获取所有学习案例文件
        cases_dir = f'{self.learning_cases_path}/{self.strategy}'
        if not os.path.exists(cases_dir):
            log_message(f"学习案例目录不存在: {cases_dir}", 'ERROR')
            return pd.DataFrame()
        
        # 获取所有日期
        all_dates = sorted([f.replace('.json', '') for f in os.listdir(cases_dir) if f.endswith('.json')])
        log_message(f"共有 {len(all_dates)} 个交易日")
        
        # 根据时间范围过滤
        if self.start_date or self.end_date:
            filtered_dates = []
            for date in all_dates:
                if self.start_date and date < self.start_date:
                    continue
                if self.end_date and date > self.end_date:
                    continue
                filtered_dates.append(date)
            all_dates = filtered_dates
            log_message(f"时间范围过滤后：{len(all_dates)} 个交易日")
        
        data_list = []
        processed_count = 0
        log_interval = max(1, len(all_dates) // 10)
        
        for date in all_dates:
            # 获取前一个交易日
            prev_date = self.get_prev_trading_date(date, all_dates)
            if not prev_date:
                continue
            
            try:
                # 读取当日学习案例
                with open(f'{cases_dir}/{date}.json', 'r') as f:
                    case_data = json.load(f)
                
                # 获取当日TOP3股票
                top3_stocks = set()
                if 'market_groups' in case_data:
                    if self.market_group is None:
                        for group_key in ['A', 'B']:
                            group_data = case_data['market_groups'].get(group_key, {})
                            for item in group_data.get('top_cases', {}).get(self.period, []):
                                top3_stocks.add(item['stock_code'])
                    else:
                        group_data = case_data['market_groups'].get(self.market_group, {})
                        for item in group_data.get('top_cases', {}).get(self.period, []):
                            top3_stocks.add(item['stock_code'])
                else:
                    for item in case_data.get('top_cases', {}).get(self.period, []):
                        stock_code = item['stock_code']
                        if self.market_group is None or self.get_stock_market_group(stock_code) == self.market_group:
                            top3_stocks.add(stock_code)
                
                # 获取当日候选股票
                index_file = f'{self.index_path}/{self.strategy}/{date}.json'
                if not os.path.exists(index_file):
                    continue
                
                with open(index_file, 'r') as f:
                    index_data = json.load(f)
                
                candidates = index_data.get('stocks', [])
                
                # 根据market_group过滤候选池
                if self.market_group is not None:
                    candidates = [s for s in candidates if self.get_stock_market_group(s) == self.market_group]
                
                # 对每个候选股票提取数据
                for stock in candidates:
                    try:
                        df = self.load_stock_data(stock)
                        if df is None or df.empty:
                            continue
                        
                        # 获取当日数据
                        curr_row = df[df['date'] == date]
                        if curr_row.empty:
                            continue
                        
                        # 获取前一日数据
                        prev_row = df[df['date'] == prev_date]
                        if prev_row.empty:
                            continue
                        
                        curr_data = curr_row.iloc[0]
                        prev_data = prev_row.iloc[0]
                        
                        # 判断股票的市场分组
                        stock_market_group = self.get_stock_market_group(stock)
                        
                        # 判断当日是否满足极致B1
                        curr_is_extreme_b1 = self.check_extreme_b1_condition(curr_data, stock_market_group, check_b1_first=False)
                        
                        # 判断前一日是否符合B1
                        prev_is_b1 = self.check_b1_condition(prev_data)
                        
                        # 只分析: 当日满足极致B1 且 前一日不符合B1 的情况
                        if not curr_is_extreme_b1 or prev_is_b1:
                            continue
                        
                        # 分析前一日不符合B1的具体原因
                        not_b1_reasons = self.analyze_not_b1_reasons(prev_data)
                        
                        # 构建数据记录
                        record = {
                            'date': date,
                            'stock': stock,
                            'market_group': stock_market_group,
                            'is_top3': 1 if stock in top3_stocks else 0,
                            
                            # 前一日因子值
                            'prev_j_value': not_b1_reasons['j_value'],
                            'prev_amplitude': not_b1_reasons['amplitude'],
                            'prev_change_pct': not_b1_reasons['change_pct'],
                            
                            # 不符合原因标记（已移除量能条件）
                            'not_b1_by_j': 1 if not_b1_reasons['not_b1_by_j'] else 0,
                            'not_b1_by_amplitude': 1 if not_b1_reasons['not_b1_by_amplitude'] else 0,
                            'not_b1_by_change': 1 if not_b1_reasons['not_b1_by_change'] else 0,
                            'not_b1_by_trend': 1 if not_b1_reasons['not_b1_by_trend'] else 0,
                            
                            # 区间分类
                            'j_interval': not_b1_reasons['j_interval'],
                            'amplitude_interval': not_b1_reasons['amplitude_interval'],
                            'change_interval': not_b1_reasons['change_interval']
                        }
                        
                        data_list.append(record)
                        
                    except Exception as e:
                        continue
                
                processed_count += 1
                if processed_count % log_interval == 0 or processed_count == len(all_dates):
                    progress = (processed_count / len(all_dates)) * 100
                    log_message(f"进度: {progress:.1f}% ({processed_count}/{len(all_dates)} 个交易日)")
                    
            except Exception as e:
                log_message(f"处理 {date} 失败: {str(e)}", 'ERROR')
                continue
        
        df = pd.DataFrame(data_list)
        
        # 输出缓存统计
        total_requests = self.cache_hits + self.cache_misses
        if total_requests > 0:
            hit_rate = (self.cache_hits / total_requests) * 100
            log_message(f"缓存统计: 命中 {self.cache_hits} 次, 未命中 {self.cache_misses} 次, 命中率 {hit_rate:.1f}%")
        
        log_message(f"收集完成，共 {len(df)} 条记录 (当日极致B1 & 前一日不符合B1)")
        
        return df
    
    def analyze_by_single_reason(self, df: pd.DataFrame) -> Dict:
        """按单一不符合原因分析"""
        log_message(f"\n开始单因素不符合原因分析...")
        
        if len(df) == 0:
            return {'error': '无有效数据'}
        
        # 全局统计
        total_samples = len(df)
        total_top3 = df['is_top3'].sum()
        global_top3_rate = (total_top3 / total_samples) if total_samples > 0 else 0
        
        log_message(f"全局统计: {total_samples}样本, {total_top3}个TOP3, 占比{global_top3_rate:.4f}")
        
        results = {}
        
        # 1. 按J值不符合分析 (含区间细分)
        not_j_df = df[df['not_b1_by_j'] == 1]
        if len(not_j_df) > 0:
            results['by_j_value'] = {
                'total_samples': len(not_j_df),
                'top3_count': int(not_j_df['is_top3'].sum()),
                'top3_rate': float(not_j_df['is_top3'].sum() / len(not_j_df)),
                'sample_ratio': float(len(not_j_df) / total_samples),
                'coverage': float(not_j_df['is_top3'].sum() / total_top3) if total_top3 > 0 else 0,
                'improvement': float((not_j_df['is_top3'].sum() / len(not_j_df)) / global_top3_rate) if global_top3_rate > 0 else 0,
                'intervals': {}
            }
            
            # J值区间细分
            for interval in ['16-30', '30-50', '50-80', '>80']:
                interval_df = not_j_df[not_j_df['j_interval'] == interval]
                if len(interval_df) > 0:
                    results['by_j_value']['intervals'][interval] = {
                        'samples': len(interval_df),
                        'top3_count': int(interval_df['is_top3'].sum()),
                        'top3_rate': float(interval_df['is_top3'].sum() / len(interval_df)),
                        'sample_ratio': float(len(interval_df) / len(not_j_df)),
                        'improvement': float((interval_df['is_top3'].sum() / len(interval_df)) / global_top3_rate) if global_top3_rate > 0 else 0
                    }
        
        # 2. 按振幅不符合分析 (含区间细分)
        not_amp_df = df[df['not_b1_by_amplitude'] == 1]
        if len(not_amp_df) > 0:
            results['by_amplitude'] = {
                'total_samples': len(not_amp_df),
                'top3_count': int(not_amp_df['is_top3'].sum()),
                'top3_rate': float(not_amp_df['is_top3'].sum() / len(not_amp_df)),
                'sample_ratio': float(len(not_amp_df) / total_samples),
                'coverage': float(not_amp_df['is_top3'].sum() / total_top3) if total_top3 > 0 else 0,
                'improvement': float((not_amp_df['is_top3'].sum() / len(not_amp_df)) / global_top3_rate) if global_top3_rate > 0 else 0,
                'intervals': {}
            }
            
            # 振幅区间细分
            for interval in ['7-9', '9-12', '>12']:
                interval_df = not_amp_df[not_amp_df['amplitude_interval'] == interval]
                if len(interval_df) > 0:
                    results['by_amplitude']['intervals'][interval] = {
                        'samples': len(interval_df),
                        'top3_count': int(interval_df['is_top3'].sum()),
                        'top3_rate': float(interval_df['is_top3'].sum() / len(interval_df)),
                        'sample_ratio': float(len(interval_df) / len(not_amp_df)),
                        'improvement': float((interval_df['is_top3'].sum() / len(interval_df)) / global_top3_rate) if global_top3_rate > 0 else 0
                    }
        
        # 3. 按涨跌幅不符合分析 (含区间细分)
        not_change_df = df[df['not_b1_by_change'] == 1]
        if len(not_change_df) > 0:
            results['by_change'] = {
                'total_samples': len(not_change_df),
                'top3_count': int(not_change_df['is_top3'].sum()),
                'top3_rate': float(not_change_df['is_top3'].sum() / len(not_change_df)),
                'sample_ratio': float(len(not_change_df) / total_samples),
                'coverage': float(not_change_df['is_top3'].sum() / total_top3) if total_top3 > 0 else 0,
                'improvement': float((not_change_df['is_top3'].sum() / len(not_change_df)) / global_top3_rate) if global_top3_rate > 0 else 0,
                'intervals': {}
            }
            
            # 涨跌幅区间细分
            for interval in ['<-5', '-5~-2.5', '2.5-5', '5-7', '>7']:
                interval_df = not_change_df[not_change_df['change_interval'] == interval]
                if len(interval_df) > 0:
                    results['by_change']['intervals'][interval] = {
                        'samples': len(interval_df),
                        'top3_count': int(interval_df['is_top3'].sum()),
                        'top3_rate': float(interval_df['is_top3'].sum() / len(interval_df)),
                        'sample_ratio': float(len(interval_df) / len(not_change_df)),
                        'improvement': float((interval_df['is_top3'].sum() / len(interval_df)) / global_top3_rate) if global_top3_rate > 0 else 0
                    }
        
        # 4. 按趋势不符合分析
        not_trend_df = df[df['not_b1_by_trend'] == 1]
        if len(not_trend_df) > 0:
            results['by_trend'] = {
                'total_samples': len(not_trend_df),
                'top3_count': int(not_trend_df['is_top3'].sum()),
                'top3_rate': float(not_trend_df['is_top3'].sum() / len(not_trend_df)),
                'sample_ratio': float(len(not_trend_df) / total_samples),
                'coverage': float(not_trend_df['is_top3'].sum() / total_top3) if total_top3 > 0 else 0,
                'improvement': float((not_trend_df['is_top3'].sum() / len(not_trend_df)) / global_top3_rate) if global_top3_rate > 0 else 0
            }
        
        # 注意: 量能条件已从B1策略中移除，不再分析
        
        return {
            'global_stats': {
                'total_samples': int(total_samples),
                'total_top3': int(total_top3),
                'global_top3_rate': float(global_top3_rate)
            },
            'reasons': results
        }
    
    def analyze(self):
        """执行不符合B1原因分析"""
        log_message(f"\n{'='*90}")
        log_message(f"不符合B1原因深度分析")
        log_message(f"{'='*90}")
        start_time = datetime.now()
        
        # 收集数据
        df = self.collect_not_b1_data()
        
        if df.empty:
            log_message("没有可用数据", 'ERROR')
            return
        
        log_message(f"\n数据规模: {len(df)} 条记录 (当日极致B1 & 前一日不符合B1)")
        log_message(f"TOP3样本数: {df['is_top3'].sum()} 条")
        
        # 分析不符合原因
        result = self.analyze_by_single_reason(df)
        
        if 'error' in result:
            log_message(f"分析失败: {result['error']}", 'ERROR')
            return
        
        # 保存结果
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        
        output_file = f'{self.output_path}/not_b1_reasons_{self.strategy}_{self.period}{market_suffix}{date_suffix}.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'strategy': self.strategy,
                'period': self.period,
                'market_group': self.market_group,
                'market_name': self.market_group_names.get(self.market_group, '全市场'),
                'start_date': self.start_date,
                'end_date': self.end_date,
                'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_samples': len(df),
                'top3_samples': int(df['is_top3'].sum()),
                'result': result
            }, f, ensure_ascii=False, indent=2)
        
        log_message(f"\n分析结果已保存到: {output_file}")
        
        # 生成可读报告
        self.generate_report(result, df)
        
        # 统计耗时
        elapsed = (datetime.now() - start_time).total_seconds()
        log_message(f"\n分析完成，耗时 {elapsed:.1f}秒")
    
    def generate_report(self, result: Dict, df: pd.DataFrame):
        """生成可读的分析报告"""
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        market_name = self.market_group_names.get(self.market_group, '全市场')
        
        report_file = f'{self.output_path}/not_b1_reasons_report_{self.strategy}_{self.period}{market_suffix}{date_suffix}.txt'
        
        global_stats = result['global_stats']
        reasons = result['reasons']
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*90 + "\n")
            f.write(f"不符合B1原因深度分析报告\n")
            f.write("="*90 + "\n")
            f.write(f"策略: {self.strategy}\n")
            f.write(f"周期: {self.period}\n")
            f.write(f"市场分组: {market_name}\n")
            if self.start_date or self.end_date:
                f.write(f"时间范围: {self.start_date or '开始'} ~ {self.end_date or '现在'}\n")
            f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*90 + "\n\n")
            
            f.write(f"分析说明:\n")
            f.write(f"  本分析针对「当日满足极致B1 & 前一日不符合B1」的股票\n")
            f.write(f"  深度分析导致前一日不符合B1的具体原因,以发现更细致的规律\n\n")
            
            f.write(f"B1策略的4个条件（已移除量能条件）:\n")
            f.write(f"  1. J值低位: J ≤ 16\n")
            f.write(f"  2. 窄幅波动: 涨跌幅在 [-2.5%, 2.5%]\n")
            f.write(f"  3. 振幅温和: 振幅 ≤ 7%\n")
            f.write(f"  4. 多头趋势: EMA10_2 > multi_line\n\n")
            
            f.write(f"全局统计 (当日极致B1 & 前一日不符合B1):\n")
            f.write(f"  总样本数: {global_stats['total_samples']}\n")
            f.write(f"  TOP3数量: {global_stats['total_top3']}\n")
            f.write(f"  基准TOP3占比: {global_stats['global_top3_rate']*100:.2f}%\n")
            f.write("="*90 + "\n\n")
            
            # 按原因分类展示
            reason_names = {
                'by_j_value': '因J值导致不符合B1',
                'by_amplitude': '因振幅导致不符合B1',
                'by_change': '因涨跌幅导致不符合B1',
                'by_trend': '因趋势导致不符合B1'
                # 注意: 已移除 'by_volume' 量能条件
            }
            
            for reason_key, reason_name in reason_names.items():
                if reason_key not in reasons:
                    continue
                
                reason_data = reasons[reason_key]
                
                f.write(f"{'='*90}\n")
                f.write(f"【{reason_name}】\n")
                f.write(f"{'='*90}\n\n")
                
                f.write(f"整体统计:\n")
                f.write(f"  样本数: {reason_data['total_samples']}\n")
                f.write(f"  占比: {reason_data['sample_ratio']*100:.1f}% (占所有不符合B1样本)\n")
                f.write(f"  TOP3数量: {reason_data['top3_count']}\n")
                f.write(f"  TOP3占比: {reason_data['top3_rate']*100:.2f}%\n")
                f.write(f"  提升倍数: {reason_data['improvement']:.2f}x\n")
                
                # 评估结论
                if reason_data['improvement'] > 1.1:
                    verdict = "✅ 正向影响 - 建议重点关注"
                elif reason_data['improvement'] > 0.95:
                    verdict = "➖ 中性影响 - 无显著差异"
                else:
                    verdict = "⚠️  负向影响 - 建议规避"
                f.write(f"  结论: {verdict}\n\n")
                
                # 如果有区间细分,展示区间分析
                if 'intervals' in reason_data and reason_data['intervals']:
                    f.write(f"区间细分分析:\n")
                    f.write(f"-" * 90 + "\n")
                    
                    # 按提升倍数排序
                    sorted_intervals = sorted(
                        reason_data['intervals'].items(),
                        key=lambda x: x[1]['improvement'],
                        reverse=True
                    )
                    
                    for interval_name, interval_data in sorted_intervals:
                        f.write(f"\n  [{interval_name}]\n")
                        f.write(f"    样本数: {interval_data['samples']} ({interval_data['sample_ratio']*100:.1f}%)\n")
                        f.write(f"    TOP3占比: {interval_data['top3_rate']*100:.2f}%\n")
                        f.write(f"    提升倍数: {interval_data['improvement']:.2f}x\n")
                        
                        if interval_data['improvement'] > 1.1:
                            interval_verdict = "✅ 优秀"
                        elif interval_data['improvement'] > 0.95:
                            interval_verdict = "➖ 一般"
                        else:
                            interval_verdict = "⚠️  较差"
                        f.write(f"    评价: {interval_verdict}\n")
                    
                    f.write(f"\n")
                
                f.write(f"\n")
            
            # 策略建议
            f.write(f"{'='*90}\n")
            f.write(f"💡 策略建议\n")
            f.write(f"{'='*90}\n\n")
            
            # 找出提升最大的原因
            best_reasons = []
            for reason_key, reason_data in reasons.items():
                if reason_data['improvement'] > 1.1:
                    best_reasons.append((reason_names[reason_key], reason_data))
            
            if best_reasons:
                f.write(f"发现以下不符合B1的原因具有正向影响:\n\n")
                for reason_name, reason_data in best_reasons:
                    f.write(f"• {reason_name}\n")
                    f.write(f"  TOP3占比: {reason_data['top3_rate']*100:.2f}%\n")
                    f.write(f"  提升倍数: {reason_data['improvement']:.2f}x\n")
                    
                    # 如果有区间,推荐最佳区间
                    if 'intervals' in reason_data and reason_data['intervals']:
                        best_interval = max(reason_data['intervals'].items(), key=lambda x: x[1]['improvement'])
                        f.write(f"  最佳区间: {best_interval[0]} (提升{best_interval[1]['improvement']:.2f}x)\n")
                    f.write(f"\n")
                
                f.write(f"建议策略: 在极致B1基础上,增加前一日状态筛选\n")
                f.write(f"  当日: 满足极致B1\n")
                f.write(f"  前一日: {' 或 '.join([r[0] for r in best_reasons])}\n\n")
            else:
                f.write(f"未发现显著的正向影响因素\n")
                f.write(f"建议继续使用极致B1策略,或从其他维度优化\n\n")
            
            # 注意事项
            f.write(f"注意事项:\n")
            f.write(f"  1. 前一日条件可能会进一步缩小候选池,需要平衡精准度和覆盖率\n")
            f.write(f"  2. 建议在回测系统中验证这些发现的实际收益\n")
            f.write(f"  3. 市场特征会变化,建议定期(如每月)重新分析\n")
            f.write(f"  4. 可以考虑将多个因素组合使用,而非单一因素\n\n")
        
        log_message(f"分析报告已保存到: {report_file}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='不符合B1原因深度分析')
    parser.add_argument('--strategy', type=str, default='B1', help='策略名称 (B1/B2/single_needle)')
    parser.add_argument('--period', type=str, default='3d', help='周期 (3d/5d/10d)')
    parser.add_argument('--market-group', type=str, default=None, choices=[None, 'A', 'B'], 
                       help='市场分组 (A=主板00/60, B=创业板/科创板/北交所30/68/92, None=全市场)')
    parser.add_argument('--start-date', type=str, default=None, 
                       help='开始日期 (格式: YYYYMMDD，如: 20240901)')
    parser.add_argument('--end-date', type=str, default=None, 
                       help='结束日期 (格式: YYYYMMDD，如: 20250129)')
    
    args = parser.parse_args()
    
    analyzer = NotB1ReasonsAnalyzer(
        strategy=args.strategy,
        period=args.period,
        market_group=args.market_group,
        start_date=args.start_date,
        end_date=args.end_date
    )
    
    market_name = analyzer.market_group_names.get(args.market_group, '全市场')
    date_range_info = ""
    if args.start_date or args.end_date:
        date_range_info = f", 时间范围={args.start_date or '开始'}~{args.end_date or '现在'}"
    
    print(f"\n{'='*90}")
    print(f"不符合B1原因深度分析")
    print(f"{'='*90}")
    print(f"配置:")
    print(f"  策略: {args.strategy}")
    print(f"  周期: {args.period}")
    print(f"  市场: {market_name}{date_range_info}")
    print(f"{'='*90}\n")
    
    analyzer.analyze()


if __name__ == '__main__':
    main()
