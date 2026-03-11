"""不符合B1组合原因分析 - 分析单一不符合和多因素组合不符合的影响"""
import sys
import os
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Set

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message


class NotB1CombinationAnalyzer:
    """不符合B1组合原因分析器"""
    
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
            'j_value': 16,
            'amplitude': 7.0,
            'change_pct': 2.5,
            'open_close_change': 2.5
            # 注意: 量能条件已从B1策略中移除
        }
        
        # 极致B1阈值配置
        self.extreme_b1_thresholds = {
            'A': {'amplitude': 2.68, 'volume_ratio': 0.59},
            'B': {'amplitude': 3.46, 'volume_ratio': 0.42}
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
        """检查是否满足B1策略条件"""
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
    
    def check_individual_conditions(self, row: pd.Series) -> Dict[str, bool]:
        """
        检查B1策略的各个条件是否满足（已移除量能条件）
        
        Returns:
            {
                'j_pass': bool,
                'amplitude_pass': bool,
                'change_pass': bool,
                'trend_pass': bool
            }
        """
        # 获取因子值
        j_value = row.get('kdj_j', np.nan)
        amplitude = row.get('factor_amplitude', np.nan)
        change_pct = row.get('factor_close_change_prev', np.nan)
        ema10_2 = row.get('ema10_2', np.nan)
        multi_line = row.get('multi_line', np.nan)
        # 注意: 量能条件已从B1策略中移除
        
        # 判断各条件是否符合
        j_pass = not pd.isna(j_value) and j_value <= self.b1_thresholds['j_value']
        amplitude_pass = not pd.isna(amplitude) and amplitude <= self.b1_thresholds['amplitude']
        change_pass = not pd.isna(change_pct) and abs(change_pct) <= self.b1_thresholds['change_pct']
        trend_pass = not pd.isna(ema10_2) and not pd.isna(multi_line) and ema10_2 > multi_line
        
        return {
            'j_pass': j_pass,
            'amplitude_pass': amplitude_pass,
            'change_pass': change_pass,
            'trend_pass': trend_pass
        }
    
    def analyze_not_b1_combination(self, row: pd.Series) -> Dict:
        """
        分析不符合B1的条件组合（已移除量能条件）
        
        Returns:
            {
                'not_pass_count': int,  # 不符合的条件数量
                'not_pass_set': set,    # 不符合的条件集合 {'j', 'amplitude', 'change', 'trend'}
                'combination_key': str,  # 组合键，如 'j+amplitude' 或 'only_j'
                'is_single': bool,       # 是否仅单一条件不符合
            }
        """
        conditions = self.check_individual_conditions(row)
        
        # 找出不符合的条件（已移除量能条件）
        not_pass_list = []
        if not conditions['j_pass']:
            not_pass_list.append('j')
        if not conditions['amplitude_pass']:
            not_pass_list.append('amplitude')
        if not conditions['change_pass']:
            not_pass_list.append('change')
        if not conditions['trend_pass']:
            not_pass_list.append('trend')
        
        not_pass_set = set(not_pass_list)
        not_pass_count = len(not_pass_set)
        
        # 生成组合键
        if not_pass_count == 0:
            combination_key = 'all_pass'  # 理论上不会出现
        elif not_pass_count == 1:
            combination_key = f'only_{not_pass_list[0]}'
        else:
            # 多条件不符合，按字母顺序排序
            sorted_list = sorted(not_pass_list)
            combination_key = '+'.join(sorted_list)
        
        return {
            'not_pass_count': not_pass_count,
            'not_pass_set': not_pass_set,
            'combination_key': combination_key,
            'is_single': not_pass_count == 1,
            'conditions': conditions
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
    
    def collect_combination_data(self) -> pd.DataFrame:
        """收集包含条件组合信息的数据"""
        market_name = self.market_group_names.get(self.market_group, '全市场')
        log_message(f"开始收集不符合B1条件组合数据 (周期={self.period}, 市场={market_name})...")
        
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
                        
                        # 分析前一日不符合B1的条件组合
                        combination_info = self.analyze_not_b1_combination(prev_data)
                        
                        # 构建数据记录
                        record = {
                            'date': date,
                            'stock': stock,
                            'market_group': stock_market_group,
                            'is_top3': 1 if stock in top3_stocks else 0,
                            
                            # 组合信息
                            'not_pass_count': combination_info['not_pass_count'],
                            'combination_key': combination_info['combination_key'],
                            'is_single': 1 if combination_info['is_single'] else 0,
                            
                            # 各条件是否通过（已移除量能条件）
                            'j_pass': 1 if combination_info['conditions']['j_pass'] else 0,
                            'amplitude_pass': 1 if combination_info['conditions']['amplitude_pass'] else 0,
                            'change_pass': 1 if combination_info['conditions']['change_pass'] else 0,
                            'trend_pass': 1 if combination_info['conditions']['trend_pass'] else 0,
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
        
        log_message(f"收集完成，共 {len(df)} 条记录")
        
        return df
    
    def analyze_combinations(self, df: pd.DataFrame) -> Dict:
        """分析条件组合的影响"""
        log_message(f"\n开始条件组合分析...")
        
        if len(df) == 0:
            return {'error': '无有效数据'}
        
        # 全局统计
        total_samples = len(df)
        total_top3 = df['is_top3'].sum()
        global_top3_rate = (total_top3 / total_samples) if total_samples > 0 else 0
        
        log_message(f"全局统计: {total_samples}样本, {total_top3}个TOP3, 占比{global_top3_rate:.4f}")
        
        results = {
            'single_conditions': {},  # 仅单一条件不符合
            'combinations': {},       # 多条件组合不符合
            'by_count': {}            # 按不符合数量分组
        }
        
        # 1. 按不符合条件数量分组（最多4个条件，已移除量能条件）
        for count in range(1, 5):
            count_df = df[df['not_pass_count'] == count]
            if len(count_df) > 0:
                results['by_count'][f'{count}_conditions'] = {
                    'samples': len(count_df),
                    'top3_count': int(count_df['is_top3'].sum()),
                    'top3_rate': float(count_df['is_top3'].sum() / len(count_df)),
                    'sample_ratio': float(len(count_df) / total_samples),
                    'improvement': float((count_df['is_top3'].sum() / len(count_df)) / global_top3_rate) if global_top3_rate > 0 else 0
                }
        
        # 2. 仅单一条件不符合的分析
        single_df = df[df['is_single'] == 1]
        if len(single_df) > 0:
            log_message(f"仅单一条件不符合: {len(single_df)}样本")
            
            for condition in ['j', 'amplitude', 'change', 'trend']:
                comb_key = f'only_{condition}'
                comb_df = df[df['combination_key'] == comb_key]
                
                if len(comb_df) > 0:
                    results['single_conditions'][comb_key] = {
                        'condition_name': condition,
                        'samples': len(comb_df),
                        'top3_count': int(comb_df['is_top3'].sum()),
                        'top3_rate': float(comb_df['is_top3'].sum() / len(comb_df)),
                        'sample_ratio': float(len(comb_df) / total_samples),
                        'single_ratio': float(len(comb_df) / len(single_df)),
                        'improvement': float((comb_df['is_top3'].sum() / len(comb_df)) / global_top3_rate) if global_top3_rate > 0 else 0
                    }
        
        # 3. 多条件组合分析（统计频率最高的组合）
        multi_df = df[df['is_single'] == 0]
        if len(multi_df) > 0:
            log_message(f"多条件组合不符合: {len(multi_df)}样本")
            
            # 统计所有组合
            combination_counts = multi_df['combination_key'].value_counts()
            
            # 只分析样本数 >= 100 的组合
            for comb_key, count in combination_counts.items():
                if count >= 100:
                    comb_df = df[df['combination_key'] == comb_key]
                    
                    results['combinations'][comb_key] = {
                        'conditions': comb_key.split('+'),
                        'samples': len(comb_df),
                        'top3_count': int(comb_df['is_top3'].sum()),
                        'top3_rate': float(comb_df['is_top3'].sum() / len(comb_df)),
                        'sample_ratio': float(len(comb_df) / total_samples),
                        'improvement': float((comb_df['is_top3'].sum() / len(comb_df)) / global_top3_rate) if global_top3_rate > 0 else 0
                    }
        
        return {
            'global_stats': {
                'total_samples': int(total_samples),
                'total_top3': int(total_top3),
                'global_top3_rate': float(global_top3_rate),
                'single_samples': int(len(single_df)) if len(single_df) > 0 else 0,
                'multi_samples': int(len(multi_df)) if len(multi_df) > 0 else 0
            },
            'analysis': results
        }
    
    def analyze(self):
        """执行组合原因分析"""
        log_message(f"\n{'='*90}")
        log_message(f"不符合B1条件组合分析")
        log_message(f"{'='*90}")
        start_time = datetime.now()
        
        # 收集数据
        df = self.collect_combination_data()
        
        if df.empty:
            log_message("没有可用数据", 'ERROR')
            return
        
        log_message(f"\n数据规模: {len(df)} 条记录")
        log_message(f"TOP3样本数: {df['is_top3'].sum()} 条")
        
        # 分析组合
        result = self.analyze_combinations(df)
        
        if 'error' in result:
            log_message(f"分析失败: {result['error']}", 'ERROR')
            return
        
        # 保存结果
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        
        output_file = f'{self.output_path}/not_b1_combination_{self.strategy}_{self.period}{market_suffix}{date_suffix}.json'
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
        
        report_file = f'{self.output_path}/not_b1_combination_report_{self.strategy}_{self.period}{market_suffix}{date_suffix}.txt'
        
        global_stats = result['global_stats']
        analysis = result['analysis']
        
        condition_display_names = {
            'j': 'J值',
            'amplitude': '振幅',
            'change': '涨跌幅',
            'trend': '趋势'
            # 注意: 已移除 'volume': '量能'
        }
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*90 + "\n")
            f.write(f"不符合B1条件组合分析报告\n")
            f.write("="*90 + "\n")
            f.write(f"策略: {self.strategy}\n")
            f.write(f"周期: {self.period}\n")
            f.write(f"市场分组: {market_name}\n")
            if self.start_date or self.end_date:
                f.write(f"时间范围: {self.start_date or '开始'} ~ {self.end_date or '现在'}\n")
            f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*90 + "\n\n")
            
            f.write(f"分析说明:\n")
            f.write(f"  本分析深入研究前一日不符合B1的条件组合特征\n")
            f.write(f"  区分「仅单一条件不符合」和「多条件组合不符合」的影响差异\n\n")
            
            f.write(f"全局统计:\n")
            f.write(f"  总样本数: {global_stats['total_samples']}\n")
            f.write(f"  TOP3数量: {global_stats['total_top3']}\n")
            f.write(f"  基准TOP3占比: {global_stats['global_top3_rate']*100:.2f}%\n")
            f.write(f"  仅单一条件不符合: {global_stats['single_samples']} ({global_stats['single_samples']/global_stats['total_samples']*100:.1f}%)\n")
            f.write(f"  多条件组合不符合: {global_stats['multi_samples']} ({global_stats['multi_samples']/global_stats['total_samples']*100:.1f}%)\n")
            f.write("="*90 + "\n\n")
            
            # 1. 按不符合条件数量分析
            f.write(f"{'='*90}\n")
            f.write(f"【第一部分】按不符合条件数量分析\n")
            f.write(f"{'='*90}\n\n")
            
            if 'by_count' in analysis and analysis['by_count']:
                sorted_by_count = sorted(
                    analysis['by_count'].items(),
                    key=lambda x: x[1]['improvement'],
                    reverse=True
                )
                
                for count_key, count_data in sorted_by_count:
                    count_num = count_key.split('_')[0]
                    f.write(f"不符合 {count_num} 个条件:\n")
                    f.write(f"  样本数: {count_data['samples']} ({count_data['sample_ratio']*100:.1f}%)\n")
                    f.write(f"  TOP3数量: {count_data['top3_count']}\n")
                    f.write(f"  TOP3占比: {count_data['top3_rate']*100:.2f}%\n")
                    f.write(f"  提升倍数: {count_data['improvement']:.2f}x\n")
                    
                    if count_data['improvement'] > 1.1:
                        verdict = "✅ 正向影响"
                    elif count_data['improvement'] > 0.95:
                        verdict = "➖ 中性影响"
                    else:
                        verdict = "⚠️  负向影响"
                    f.write(f"  评价: {verdict}\n\n")
            
            # 2. 仅单一条件不符合分析
            f.write(f"{'='*90}\n")
            f.write(f"【第二部分】仅单一条件不符合分析\n")
            f.write(f"{'='*90}\n\n")
            
            if 'single_conditions' in analysis and analysis['single_conditions']:
                f.write(f"说明: 前一日仅因某一个条件不符合B1，其他4个条件都符合\n\n")
                
                # 按提升倍数排序
                sorted_single = sorted(
                    analysis['single_conditions'].items(),
                    key=lambda x: x[1]['improvement'],
                    reverse=True
                )
                
                for i, (comb_key, comb_data) in enumerate(sorted_single, 1):
                    condition_name = condition_display_names.get(comb_data['condition_name'], comb_data['condition_name'])
                    
                    f.write(f"[{i}] 仅{condition_name}不符合\n")
                    f.write(f"-" * 90 + "\n")
                    f.write(f"  样本数: {comb_data['samples']} (占全部样本{comb_data['sample_ratio']*100:.1f}%, 占单一不符合{comb_data['single_ratio']*100:.1f}%)\n")
                    f.write(f"  TOP3数量: {comb_data['top3_count']}\n")
                    f.write(f"  TOP3占比: {comb_data['top3_rate']*100:.2f}%\n")
                    f.write(f"  提升倍数: {comb_data['improvement']:.2f}x\n")
                    
                    if comb_data['improvement'] > 1.1:
                        verdict = "✅ 正向影响 - 建议重点关注"
                    elif comb_data['improvement'] > 0.95:
                        verdict = "➖ 中性影响 - 无显著差异"
                    else:
                        verdict = "⚠️  负向影响 - 建议规避"
                    f.write(f"  评价: {verdict}\n\n")
            
            # 3. 多条件组合分析
            f.write(f"{'='*90}\n")
            f.write(f"【第三部分】多条件组合不符合分析 (样本数≥100)\n")
            f.write(f"{'='*90}\n\n")
            
            if 'combinations' in analysis and analysis['combinations']:
                f.write(f"说明: 前一日同时有多个条件不符合B1\n\n")
                
                # 按提升倍数排序
                sorted_combs = sorted(
                    analysis['combinations'].items(),
                    key=lambda x: x[1]['improvement'],
                    reverse=True
                )
                
                for i, (comb_key, comb_data) in enumerate(sorted_combs, 1):
                    conditions_display = [condition_display_names.get(c, c) for c in comb_data['conditions']]
                    
                    f.write(f"[{i}] {' + '.join(conditions_display)} 组合不符合\n")
                    f.write(f"-" * 90 + "\n")
                    f.write(f"  样本数: {comb_data['samples']} ({comb_data['sample_ratio']*100:.1f}%)\n")
                    f.write(f"  TOP3数量: {comb_data['top3_count']}\n")
                    f.write(f"  TOP3占比: {comb_data['top3_rate']*100:.2f}%\n")
                    f.write(f"  提升倍数: {comb_data['improvement']:.2f}x\n")
                    
                    if comb_data['improvement'] > 1.1:
                        verdict = "✅ 正向影响"
                    elif comb_data['improvement'] > 0.95:
                        verdict = "➖ 中性影响"
                    else:
                        verdict = "⚠️  负向影响"
                    f.write(f"  评价: {verdict}\n\n")
            
            # 4. 对比分析
            f.write(f"{'='*90}\n")
            f.write(f"📊 核心对比\n")
            f.write(f"{'='*90}\n\n")
            
            f.write(f"单一 vs 多条件不符合:\n")
            single_samples = global_stats['single_samples']
            multi_samples = global_stats['multi_samples']
            
            if single_samples > 0 and 'single_conditions' in analysis:
                single_top3_total = sum(d['top3_count'] for d in analysis['single_conditions'].values())
                single_top3_rate = single_top3_total / single_samples if single_samples > 0 else 0
                f.write(f"  仅单一条件不符合: TOP3占比 {single_top3_rate*100:.2f}% (样本{single_samples})\n")
            
            if multi_samples > 0 and 'combinations' in analysis:
                multi_top3_total = sum(d['top3_count'] for d in analysis['combinations'].values())
                multi_top3_rate = multi_top3_total / sum(d['samples'] for d in analysis['combinations'].values()) if analysis['combinations'] else 0
                f.write(f"  多条件组合不符合: TOP3占比 {multi_top3_rate*100:.2f}%\n")
            
            f.write(f"\n")
            
            # 5. 策略建议
            f.write(f"{'='*90}\n")
            f.write(f"💡 策略建议\n")
            f.write(f"{'='*90}\n\n")
            
            # 找出最佳的单一条件
            if 'single_conditions' in analysis and analysis['single_conditions']:
                best_single = max(analysis['single_conditions'].items(), key=lambda x: x[1]['improvement'])
                best_condition_name = condition_display_names.get(best_single[1]['condition_name'], best_single[1]['condition_name'])
                
                if best_single[1]['improvement'] > 1.1:
                    f.write(f"【推荐】聚焦单一条件不符合\n\n")
                    f.write(f"最佳单一条件: 仅{best_condition_name}不符合\n")
                    f.write(f"  TOP3占比: {best_single[1]['top3_rate']*100:.2f}%\n")
                    f.write(f"  提升倍数: {best_single[1]['improvement']:.2f}x\n")
                    f.write(f"  样本数: {best_single[1]['samples']}\n\n")
                    
                    f.write(f"策略实施:\n")
                    f.write(f"  1. 当日: 满足极致B1\n")
                    f.write(f"  2. 前一日: 仅{best_condition_name}不符合，其他条件都符合\n\n")
            
            # 找出最佳的组合
            if 'combinations' in analysis and analysis['combinations']:
                best_comb = max(analysis['combinations'].items(), key=lambda x: x[1]['improvement'])
                conditions_display = [condition_display_names.get(c, c) for c in best_comb[1]['conditions']]
                
                if best_comb[1]['improvement'] > 1.1:
                    f.write(f"【参考】最佳组合条件\n\n")
                    f.write(f"组合: {' + '.join(conditions_display)} 不符合\n")
                    f.write(f"  TOP3占比: {best_comb[1]['top3_rate']*100:.2f}%\n")
                    f.write(f"  提升倍数: {best_comb[1]['improvement']:.2f}x\n")
                    f.write(f"  样本数: {best_comb[1]['samples']}\n\n")
            
            f.write(f"注意事项:\n")
            f.write(f"  1. 单一条件不符合的样本更纯粹，可能效果更稳定\n")
            f.write(f"  2. 多条件组合可能样本量较少，需要谨慎验证\n")
            f.write(f"  3. 建议结合第一阶段分析的区间细分，制定更精准的策略\n")
            f.write(f"  4. 在回测系统中验证实际收益效果\n\n")
        
        log_message(f"分析报告已保存到: {report_file}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='不符合B1条件组合分析')
    parser.add_argument('--strategy', type=str, default='B1', help='策略名称 (B1/B2/single_needle)')
    parser.add_argument('--period', type=str, default='3d', help='周期 (3d/5d/10d)')
    parser.add_argument('--market-group', type=str, default=None, choices=[None, 'A', 'B'], 
                       help='市场分组 (A=主板00/60, B=创业板/科创板/北交所30/68/92, None=全市场)')
    parser.add_argument('--start-date', type=str, default=None, 
                       help='开始日期 (格式: YYYYMMDD，如: 20240901)')
    parser.add_argument('--end-date', type=str, default=None, 
                       help='结束日期 (格式: YYYYMMDD，如: 20250129)')
    
    args = parser.parse_args()
    
    analyzer = NotB1CombinationAnalyzer(
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
    print(f"不符合B1条件组合分析")
    print(f"{'='*90}")
    print(f"配置:")
    print(f"  策略: {args.strategy}")
    print(f"  周期: {args.period}")
    print(f"  市场: {market_name}{date_range_info}")
    print(f"{'='*90}\n")
    
    analyzer.analyze()


if __name__ == '__main__':
    main()
