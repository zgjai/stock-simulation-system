"""基于因子分析结果生成优化策略"""
import sys
import os
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List
import traceback

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message


class OptimizedStrategyGenerator:
    """优化策略生成器"""
    
    def __init__(self,
                 base_strategy='B1',
                 output_strategy='B1_plus',
                 processed_path='processed_data',
                 base_index_path='strategy_index',
                 output_index_path='strategy_index',
                 factor_analysis_path='data/factor_analysis'):
        self.base_strategy = base_strategy
        self.output_strategy = output_strategy
        self.processed_path = processed_path
        self.base_index_path = base_index_path
        self.output_index_path = output_index_path
        self.factor_analysis_path = factor_analysis_path
        
        # 确保输出目录存在
        ensure_dir(f'{self.output_index_path}/{self.output_strategy}')
        
        # 因子筛选条件（默认条件，可通过配置文件覆盖）
        self.factor_filters = {}
        
        # 统计信息
        self.total_dates = 0
        self.processed_dates = 0
        self.total_stocks_before = 0
        self.total_stocks_after = 0
    
    def load_filter_rules(self, period: str = '3d'):
        """
        从因子分析结果中加载筛选规则
        
        Args:
            period: 周期 (3d/5d/10d)
        """
        analysis_file = f'{self.factor_analysis_path}/single_factor_analysis_{self.base_strategy}_{period}.json'
        
        if not os.path.exists(analysis_file):
            log_message(f"因子分析文件不存在: {analysis_file}", 'WARNING')
            log_message("使用默认筛选条件", 'INFO')
            self._use_default_filters()
            return
        
        log_message(f"从分析结果加载筛选规则: {analysis_file}")
        
        try:
            with open(analysis_file, 'r', encoding='utf-8') as f:
                analysis = json.load(f)
            
            # 提取显著相关的因子
            results = analysis.get('results', [])
            self.factor_filters = {}
            
            for result in results:
                factor = result['factor']
                correlation = result.get('correlation', 0)
                t_test = result.get('t_test')
                
                # 只考虑显著相关的因子 (|相关系数| > 0.05 且 p < 0.1)
                if abs(correlation) > 0.05 and t_test and t_test.get('p_value', 1) < 0.1:
                    top5_mean = result['top5_stats'].get('mean')
                    top5_median = result['top5_stats'].get('median')
                    
                    if top5_mean is not None and top5_median is not None:
                        if correlation < 0:
                            # 负相关：TOP5的因子值较低，设置上限
                            threshold = top5_median * 1.2  # 允许20%的余量
                            self.factor_filters[factor] = {
                                'type': 'max',
                                'value': threshold,
                                'correlation': correlation
                            }
                            log_message(f"  {factor}: < {threshold:.2f} (负相关)")
                        else:
                            # 正相关：TOP5的因子值较高，设置下限
                            threshold = top5_median * 0.8  # 允许20%的余量
                            self.factor_filters[factor] = {
                                'type': 'min',
                                'value': threshold,
                                'correlation': correlation
                            }
                            log_message(f"  {factor}: > {threshold:.2f} (正相关)")
            
            if not self.factor_filters:
                log_message("未找到显著相关的因子，使用默认筛选条件", 'WARNING')
                self._use_default_filters()
            else:
                log_message(f"已加载 {len(self.factor_filters)} 个因子筛选条件")
                
        except Exception as e:
            log_message(f"加载筛选规则失败: {str(e)}", 'ERROR')
            traceback.print_exc()
            self._use_default_filters()
    
    def _use_default_filters(self):
        """使用默认的筛选条件（基于经验）"""
        self.factor_filters = {
            'factor_j_value': {
                'type': 'max',
                'value': 20.0,
                'correlation': -0.15,
                'description': 'J值低位（超卖区）'
            },
            'factor_amplitude': {
                'type': 'max',
                'value': 5.0,
                'correlation': -0.10,
                'description': '低振幅（横盘）'
            },
            'factor_volume_ratio': {
                'type': 'min',
                'value': 0.8,
                'correlation': 0.08,
                'description': '成交量适中或放大'
            }
        }
        log_message("使用默认筛选条件:")
        for factor, config in self.factor_filters.items():
            op = '<' if config['type'] == 'max' else '>'
            log_message(f"  {factor} {op} {config['value']}")
    
    def apply_filters(self, stock_code: str, date: str) -> bool:
        """
        对指定股票应用因子筛选条件
        
        Returns:
            是否通过筛选
        """
        try:
            csv_file = f'{self.processed_path}/{stock_code}.csv'
            if not os.path.exists(csv_file):
                return False
            
            df = pd.read_csv(csv_file)
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
            
            row = df[df['date'] == date]
            if row.empty:
                return False
            
            # 应用每个筛选条件
            for factor, config in self.factor_filters.items():
                if factor not in row.columns:
                    continue
                
                value = row.iloc[0][factor]
                
                # 跳过NaN值
                if pd.isna(value):
                    return False
                
                # 检查条件
                if config['type'] == 'max' and value > config['value']:
                    return False
                elif config['type'] == 'min' and value < config['value']:
                    return False
            
            return True
            
        except Exception as e:
            log_message(f"筛选 {stock_code} 失败: {str(e)}", 'ERROR')
            return False
    
    def generate_optimized_index(self):
        """生成优化后的策略索引"""
        log_message(f"\n开始生成 {self.output_strategy} 策略索引...")
        start_time = datetime.now()
        
        # 获取基础策略的所有日期索引
        base_index_dir = f'{self.base_index_path}/{self.base_strategy}'
        if not os.path.exists(base_index_dir):
            log_message(f"基础策略目录不存在: {base_index_dir}", 'ERROR')
            return
        
        index_files = [f for f in os.listdir(base_index_dir) if f.endswith('.json')]
        self.total_dates = len(index_files)
        
        log_message(f"发现 {self.total_dates} 个交易日")
        
        # 处理每个日期
        for i, index_file in enumerate(index_files, 1):
            date = index_file.replace('.json', '')
            
            try:
                # 读取基础策略的候选池
                with open(f'{base_index_dir}/{index_file}', 'r') as f:
                    base_data = json.load(f)
                
                base_stocks = base_data.get('stocks', [])
                self.total_stocks_before += len(base_stocks)
                
                # 应用因子筛选
                filtered_stocks = []
                for stock in base_stocks:
                    if self.apply_filters(stock, date):
                        filtered_stocks.append(stock)
                
                self.total_stocks_after += len(filtered_stocks)
                
                # 保存优化后的索引
                output_data = {
                    'date': date,
                    'strategy': self.output_strategy,
                    'base_strategy': self.base_strategy,
                    'stocks': filtered_stocks,
                    'stock_count': len(filtered_stocks),
                    'base_stock_count': len(base_stocks),
                    'filter_rate': f"{(1 - len(filtered_stocks)/len(base_stocks))*100:.1f}%" if len(base_stocks) > 0 else "0%",
                    'filters': self.factor_filters
                }
                
                output_file = f'{self.output_index_path}/{self.output_strategy}/{date}.json'
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(output_data, f, ensure_ascii=False, indent=2)
                
                self.processed_dates += 1
                
                # 进度显示
                if i % 100 == 0:
                    log_message(f"进度: {i}/{self.total_dates} ({i/self.total_dates*100:.1f}%)")
                
            except Exception as e:
                log_message(f"处理 {date} 失败: {str(e)}", 'ERROR')
                traceback.print_exc()
                continue
        
        # 统计信息
        elapsed = (datetime.now() - start_time).total_seconds()
        
        print("\n" + "="*80)
        log_message(f"{self.output_strategy} 策略生成完成！", 'INFO')
        print("="*80)
        print(f"处理日期数: {self.processed_dates}/{self.total_dates}")
        print(f"总股票数 (优化前): {self.total_stocks_before}")
        print(f"总股票数 (优化后): {self.total_stocks_after}")
        
        if self.total_stocks_before > 0:
            filter_rate = (1 - self.total_stocks_after / self.total_stocks_before) * 100
            avg_before = self.total_stocks_before / self.processed_dates
            avg_after = self.total_stocks_after / self.processed_dates
            
            print(f"平均候选池大小 (优化前): {avg_before:.1f}")
            print(f"平均候选池大小 (优化后): {avg_after:.1f}")
            print(f"平均过滤率: {filter_rate:.1f}%")
        
        print(f"耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
        print("="*80)
        
        # 保存配置
        self.save_strategy_config()
        
        print(f"\n策略索引已保存到: {self.output_index_path}/{self.output_strategy}/")
        print(f"配置文件已保存到: {self.output_index_path}/{self.output_strategy}/config.json")
    
    def save_strategy_config(self):
        """保存策略配置"""
        config = {
            'strategy_name': self.output_strategy,
            'base_strategy': self.base_strategy,
            'description': f'基于{self.base_strategy}策略，通过因子筛选优化的版本',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'filters': self.factor_filters,
            'statistics': {
                'total_dates': self.processed_dates,
                'avg_stocks_before': self.total_stocks_before / self.processed_dates if self.processed_dates > 0 else 0,
                'avg_stocks_after': self.total_stocks_after / self.processed_dates if self.processed_dates > 0 else 0,
                'filter_rate': f"{(1 - self.total_stocks_after / self.total_stocks_before)*100:.1f}%" if self.total_stocks_before > 0 else "0%"
            }
        }
        
        config_file = f'{self.output_index_path}/{self.output_strategy}/config.json'
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    
    def generate_comparison_report(self):
        """生成对比报告（基础策略 vs 优化策略）"""
        log_message("\n生成对比报告...")
        
        report_file = f'{self.output_index_path}/{self.output_strategy}/comparison_report.txt'
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write(f"策略对比报告\n")
            f.write("="*80 + "\n")
            f.write(f"基础策略: {self.base_strategy}\n")
            f.write(f"优化策略: {self.output_strategy}\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*80 + "\n\n")
            
            f.write("1. 筛选条件\n")
            f.write("-"*80 + "\n")
            for factor, config in self.factor_filters.items():
                op = '<' if config['type'] == 'max' else '>'
                corr = config.get('correlation', 'N/A')
                desc = config.get('description', '')
                f.write(f"  {factor} {op} {config['value']:.2f}")
                if desc:
                    f.write(f"  # {desc}")
                if corr != 'N/A':
                    f.write(f"  (相关系数: {corr:.4f})")
                f.write("\n")
            
            f.write("\n2. 统计对比\n")
            f.write("-"*80 + "\n")
            f.write(f"  处理日期数: {self.processed_dates}\n")
            f.write(f"  总股票数 (优化前): {self.total_stocks_before}\n")
            f.write(f"  总股票数 (优化后): {self.total_stocks_after}\n")
            
            if self.processed_dates > 0 and self.total_stocks_before > 0:
                avg_before = self.total_stocks_before / self.processed_dates
                avg_after = self.total_stocks_after / self.processed_dates
                filter_rate = (1 - self.total_stocks_after / self.total_stocks_before) * 100
                
                f.write(f"  平均候选池大小 (优化前): {avg_before:.1f}\n")
                f.write(f"  平均候选池大小 (优化后): {avg_after:.1f}\n")
                f.write(f"  平均过滤率: {filter_rate:.1f}%\n")
            
            f.write("\n3. 使用说明\n")
            f.write("-"*80 + "\n")
            f.write(f"  在回测设置中选择策略 '{self.output_strategy}'，系统会自动使用优化后的候选池\n")
            f.write(f"  优化策略已自动应用因子筛选，无需额外配置\n")
            
            f.write("\n4. 预期效果\n")
            f.write("-"*80 + "\n")
            f.write(f"  - 候选池更加精准，减少了不符合条件的股票\n")
            f.write(f"  - 提高了优秀案例的命中率\n")
            f.write(f"  - 需要通过回测验证实际收益效果\n")
        
        log_message(f"对比报告已保存到: {report_file}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='生成优化策略')
    parser.add_argument('--base', type=str, default='B1', help='基础策略名称')
    parser.add_argument('--output', type=str, default='B1_plus', help='输出策略名称')
    parser.add_argument('--period', type=str, default='3d', help='使用哪个周期的分析结果 (3d/5d/10d)')
    parser.add_argument('--use-default', action='store_true', help='使用默认筛选条件而不是分析结果')
    
    args = parser.parse_args()
    
    generator = OptimizedStrategyGenerator(
        base_strategy=args.base,
        output_strategy=args.output
    )
    
    # 加载筛选规则
    if args.use_default:
        generator._use_default_filters()
    else:
        generator.load_filter_rules(period=args.period)
    
    # 生成优化索引
    generator.generate_optimized_index()
    
    # 生成对比报告
    generator.generate_comparison_report()


if __name__ == '__main__':
    main()
