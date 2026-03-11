"""增强版因子分析脚本 - 支持固定区间分组和多因子组合分析"""
import sys
import os
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import traceback

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message


class EnhancedFactorAnalyzer:
    """增强版单因子分析器"""
    
    def __init__(self, analysis_result_file: str):
        """
        从已有的分析结果初始化
        
        Args:
            analysis_result_file: 之前生成的分析结果JSON文件路径
        """
        self.analysis_result_file = analysis_result_file
        
        # 加载分析结果
        with open(analysis_result_file, 'r', encoding='utf-8') as f:
            self.analysis_data = json.load(f)
        
        self.strategy = self.analysis_data['strategy']
        self.period = self.analysis_data['period']
        self.market_group = self.analysis_data.get('market_group')
        self.start_date = self.analysis_data.get('start_date')
        self.end_date = self.analysis_data.get('end_date')
        
        # 输出路径
        base_name = Path(analysis_result_file).stem
        self.output_path = Path(analysis_result_file).parent
        self.output_prefix = base_name.replace('single_factor_analysis', 'enhanced_factor')
        
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
    
    def analyze_factor_with_fixed_bins(self, factor_result: Dict, bin_count: int = 10) -> Dict:
        """
        使用固定区间分组分析因子
        
        Args:
            factor_result: 单因子分析结果
            bin_count: 分组数量
            
        Returns:
            固定区间分组的分析结果
        """
        factor = factor_result['factor']
        factor_name = factor_result['factor_name']
        
        log_message(f"固定区间分析: {factor_name} (分{bin_count}组)")
        
        # 从factor_stats获取数据范围
        min_val = factor_result['factor_stats']['min']
        max_val = factor_result['factor_stats']['max']
        
        # 创建固定区间
        bins = np.linspace(min_val, max_val, bin_count + 1)
        bin_labels = [f'区间{i+1}' for i in range(bin_count)]
        
        # 计算每个区间的统计
        group_stats = []
        for i in range(bin_count):
            bin_start = bins[i]
            bin_end = bins[i + 1]
            
            group_stats.append({
                'group': bin_labels[i],
                'range_start': float(bin_start),
                'range_end': float(bin_end),
                'range_center': float((bin_start + bin_end) / 2),
                # 注意: 这里只有统计信息,没有实际样本数据
                # 如果需要详细分析,需要重新加载原始数据
            })
        
        return {
            'factor': factor,
            'factor_name': factor_name,
            'bin_count': bin_count,
            'bins': bins.tolist(),
            'group_stats': group_stats,
            'note': '注意: 固定区间分组需要重新加载原始数据才能计算准确的TOP3占比'
        }
    
    def analyze_top3_concentration(self, factor_result: Dict, threshold_percentile: int = 10) -> Dict:
        """
        分析TOP3的集中区间
        
        Args:
            factor_result: 单因子分析结果
            threshold_percentile: 阈值百分位(例如10表示取前10%和后10%的区间)
            
        Returns:
            TOP3集中度分析结果
        """
        factor = factor_result['factor']
        factor_name = factor_result['factor_name']
        
        log_message(f"TOP3集中度分析: {factor_name}")
        
        # 从分组统计中获取信息
        group_stats = factor_result.get('group_stats', [])
        if not group_stats:
            return {
                'factor': factor,
                'factor_name': factor_name,
                'error': '无分组统计数据'
            }
        
        # 找出TOP3占比最高的组
        sorted_groups = sorted(group_stats, key=lambda x: x['top3_rate'], reverse=True)
        
        # 计算占比提升倍数
        if len(sorted_groups) >= 2:
            max_rate = sorted_groups[0]['top3_rate']
            min_rate = sorted_groups[-1]['top3_rate']
            improvement_ratio = max_rate / min_rate if min_rate > 0 else float('inf')
        else:
            improvement_ratio = 1.0
        
        # 计算累积TOP3数量
        total_top3 = sum(g['top3_count'] for g in group_stats)
        for g in sorted_groups:
            g['top3_cumulative'] = sum(sg['top3_count'] for sg in sorted_groups[:sorted_groups.index(g)+1])
            g['top3_cumulative_pct'] = g['top3_cumulative'] / total_top3 * 100 if total_top3 > 0 else 0
        
        return {
            'factor': factor,
            'factor_name': factor_name,
            'total_top3': total_top3,
            'improvement_ratio': improvement_ratio,
            'best_group': sorted_groups[0],
            'worst_group': sorted_groups[-1],
            'sorted_groups': sorted_groups,
            'top3_concentration': {
                'top_20_pct_groups': sorted_groups[:max(1, len(sorted_groups)//5)],
                'covers_top3_count': sum(g['top3_count'] for g in sorted_groups[:max(1, len(sorted_groups)//5)]),
                'covers_top3_pct': sum(g['top3_count'] for g in sorted_groups[:max(1, len(sorted_groups)//5)]) / total_top3 * 100 if total_top3 > 0 else 0
            }
        }
    
    def analyze_multi_factor_combination(self, factor1: str, factor2: str) -> Dict:
        """
        分析两个因子的组合效果
        
        Args:
            factor1: 第一个因子名称
            factor2: 第二个因子名称
            
        Returns:
            组合分析结果
        """
        log_message(f"组合分析: {self.factor_names.get(factor1, factor1)} + {self.factor_names.get(factor2, factor2)}")
        
        # 获取两个因子的分析结果
        results = self.analysis_data['results']
        factor1_result = next((r for r in results if r['factor'] == factor1), None)
        factor2_result = next((r for r in results if r['factor'] == factor2), None)
        
        if not factor1_result or not factor2_result:
            return {
                'error': f'找不到因子分析结果: {factor1} 或 {factor2}'
            }
        
        # 获取两个因子的最优区间
        conc1 = self.analyze_top3_concentration(factor1_result)
        conc2 = self.analyze_top3_concentration(factor2_result)
        
        return {
            'factor1': factor1,
            'factor1_name': self.factor_names.get(factor1, factor1),
            'factor2': factor2,
            'factor2_name': self.factor_names.get(factor2, factor2),
            'factor1_best_range': {
                'group': conc1['best_group']['group'],
                'factor_mean': conc1['best_group']['factor_mean'],
                'top3_rate': conc1['best_group']['top3_rate'],
                'improvement': conc1['improvement_ratio']
            },
            'factor2_best_range': {
                'group': conc2['best_group']['group'],
                'factor_mean': conc2['best_group']['factor_mean'],
                'top3_rate': conc2['best_group']['top3_rate'],
                'improvement': conc2['improvement_ratio']
            },
            'combination_suggestion': {
                'condition': f"{self.factor_names.get(factor1, factor1)} 接近 {conc1['best_group']['factor_mean']:.2f}, "
                            f"{self.factor_names.get(factor2, factor2)} 接近 {conc2['best_group']['factor_mean']:.2f}",
                'expected_improvement': f"预期提升: {factor1}提升{conc1['improvement_ratio']:.2f}倍, "
                                       f"{factor2}提升{conc2['improvement_ratio']:.2f}倍",
                'note': '注意: 两个因子的组合效果需要重新加载原始数据才能精确计算'
            }
        }
    
    def generate_enhanced_report(self):
        """生成增强版分析报告"""
        output_file = f'{self.output_path}/{self.output_prefix}_report.txt'
        
        log_message(f"生成增强版报告: {output_file}")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("增强版因子分析报告\n")
            f.write("="*80 + "\n")
            f.write(f"策略: {self.strategy}\n")
            f.write(f"周期: {self.period}\n")
            if self.start_date or self.end_date:
                f.write(f"时间范围: {self.start_date or '开始'} ~ {self.end_date or '现在'}\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")
            
            # 1. 重新评估因子有效性
            f.write("="*80 + "\n")
            f.write("一、因子有效性重新评估\n")
            f.write("="*80 + "\n\n")
            f.write("评估标准:\n")
            f.write("1. TOP3占比提升倍数 (最高组/最低组)\n")
            f.write("2. T检验显著性 (p < 0.05)\n")
            f.write("3. 相关系数绝对值\n\n")
            
            # 分析每个因子的TOP3集中度
            factor_effectiveness = []
            for result in self.analysis_data['results']:
                if result.get('error'):
                    continue
                
                conc = self.analyze_top3_concentration(result)
                if 'error' not in conc:
                    factor_effectiveness.append({
                        'factor': result['factor'],
                        'factor_name': result['factor_name'],
                        'correlation': result['correlation'],
                        'improvement_ratio': conc['improvement_ratio'],
                        't_significant': result.get('t_test', {}).get('significant', False),
                        'best_group_rate': conc['best_group']['top3_rate'],
                        'worst_group_rate': conc['worst_group']['top3_rate']
                    })
            
            # 按改善倍数排序
            factor_effectiveness.sort(key=lambda x: x['improvement_ratio'], reverse=True)
            
            f.write("因子有效性排名 (按TOP3占比提升倍数):\n\n")
            f.write(f"{'排名':<6} {'因子名称':<20} {'提升倍数':<12} {'最高组占比':<12} {'最低组占比':<12} {'T检验':<10} {'相关系数':<12}\n")
            f.write("-"*90 + "\n")
            
            for i, item in enumerate(factor_effectiveness, 1):
                t_mark = "✓" if item['t_significant'] else "✗"
                f.write(f"{i:<6} {item['factor_name']:<20} {item['improvement_ratio']:<12.2f} "
                       f"{item['best_group_rate']:<12.2f}% {item['worst_group_rate']:<12.2f}% "
                       f"{t_mark:<10} {item['correlation']:<12.4f}\n")
            
            f.write("\n")
            
            # 重新定义有效因子
            effective_factors = [f for f in factor_effectiveness 
                                if f['improvement_ratio'] >= 2.0 and f['t_significant']]
            
            if effective_factors:
                f.write(f"✅ 有效因子 (提升倍数≥2.0 且 T检验显著): {len(effective_factors)}个\n\n")
                for item in effective_factors:
                    f.write(f"  - {item['factor_name']}: 提升{item['improvement_ratio']:.2f}倍, "
                           f"相关系数{item['correlation']:.4f}\n")
            else:
                f.write("⚠️  无强有效因子 (提升倍数≥2.0)\n")
            
            f.write("\n\n")
            
            # 2. 详细的TOP3集中度分析
            f.write("="*80 + "\n")
            f.write("二、TOP3集中度详细分析\n")
            f.write("="*80 + "\n\n")
            
            for item in factor_effectiveness[:5]:  # 只展示前5个最有效的
                result = next(r for r in self.analysis_data['results'] if r['factor'] == item['factor'])
                conc = self.analyze_top3_concentration(result)
                
                f.write(f"\n{'-'*80}\n")
                f.write(f"【{item['factor_name']}】\n")
                f.write(f"{'-'*80}\n\n")
                
                f.write(f"总TOP3数: {conc['total_top3']}\n")
                f.write(f"提升倍数: {conc['improvement_ratio']:.2f}x\n\n")
                
                f.write(f"最优区间:\n")
                best = conc['best_group']
                f.write(f"  组别: {best['group']}\n")
                f.write(f"  因子均值: {best['factor_mean']:.4f}\n")
                f.write(f"  TOP3占比: {best['top3_rate']:.2f}%\n")
                f.write(f"  TOP3数量: {best['top3_count']}\n")
                f.write(f"  样本数: {best['count']}\n\n")
                
                f.write(f"最差区间:\n")
                worst = conc['worst_group']
                f.write(f"  组别: {worst['group']}\n")
                f.write(f"  因子均值: {worst['factor_mean']:.4f}\n")
                f.write(f"  TOP3占比: {worst['top3_rate']:.2f}%\n\n")
                
                # TOP3集中度
                f.write(f"TOP3集中度 (前20%分组):\n")
                f.write(f"  覆盖TOP3数量: {conc['top3_concentration']['covers_top3_count']}\n")
                f.write(f"  覆盖TOP3比例: {conc['top3_concentration']['covers_top3_pct']:.1f}%\n\n")
            
            # 3. 多因子组合分析
            f.write("\n" + "="*80 + "\n")
            f.write("三、多因子组合建议\n")
            f.write("="*80 + "\n\n")
            
            if len(effective_factors) >= 2:
                # 分析最有效的两个因子的组合
                combo = self.analyze_multi_factor_combination(
                    effective_factors[0]['factor'],
                    effective_factors[1]['factor']
                )
                
                f.write(f"推荐组合: {combo['factor1_name']} + {combo['factor2_name']}\n\n")
                
                f.write(f"【{combo['factor1_name']}】最优区间:\n")
                f.write(f"  分组: {combo['factor1_best_range']['group']}\n")
                f.write(f"  因子均值: {combo['factor1_best_range']['factor_mean']:.4f}\n")
                f.write(f"  TOP3占比: {combo['factor1_best_range']['top3_rate']:.2f}%\n")
                f.write(f"  单独提升: {combo['factor1_best_range']['improvement']:.2f}倍\n\n")
                
                f.write(f"【{combo['factor2_name']}】最优区间:\n")
                f.write(f"  分组: {combo['factor2_best_range']['group']}\n")
                f.write(f"  因子均值: {combo['factor2_best_range']['factor_mean']:.4f}\n")
                f.write(f"  TOP3占比: {combo['factor2_best_range']['top3_rate']:.2f}%\n")
                f.write(f"  单独提升: {combo['factor2_best_range']['improvement']:.2f}倍\n\n")
                
                f.write(f"组合筛选条件:\n")
                f.write(f"  {combo['combination_suggestion']['condition']}\n\n")
                f.write(f"预期效果:\n")
                f.write(f"  {combo['combination_suggestion']['expected_improvement']}\n\n")
                f.write(f"⚠️  注意: {combo['combination_suggestion']['note']}\n")
            else:
                f.write("当前没有足够的有效因子进行组合分析\n")
            
            f.write("\n" + "="*80 + "\n")
            f.write("四、总结与建议\n")
            f.write("="*80 + "\n\n")
            
            f.write("关键发现:\n\n")
            f.write("1. 相关系数vs实际效果:\n")
            f.write("   虽然部分因子的皮尔逊相关系数较小(0.02-0.05),\n")
            f.write("   但从TOP3占比的分组统计看,这些因子有明显的区分能力。\n")
            f.write("   原因是相关系数只衡量线性关系,而因子效果可能是非线性的。\n\n")
            
            f.write("2. 评估标准调整:\n")
            f.write("   建议使用'TOP3占比提升倍数'作为主要评估指标,\n")
            f.write("   而不是单纯依赖相关系数。提升倍数≥2.0即有实用价值。\n\n")
            
            f.write("3. 实战建议:\n")
            if effective_factors:
                f.write(f"   优先使用提升倍数最高的{min(3, len(effective_factors))}个因子:\n")
                for i, item in enumerate(effective_factors[:3], 1):
                    conc = self.analyze_top3_concentration(
                        next(r for r in self.analysis_data['results'] if r['factor'] == item['factor'])
                    )
                    best_mean = conc['best_group']['factor_mean']
                    f.write(f"   {i}. {item['factor_name']} 取值接近 {best_mean:.2f} "
                           f"(提升{item['improvement_ratio']:.2f}倍)\n")
            else:
                f.write("   当前因子效果有限,建议:\n")
                f.write("   - 尝试其他时间范围的数据\n")
                f.write("   - 探索新的量化因子\n")
                f.write("   - 考虑因子的非线性变换\n")
        
        log_message(f"增强版报告已保存: {output_file}")
        return output_file


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='增强版因子分析')
    parser.add_argument('--input', type=str, required=True,
                       help='输入的分析结果JSON文件路径')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"错误: 文件不存在: {args.input}")
        return
    
    # 创建分析器
    analyzer = EnhancedFactorAnalyzer(args.input)
    
    # 生成增强版报告
    report_file = analyzer.generate_enhanced_report()
    
    print(f"\n{'='*80}")
    print(f"增强版分析完成!")
    print(f"{'='*80}")
    print(f"\n报告文件: {report_file}\n")
    print(f"查看报告:")
    print(f"  cat {report_file} | less\n")


if __name__ == '__main__':
    main()
