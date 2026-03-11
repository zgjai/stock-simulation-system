"""双因子最优区间分析 - 分析两个因子组合的最优区间"""
import sys
import os
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
from itertools import product

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message


class DualFactorIntervalAnalyzer:
    """双因子区间组合分析器"""
    
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
                        
                        # 提取需要的因子
                        factor_data = {
                            'factor_amplitude': row.iloc[0].get('factor_amplitude', np.nan),
                            'factor_volume_ratio': row.iloc[0].get('factor_volume_ratio', np.nan),
                            'is_top3': 1 if stock in top3_stocks else 0,
                            'date': date,
                            'stock': stock
                        }
                        
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
    
    def find_dual_optimal_intervals(self, df: pd.DataFrame, 
                                   factor1: str, factor2: str,
                                   min_coverage: float = 0.5,
                                   min_improvement: float = 1.2,
                                   step_count: int = 15) -> Dict:
        """
        找出两个因子组合的最优区间
        
        Args:
            df: 数据框
            factor1: 第一个因子名称
            factor2: 第二个因子名称
            min_coverage: 最小覆盖率要求
            min_improvement: 最小提升倍数要求
            step_count: 每个因子的扫描步数
            
        Returns:
            双因子最优区间分析结果
        """
        factor1_name = self.factor_names.get(factor1, factor1)
        factor2_name = self.factor_names.get(factor2, factor2)
        
        log_message(f"\n开始双因子区间分析: {factor1_name} + {factor2_name}")
        
        # 过滤掉任一因子为NaN的数据
        valid_df = df[[factor1, factor2, 'is_top3']].dropna()
        
        if len(valid_df) == 0:
            return {
                'error': '无有效数据'
            }
        
        # 全局统计
        total_samples = len(valid_df)
        total_top3 = valid_df['is_top3'].sum()
        global_top3_rate = (total_top3 / total_samples) if total_samples > 0 else 0
        
        log_message(f"全局统计: {total_samples}样本, {total_top3}个TOP3, 占比{global_top3_rate:.4f}")
        
        # 因子1的值域
        factor1_min = valid_df[factor1].min()
        factor1_max = valid_df[factor1].max()
        
        # 因子2的值域
        factor2_min = valid_df[factor2].min()
        factor2_max = valid_df[factor2].max()
        
        log_message(f"{factor1_name} 值域: [{factor1_min:.2f}, {factor1_max:.2f}]")
        log_message(f"{factor2_name} 值域: [{factor2_min:.2f}, {factor2_max:.2f}]")
        
        # 生成因子1的候选边界点
        percentiles1 = np.linspace(0, 100, step_count + 1)
        boundaries1 = [valid_df[factor1].quantile(p/100) for p in percentiles1]
        boundaries1 = sorted(list(set(boundaries1)))
        
        # 生成因子2的候选边界点
        percentiles2 = np.linspace(0, 100, step_count + 1)
        boundaries2 = [valid_df[factor2].quantile(p/100) for p in percentiles2]
        boundaries2 = sorted(list(set(boundaries2)))
        
        log_message(f"扫描空间: {len(boundaries1)} x {len(boundaries2)} = {len(boundaries1) * len(boundaries2)} 个边界点组合")
        
        # 遍历所有可能的区间组合
        best_combinations = []
        total_combinations = 0
        
        for i1 in range(len(boundaries1)):
            for j1 in range(i1 + 1, len(boundaries1)):
                lower1 = boundaries1[i1]
                upper1 = boundaries1[j1]
                
                # 先筛选因子1的区间
                f1_mask = (valid_df[factor1] >= lower1) & (valid_df[factor1] <= upper1)
                
                for i2 in range(len(boundaries2)):
                    for j2 in range(i2 + 1, len(boundaries2)):
                        lower2 = boundaries2[i2]
                        upper2 = boundaries2[j2]
                        
                        # 再筛选因子2的区间（在因子1的基础上）
                        f2_mask = (valid_df[factor2] >= lower2) & (valid_df[factor2] <= upper2)
                        
                        # 同时满足两个因子的条件
                        combined_mask = f1_mask & f2_mask
                        interval_df = valid_df[combined_mask]
                        
                        total_combinations += 1
                        
                        if len(interval_df) == 0:
                            continue
                        
                        # 计算区间统计
                        interval_samples = len(interval_df)
                        interval_top3 = interval_df['is_top3'].sum()
                        interval_top3_rate = (interval_top3 / interval_samples) if interval_samples > 0 else 0
                        
                        # 计算覆盖率和提升倍数
                        coverage = (interval_top3 / total_top3) if total_top3 > 0 else 0
                        improvement = (interval_top3_rate / global_top3_rate) if global_top3_rate > 0 else 0
                        
                        # 计算区间占比
                        interval_ratio = (interval_samples / total_samples) if total_samples > 0 else 0
                        
                        # 过滤条件
                        if coverage < min_coverage:  # 覆盖率不足
                            continue
                        if improvement < min_improvement:  # 提升倍数不足
                            continue
                        if interval_samples < 100:  # 样本数太少
                            continue
                        
                        # 综合评分：平衡覆盖率、提升倍数和区间大小
                        # 覆盖率越高越好，提升倍数越大越好，区间占比越小越好
                        score = (coverage * improvement) / (interval_ratio + 0.1)
                        
                        best_combinations.append({
                            'factor1_interval': {
                                'lower': float(lower1),
                                'upper': float(upper1)
                            },
                            'factor2_interval': {
                                'lower': float(lower2),
                                'upper': float(upper2)
                            },
                            'interval_samples': int(interval_samples),
                            'interval_ratio': float(interval_ratio),
                            'interval_top3': int(interval_top3),
                            'interval_top3_rate': float(interval_top3_rate),
                            'coverage': float(coverage),
                            'improvement': float(improvement),
                            'score': float(score)
                        })
        
        log_message(f"共评估 {total_combinations} 个区间组合，找到 {len(best_combinations)} 个满足条件的组合")
        
        # 按综合评分排序
        best_combinations.sort(key=lambda x: x['score'], reverse=True)
        
        return {
            'factor1': factor1,
            'factor1_name': factor1_name,
            'factor2': factor2,
            'factor2_name': factor2_name,
            'global_stats': {
                'total_samples': int(total_samples),
                'total_top3': int(total_top3),
                'global_top3_rate': float(global_top3_rate),
                'factor1_range': [float(factor1_min), float(factor1_max)],
                'factor2_range': [float(factor2_min), float(factor2_max)]
            },
            'best_combinations': best_combinations[:20],  # 返回前20个最优组合
            'total_evaluated': total_combinations,
            'total_qualified': len(best_combinations),
            'search_params': {
                'min_coverage': min_coverage,
                'min_improvement': min_improvement,
                'step_count': step_count
            }
        }
    
    def analyze(self, factor1='factor_amplitude', factor2='factor_volume_ratio',
                min_coverage=0.5, min_improvement=1.2):
        """执行双因子分析"""
        log_message(f"\n{'='*90}")
        log_message(f"双因子最优区间分析")
        log_message(f"{'='*90}")
        start_time = datetime.now()
        
        # 收集数据
        df = self.collect_factor_data()
        
        if df.empty:
            log_message("没有可用数据", 'ERROR')
            return
        
        log_message(f"\n数据规模: {len(df)} 条记录")
        log_message(f"TOP3样本数: {df['is_top3'].sum()} 条")
        
        # 分析双因子组合
        result = self.find_dual_optimal_intervals(
            df, factor1, factor2,
            min_coverage=min_coverage,
            min_improvement=min_improvement
        )
        
        if 'error' in result:
            log_message(f"分析失败: {result['error']}", 'ERROR')
            return
        
        # 保存结果
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        
        output_file = f'{self.output_path}/dual_factor_interval_{self.strategy}_{self.period}{market_suffix}{date_suffix}.json'
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
        self.generate_report(result, len(df), int(df['is_top3'].sum()))
        
        # 统计耗时
        elapsed = (datetime.now() - start_time).total_seconds()
        log_message(f"\n分析完成，耗时 {elapsed:.1f}秒")
    
    def generate_report(self, result: Dict, total_samples: int, top3_samples: int):
        """生成可读的分析报告"""
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        market_name = self.market_group_names.get(self.market_group, '全市场')
        
        report_file = f'{self.output_path}/dual_factor_report_{self.strategy}_{self.period}{market_suffix}{date_suffix}.txt'
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*90 + "\n")
            f.write(f"双因子最优区间分析报告\n")
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
            f.write("="*90 + "\n\n")
            
            f.write(f"分析因子:\n")
            f.write(f"  因子1: {result['factor1_name']} ({result['factor1']})\n")
            f.write(f"  因子2: {result['factor2_name']} ({result['factor2']})\n\n")
            
            global_stats = result['global_stats']
            f.write(f"全局统计:\n")
            f.write(f"  {result['factor1_name']} 值域: [{global_stats['factor1_range'][0]:.2f}, {global_stats['factor1_range'][1]:.2f}]\n")
            f.write(f"  {result['factor2_name']} 值域: [{global_stats['factor2_range'][0]:.2f}, {global_stats['factor2_range'][1]:.2f}]\n")
            f.write(f"  总样本数: {global_stats['total_samples']}\n")
            f.write(f"  TOP3数量: {global_stats['total_top3']}\n")
            f.write(f"  TOP3占比: {global_stats['global_top3_rate']*100:.2f}%\n\n")
            
            search_params = result['search_params']
            f.write(f"筛选条件:\n")
            f.write(f"  - 最小覆盖率: {search_params['min_coverage']*100:.0f}% (区间内TOP3数量/总TOP3数量)\n")
            f.write(f"  - 最小提升倍数: {search_params['min_improvement']:.1f}x (区间TOP3占比/全局TOP3占比)\n")
            f.write(f"  - 最小样本数: 100\n\n")
            
            f.write(f"搜索结果:\n")
            f.write(f"  评估组合数: {result['total_evaluated']}\n")
            f.write(f"  满足条件的组合: {result['total_qualified']}\n")
            f.write("="*90 + "\n\n")
            
            best_combinations = result['best_combinations']
            
            if not best_combinations:
                f.write("⚠️  未找到满足条件的区间组合\n")
                f.write("建议:\n")
                f.write("  1. 降低min_coverage参数(如0.4)\n")
                f.write("  2. 降低min_improvement参数(如1.1)\n")
                f.write("  3. 增加step_count以获得更精细的区间划分\n")
                return
            
            f.write(f"找到 {len(best_combinations)} 个最优区间组合 (按综合评分排序):\n\n")
            
            for i, combo in enumerate(best_combinations[:10], 1):  # 只展示前10个
                f.write(f"{'='*90}\n")
                f.write(f"[组合{i}] 综合评分: {combo['score']:.2f}\n")
                f.write(f"{'='*90}\n\n")
                
                f1_interval = combo['factor1_interval']
                f2_interval = combo['factor2_interval']
                
                f.write(f"因子区间:\n")
                f.write(f"  {result['factor1_name']}: [{f1_interval['lower']:.2f}, {f1_interval['upper']:.2f}]\n")
                f.write(f"  {result['factor2_name']}: [{f2_interval['lower']:.2f}, {f2_interval['upper']:.2f}]\n\n")
                
                f.write(f"性能指标:\n")
                f.write(f"  ┌─ 样本统计:\n")
                f.write(f"  │   筛选后样本数: {combo['interval_samples']}\n")
                f.write(f"  │   样本占比: {combo['interval_ratio']*100:.1f}% (候选池缩小到{combo['interval_ratio']*100:.1f}%)\n")
                f.write(f"  │   TOP3数量: {combo['interval_top3']}\n")
                f.write(f"  │   TOP3占比: {combo['interval_top3_rate']*100:.2f}%\n")
                f.write(f"  ├─ 效果评估:\n")
                f.write(f"  │   覆盖率: {combo['coverage']*100:.1f}% (覆盖了{combo['coverage']*100:.1f}%的TOP3案例)\n")
                f.write(f"  │   提升倍数: {combo['improvement']:.2f}x (比全局提升{combo['improvement']:.2f}倍)\n")
                f.write(f"  │   综合评分: {combo['score']:.2f}\n")
                f.write(f"  └─ 实战建议:\n")
                f.write(f"      在候选池中筛选同时满足以下条件的股票:\n")
                f.write(f"      • {result['factor1_name']} ∈ [{f1_interval['lower']:.2f}, {f1_interval['upper']:.2f}]\n")
                f.write(f"      • {result['factor2_name']} ∈ [{f2_interval['lower']:.2f}, {f2_interval['upper']:.2f}]\n")
                f.write(f"\n")
            
            # 推荐最佳组合
            f.write(f"\n{'='*90}\n")
            f.write(f"💡 推荐策略\n")
            f.write(f"{'='*90}\n\n")
            
            best = best_combinations[0]
            f1_interval = best['factor1_interval']
            f2_interval = best['factor2_interval']
            
            f.write(f"【最优组合】\n\n")
            f.write(f"筛选条件:\n")
            f.write(f"  1) {result['factor1_name']} ∈ [{f1_interval['lower']:.2f}, {f1_interval['upper']:.2f}]\n")
            f.write(f"  2) {result['factor2_name']} ∈ [{f2_interval['lower']:.2f}, {f2_interval['upper']:.2f}]\n\n")
            
            f.write(f"预期效果:\n")
            f.write(f"  • 候选池缩减: {combo['interval_ratio']*100:.1f}% (只需筛选{combo['interval_ratio']*100:.1f}%的股票)\n")
            f.write(f"  • TOP3覆盖率: {best['coverage']*100:.1f}% (覆盖{best['coverage']*100:.1f}%的高收益案例)\n")
            f.write(f"  • 胜率提升: {best['improvement']:.2f}x (是全局TOP3占比的{best['improvement']:.2f}倍)\n")
            f.write(f"  • 筛选后TOP3占比: {best['interval_top3_rate']*100:.2f}%\n\n")
            
            f.write(f"实施建议:\n")
            f.write(f"  1. 将此双因子筛选条件应用于策略的候选池\n")
            f.write(f"  2. 可以进一步结合其他因子构建多因子模型\n")
            f.write(f"  3. 建议在实际回测中验证效果\n")
            f.write(f"  4. 定期重新分析因子区间以适应市场变化\n\n")
            
            # 如果有多个好的组合，提供备选方案
            if len(best_combinations) >= 3:
                f.write(f"\n【备选方案】\n\n")
                for i in range(1, min(4, len(best_combinations))):
                    combo = best_combinations[i]
                    f1_interval = combo['factor1_interval']
                    f2_interval = combo['factor2_interval']
                    
                    f.write(f"方案{i+1}: (评分: {combo['score']:.2f})\n")
                    f.write(f"  {result['factor1_name']}: [{f1_interval['lower']:.2f}, {f1_interval['upper']:.2f}]\n")
                    f.write(f"  {result['factor2_name']}: [{f2_interval['lower']:.2f}, {f2_interval['upper']:.2f}]\n")
                    f.write(f"  覆盖率: {combo['coverage']*100:.1f}%, 提升倍数: {combo['improvement']:.2f}x, 样本占比: {combo['interval_ratio']*100:.1f}%\n\n")
        
        log_message(f"分析报告已保存到: {report_file}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='双因子最优区间分析')
    parser.add_argument('--strategy', type=str, default='B1', help='策略名称 (B1/B2/single_needle)')
    parser.add_argument('--period', type=str, default='3d', help='周期 (3d/5d/10d)')
    parser.add_argument('--market-group', type=str, default=None, choices=[None, 'A', 'B'], 
                       help='市场分组 (A=主板00/60, B=创业板/科创板/北交所30/68/92, None=全市场)')
    parser.add_argument('--start-date', type=str, default=None, 
                       help='开始日期 (格式: YYYYMMDD，如: 20240901)')
    parser.add_argument('--end-date', type=str, default=None, 
                       help='结束日期 (格式: YYYYMMDD，如: 20250129)')
    parser.add_argument('--factor1', type=str, default='factor_amplitude', 
                       help='第一个因子名称')
    parser.add_argument('--factor2', type=str, default='factor_volume_ratio', 
                       help='第二个因子名称')
    parser.add_argument('--min-coverage', type=float, default=0.5, 
                       help='最小覆盖率 (0-1，默认0.5表示至少覆盖50%%的TOP3)')
    parser.add_argument('--min-improvement', type=float, default=1.2, 
                       help='最小提升倍数 (默认1.2表示区间TOP3占比至少是全局的1.2倍)')
    parser.add_argument('--step-count', type=int, default=15, 
                       help='每个因子的扫描步数 (默认15，步数越大越精确但耗时越长)')
    
    args = parser.parse_args()
    
    analyzer = DualFactorIntervalAnalyzer(
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
    
    factor1_name = analyzer.factor_names.get(args.factor1, args.factor1)
    factor2_name = analyzer.factor_names.get(args.factor2, args.factor2)
    
    print(f"\n{'='*90}")
    print(f"双因子最优区间分析")
    print(f"{'='*90}")
    print(f"配置:")
    print(f"  策略: {args.strategy}")
    print(f"  周期: {args.period}")
    print(f"  市场: {market_name}{date_range_info}")
    print(f"  因子1: {factor1_name}")
    print(f"  因子2: {factor2_name}")
    print(f"  最小覆盖率: {args.min_coverage*100:.0f}%")
    print(f"  最小提升倍数: {args.min_improvement:.1f}x")
    print(f"  扫描步数: {args.step_count}")
    print(f"{'='*90}\n")
    
    analyzer.analyze(
        factor1=args.factor1,
        factor2=args.factor2,
        min_coverage=args.min_coverage,
        min_improvement=args.min_improvement
    )


if __name__ == '__main__':
    main()
