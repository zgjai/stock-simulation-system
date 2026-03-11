"""计算因子并添加到processed_data的CSV文件中"""
import sys
import os
import pandas as pd
import numpy as np
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


class FactorCalculator:
    """因子计算器"""
    
    def __init__(self, processed_path='processed_data', log_path='data'):
        self.processed_path = processed_path
        self.log_path = log_path
        
        # 确保目录存在
        ensure_dir(self.log_path)
        
        # 统计信息
        self.total_stocks = 0
        self.processed_stocks = 0
        self.failed_stocks = []
    
    def calc_amplitude(self, df: pd.DataFrame) -> pd.Series:
        """
        计算当日振幅
        公式: (最高价 - 最低价) / 昨收价 * 100
        """
        amplitude = ((df['high'] - df['low']) / df['prev_close'] * 100).round(2)
        return amplitude
    
    def calc_volume_ratio(self, df: pd.DataFrame, window=60) -> pd.Series:
        """
        计算当日成交量 / N日均成交量比例
        
        Args:
            df: 数据框
            window: 均量周期，默认60日
        """
        vol_ma = df['volumn'].rolling(window=window, min_periods=1).mean()
        volume_ratio = (df['volumn'] / vol_ma).round(2)
        return volume_ratio
    
    def calc_wash_ratio(self, df: pd.DataFrame) -> pd.Series:
        """
        计算知行趋势线 / 知行多空线比例
        wash_short / wash_long
        """
        wash_ratio = (df['wash_short'] / df['wash_long']).round(4)
        # 处理除零情况
        wash_ratio = wash_ratio.replace([np.inf, -np.inf], np.nan)
        return wash_ratio
    
    def calc_j_value(self, df: pd.DataFrame) -> pd.Series:
        """
        J值（已存在于kdj_j列）
        直接返回，保留2位小数
        """
        return df['kdj_j'].round(2)
    
    def calc_close_change_from_prev(self, df: pd.DataFrame) -> pd.Series:
        """
        相对于昨日收盘价的涨跌幅
        公式: (收盘价 - 昨收价) / 昨收价 * 100
        """
        close_change = ((df['close'] - df['prev_close']) / df['prev_close'] * 100).round(2)
        return close_change
    
    def calc_close_change_from_open(self, df: pd.DataFrame) -> pd.Series:
        """
        相对于当日开盘价的涨跌幅
        公式: (收盘价 - 开盘价) / 开盘价 * 100
        """
        close_change = ((df['close'] - df['open']) / df['open'] * 100).round(2)
        return close_change
    
    def calc_body_ratio(self, df: pd.DataFrame) -> pd.Series:
        """
        K线实体比例
        公式: |收盘价 - 开盘价| / (最高价 - 最低价)
        表示K线实体占整个K线的比例，范围0-1
        """
        body = np.abs(df['close'] - df['open'])
        total_range = df['high'] - df['low']
        
        # 避免除零
        body_ratio = np.where(total_range > 0, body / total_range, 0)
        body_ratio = pd.Series(body_ratio, index=df.index).round(4)
        
        return body_ratio
    
    def calc_upper_shadow_ratio(self, df: pd.DataFrame) -> pd.Series:
        """
        上影线比例
        公式: (最高价 - max(开盘价, 收盘价)) / (最高价 - 最低价)
        表示上影线占整个K线的比例，范围0-1
        """
        upper_point = df[['open', 'close']].max(axis=1)
        upper_shadow = df['high'] - upper_point
        total_range = df['high'] - df['low']
        
        # 避免除零
        upper_shadow_ratio = np.where(total_range > 0, upper_shadow / total_range, 0)
        upper_shadow_ratio = pd.Series(upper_shadow_ratio, index=df.index).round(4)
        
        return upper_shadow_ratio
    
    def calc_lower_shadow_ratio(self, df: pd.DataFrame) -> pd.Series:
        """
        下影线比例
        公式: (min(开盘价, 收盘价) - 最低价) / (最高价 - 最低价)
        表示下影线占整个K线的比例，范围0-1
        """
        lower_point = df[['open', 'close']].min(axis=1)
        lower_shadow = lower_point - df['low']
        total_range = df['high'] - df['low']
        
        # 避免除零
        lower_shadow_ratio = np.where(total_range > 0, lower_shadow / total_range, 0)
        lower_shadow_ratio = pd.Series(lower_shadow_ratio, index=df.index).round(4)
        
        return lower_shadow_ratio
    
    def calc_close_position(self, df: pd.DataFrame) -> pd.Series:
        """
        收盘价在日内的位置
        公式: (收盘价 - 最低价) / (最高价 - 最低价)
        0表示收在最低，1表示收在最高，0.5表示收在中间
        """
        close_pos = df['close'] - df['low']
        total_range = df['high'] - df['low']
        
        # 避免除零
        close_position = np.where(total_range > 0, close_pos / total_range, 0.5)
        close_position = pd.Series(close_position, index=df.index).round(4)
        
        return close_position
    
    def calc_consecutive_small_amplitude(self, df: pd.DataFrame, threshold=3.0) -> pd.Series:
        """
        连续小振幅天数
        计算当前日期之前（包括当日）连续多少天振幅小于阈值（默认3%）
        
        Args:
            df: 数据框
            threshold: 振幅阈值（百分比），默认3.0
        """
        # 先计算振幅
        amplitude = self.calc_amplitude(df)
        
        # 判断是否为小振幅（小于阈值）
        is_small_amp = (amplitude < threshold).astype(int)
        
        # 计算连续小振幅天数
        consecutive_days = []
        count = 0
        
        for val in is_small_amp:
            if val == 1:
                count += 1
            else:
                count = 0
            consecutive_days.append(count)
        
        return pd.Series(consecutive_days, index=df.index)
    
    def process_stock(self, stock_code: str) -> bool:
        """
        处理单个股票，计算并添加因子列
        
        Args:
            stock_code: 股票代码（不带.csv后缀）
            
        Returns:
            是否处理成功
        """
        try:
            csv_file = f'{self.processed_path}/{stock_code}.csv'
            
            # 读取CSV
            df = pd.read_csv(csv_file)
            
            # 计算所有因子
            log_message(f"正在计算 {stock_code} 的因子...")
            
            # 1. 当日振幅
            df['factor_amplitude'] = self.calc_amplitude(df)
            
            # 2. 成交量比率（当日成交量/60日均成交量）
            df['factor_volume_ratio'] = self.calc_volume_ratio(df, window=60)
            
            # 3. 知行比率（趋势线/多空线）
            df['factor_wash_ratio'] = self.calc_wash_ratio(df)
            
            # 4. J值
            df['factor_j_value'] = self.calc_j_value(df)
            
            # 5. 相对昨收涨跌幅
            df['factor_close_change_prev'] = self.calc_close_change_from_prev(df)
            
            # 6. 相对今开涨跌幅
            df['factor_close_change_open'] = self.calc_close_change_from_open(df)
            
            # 7. K线实体比例
            df['factor_body_ratio'] = self.calc_body_ratio(df)
            
            # 8. 上影线比例
            df['factor_upper_shadow'] = self.calc_upper_shadow_ratio(df)
            
            # 9. 下影线比例
            df['factor_lower_shadow'] = self.calc_lower_shadow_ratio(df)
            
            # 10. 收盘价位置
            df['factor_close_position'] = self.calc_close_position(df)
            
            # 11. 连续小振幅天数
            df['factor_consecutive_small_amp'] = self.calc_consecutive_small_amplitude(df, threshold=3.0)
            
            # 保存回CSV
            df.to_csv(csv_file, index=False)
            
            self.processed_stocks += 1
            return True
            
        except Exception as e:
            log_message(f"处理 {stock_code} 失败: {str(e)}", 'ERROR')
            traceback.print_exc()
            self.failed_stocks.append({
                'stock_code': stock_code,
                'error': str(e)
            })
            return False
    
    def process_all_stocks(self):
        """处理所有股票"""
        start_time = datetime.now()
        log_message("开始计算因子...")
        
        # 获取所有CSV文件
        csv_files = [f for f in os.listdir(self.processed_path) if f.endswith('.csv')]
        self.total_stocks = len(csv_files)
        
        if self.total_stocks == 0:
            log_message("未找到处理后的股票数据", 'ERROR')
            return
        
        log_message(f"发现 {self.total_stocks} 个股票文件")
        
        # 逐个处理
        for i, csv_file in enumerate(csv_files, 1):
            stock_code = csv_file.replace('.csv', '')
            
            self.process_stock(stock_code)
            
            # 进度显示
            if i % 100 == 0:
                log_message(f"进度: {i}/{self.total_stocks} ({i/self.total_stocks*100:.1f}%)")
        
        # 保存日志
        self.save_logs()
        
        # 统计信息
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        print("\n" + "="*60)
        log_message("因子计算完成！", 'INFO')
        print("="*60)
        print(f"总股票数: {self.total_stocks}")
        print(f"成功处理: {self.processed_stocks}")
        print(f"失败数量: {len(self.failed_stocks)}")
        print(f"耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
        print("="*60)
        
        if self.failed_stocks:
            print("\n失败股票:")
            for item in self.failed_stocks[:10]:
                print(f"  - {item['stock_code']}: {item['error']}")
            if len(self.failed_stocks) > 10:
                print(f"  ... 还有 {len(self.failed_stocks)-10} 个")
        
        print(f"\n详细日志已保存到 {self.log_path}/")
        
        # 显示新增的因子列
        print("\n新增的因子列:")
        print("  1. factor_amplitude - 当日振幅")
        print("  2. factor_volume_ratio - 成交量/60日均量")
        print("  3. factor_wash_ratio - 知行趋势线/多空线")
        print("  4. factor_j_value - J值")
        print("  5. factor_close_change_prev - 相对昨收涨跌幅")
        print("  6. factor_close_change_open - 相对今开涨跌幅")
        print("  7. factor_body_ratio - K线实体比例")
        print("  8. factor_upper_shadow - 上影线比例")
        print("  9. factor_lower_shadow - 下影线比例")
        print(" 10. factor_close_position - 收盘价在日内位置")
        print(" 11. factor_consecutive_small_amp - 连续小振幅天数")
    
    def save_logs(self):
        """保存处理日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 更新日志
        log_file = f'{self.log_path}/factor_calculation_log.txt'
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"[{timestamp}] 因子计算完成\n")
            f.write(f"总股票数: {self.total_stocks}\n")
            f.write(f"成功处理: {self.processed_stocks}\n")
            f.write(f"失败数量: {len(self.failed_stocks)}\n")
            
            if self.failed_stocks:
                f.write(f"\n失败股票列表:\n")
                for item in self.failed_stocks:
                    f.write(f"  - {item['stock_code']}: {item['error']}\n")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='计算因子并添加到processed_data')
    parser.add_argument('--processed', type=str, default='processed_data', help='处理后数据目录')
    parser.add_argument('--log', type=str, default='data', help='日志目录')
    
    args = parser.parse_args()
    
    # 创建计算器并运行
    calculator = FactorCalculator(
        processed_path=args.processed,
        log_path=args.log
    )
    
    calculator.process_all_stocks()


if __name__ == '__main__':
    main()
