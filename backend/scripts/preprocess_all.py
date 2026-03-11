"""批量预处理所有股票数据"""
import sys
import os
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Set
import traceback

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

# 添加脚本目录到路径
sys.path.append(str(Path(__file__).parent))

from indicators import add_all_indicators
from strategies import add_strategy_signals
from utils import (
    detect_anomaly, 
    get_stock_code_from_filename, 
    ensure_dir,
    log_message
)


class StockPreprocessor:
    """股票数据预处理器"""
    
    def __init__(self, origin_path='origin_data', processed_path='processed_data', 
                 index_path='strategy_index', log_path='data'):
        self.origin_path = origin_path
        self.processed_path = processed_path
        self.index_path = index_path
        self.log_path = log_path
        
        # 确保目录存在
        ensure_dir(self.processed_path)
        ensure_dir(f"{self.index_path}/B1")
        ensure_dir(f"{self.index_path}/B2")
        ensure_dir(f"{self.index_path}/brick")
        ensure_dir(f"{self.index_path}/single_needle")
        ensure_dir(self.log_path)
        
        # 统计信息
        self.total_stocks = 0
        self.processed_stocks = 0
        self.failed_stocks = []
        self.anomaly_records = []
        
        # 策略索引（按日期组织）
        self.strategy_index = {
            'B1': {},
            'B2': {},
            'brick': {},
            'single_needle': {}
        }
    
    def process_single_stock(self, stock_code: str) -> bool:
        """
        处理单个股票
        
        Args:
            stock_code: 股票代码
            
        Returns:
            是否处理成功
        """
        try:
            # 1. 读取原始数据
            input_file = f'{self.origin_path}/price_{stock_code}.csv'
            df = pd.read_csv(input_file)
            
            # 重命名列
            df.rename(columns={'timetag': 'date'}, inplace=True)
            df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
            df = df.sort_values('date').reset_index(drop=True)
            
            # 2. 检测异常数据
            df['prev_close'] = df['close'].shift(1)
            for idx, row in df.iterrows():
                is_anomaly, reason = detect_anomaly(row)
                if is_anomaly:
                    date_str = row['date'].strftime('%Y-%m-%d')
                    self.anomaly_records.append({
                        'stock_code': stock_code,
                        'date': date_str,
                        'reason': reason
                    })
                    # 标记为不可交易
                    df.at[idx, 'can_trade'] = 0
            
            # 3. 计算指标
            df = add_all_indicators(df, stock_code)
            
            # 4. 计算策略
            df = add_strategy_signals(df)
            
            # 5. 保存增强CSV
            output_file = f'{self.processed_path}/{stock_code}.csv'
            df.to_csv(output_file, index=False, date_format='%Y-%m-%d')
            
            # 6. 更新策略索引
            self._update_strategy_index(stock_code, df)
            
            self.processed_stocks += 1
            return True
            
        except Exception as e:
            log_message(f"处理失败 {stock_code}: {str(e)}", 'ERROR')
            self.failed_stocks.append({
                'stock_code': stock_code,
                'error': str(e),
                'traceback': traceback.format_exc()
            })
            return False
    
    def _update_strategy_index(self, stock_code: str, df: pd.DataFrame):
        """
        更新策略索引
        
        Args:
            stock_code: 股票代码
            df: 包含策略信号的DataFrame
        """
        # B1策略
        b1_dates = df[df['b1_signal'] == 1]['date'].dt.strftime('%Y%m%d').tolist()
        for date in b1_dates:
            if date not in self.strategy_index['B1']:
                self.strategy_index['B1'][date] = []
            self.strategy_index['B1'][date].append(stock_code)
        
        # B2策略
        b2_dates = df[df['b2_signal'] == 1]['date'].dt.strftime('%Y%m%d').tolist()
        for date in b2_dates:
            if date not in self.strategy_index['B2']:
                self.strategy_index['B2'][date] = []
            self.strategy_index['B2'][date].append(stock_code)
        
        # 砖型选股策略
        if 'brick_signal' in df.columns:
            brick_dates = df[df['brick_signal'] == 1]['date'].dt.strftime('%Y%m%d').tolist()
            for date in brick_dates:
                if date not in self.strategy_index['brick']:
                    self.strategy_index['brick'][date] = []
                self.strategy_index['brick'][date].append(stock_code)
        
        # 单针策略
        sn_dates = df[df['single_needle_signal'] == 1]['date'].dt.strftime('%Y%m%d').tolist()
        for date in sn_dates:
            if date not in self.strategy_index['single_needle']:
                self.strategy_index['single_needle'][date] = []
            self.strategy_index['single_needle'][date].append(stock_code)
    
    def save_strategy_index(self):
        """保存策略索引到JSON文件"""
        log_message("保存策略索引...")
        
        for strategy_name, date_dict in self.strategy_index.items():
            for date, stock_list in date_dict.items():
                index_file = f'{self.index_path}/{strategy_name}/{date}.json'
                data = {
                    'date': date,
                    'strategy': strategy_name,
                    'stocks': sorted(stock_list),
                    'count': len(stock_list)
                }
                with open(index_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 统计索引文件数量
        total_index_files = sum(len(date_dict) for date_dict in self.strategy_index.values())
        log_message(f"策略索引保存完成，共 {total_index_files} 个文件")
    
    def save_logs(self):
        """保存处理日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 更新日志
        update_log_file = f'{self.log_path}/update_log.txt'
        with open(update_log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{timestamp}] 批量预处理完成\n")
            f.write(f"总股票数: {self.total_stocks}\n")
            f.write(f"成功处理: {self.processed_stocks}\n")
            f.write(f"失败数量: {len(self.failed_stocks)}\n")
            f.write(f"异常数据: {len(self.anomaly_records)} 条\n")
            
            if self.failed_stocks:
                f.write(f"\n失败股票列表:\n")
                for item in self.failed_stocks:
                    f.write(f"  - {item['stock_code']}: {item['error']}\n")
        
        # 异常数据日志
        if self.anomaly_records:
            anomaly_log_file = f'{self.log_path}/anomaly_log.txt'
            with open(anomaly_log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{timestamp}] 异常数据记录\n")
                for record in self.anomaly_records:
                    f.write(f"{record['stock_code']} | {record['date']} | {record['reason']}\n")
        
        # 失败详情日志
        if self.failed_stocks:
            failed_log_file = f'{self.log_path}/failed_log.txt'
            with open(failed_log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"[{timestamp}] 失败详情\n")
                for item in self.failed_stocks:
                    f.write(f"\n股票: {item['stock_code']}\n")
                    f.write(f"错误: {item['error']}\n")
                    f.write(f"堆栈:\n{item['traceback']}\n")
    
    def process_all(self):
        """批量处理所有股票"""
        start_time = datetime.now()
        log_message("开始批量预处理...")
        
        # 获取所有原始数据文件
        stock_files = sorted([f for f in os.listdir(self.origin_path) if f.endswith('.csv')])
        self.total_stocks = len(stock_files)
        
        log_message(f"发现 {self.total_stocks} 个股票数据文件")
        
        # 逐个处理
        for i, filename in enumerate(stock_files, 1):
            stock_code = get_stock_code_from_filename(filename)
            
            if i % 100 == 0:
                log_message(f"进度: {i}/{self.total_stocks} ({i/self.total_stocks*100:.1f}%)")
            
            self.process_single_stock(stock_code)
        
        # 保存策略索引
        self.save_strategy_index()
        
        # 保存日志
        self.save_logs()
        
        # 统计信息
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        print("\n" + "="*60)
        log_message("批量预处理完成！", 'INFO')
        print("="*60)
        print(f"总股票数: {self.total_stocks}")
        print(f"成功处理: {self.processed_stocks}")
        print(f"失败数量: {len(self.failed_stocks)}")
        print(f"异常数据: {len(self.anomaly_records)} 条")
        print(f"耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
        print("="*60)
        
        if self.failed_stocks:
            print("\n失败股票:")
            for item in self.failed_stocks[:10]:  # 只显示前10个
                print(f"  - {item['stock_code']}: {item['error']}")
            if len(self.failed_stocks) > 10:
                print(f"  ... 还有 {len(self.failed_stocks)-10} 个")
        
        print(f"\n详细日志已保存到 {self.log_path}/")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='批量预处理所有股票数据')
    parser.add_argument('--origin', type=str, default='origin_data', help='原始数据目录')
    parser.add_argument('--processed', type=str, default='processed_data', help='处理后数据目录')
    parser.add_argument('--index', type=str, default='strategy_index', help='策略索引目录')
    parser.add_argument('--log', type=str, default='data', help='日志目录')
    
    args = parser.parse_args()
    
    # 创建预处理器并运行
    preprocessor = StockPreprocessor(
        origin_path=args.origin,
        processed_path=args.processed,
        index_path=args.index,
        log_path=args.log
    )
    
    preprocessor.process_all()


if __name__ == '__main__':
    main()
