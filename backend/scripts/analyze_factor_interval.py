"""因子区间覆盖率分析 - 找出能覆盖最多TOP3的最优值域区间"""
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


class FactorIntervalAnalyzer:
    """因子区间覆盖率分析器"""
    
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
        """获取股票的市场分组"""
        prefix = stock_code[:2]
        if prefix in ['00', '60']:
            return 'A'
        elif prefix in ['30', '68', '92']:
            return 'B'
        else:
            return 'A'
    
    def collect_factor_data(self) -> pd.DataFrame:
        """收集因子数据"""
        market_name = self.market_group_names.get(self.market_group, '全市场')
        log_message(f"开始收集 {self.period} 周期的数据 (市场分组: {market_name})...")
        
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
        
        log_message(f"发现 {len(case_files)} 个学习案例文件")
        
        data_list = []
        processed_count = 0
        
        for case_file in case_files:
            date = case_file.replace('.json', '')
            
            try:
                # 读取学习案例
                with open(f'{cases_dir}/{case_file}', 'r') as f:
                    case_data = json.load(f)
                
                # 获取TOP3股票
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
                    try:
                        csv_file = f'{self.processed_path}/{stock}.csv'
                        if not os.path.exists(csv_file):
                            continue
                        
                        df = pd.read_csv(csv_file)
                        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
                        
                        row = df[df['date'] == date]
                        if row.empty:
                            continue
                        
                        # 提取因子数据
                        factor_data = {}
                        for factor in self.factor_columns:
                            if factor in row.columns:
                                factor_data[factor] = row.iloc[0][factor]
                            else:
                                factor_data[factor] = np.nan
                        
                        # 添加标签
                        factor_data['is_top3'] = 1 if stock in top3_stocks else 0
                        factor_data['date'] = date
                        factor_data['stock'] = stock
                        
                        data_list.append(factor_data)
                        
                    except Exception as e:
                        continue
                
                processed_count += 1
                if processed_count % 100 == 0:
                    log_message(f"已处理 {processed_count}/{len(case_files)} 个日期")
                    
            except Exception as e:
                log_message(f"处理 {date} 失败: {str(e)}", 'ERROR')
                continue
        
        df = pd.DataFrame(data_list)
        log_message(f"收集完成，共 {len(df)} 条数据")
        
        return df
    
    def find_optimal_interval(self, df: pd.DataFrame, factor: str, 
                             min_coverage: float = 0.6,
                             min_improvement: float = 1.5,
                             step_count: int = 20) -> Dict:
        """
        找出能覆盖最多TOP3的最优值域区间
        
        Args:
            df: 数据框
            factor: 因子名称
            min_coverage: 最小覆盖率要求(如0.6表示至少覆盖60%的TOP3)
            min_improvement: 最小提升倍数要求(如1.5表示该区间的TOP3占比至少是全局的1.5倍)
            step_count: 扫描步数
            
        Returns:
            最优区间分析结果
        """
        factor_name = self.factor_names.get(factor, factor)
        log_message(f"区间优化分析: {factor_name}")
        
        # 过滤掉NaN值
        valid_df = df[[factor, 'is_top3']].dropna()
        
        if len(valid_df) == 0:
            return {
                'factor': factor,
                'factor_name': factor_name,
                'error': '无有效数据'
            }
        
        # 全局统计
        total_samples = len(valid_df)
        total_top3 = valid_df['is_top3'].sum()
        global_top3_rate = (total_top3 / total_samples * 100) if total_samples > 0 else 0
        
        log_message(f"  全局: {total_samples}样本, {total_top3}个TOP3, 占比{global_top3_rate:.2f}%")
        
        # 因子值范围
        min_val = valid_df[factor].min()
        max_val = valid_df[factor].max()
        
        # 扫描所有可能的区间
        best_intervals = []
        
        # 生成候选边界点
        percentiles = np.linspace(0, 100, step_count + 1)
        boundaries = [valid_df[factor].quantile(p/100) for p in percentiles]
        boundaries = sorted(list(set(boundaries)))  # 去重并排序
        
        log_message(f"  扫描 {len(boundaries)} 个边界点...")
        
        # 遍历所有可能的区间
        for i in range(len(boundaries)):
            for j in range(i + 1, len(boundaries)):
                lower = boundaries[i]
                upper = boundaries[j]
                
                # 筛选该区间的数据
                interval_df = valid_df[(valid_df[factor] >= lower) & (valid_df[factor] <= upper)]
                
                if len(interval_df) == 0:
                    continue
                
                # 计算区间统计
                interval_samples = len(interval_df)
                interval_top3 = interval_df['is_top3'].sum()
                interval_top3_rate = (interval_top3 / interval_samples * 100) if interval_samples > 0 else 0
                
                # 计算覆盖率和提升倍数
                coverage = (interval_top3 / total_top3 * 100) if total_top3 > 0 else 0
                improvement = (interval_top3_rate / global_top3_rate) if global_top3_rate > 0 else 0
                
                # 计算区间占比(样本数占比)
                interval_ratio = (interval_samples / total_samples * 100) if total_samples > 0 else 0
                
                # 过滤条件
                if coverage < min_coverage * 100:  # 覆盖率不足
                    continue
                if improvement < min_improvement:  # 提升倍数不足
                    continue
                if interval_samples < 100:  # 样本数太少
                    continue
                
                best_intervals.append({
                    'lower': float(lower),
                    'upper': float(upper),
                    'interval_samples': int(interval_samples),
                    'interval_ratio': float(interval_ratio),
                    'interval_top3': int(interval_top3),
                    'interval_top3_rate': float(interval_top3_rate),
                    'coverage': float(coverage),
                    'improvement': float(improvement),
                    'score': float(coverage * improvement / (interval_ratio + 10))  # 综合评分
                })
        
        # 按综合评分排序
        best_intervals.sort(key=lambda x: x['score'], reverse=True)
        
        return {
            'factor': factor,
            'factor_name': factor_name,
            'global_stats': {
                'total_samples': int(total_samples),
                'total_top3': int(total_top3),
                'global_top3_rate': float(global_top3_rate),
                'min_value': float(min_val),
                'max_value': float(max_val)
            },
            'best_intervals': best_intervals[:10],  # 返回前10个最优区间
            'search_params': {
                'min_coverage': min_coverage,
                'min_improvement': min_improvement,
                'step_count': step_count
            }
        }
    
    def analyze_all_factors(self, min_coverage=0.6, min_improvement=1.5):
        """分析所有因子的最优区间"""
        log_message(f"\n开始因子区间优化分析...")
        start_time = datetime.now()
        
        # 收集数据
        df = self.collect_factor_data()
        
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
            
            result = self.find_optimal_interval(
                df, factor, 
                min_coverage=min_coverage,
                min_improvement=min_improvement
            )
            results.append(result)
        
        # 保存结果
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        
        output_file = f'{self.output_path}/factor_interval_analysis_{self.strategy}_{self.period}{market_suffix}{date_suffix}.json'
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
                'search_params': {
                    'min_coverage': min_coverage,
                    'min_improvement': min_improvement
                },
                'results': results
            }, f, ensure_ascii=False, indent=2)
        
        log_message(f"分析结果已保存到: {output_file}")
        
        # 生成可读报告
        self.generate_report(results, len(df), int(df['is_top3'].sum()), 
                           min_coverage, min_improvement)
        
        # 统计耗时
        elapsed = (datetime.now() - start_time).total_seconds()
        log_message(f"分析完成，耗时 {elapsed:.1f}秒")
    
    def generate_report(self, results: List[Dict], total_samples: int, 
                       top3_samples: int, min_coverage: float, min_improvement: float):
        """生成可读的分析报告"""
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        market_name = self.market_group_names.get(self.market_group, '全市场')
        report_file = f'{self.output_path}/factor_interval_report_{self.strategy}_{self.period}{market_suffix}{date_suffix}.txt'
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*90 + "\n")
            f.write(f"因子最优区间分析报告\n")
            f.write("="*90 + "\n")
            f.write(f"策略: {self.strategy}\n")
            f.write(f"周期: {self.period}\n")
            f.write(f"市场分组: {market_name}\n")
            if self.start_date or self.end_date:
                f.write(f"时间范围: {self.start_date or '开始'} ~ {self.end_date or '现在'}\n")
            f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总样本数: {total_samples}\n")
            f.write(f"TOP3样本数: {top3_samples}\n")
            f.write(f"全局TOP3占比: {top3_samples/total_samples*100:.2f}%\n")
            f.write("="*90 + "\n")
            f.write(f"\n筛选条件:\n")
            f.write(f"  - 最小覆盖率: {min_coverage*100:.0f}% (区间内TOP3数量/总TOP3数量)\n")
            f.write(f"  - 最小提升倍数: {min_improvement:.1f}x (区间TOP3占比/全局TOP3占比)\n")
            f.write(f"  - 最小样本数: 100\n")
            f.write("="*90 + "\n\n")
            
            # 找出有最优区间的因子
            valid_results = [r for r in results if not r.get('error') and r.get('best_intervals')]
            
            if not valid_results:
                f.write("⚠️  未找到满足条件的最优区间\n")
                f.write("建议:\n")
                f.write("  1. 降低min_coverage参数(如0.5)\n")
                f.write("  2. 降低min_improvement参数(如1.2)\n")
                return
            
            # 按最佳区间的综合评分排序
            valid_results.sort(key=lambda x: x['best_intervals'][0]['score'] if x['best_intervals'] else 0, reverse=True)
            
            f.write(f"找到 {len(valid_results)} 个因子的最优区间\n\n")
            
            for i, result in enumerate(valid_results, 1):
                f.write(f"\n{'='*90}\n")
                f.write(f"[{i}] {result['factor_name']} ({result['factor']})\n")
                f.write(f"{'='*90}\n\n")
                
                global_stats = result['global_stats']
                f.write(f"全局统计:\n")
                f.write(f"  值域范围: [{global_stats['min_value']:.2f}, {global_stats['max_value']:.2f}]\n")
                f.write(f"  总样本数: {global_stats['total_samples']}\n")
                f.write(f"  TOP3数量: {global_stats['total_top3']}\n")
                f.write(f"  TOP3占比: {global_stats['global_top3_rate']:.2f}%\n\n")
                
                best_intervals = result['best_intervals']
                
                if not best_intervals:
                    f.write("  ❌ 未找到满足条件的区间\n")
                    continue
                
                f.write(f"找到 {len(best_intervals)} 个满足条件的区间:\n\n")
                
                for j, interval in enumerate(best_intervals[:5], 1):  # 只展示前5个
                    f.write(f"  区间{j}: [{interval['lower']:.2f}, {interval['upper']:.2f}]\n")
                    f.write(f"  ┌─ 区间统计:\n")
                    f.write(f"  │   样本数: {interval['interval_samples']} ({interval['interval_ratio']:.1f}%)\n")
                    f.write(f"  │   TOP3数: {interval['interval_top3']}\n")
                    f.write(f"  │   TOP3占比: {interval['interval_top3_rate']:.2f}%\n")
                    f.write(f"  ├─ 性能指标:\n")
                    f.write(f"  │   覆盖率: {interval['coverage']:.1f}% (覆盖了{interval['coverage']:.1f}%的TOP3)\n")
                    f.write(f"  │   提升倍数: {interval['improvement']:.2f}x (比全局提升{interval['improvement']:.2f}倍)\n")
                    f.write(f"  │   综合评分: {interval['score']:.2f}\n")
                    f.write(f"  └─ 实战建议: 筛选{result['factor_name']}在{interval['lower']:.2f}到{interval['upper']:.2f}之间的股票\n")
                    f.write(f"\n")
                
                # 给出最佳区间的详细建议
                best = best_intervals[0]
                f.write(f"💡 推荐使用区间1: [{best['lower']:.2f}, {best['upper']:.2f}]\n")
                f.write(f"   理由:\n")
                f.write(f"   - 覆盖了{best['coverage']:.1f}%的TOP3案例\n")
                f.write(f"   - TOP3占比提升{best['improvement']:.2f}倍\n")
                f.write(f"   - 只需筛选{best['interval_ratio']:.1f}%的候选股票\n")
                f.write(f"\n")
            
            # 总结
            f.write(f"\n{'='*90}\n")
            f.write(f"总结与建议\n")
            f.write(f"{'='*90}\n\n")
            
            f.write(f"最优因子排名 (按综合评分):\n\n")
            for i, result in enumerate(valid_results[:5], 1):
                best = result['best_intervals'][0]
                f.write(f"{i}. {result['factor_name']}\n")
                f.write(f"   区间: [{best['lower']:.2f}, {best['upper']:.2f}]\n")
                f.write(f"   覆盖率: {best['coverage']:.1f}%  提升倍数: {best['improvement']:.2f}x  样本占比: {best['interval_ratio']:.1f}%\n\n")
            
            f.write(f"\n组合策略建议:\n\n")
            if len(valid_results) >= 2:
                f.write(f"使用前{min(3, len(valid_results))}个因子的最优区间组合筛选:\n\n")
                for i, result in enumerate(valid_results[:3], 1):
                    best = result['best_intervals'][0]
                    f.write(f"  {i}) {result['factor_name']} ∈ [{best['lower']:.2f}, {best['upper']:.2f}]\n")
                f.write(f"\n预期效果:\n")
                f.write(f"  - 单因子覆盖率: {valid_results[0]['best_intervals'][0]['coverage']:.1f}%\n")
                f.write(f"  - 多因子组合可能进一步缩小候选池，同时保持较高的TOP3覆盖率\n")
                f.write(f"  - 建议在实际回测中验证组合效果\n")
            else:
                f.write(f"  当前只有{len(valid_results)}个有效因子，建议:\n")
                f.write(f"  - 调整筛选条件，寻找更多有效因子\n")
                f.write(f"  - 使用单因子进行筛选\n")
        
        log_message(f"分析报告已保存到: {report_file}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='因子最优区间分析')
    parser.add_argument('--strategy', type=str, default='B1', help='策略名称 (B1/B2/single_needle)')
    parser.add_argument('--period', type=str, default='3d', help='周期 (3d/5d/10d)')
    parser.add_argument('--market-group', type=str, default=None, choices=[None, 'A', 'B'], 
                       help='市场分组 (A=主板00/60, B=创业板/科创板/北交所30/68/92, None=全市场)')
    parser.add_argument('--start-date', type=str, default=None, 
                       help='开始日期 (格式: YYYYMMDD，如: 20240901)')
    parser.add_argument('--end-date', type=str, default=None, 
                       help='结束日期 (格式: YYYYMMDD，如: 20250129)')
    parser.add_argument('--min-coverage', type=float, default=0.6, 
                       help='最小覆盖率 (0-1，默认0.6表示至少覆盖60%%的TOP3)')
    parser.add_argument('--min-improvement', type=float, default=1.5, 
                       help='最小提升倍数 (默认1.5表示区间TOP3占比至少是全局的1.5倍)')
    
    args = parser.parse_args()
    
    analyzer = FactorIntervalAnalyzer(
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
    print(f"分析配置:")
    print(f"  策略: {args.strategy}")
    print(f"  周期: {args.period}")
    print(f"  市场: {market_name}{date_range_info}")
    print(f"  最小覆盖率: {args.min_coverage*100:.0f}%")
    print(f"  最小提升倍数: {args.min_improvement:.1f}x")
    print(f"{'='*90}")
    
    analyzer.analyze_all_factors(
        min_coverage=args.min_coverage,
        min_improvement=args.min_improvement
    )


if __name__ == '__main__':
    main()
