"""预处理样本股票（用于快速测试）"""
import sys
import os
from pathlib import Path

# 切换到项目根目录
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

sys.path.append(str(Path(__file__).parent))

from preprocess_all import StockPreprocessor
from utils import log_message

def main():
    """处理样本股票"""
    # 测试股票列表（主板、创业板、科创板、北交所各选几只）
    sample_stocks = [
        '000001',  # 平安银行（主板）
        '000002',  # 万科A（主板）
        '600519',  # 贵州茅台（主板）
        '300750',  # 宁德时代（创业板）
        '688981',  # 中芯国际（科创板）
    ]
    
    log_message(f"处理样本股票: {', '.join(sample_stocks)}")
    
    preprocessor = StockPreprocessor()
    preprocessor.total_stocks = len(sample_stocks)
    
    for i, stock_code in enumerate(sample_stocks, 1):
        log_message(f"处理 {i}/{len(sample_stocks)}: {stock_code}")
        success = preprocessor.process_single_stock(stock_code)
        if not success:
            log_message(f"失败: {stock_code}", 'ERROR')
    
    # 保存策略索引
    preprocessor.save_strategy_index()
    
    # 保存日志
    preprocessor.save_logs()
    
    print("\n" + "="*60)
    log_message("样本处理完成！")
    print("="*60)
    print(f"总数: {preprocessor.total_stocks}")
    print(f"成功: {preprocessor.processed_stocks}")
    print(f"失败: {len(preprocessor.failed_stocks)}")
    print(f"异常数据: {len(preprocessor.anomaly_records)} 条")
    print("="*60)

if __name__ == '__main__':
    main()
