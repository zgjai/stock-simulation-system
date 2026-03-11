"""计算学习案例（优秀案例）的预计算脚本"""
import sys
import os
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import traceback
from multiprocessing import Pool, cpu_count

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from utils import ensure_dir, log_message

# 全局缓存，用于多进程共享（每个进程有自己的缓存）
_stock_data_cache = {}


def process_single_date_worker(args):
    """
    多进程worker函数：处理单个日期
    
    Args:
        args: (date, strategy, processed_path, index_path, output_path, periods)
    
    Returns:
        (success, date, error_msg)
    """
    date, strategy, processed_path, index_path, output_path, periods = args
    
    try:
        # 创建临时calculator（每个进程独立）
        temp_calc = LearningCaseCalculator(
            processed_path=processed_path,
            index_path=index_path,
            output_path=output_path
        )
        temp_calc.periods = periods
        
        # 计算学习案例
        learning_case = temp_calc.calc_learning_cases_for_date(date, strategy)
        
        # 保存到JSON文件
        output_file = f'{output_path}/{strategy}/{date}.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(learning_case, f, ensure_ascii=False, indent=2)
        
        return (True, date, None)
    except Exception as e:
        return (False, date, str(e))


class LearningCaseCalculator:
    """学习案例计算器"""
    
    def __init__(self, processed_path='processed_data', 
                 index_path='strategy_index', 
                 output_path='learning_cases',
                 log_path='data'):
        self.processed_path = processed_path
        self.index_path = index_path
        self.output_path = output_path
        self.log_path = log_path
        
        # 确保目录存在
        ensure_dir(f"{self.output_path}/B1")
        ensure_dir(f"{self.output_path}/B2")
        ensure_dir(f"{self.output_path}/brick")
        ensure_dir(f"{self.output_path}/single_needle")
        ensure_dir(self.log_path)
        
        # 统计信息
        self.total_dates = 0
        self.processed_dates = 0
        self.failed_dates = []
        
        # 支持的计算周期
        self.periods = [3, 5, 10]
        
        # 添加缓存：避免重复读取相同股票数据
        self.stock_data_cache = {}
        self.cache_hits = 0
        self.cache_misses = 0
    
    def get_trading_dates(self, stock_code: str) -> List[str]:
        """获取交易日序列（从任一股票文件）"""
        try:
            df = pd.read_csv(f'{self.processed_path}/{stock_code}.csv', usecols=['date'])
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
            return sorted(df['date'].tolist())
        except Exception as e:
            log_message(f"获取交易日序列失败: {str(e)}", 'ERROR')
            return []
    
    def load_stock_data(self, stock_code: str) -> pd.DataFrame:
        """
        加载股票数据（带缓存）
        
        Args:
            stock_code: 股票代码
            
        Returns:
            DataFrame 或 None
        """
        # 检查缓存
        if stock_code in self.stock_data_cache:
            self.cache_hits += 1
            return self.stock_data_cache[stock_code]
        
        self.cache_misses += 1
        
        try:
            df = pd.read_csv(f'{self.processed_path}/{stock_code}.csv')
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
            
            # 缓存数据（大内存优化：缓存所有股票）
            self.stock_data_cache[stock_code] = df
            
            return df
        except Exception as e:
            return None
    
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
    
    def calc_all_periods_return(self, stock_code: str, start_date: str) -> Dict[int, Tuple]:
        """
        一次性计算所有周期的收益（优化性能）
        
        Args:
            stock_code: 股票代码
            start_date: 起始日期
            
        Returns:
            {3: (return_pct, max_date, start_price, max_price), 5: (...), 10: (...)}
        """
        try:
            df = self.load_stock_data(stock_code)
            if df is None or df.empty:
                return {}
            
            # 找到起始日期的索引
            start_idx = df[df['date'] == start_date].index
            if len(start_idx) == 0:
                return {}
            
            start_idx = start_idx[0]
            start_price = df.iloc[start_idx]['close']
            
            # 一次遍历，同时计算所有周期
            max_period = max(self.periods)  # 10
            results = {}
            
            # 为每个周期初始化跟踪变量
            period_trackers = {
                period: {
                    'max_price': start_price,
                    'max_date': start_date,
                    'valid_days': 0,
                    'completed': False
                }
                for period in self.periods
            }
            
            valid_days = 0
            for i in range(start_idx + 1, len(df)):
                row = df.iloc[i]
                
                # 检查是否可交易
                if row.get('can_trade', 1) == 1 and row['volumn'] > 0:
                    valid_days += 1
                    current_close = row['close']
                    current_date = row['date']
                    
                    # 更新所有未完成周期的最高价
                    for period in self.periods:
                        tracker = period_trackers[period]
                        if not tracker['completed']:
                            tracker['valid_days'] = valid_days
                            if current_close > tracker['max_price']:
                                tracker['max_price'] = current_close
                                tracker['max_date'] = current_date
                            
                            # 检查是否达到该周期
                            if valid_days == period:
                                tracker['completed'] = True
                                max_price = tracker['max_price']
                                max_date = tracker['max_date']
                                return_pct = (max_price - start_price) / start_price * 100
                                results[period] = (return_pct, max_date, start_price, max_price)
                    
                    # 如果所有周期都完成了，提前退出
                    if all(tracker['completed'] for tracker in period_trackers.values()):
                        break
                    
                    # 如果已经超过最大周期，也退出
                    if valid_days >= max_period:
                        break
            
            # 处理未完成的周期（数据不足）
            for period in self.periods:
                if period not in results and period_trackers[period]['valid_days'] > 0:
                    tracker = period_trackers[period]
                    max_price = tracker['max_price']
                    max_date = tracker['max_date']
                    return_pct = (max_price - start_price) / start_price * 100
                    results[period] = (return_pct, max_date, start_price, max_price)
            
            return results
            
        except Exception as e:
            return {}
    
    def calc_n_day_return(self, stock_code: str, start_date: str, n_days: int) -> Tuple[float, str, float, float]:
        """
        计算N个交易日内的最高涨幅
        
        Args:
            stock_code: 股票代码
            start_date: 起始日期（YYYYMMDD）
            n_days: 交易日数量
            
        Returns:
            (涨幅百分比, 最高价格日期, 起始价格, 最高价格) 或 (None, None, None, None) 表示数据不足
        """
        try:
            # 使用缓存加载数据
            df = self.load_stock_data(stock_code)
            if df is None or df.empty:
                return None, None, None, None
            
            # 找到起始日期的索引
            start_idx = df[df['date'] == start_date].index
            if len(start_idx) == 0:
                return None, None, None, None
            
            start_idx = start_idx[0]
            start_price = df.iloc[start_idx]['close']
            
            # 向后查找N个有数据的交易日（跳过停牌），记录期间最高收盘价
            valid_days = 0
            max_price = start_price
            max_price_date = start_date
            
            for i in range(start_idx + 1, len(df)):
                row = df.iloc[i]
                # 检查是否可交易（有成交量）
                if row.get('can_trade', 1) == 1 and row['volumn'] > 0:
                    valid_days += 1
                    current_close = row['close']
                    current_date = row['date']
                    
                    # 更新最高价格
                    if current_close > max_price:
                        max_price = current_close
                        max_price_date = current_date
                    
                    # 达到N个交易日后结束
                    if valid_days == n_days:
                        break
            
            # 如果找到了有效的交易日数据
            if valid_days > 0:
                return_pct = (max_price - start_price) / start_price * 100
                return return_pct, max_price_date, start_price, max_price
            
            # 数据不足
            return None, None, None, None
            
        except Exception as e:
            return None, None, None, None
    
    def calc_learning_cases_for_date(self, date: str, strategy: str) -> Dict:
        """
        计算指定日期和策略的学习案例（按市场分组）
        
        Args:
            date: 日期（YYYYMMDD）
            strategy: 策略名称
            
        Returns:
            学习案例数据
        """
        try:
            # 读取当日的策略候选池
            index_file = f'{self.index_path}/{strategy}/{date}.json'
            if not os.path.exists(index_file):
                return {
                    'date': date,
                    'strategy': strategy,
                    'total_candidates': 0,
                    'market_groups': {
                        'A': {'name': '主板(00/60)', 'total': 0, 'top_cases': {f'{p}d': [] for p in self.periods}},
                        'B': {'name': '创业板/科创板/北交所(30/68/92)', 'total': 0, 'top_cases': {f'{p}d': [] for p in self.periods}}
                    }
                }
            
            with open(index_file, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
            
            candidates = index_data.get('stocks', [])
            if len(candidates) == 0:
                return {
                    'date': date,
                    'strategy': strategy,
                    'total_candidates': 0,
                    'market_groups': {
                        'A': {'name': '主板(00/60)', 'total': 0, 'top_cases': {f'{p}d': [] for p in self.periods}},
                        'B': {'name': '创业板/科创板/北交所(30/68/92)', 'total': 0, 'top_cases': {f'{p}d': [] for p in self.periods}}
                    }
                }
            
            # 按市场分组
            market_groups = {
                'A': [],  # 主板 (00/60)
                'B': []   # 创业板/科创板/北交所 (30/68/92)
            }
            
            for stock_code in candidates:
                group = self.get_stock_market_group(stock_code)
                market_groups[group].append(stock_code)
            
            # 对每个市场分组的每个周期计算涨幅
            result_groups = {
                'A': {
                    'name': '主板(00/60)',
                    'total': len(market_groups['A']),
                    'top_cases': {}
                },
                'B': {
                    'name': '创业板/科创板/北交所(30/68/92)',
                    'total': len(market_groups['B']),
                    'top_cases': {}
                }
            }
            
            # 优化：对每只股票一次性计算所有周期，避免重复读取
            for group_key, stocks in market_groups.items():
                # 为每个周期初始化列表
                period_returns = {period: [] for period in self.periods}
                
                # 对每只股票计算所有周期的收益
                for stock_code in stocks:
                    all_returns = self.calc_all_periods_return(stock_code, date)
                    
                    for period in self.periods:
                        if period in all_returns:
                            return_pct, max_date, start_price, max_price = all_returns[period]
                            period_returns[period].append({
                                'stock_code': stock_code,
                                'start_price': round(start_price, 2),
                                'max_price': round(max_price, 2),
                                'return_pct': round(return_pct, 2),
                                'max_date': max_date,
                                'trading_days': period
                            })
                
                # 对每个周期排序并取TOP3
                for period in self.periods:
                    period_returns[period].sort(key=lambda x: x['return_pct'], reverse=True)
                    result_groups[group_key]['top_cases'][f'{period}d'] = period_returns[period][:3]
            
            return {
                'date': date,
                'strategy': strategy,
                'total_candidates': len(candidates),
                'market_groups': result_groups
            }
            
        except Exception as e:
            log_message(f"计算日期 {date} 策略 {strategy} 的学习案例失败: {str(e)}", 'ERROR')
            traceback.print_exc()
            return {
                'date': date,
                'strategy': strategy,
                'total_candidates': 0,
                'market_groups': {
                    'A': {'name': '主板(00/60)', 'total': 0, 'top_cases': {f'{p}d': [] for p in self.periods}},
                    'B': {'name': '创业板/科创板/北交所(30/68/92)', 'total': 0, 'top_cases': {f'{p}d': [] for p in self.periods}}
                },
                'error': str(e)
            }
    
    def process_all_strategies(self, use_multiprocess=False, num_workers=None):
        """
        处理所有策略的所有日期
        
        Args:
            use_multiprocess: 是否使用多进程加速
            num_workers: 进程数（None表示自动检测）
        """
        start_time = datetime.now()
        log_message("开始计算学习案例...")
        
        if use_multiprocess:
            if num_workers is None:
                num_workers = min(cpu_count(), 8)  # 最多8个进程
            log_message(f"多进程模式已启用 (进程数: {num_workers})")
        else:
            log_message("单进程模式")
        
        strategies = ['B1', 'B2', 'brick', 'single_needle']
        
        # 获取交易日序列（使用第一个股票文件）
        sample_files = [f for f in os.listdir(self.processed_path) if f.endswith('.csv')]
        if not sample_files:
            log_message("未找到处理后的股票数据", 'ERROR')
            return
        
        sample_stock = sample_files[0].replace('.csv', '')
        trading_dates = self.get_trading_dates(sample_stock)
        
        if not trading_dates:
            log_message("获取交易日序列失败", 'ERROR')
            return
        
        log_message(f"发现 {len(trading_dates)} 个交易日")
        
        # 对每个策略的每个日期计算学习案例
        for strategy in strategies:
            log_message(f"\n处理策略: {strategy}")
            
            # 获取该策略的所有日期索引
            strategy_index_dir = f'{self.index_path}/{strategy}'
            if not os.path.exists(strategy_index_dir):
                log_message(f"策略 {strategy} 的索引目录不存在，跳过", 'WARNING')
                continue
            
            index_files = [f.replace('.json', '') for f in os.listdir(strategy_index_dir) if f.endswith('.json')]
            self.total_dates += len(index_files)
            
            log_message(f"策略 {strategy} 共有 {len(index_files)} 个交易日")
            
            if use_multiprocess:
                # 多进程模式
                log_message(f"使用多进程处理 (进程数: {num_workers})")
                
                # 准备参数
                args_list = [
                    (date, strategy, self.processed_path, self.index_path, 
                     self.output_path, self.periods)
                    for date in index_files
                ]
                
                # 使用进程池处理
                with Pool(processes=num_workers) as pool:
                    results = pool.map(process_single_date_worker, args_list)
                    
                    # 统计结果
                    for i, (success, date, error_msg) in enumerate(results, 1):
                        if success:
                            self.processed_dates += 1
                        else:
                            self.failed_dates.append({
                                'date': date,
                                'strategy': strategy,
                                'error': error_msg
                            })
                        
                        # 进度显示
                        if i % 100 == 0 or i == len(index_files):
                            log_message(f"进度: {i}/{len(index_files)} ({i/len(index_files)*100:.1f}%)")
            else:
                # 单进程模式（原有逻辑，带缓存优化）
                for i, date in enumerate(index_files, 1):
                    try:
                        # 计算学习案例
                        learning_case = self.calc_learning_cases_for_date(date, strategy)
                        
                        # 保存到JSON文件
                        output_file = f'{self.output_path}/{strategy}/{date}.json'
                        with open(output_file, 'w', encoding='utf-8') as f:
                            json.dump(learning_case, f, ensure_ascii=False, indent=2)
                        
                        self.processed_dates += 1
                        
                        # 进度显示（每50个或每10%显示）
                        if i % 50 == 0 or i == len(index_files):
                            cache_hit_rate = self.cache_hits / (self.cache_hits + self.cache_misses) * 100 if (self.cache_hits + self.cache_misses) > 0 else 0
                            log_message(f"进度: {i}/{len(index_files)} ({i/len(index_files)*100:.1f}%) - 缓存命中率: {cache_hit_rate:.1f}%")
                        
                    except Exception as e:
                        log_message(f"处理日期 {date} 失败: {str(e)}", 'ERROR')
                        self.failed_dates.append({
                            'date': date,
                            'strategy': strategy,
                            'error': str(e)
                        })
        
        # 保存日志
        self.save_logs()
        
        # 统计信息
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        print("\n" + "="*60)
        log_message("学习案例计算完成！", 'INFO')
        print("="*60)
        print(f"总日期数: {self.total_dates}")
        print(f"成功处理: {self.processed_dates}")
        print(f"失败数量: {len(self.failed_dates)}")
        print(f"缓存命中: {self.cache_hits} 次")
        print(f"缓存未命中: {self.cache_misses} 次")
        cache_hit_rate = self.cache_hits / (self.cache_hits + self.cache_misses) * 100 if (self.cache_hits + self.cache_misses) > 0 else 0
        print(f"缓存命中率: {cache_hit_rate:.1f}%")
        print(f"耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
        print("="*60)
        
        if self.failed_dates:
            print("\n失败日期:")
            for item in self.failed_dates[:10]:
                print(f"  - {item['date']} ({item['strategy']}): {item['error']}")
            if len(self.failed_dates) > 10:
                print(f"  ... 还有 {len(self.failed_dates)-10} 个")
        
        print(f"\n详细日志已保存到 {self.log_path}/")
    
    def save_logs(self):
        """保存处理日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 更新日志
        log_file = f'{self.log_path}/learning_cases_log.txt'
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{timestamp}] 学习案例计算完成\n")
            f.write(f"总日期数: {self.total_dates}\n")
            f.write(f"成功处理: {self.processed_dates}\n")
            f.write(f"失败数量: {len(self.failed_dates)}\n")
            
            if self.failed_dates:
                f.write(f"\n失败日期列表:\n")
                for item in self.failed_dates:
                    f.write(f"  - {item['date']} ({item['strategy']}): {item['error']}\n")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='计算学习案例（优秀案例）')
    parser.add_argument('--processed', type=str, default='processed_data', help='处理后数据目录')
    parser.add_argument('--index', type=str, default='strategy_index', help='策略索引目录')
    parser.add_argument('--output', type=str, default='learning_cases', help='学习案例输出目录')
    parser.add_argument('--log', type=str, default='data', help='日志目录')
    parser.add_argument('--multiprocess', action='store_true', help='使用多进程加速')
    parser.add_argument('--workers', type=int, default=None, help='进程数（默认自动检测，最多8个）')
    
    args = parser.parse_args()
    
    # 创建计算器并运行
    calculator = LearningCaseCalculator(
        processed_path=args.processed,
        index_path=args.index,
        output_path=args.output,
        log_path=args.log
    )
    
    calculator.process_all_strategies(
        use_multiprocess=args.multiprocess,
        num_workers=args.workers
    )


if __name__ == '__main__':
    main()
