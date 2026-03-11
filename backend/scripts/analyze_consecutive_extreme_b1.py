"""连续极致B1天数影响分析 - 分析连续N日极致B1对当日表现的影响"""
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


class ConsecutiveExtremeB1Analyzer:
    """连续极致B1天数分析器"""
    
    def __init__(self, 
                 processed_path='processed_data',
                 learning_cases_path='learning_cases',
                 index_path='strategy_index',
                 output_path='data/factor_analysis',
                 strategy='B1',
                 period='3d',
                 market_group=None,
                 start_date=None,
                 end_date=None,
                 max_consecutive_days=5):
        self.processed_path = processed_path
        self.learning_cases_path = learning_cases_path
        self.index_path = index_path
        self.output_path = output_path
        self.strategy = strategy
        self.period = period
        self.market_group = market_group
        self.start_date = start_date
        self.end_date = end_date
        self.max_consecutive_days = max_consecutive_days
        
        ensure_dir(self.output_path)
        
        # 市场分组名称
        self.market_group_names = {
            'A': '主板(00/60)',
            'B': '创业板/科创板/北交所(30/68/92)',
            None: '全市场'
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
    
    def check_extreme_b1_condition(self, row: pd.Series, market_group: str, check_b1_first: bool = False) -> bool:
        """
        检查是否满足极致B1条件
        
        Args:
            row: 数据行
            market_group: 市场分组
            check_b1_first: 是否先检查B1条件
                - False: 当日(已在B1候选池中,不需要再检查B1)
                - True: 前N日(需要先检查B1条件)
        
        Returns:
            bool: 是否满足极致B1条件
        """
        # 如果需要先检查B1条件 (用于前N日判断)
        if check_b1_first:
            if not self.check_b1_condition(row):
                return False
        
        # 检查双因子阈值
        amplitude = row.get('factor_amplitude', None)
        volume_ratio = row.get('factor_volume_ratio', None)
        
        if pd.isna(amplitude) or pd.isna(volume_ratio):
            return False
        
        thresholds = self.extreme_b1_thresholds.get(market_group, self.extreme_b1_thresholds['A'])
        return amplitude >= thresholds['amplitude'] and volume_ratio >= thresholds['volume_ratio']
    
    def get_consecutive_extreme_b1_days(self, stock_df: pd.DataFrame, date: str, 
                                       all_dates: List[str], stock_market_group: str) -> int:
        """
        获取截止到前一日,连续极致B1的天数
        
        Returns:
            0: 前一日不是极致B1
            1: 前1日是极致B1(前2日不是)
            2: 前1-2日都是极致B1(前3日不是)
            ...
            5: 前1-5日都是极致B1
        """
        try:
            curr_idx = all_dates.index(date)
        except ValueError:
            return 0
        
        consecutive_days = 0
        
        for i in range(1, self.max_consecutive_days + 1):
            if curr_idx - i < 0:
                break
            
            prev_date = all_dates[curr_idx - i]
            prev_row = stock_df[stock_df['date'] == prev_date]
            
            if prev_row.empty:
                break
            
            # 检查前N日是否满足极致B1 (需要先检查B1条件)
            if self.check_extreme_b1_condition(prev_row.iloc[0], stock_market_group, check_b1_first=True):
                consecutive_days = i
            else:
                break  # 一旦中断就停止
        
        return consecutive_days
    
    def collect_data_with_consecutive_info(self) -> pd.DataFrame:
        """收集包含连续极致B1信息的数据"""
        market_name = self.market_group_names.get(self.market_group, '全市场')
        log_message(f"开始收集连续极致B1数据 (周期: {self.period}, 市场: {market_name})...")
        
        # 获取所有学习案例文件
        cases_dir = f'{self.learning_cases_path}/{self.strategy}'
        if not os.path.exists(cases_dir):
            log_message(f"学习案例目录不存在: {cases_dir}", 'ERROR')
            return pd.DataFrame()
        
        # 一次性获取所有日期
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
                
                # 对每个候选股票分析连续极致B1天数
                for stock in candidates:
                    try:
                        # 使用缓存加载股票数据
                        df = self.load_stock_data(stock)
                        if df is None or df.empty:
                            continue
                        
                        # 获取当日数据
                        curr_row = df[df['date'] == date]
                        if curr_row.empty:
                            continue
                        
                        curr_data = curr_row.iloc[0]
                        stock_market_group = self.get_stock_market_group(stock)
                        
                        # 判断当日是否满足极致B1条件 (当日已在B1候选池,不需要check_b1_first)
                        curr_is_extreme_b1 = self.check_extreme_b1_condition(curr_data, stock_market_group, check_b1_first=False)
                        
                        # 只分析当日满足极致B1条件的股票
                        if not curr_is_extreme_b1:
                            continue
                        
                        # 获取连续极致B1天数
                        consecutive_days = self.get_consecutive_extreme_b1_days(
                            df, date, all_dates, stock_market_group
                        )
                        
                        # 构建数据记录
                        record = {
                            'date': date,
                            'stock': stock,
                            'market_group': stock_market_group,
                            'is_top3': 1 if stock in top3_stocks else 0,
                            'consecutive_days': consecutive_days,
                            'curr_amplitude': curr_data.get('factor_amplitude', np.nan),
                            'curr_volume_ratio': curr_data.get('factor_volume_ratio', np.nan)
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
        
        log_message(f"收集完成，共 {len(df)} 条记录 (当日均满足极致B1)")
        
        return df
    
    def analyze_consecutive_impact(self, df: pd.DataFrame) -> Dict:
        """分析连续极致B1天数对当日表现的影响"""
        log_message(f"\n开始连续极致B1天数影响分析...")
        
        if len(df) == 0:
            return {'error': '无有效数据'}
        
        # 全局统计
        total_samples = len(df)
        total_top3 = df['is_top3'].sum()
        global_top3_rate = (total_top3 / total_samples) if total_samples > 0 else 0
        
        log_message(f"全局统计(当日均满足极致B1): {total_samples}样本, {total_top3}个TOP3, 占比{global_top3_rate:.4f}")
        
        # 按连续天数分组分析
        results = {}
        
        for days in range(0, self.max_consecutive_days + 1):
            day_df = df[df['consecutive_days'] == days]
            
            if len(day_df) == 0:
                continue
            
            results[f'consecutive_{days}d'] = {
                'days': days,
                'samples': len(day_df),
                'top3_count': int(day_df['is_top3'].sum()),
                'top3_rate': float(day_df['is_top3'].sum() / len(day_df)),
                'sample_ratio': float(len(day_df) / total_samples),
                'coverage': float(day_df['is_top3'].sum() / total_top3) if total_top3 > 0 else 0,
                'improvement': float((day_df['is_top3'].sum() / len(day_df)) / global_top3_rate) if global_top3_rate > 0 else 0
            }
        
        return {
            'global_stats': {
                'total_samples': int(total_samples),
                'total_top3': int(total_top3),
                'global_top3_rate': float(global_top3_rate)
            },
            'categories': results
        }
    
    def analyze(self):
        """执行连续极致B1分析"""
        log_message(f"\n{'='*90}")
        log_message(f"连续极致B1天数影响分析")
        log_message(f"{'='*90}")
        start_time = datetime.now()
        
        # 收集数据
        df = self.collect_data_with_consecutive_info()
        
        if df.empty:
            log_message("没有可用数据", 'ERROR')
            return
        
        log_message(f"\n数据规模: {len(df)} 条记录")
        log_message(f"TOP3样本数: {df['is_top3'].sum()} 条")
        
        # 分析连续天数影响
        result = self.analyze_consecutive_impact(df)
        
        if 'error' in result:
            log_message(f"分析失败: {result['error']}", 'ERROR')
            return
        
        # 保存结果
        market_suffix = f'_{self.market_group}' if self.market_group else '_all'
        date_suffix = ""
        if self.start_date or self.end_date:
            date_suffix = f"_{self.start_date or 'start'}_{self.end_date or 'end'}"
        
        output_file = f'{self.output_path}/consecutive_extreme_b1_{self.strategy}_{self.period}{market_suffix}{date_suffix}.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                'strategy': self.strategy,
                'period': self.period,
                'market_group': self.market_group,
                'market_name': self.market_group_names.get(self.market_group, '全市场'),
                'start_date': self.start_date,
                'end_date': self.end_date,
                'max_consecutive_days': self.max_consecutive_days,
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
        
        report_file = f'{self.output_path}/consecutive_extreme_b1_report_{self.strategy}_{self.period}{market_suffix}{date_suffix}.txt'
        
        global_stats = result['global_stats']
        categories = result['categories']
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("="*90 + "\n")
            f.write(f"连续极致B1天数影响分析报告\n")
            f.write("="*90 + "\n")
            f.write(f"策略: {self.strategy}\n")
            f.write(f"周期: {self.period}\n")
            f.write(f"市场分组: {market_name}\n")
            if self.start_date or self.end_date:
                f.write(f"时间范围: {self.start_date or '开始'} ~ {self.end_date or '现在'}\n")
            f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*90 + "\n\n")
            
            f.write(f"分析说明:\n")
            f.write(f"  本分析研究「连续N日都是极致B1」对当日TOP3表现的影响\n")
            f.write(f"  分析范围: 当日满足极致B1条件的所有股票\n")
            f.write(f"  目标: 发现\"持续强势\"是否比\"偶尔强势\"更容易成为TOP3\n\n")
            
            f.write(f"全局统计 (当日均满足极致B1):\n")
            f.write(f"  总样本数: {global_stats['total_samples']}\n")
            f.write(f"  TOP3数量: {global_stats['total_top3']}\n")
            f.write(f"  基准TOP3占比: {global_stats['global_top3_rate']*100:.2f}%\n")
            f.write("="*90 + "\n\n")
            
            # 按连续天数排序显示
            sorted_categories = sorted(
                [(k, v) for k, v in categories.items()],
                key=lambda x: x[1]['days']
            )
            
            for i, (cat_key, cat_data) in enumerate(sorted_categories, 1):
                days = cat_data['days']
                if days == 0:
                    cat_name = f"连续0日 (前1日非极致B1)"
                else:
                    cat_name = f"连续{days}日 (前{days}日都是极致B1)"
                
                f.write(f"{'='*90}\n")
                f.write(f"[分类{i}] {cat_name}\n")
                f.write(f"{'='*90}\n\n")
                
                f.write(f"样本统计:\n")
                f.write(f"  样本数: {cat_data['samples']}\n")
                f.write(f"  占比: {cat_data['sample_ratio']*100:.1f}% (占极致B1总样本的{cat_data['sample_ratio']*100:.1f}%)\n")
                f.write(f"  TOP3数量: {cat_data['top3_count']}\n")
                f.write(f"  TOP3占比: {cat_data['top3_rate']*100:.2f}%\n\n")
                
                f.write(f"效果评估:\n")
                f.write(f"  覆盖率: {cat_data['coverage']*100:.1f}% (覆盖了{cat_data['coverage']*100:.1f}%的TOP3案例)\n")
                f.write(f"  提升倍数: {cat_data['improvement']:.2f}x (相对基准的提升)\n")
                
                # 评估结论
                if cat_data['improvement'] > 1.1:
                    verdict = "✅ 正向影响 - 建议优先考虑"
                elif cat_data['improvement'] > 0.95:
                    verdict = "➖ 中性影响 - 无显著差异"
                else:
                    verdict = "⚠️  负向影响 - 建议规避"
                
                f.write(f"  结论: {verdict}\n\n")
            
            # 对比分析
            f.write(f"{'='*90}\n")
            f.write(f"📊 对比分析\n")
            f.write(f"{'='*90}\n\n")
            
            # 找出最佳和最差的类别
            if len(sorted_categories) >= 2:
                sorted_by_improvement = sorted(sorted_categories, key=lambda x: x[1]['improvement'], reverse=True)
                best_cat_key, best_cat = sorted_by_improvement[0]
                worst_cat_key, worst_cat = sorted_by_improvement[-1]
                
                best_days = best_cat['days']
                worst_days = worst_cat['days']
                
                f.write(f"最佳连续天数: {'连续0日(非连续)' if best_days == 0 else f'连续{best_days}日'}\n")
                f.write(f"  TOP3占比: {best_cat['top3_rate']*100:.2f}%\n")
                f.write(f"  提升倍数: {best_cat['improvement']:.2f}x\n")
                f.write(f"  样本占比: {best_cat['sample_ratio']*100:.1f}%\n\n")
                
                f.write(f"最差连续天数: {'连续0日(非连续)' if worst_days == 0 else f'连续{worst_days}日'}\n")
                f.write(f"  TOP3占比: {worst_cat['top3_rate']*100:.2f}%\n")
                f.write(f"  提升倍数: {worst_cat['improvement']:.2f}x\n")
                f.write(f"  样本占比: {worst_cat['sample_ratio']*100:.1f}%\n\n")
                
                gap = best_cat['improvement'] - worst_cat['improvement']
                if worst_cat['improvement'] > 0:
                    gap_pct = abs(gap) / worst_cat['improvement'] * 100
                    f.write(f"提升倍数差距: {gap:.2f}x ({gap_pct:.1f}%差异)\n\n")
                else:
                    f.write(f"提升倍数差距: {gap:.2f}x\n\n")
            
            # 策略建议
            f.write(f"{'='*90}\n")
            f.write(f"💡 策略建议\n")
            f.write(f"{'='*90}\n\n")
            
            if len(sorted_by_improvement) > 0:
                best_cat_key, best_cat = sorted_by_improvement[0]
                best_days = best_cat['days']
                
                if best_cat['improvement'] > 1.1:
                    f.write(f"【推荐策略】超级极致B1 - 连续{best_days}日模式\n\n")
                    f.write(f"筛选条件:\n")
                    f.write(f"  1) 当日满足极致B1条件\n")
                    if best_days == 0:
                        f.write(f"  2) 前1日不是极致B1 (新鲜血液)\n")
                    else:
                        f.write(f"  2) 前{best_days}日连续都是极致B1 (持续强势)\n")
                    f.write(f"\n")
                    f.write(f"预期效果:\n")
                    f.write(f"  • TOP3占比: {best_cat['top3_rate']*100:.2f}%\n")
                    f.write(f"  • 相比普通极致B1提升: {(best_cat['improvement']-1)*100:.1f}%\n")
                    f.write(f"  • 候选池缩减至: {best_cat['sample_ratio']*100:.1f}%的极致B1股票\n\n")
                else:
                    f.write(f"【结论】\n\n")
                    f.write(f"连续天数对极致B1策略的提升有限，建议:\n")
                    f.write(f"  1. 继续使用当前极致B1策略即可\n")
                    f.write(f"  2. 连续天数不是关键因素\n\n")
            
            # 实施建议
            f.write(f"实施建议:\n")
            f.write(f"  1. 在回测系统中测试最优连续天数模式的实际收益\n")
            f.write(f"  2. 注意连续条件会进一步减少候选池,需平衡覆盖率和精准度\n")
            f.write(f"  3. 定期(如每月)重新分析,市场特征可能变化\n\n")
            
            # 统计分布
            f.write(f"{'='*90}\n")
            f.write(f"📈 连续天数分布\n")
            f.write(f"{'='*90}\n\n")
            
            for cat_key, cat_data in sorted_categories:
                days = cat_data['days']
                cat_name = f"连续{days}日" if days > 0 else "非连续"
                bar_length = int(cat_data['sample_ratio'] * 50)
                bar = '█' * bar_length + '░' * (50 - bar_length)
                f.write(f"{cat_name:15s} {bar} {cat_data['sample_ratio']*100:5.1f}%  TOP3:{cat_data['top3_rate']*100:5.2f}%\n")
        
        log_message(f"分析报告已保存到: {report_file}")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='连续极致B1天数影响分析')
    parser.add_argument('--strategy', type=str, default='B1', help='策略名称 (B1/B2/single_needle)')
    parser.add_argument('--period', type=str, default='3d', help='周期 (3d/5d/10d)')
    parser.add_argument('--market-group', type=str, default=None, choices=[None, 'A', 'B'], 
                       help='市场分组 (A=主板00/60, B=创业板/科创板/北交所30/68/92, None=全市场)')
    parser.add_argument('--start-date', type=str, default=None, 
                       help='开始日期 (格式: YYYYMMDD，如: 20240901)')
    parser.add_argument('--end-date', type=str, default=None, 
                       help='结束日期 (格式: YYYYMMDD，如: 20250129)')
    parser.add_argument('--max-days', type=int, default=5,
                       help='最大连续天数 (默认5，分析连续1-5日)')
    
    args = parser.parse_args()
    
    analyzer = ConsecutiveExtremeB1Analyzer(
        strategy=args.strategy,
        period=args.period,
        market_group=args.market_group,
        start_date=args.start_date,
        end_date=args.end_date,
        max_consecutive_days=args.max_days
    )
    
    market_name = analyzer.market_group_names.get(args.market_group, '全市场')
    date_range_info = ""
    if args.start_date or args.end_date:
        date_range_info = f", 时间范围={args.start_date or '开始'}~{args.end_date or '现在'}"
    
    print(f"\n{'='*90}")
    print(f"连续极致B1天数影响分析")
    print(f"{'='*90}")
    print(f"配置:")
    print(f"  策略: {args.strategy}")
    print(f"  周期: {args.period}")
    print(f"  市场: {market_name}{date_range_info}")
    print(f"  最大连续天数: {args.max_days}")
    print(f"{'='*90}\n")
    
    analyzer.analyze()


if __name__ == '__main__':
    main()
