"""单因子相关性分析脚本"""
import sys
import os
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import traceback
from collections import defaultdict
from multiprocessing import Pool, cpu_count
from functools import partial

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message


def process_single_date(args):
    """
    处理单个日期的数据（用于多进程）
    
    Args:
        args: (case_file, cases_dir, index_path, processed_path, strategy, period, factor_columns, market_group)
    
    Returns:
        data_list: 该日期的所有数据记录
    """
    case_file, cases_dir, index_path, processed_path, strategy, period, factor_columns, market_group = args
    date = case_file.replace('.json', '')
    
    def get_stock_market_group(stock_code: str) -> str:
        """获取股票的市场分组"""
        prefix = stock_code[:2]
        if prefix in ['00', '60']:
            return 'A'
        elif prefix in ['30', '68', '92']:
            return 'B'
        else:
            return 'A'
    
    try:
        # 读取学习案例
        with open(f'{cases_dir}/{case_file}', 'r') as f:
            case_data = json.load(f)
        
        # 新格式：从market_groups中获取数据
        if 'market_groups' in case_data:
            # 根据market_group参数获取对应组的TOP3
            top3_stocks = set()
            if market_group is None:
                # 所有市场：合并A和B组的TOP3
                for group_key in ['A', 'B']:
                    group_data = case_data['market_groups'].get(group_key, {})
                    for item in group_data.get('top_cases', {}).get(period, []):
                        top3_stocks.add(item['stock_code'])
            else:
                # 特定市场
                group_data = case_data['market_groups'].get(market_group, {})
                for item in group_data.get('top_cases', {}).get(period, []):
                    top3_stocks.add(item['stock_code'])
        else:
            # 旧格式兼容：从top_cases中获取TOP5
            top3_stocks = set()
            for item in case_data.get('top_cases', {}).get(period, []):
                stock_code = item['stock_code']
                # 如果指定了market_group，需要过滤
                if market_group is None or get_stock_market_group(stock_code) == market_group:
                    top3_stocks.add(stock_code)
        
        # 获取当日所有候选股票
        index_file = f'{index_path}/{strategy}/{date}.json'
        if not os.path.exists(index_file):
            return []
        
        with open(index_file, 'r') as f:
            index_data = json.load(f)
        
        candidates = index_data.get('stocks', [])
        
        # 根据market_group过滤候选池
        if market_group is not None:
            candidates = [s for s in candidates if get_stock_market_group(s) == market_group]
        
        # 对每个候选股票提取因子数据
        data_list = []
        for stock in candidates:
            # 加载因子数据
            try:
                csv_file = f'{processed_path}/{stock}.csv'
                if not os.path.exists(csv_file):
                    continue
                
                df = pd.read_csv(csv_file)
                df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
                
                row = df[df['date'] == date]
                if row.empty:
                    continue
                
                # 提取因子数据
                factor_data = {}
                for factor in factor_columns:
                    if factor in row.columns:
                        factor_data[factor] = row.iloc[0][factor]
                    else:
                        factor_data[factor] = np.nan
                
                # 添加标签：是否为TOP3
                factor_data['is_top3'] = 1 if stock in top3_stocks else 0
                factor_data['date'] = date
                factor_data['stock'] = stock
                
                # 添加收益率（从学习案例中获取）
                return_pct = None
                
                # 新格式
                if 'market_groups' in case_data:
                    stock_group = get_stock_market_group(stock)
                    if market_group is None or stock_group == market_group:
                        group_data = case_data['market_groups'].get(stock_group, {})
                        for case in group_data.get('top_cases', {}).get(period, []):
                            if case['stock_code'] == stock:
                                return_pct = case['return_pct']
                                break
                else:
                    # 旧格式兼容
                    for case in case_data.get('top_cases', {}).get(period, []):
                        if case['stock_code'] == stock:
                            return_pct = case['return_pct']
                            break
                
                factor_data['return_pct'] = return_pct if return_pct is not None else 0.0
                
                data_list.append(factor_data)
                
            except Exception as e:
                continue
        
        return data_list
        
    except Exception as e:
        return []


class SingleFactorAnalyzer:
    """单因子分析器"""
    
    def __init__(self, 
                 processed_path='processed_data',
                 learning_cases_path='learning_cases',
                 index_path='strategy_index',
                 output_path='data/factor_analysis',
                 strategy='B1',
                 market_group=None,
                 start_date=None,
                 end_date=None):
        self.processed_path = processed_path
        self.learning_cases_path = learning_cases_path
        self.index_path = index_path
        self.output_path = output_path
        self.strategy = strategy
        self.market_group = market_group  # None表示所有市场，'A'表示主板，'B'表示创业板等
        self.start_date = start_date  # 开始日期，格式：YYYYMMDD
        self.end_date = end_date      # 结束日期，格式：YYYYMMDD
        
        # 确保输出目录存在
        ensure_dir(self.output_path)
        
        # 因子列表
        self.factor_columns = [
            'factor_amplitude',
            'factor_volume_ratio',
            'factor_wash_ratio',
            'factor_j_value',
            'factor_close_change_prev',
            'factor_close_change_open',
            'factor_body_ratio',
            'factor_upper_shadow',
            'factor_lower_shadow',
            'factor_close_position',
            'factor_consecutive_small_amp'
        ]
        
        # 因子中文名称映射
        self.factor_names = {
            'factor_amplitude': '当日振幅',
            'factor_volume_ratio': '成交量比率',
            'factor_wash_ratio': '知行比率',
            'factor_j_value': 'J值',
            'factor_close_change_prev': '相对昨收涨跌幅',
            'factor_close_change_open': '相对今开涨跌幅',
            'factor_body_ratio': 'K线实体比例',
            'factor_upper_shadow': '上影线比例',
            'factor_lower_shadow': '下影线比例',
            'factor_close_position': '收盘价位置',
            'factor_consecutive_small_amp': '连续小振幅天数'
        }
        
        # 市场分组名称
        self.market_group_names = {
            'A': '主板(00/60)',
            'B': '创业板/科创板/北交所(30/68/92)',
            None: '全市场'
        }
    
    def get_stock_market_group(self, stock_code: str) -> str:
        """
        获取股票的市场分组
        
        Args:
            stock_code: 股票代码
            
        Returns:
            'A' for 00/60 (主板), 'B' for 30/68/92 (创业板/科创板/北交所)
        """
        prefix = stock_code[:2]
        if prefix in ['00', '60']:
            return 'A'  # 主板（涨跌幅限制10%）
        elif prefix in ['30', '68', '92']:
            return 'B'  # 创业板/科创板/北交所（涨跌幅限制20%）
        else:
            return 'A'  # 默认归为主板
    
    def load_factor_data(self, stock_code: str, date: str) -> Dict:
        """
        加载指定股票和日期的因子数据
        
        Returns:
            因子字典，如果数据不存在返回None
        """
        try:
            csv_file = f'{self.processed_path}/{stock_code}.csv'
            if not os.path.exists(csv_file):
                return None
            
            df = pd.read_csv(csv_file)
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
            
            row = df[df['date'] == date]
            if row.empty:
                return None
            
            # 提取因子数据
            factor_data = {}
            for factor in self.factor_columns:
                if factor in row.columns:
                    factor_data[factor] = row.iloc[0][factor]
                else:
                    factor_data[factor] = np.nan
            
            return factor_data
            
        except Exception as e:
            log_message(f"加载 {stock_code} 的因子数据失败: {str(e)}", 'ERROR')
            return None
    
    def collect_data_for_period(self, period: str = '3d', max_dates: int = None, use_multiprocess: bool = True, num_workers: int = None) -> pd.DataFrame:
        """
        收集指定周期的因子和收益数据
        
        Args:
            period: '3d', '5d', '10d'
            max_dates: 最多处理多少个交易日（用于测试，None表示全部）
            use_multiprocess: 是否使用多进程加速
            num_workers: 进程数（None表示自动检测CPU核心数）
            
        Returns:
            DataFrame包含因子值和是否为TOP3的标签
        """
        market_name = self.market_group_names.get(self.market_group, '全市场')
        date_range_info = ""
        if self.start_date or self.end_date:
            date_range_info = f", 时间范围: {self.start_date or '开始'} ~ {self.end_date or '现在'}"
        log_message(f"开始收集 {period} 周期的数据 (市场分组: {market_name}{date_range_info})...")
        
        # 获取所有学习案例文件
        cases_dir = f'{self.learning_cases_path}/{self.strategy}'
        if not os.path.exists(cases_dir):
            log_message(f"学习案例目录不存在: {cases_dir}", 'ERROR')
            return pd.DataFrame()
        
        case_files = [f for f in os.listdir(cases_dir) if f.endswith('.json')]
        
        # 根据时间范围过滤
        if self.start_date or self.end_date:
            filtered_files = []
            for f in case_files:
                date = f.replace('.json', '')
                if self.start_date and date < self.start_date:
                    continue
                if self.end_date and date > self.end_date:
                    continue
                filtered_files.append(f)
            case_files = filtered_files
            log_message(f"时间范围过滤后：{len(case_files)} 个交易日")
        
        # 测试模式：只处理部分数据
        if max_dates is not None and max_dates > 0:
            case_files = case_files[:max_dates]
            log_message(f"测试模式：只处理前 {len(case_files)} 个交易日")
        else:
            log_message(f"发现 {len(case_files)} 个学习案例文件")
        
        # 多进程处理
        if use_multiprocess and len(case_files) > 10:
            if num_workers is None:
                num_workers = min(cpu_count(), 8)  # 最多用8个进程
            
            log_message(f"使用多进程加速 (进程数: {num_workers})")
            
            # 准备参数
            args_list = [
                (case_file, cases_dir, self.index_path, self.processed_path, 
                 self.strategy, period, self.factor_columns, self.market_group)
                for case_file in case_files
            ]
            
            # 多进程处理
            data_list = []
            with Pool(processes=num_workers) as pool:
                results = pool.map(process_single_date, args_list)
                
                for i, result in enumerate(results, 1):
                    data_list.extend(result)
                    if i % 100 == 0:
                        log_message(f"已处理 {i}/{len(case_files)} 个日期")
            
            log_message(f"多进程处理完成")
        else:
            # 单进程处理（原有逻辑）
            if use_multiprocess and len(case_files) <= 10:
                log_message(f"数据量较小，使用单进程处理")
            
            data_list = []
            processed_count = 0
            
            for case_file in case_files:
                date = case_file.replace('.json', '')
                
                try:
                    # 读取学习案例
                    with open(f'{cases_dir}/{case_file}', 'r') as f:
                        case_data = json.load(f)
                    
                    # 新格式：从market_groups中获取数据
                    if 'market_groups' in case_data:
                        # 根据market_group参数获取对应组的TOP3
                        top3_stocks = set()
                        if self.market_group is None:
                            # 所有市场：合并A和B组的TOP3
                            for group_key in ['A', 'B']:
                                group_data = case_data['market_groups'].get(group_key, {})
                                for item in group_data.get('top_cases', {}).get(period, []):
                                    top3_stocks.add(item['stock_code'])
                        else:
                            # 特定市场
                            group_data = case_data['market_groups'].get(self.market_group, {})
                            for item in group_data.get('top_cases', {}).get(period, []):
                                top3_stocks.add(item['stock_code'])
                    else:
                        # 旧格式兼容：从top_cases中获取TOP5
                        top3_stocks = set()
                        for item in case_data.get('top_cases', {}).get(period, []):
                            stock_code = item['stock_code']
                            # 如果指定了market_group，需要过滤
                            if self.market_group is None or self.get_stock_market_group(stock_code) == self.market_group:
                                top3_stocks.add(stock_code)
                    
                    # 获取当日所有候选股票
                    index_file = f'{self.index_path}/{self.strategy}/{date}.json'
                    if not os.path.exists(index_file):
                        continue
                    
                    with open(index_file, 'r') as f:
                        index_data = json.load(f)
                    
                    candidates = index_data.get('stocks', [])
                    
                    # 根据market_group过滤候选池
                    if self.market_group is not None:
                        candidates = [s for s in candidates if self.get_stock_market_group(s) == self.market_group]
                    
                    # 对每个候选股票提取因子数据
                    for stock in candidates:
                        factor_data = self.load_factor_data(stock, date)
                        if factor_data is None:
                            continue
                        
                        # 添加标签：是否为TOP3
                        factor_data['is_top3'] = 1 if stock in top3_stocks else 0
                        factor_data['date'] = date
                        factor_data['stock'] = stock
                        
                        # 添加收益率（从学习案例中获取）
                        return_pct = None
                        
                        # 新格式
                        if 'market_groups' in case_data:
                            stock_group = self.get_stock_market_group(stock)
                            if self.market_group is None or stock_group == self.market_group:
                                group_data = case_data['market_groups'].get(stock_group, {})
                                for case in group_data.get('top_cases', {}).get(period, []):
                                    if case['stock_code'] == stock:
                                        return_pct = case['return_pct']
                                        break
                        else:
                            # 旧格式兼容
                            for case in case_data.get('top_cases', {}).get(period, []):
                                if case['stock_code'] == stock:
                                    return_pct = case['return_pct']
                                    break
                        
                        factor_data['return_pct'] = return_pct if return_pct is not None else 0.0
                        
                        data_list.append(factor_data)
                    
                    processed_count += 1
                    if processed_count % 100 == 0:
                        log_message(f"已处理 {processed_count}/{len(case_files)} 个日期")
                        
                except Exception as e:
                    log_message(f"处理 {date} 失败: {str(e)}", 'ERROR')
                    continue
        
        df = pd.DataFrame(data_list)
        log_message(f"收集完成，共 {len(df)} 条数据")
        
        return df
    
    def analyze_factor(self, df: pd.DataFrame, factor: str) -> Dict:
        """
        分析单个因子与收益的关系
        
        Args:
            df: 数据框
            factor: 因子名称
            
        Returns:
            分析结果字典
        """
        log_message(f"分析因子: {self.factor_names.get(factor, factor)}")
        
        # 过滤掉NaN值
        valid_df = df[[factor, 'is_top3', 'return_pct']].dropna()
        
        if len(valid_df) == 0:
            return {
                'factor': factor,
                'factor_name': self.factor_names.get(factor, factor),
                'sample_size': 0,
                'error': '无有效数据'
            }
        
        # 1. 基础统计
        factor_stats = {
            'mean': float(valid_df[factor].mean()),
            'std': float(valid_df[factor].std()),
            'min': float(valid_df[factor].min()),
            'q25': float(valid_df[factor].quantile(0.25)),
            'median': float(valid_df[factor].median()),
            'q75': float(valid_df[factor].quantile(0.75)),
            'max': float(valid_df[factor].max()),
        }
        
        # 2. TOP3与非TOP3的对比
        top3_df = valid_df[valid_df['is_top3'] == 1]
        non_top3_df = valid_df[valid_df['is_top3'] == 0]
        
        top3_stats = {
            'count': int(len(top3_df)),
            'mean': float(top3_df[factor].mean()) if len(top3_df) > 0 else None,
            'std': float(top3_df[factor].std()) if len(top3_df) > 0 else None,
            'median': float(top3_df[factor].median()) if len(top3_df) > 0 else None,
        }
        
        non_top3_stats = {
            'count': int(len(non_top3_df)),
            'mean': float(non_top3_df[factor].mean()) if len(non_top3_df) > 0 else None,
            'std': float(non_top3_df[factor].std()) if len(non_top3_df) > 0 else None,
            'median': float(non_top3_df[factor].median()) if len(non_top3_df) > 0 else None,
        }
        
        # 3. 相关性分析
        correlation = float(valid_df[factor].corr(valid_df['return_pct']))
        
        # 4. 分组统计（将因子值分为5组）
        try:
            # 使用qcut自动分组，不指定labels让pandas自动生成
            valid_df_copy = valid_df.copy()
            valid_df_copy['factor_group'] = pd.qcut(valid_df_copy[factor], q=5, duplicates='drop')
            
            group_stats = []
            unique_groups = sorted(valid_df_copy['factor_group'].unique())
            
            for i, group in enumerate(unique_groups, 1):
                group_df = valid_df_copy[valid_df_copy['factor_group'] == group]
                if len(group_df) > 0:
                    group_stats.append({
                        'group': f'G{i}',
                        'count': int(len(group_df)),
                        'factor_mean': float(group_df[factor].mean()),
                        'return_mean': float(group_df['return_pct'].mean()),
                        'top3_count': int(group_df['is_top3'].sum()),
                        'top3_rate': float(group_df['is_top3'].mean() * 100)
                    })
        except Exception as e:
            log_message(f"分组统计失败: {str(e)}", 'WARNING')
            group_stats = []
        
        # 5. T检验（TOP3 vs 非TOP3）
        from scipy import stats
        try:
            if len(top3_df) > 0 and len(non_top3_df) > 0:
                t_stat, p_value = stats.ttest_ind(
                    top3_df[factor].dropna(),
                    non_top3_df[factor].dropna()
                )
                t_test = {
                    't_statistic': float(t_stat),
                    'p_value': float(p_value),
                    'significant': bool(p_value < 0.05)  # 确保转换为Python bool
                }
            else:
                t_test = None
        except Exception as e:
            log_message(f"T检验失败: {str(e)}", 'WARNING')
            t_test = None
        
        return {
            'factor': factor,
            'factor_name': self.factor_names.get(factor, factor),
            'sample_size': int(len(valid_df)),
            'factor_stats': factor_stats,
            'top3_stats': top3_stats,
            'non_top3_stats': non_top3_stats,
            'correlation': correlation,
            'group_stats': group_stats,
            't_test': t_test
        }
    
    def analyze_all_factors(self, period: str = '3d', max_dates: int = None, use_multiprocess: bool = True):
        """
        分析所有因子
        
        Args:
            period: 周期 ('3d', '5d', '10d')
            max_dates: 最多处理多少个交易日（用于测试，None表示全部）
            use_multiprocess: 是否使用多进程加速
        """
        market_name = self.market_group_names.get(self.market_group, '全市场')
        date_range_info = ""
        if self.start_date or self.end_date:
            date_range_info = f", 时间范围: {self.start_date or '开始'} ~ {self.end_date or '现在'}"
        log_message(f"\n开始分析所有因子 (周期: {period}, 市场分组: {market_name}{date_range_info})...")
        start_time = datetime.now()
        
        # 收集数据
        df = self.collect_data_for_period(period, max_dates=max_dates, use_multiprocess=use_multiprocess)
        
        if df.empty:
            log_message("没有可用数据", 'ERROR')
            return
        
        log_message(f"数据规模: {len(df)} 条记录")
        log_message(f"TOP3样本数: {df['is_top3'].sum()} 条")
        
        # 分析每个因子
        results = []
        for factor in self.factor_columns:
            if factor not in df.columns:
                log_message(f"因子 {factor} 不存在，跳过", 'WARNING')
                continue
            
            result = self.analyze_factor(df, factor)
            results.append(result)
        
        # 保存结果
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        output_file = f'{self.output_path}/single_factor_analysis_{self.strategy}_{period}{market_suffix}{date_suffix}.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'strategy': self.strategy,
                'period': period,
                'market_group': self.market_group,
                'market_name': market_name,
                'start_date': self.start_date,
                'end_date': self.end_date,
                'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_samples': len(df),
                'top3_samples': int(df['is_top3'].sum()),
                'results': results
            }, f, ensure_ascii=False, indent=2)
        
        log_message(f"分析结果已保存到: {output_file}")
        
        # 生成可读报告
        self.generate_report(results, period, len(df), int(df['is_top3'].sum()))
        
        # 统计耗时
        elapsed = (datetime.now() - start_time).total_seconds()
        log_message(f"分析完成，耗时 {elapsed:.1f}秒")
    
    def generate_report(self, results: List[Dict], period: str, total_samples: int, top3_samples: int):
        """生成可读的分析报告"""
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        market_name = self.market_group_names.get(self.market_group, '全市场')
        report_file = f'{self.output_path}/single_factor_report_{self.strategy}_{period}{market_suffix}{date_suffix}.txt'
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write(f"单因子相关性分析报告\n")
            f.write("="*80 + "\n")
            f.write(f"策略: {self.strategy}\n")
            f.write(f"周期: {period}\n")
            f.write(f"市场分组: {market_name}\n")
            if self.start_date or self.end_date:
                f.write(f"时间范围: {self.start_date or '开始'} ~ {self.end_date or '现在'}\n")
            f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总样本数: {total_samples}\n")
            f.write(f"TOP3样本数: {top3_samples}\n")
            f.write("="*80 + "\n\n")
            
            # 按相关性绝对值排序
            sorted_results = sorted(results, key=lambda x: abs(x.get('correlation', 0)), reverse=True)
            
            for i, result in enumerate(sorted_results, 1):
                f.write(f"\n{'='*80}\n")
                f.write(f"[{i}] {result['factor_name']} ({result['factor']})\n")
                f.write(f"{'='*80}\n\n")
                
                if result.get('error'):
                    f.write(f"错误: {result['error']}\n")
                    continue
                
                # 基础统计
                f.write(f"1. 基础统计 (样本数: {result['sample_size']})\n")
                f.write(f"   均值: {result['factor_stats']['mean']:.4f}\n")
                f.write(f"   标准差: {result['factor_stats']['std']:.4f}\n")
                f.write(f"   最小值: {result['factor_stats']['min']:.4f}\n")
                f.write(f"   25分位: {result['factor_stats']['q25']:.4f}\n")
                f.write(f"   中位数: {result['factor_stats']['median']:.4f}\n")
                f.write(f"   75分位: {result['factor_stats']['q75']:.4f}\n")
                f.write(f"   最大值: {result['factor_stats']['max']:.4f}\n\n")
                
                # TOP3 vs 非TOP3对比
                f.write(f"2. TOP3 vs 非TOP3对比\n")
                f.write(f"   TOP3组:\n")
                f.write(f"     样本数: {result['top3_stats']['count']}\n")
                f.write(f"     均值: {result['top3_stats']['mean']:.4f}\n")
                f.write(f"     中位数: {result['top3_stats']['median']:.4f}\n")
                f.write(f"   非TOP3组:\n")
                f.write(f"     样本数: {result['non_top3_stats']['count']}\n")
                f.write(f"     均值: {result['non_top3_stats']['mean']:.4f}\n")
                f.write(f"     中位数: {result['non_top3_stats']['median']:.4f}\n\n")
                
                # 相关性
                f.write(f"3. 相关性分析\n")
                f.write(f"   与收益率的相关系数: {result['correlation']:.4f}\n")
                corr_strength = "强" if abs(result['correlation']) > 0.3 else "中等" if abs(result['correlation']) > 0.1 else "弱"
                corr_direction = "正相关" if result['correlation'] > 0 else "负相关"
                f.write(f"   相关性强度: {corr_strength}{corr_direction}\n\n")
                
                # T检验
                if result.get('t_test'):
                    f.write(f"4. T检验 (TOP3 vs 非TOP3)\n")
                    f.write(f"   t统计量: {result['t_test']['t_statistic']:.4f}\n")
                    f.write(f"   p值: {result['t_test']['p_value']:.6f}\n")
                    f.write(f"   是否显著 (p<0.05): {'是' if result['t_test']['significant'] else '否'}\n\n")
                
                # 分组统计
                if result.get('group_stats'):
                    f.write(f"5. 分组统计 (按因子值分5组)\n")
                    f.write(f"   {'组别':<6} {'样本数':<8} {'因子均值':<12} {'收益均值':<12} {'TOP3数':<10} {'TOP3占比':<10}\n")
                    f.write(f"   {'-'*70}\n")
                    for group in result['group_stats']:
                        f.write(f"   {group['group']:<6} {group['count']:<8} {group['factor_mean']:<12.4f} "
                               f"{group['return_mean']:<12.2f}% {group['top3_count']:<10} {group['top3_rate']:<10.2f}%\n")
                    f.write("\n")
                
                # 结论
                f.write(f"6. 结论\n")
                if abs(result['correlation']) > 0.1 and result.get('t_test') and result['t_test']['significant']:
                    f.write(f"   ✅ 该因子与收益有显著{corr_direction}关系，可作为选股参考\n")
                elif abs(result['correlation']) > 0.05:
                    f.write(f"   ⚠️  该因子与收益有弱{corr_direction}关系，建议结合其他因子使用\n")
                else:
                    f.write(f"   ❌ 该因子与收益相关性很弱，不建议作为主要选股依据\n")
                
                f.write("\n")
            
            # 总结
            f.write(f"\n{'='*80}\n")
            f.write(f"总结\n")
            f.write(f"{'='*80}\n\n")
            
            # 找出最有用的因子
            significant_factors = [r for r in sorted_results 
                                 if abs(r.get('correlation', 0)) > 0.1 
                                 and r.get('t_test') 
                                 and r['t_test'].get('significant')]
            
            f.write(f"1. 显著相关的因子 (|相关系数|>0.1 且 p<0.05):\n")
            if significant_factors:
                for r in significant_factors:
                    f.write(f"   - {r['factor_name']}: 相关系数={r['correlation']:.4f}\n")
            else:
                f.write(f"   无显著相关因子\n")
            
            f.write(f"\n2. 推荐的选股条件:\n")
            if significant_factors:
                f.write(f"   基于以上分析，建议在{self.strategy}策略基础上增加以下条件:\n")
                for r in significant_factors[:3]:  # 取前3个最相关的
                    if r['correlation'] < 0:  # 负相关，取低值
                        threshold = r['top3_stats']['q75'] if 'q75' in r['top3_stats'] else r['top3_stats']['median']
                        f.write(f"   - {r['factor_name']} < {threshold:.2f}\n")
                    else:  # 正相关，取高值
                        threshold = r['top3_stats']['q25'] if 'q25' in r['top3_stats'] else r['top3_stats']['median']
                        f.write(f"   - {r['factor_name']} > {threshold:.2f}\n")
            else:
                f.write(f"   当前因子与收益相关性较弱，建议继续探索其他因子\n")
        
        log_message(f"分析报告已保存到: {report_file}")
        
        # 在控制台打印摘要
        print("\n" + "="*80)
        print(f"分析摘要 (市场分组: {market_name})")
        print("="*80)
        print(f"最相关的前5个因子:")
        for i, r in enumerate(sorted_results[:5], 1):
            corr_sign = "+" if r.get('correlation', 0) >= 0 else ""
            print(f"  {i}. {r['factor_name']}: {corr_sign}{r.get('correlation', 0):.4f}")
        print("="*80)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='单因子相关性分析')
    parser.add_argument('--strategy', type=str, default='B1', help='策略名称 (B1/B2/single_needle)')
    parser.add_argument('--period', type=str, default='3d', help='周期 (3d/5d/10d)')
    parser.add_argument('--market-group', type=str, default=None, choices=[None, 'A', 'B'], 
                       help='市场分组 (A=主板00/60, B=创业板/科创板/北交所30/68/92, None=全市场)')
    parser.add_argument('--start-date', type=str, default=None, 
                       help='开始日期 (格式: YYYYMMDD，如: 20240901)')
    parser.add_argument('--end-date', type=str, default=None, 
                       help='结束日期 (格式: YYYYMMDD，如: 20250129)')
    parser.add_argument('--all-periods', action='store_true', help='分析所有周期')
    parser.add_argument('--all-markets', action='store_true', help='分析所有市场分组')
    parser.add_argument('--test', type=int, default=None, metavar='N', 
                       help='测试模式：只处理前N个交易日（如 --test 10）')
    parser.add_argument('--no-multiprocess', action='store_true', 
                       help='禁用多进程加速（调试时使用）')
    parser.add_argument('--workers', type=int, default=None, 
                       help='进程数（默认自动检测，最多8个）')
    
    args = parser.parse_args()
    
    use_multiprocess = not args.no_multiprocess
    
    if args.test:
        log_message(f"⚠️  测试模式：只处理前 {args.test} 个交易日", 'INFO')
        print(f"\n{'='*80}")
        print(f"⚠️  测试模式：快速验证脚本，只处理前 {args.test} 个交易日")
        print(f"{'='*80}\n")
    
    if use_multiprocess:
        workers = args.workers if args.workers else min(cpu_count(), 8)
        log_message(f"多进程模式已启用 (最多 {workers} 个进程)", 'INFO')
    else:
        log_message(f"单进程模式", 'INFO')
    
    # 确定要分析的周期和市场
    periods = ['3d', '5d', '10d'] if args.all_periods else [args.period]
    market_groups = [None, 'A', 'B'] if args.all_markets else [args.market_group]
    
    # 遍历所有组合
    for market_group in market_groups:
        for period in periods:
            analyzer = SingleFactorAnalyzer(
                strategy=args.strategy, 
                market_group=market_group,
                start_date=args.start_date,
                end_date=args.end_date
            )
            
            market_name = analyzer.market_group_names.get(market_group, '全市场')
            date_range_info = ""
            if args.start_date or args.end_date:
                date_range_info = f", 时间范围={args.start_date or '开始'}~{args.end_date or '现在'}"
            print(f"\n{'='*80}")
            print(f"分析配置: 策略={args.strategy}, 周期={period}, 市场={market_name}{date_range_info}")
            print(f"{'='*80}")
            
            analyzer.analyze_all_factors(period=period, max_dates=args.test, use_multiprocess=use_multiprocess)


if __name__ == '__main__':
    main()
