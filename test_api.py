#!/usr/bin/env python3
"""
API功能测试脚本

测试数据库版API的基本功能
"""

import requests
import json
import sys
from datetime import datetime

# API基础URL
BASE_URL = "http://127.0.0.1:8000"

def test_health_check():
    """测试健康检查"""
    print("\n【1/6】测试健康检查...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        data = response.json()
        if data.get("status") == "ok":
            print("✅ 健康检查通过")
            return True
        else:
            print("❌ 健康检查失败")
            return False
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        print("   请确保后端服务已启动: cd backend && uvicorn app.main:app --reload")
        return False


def test_get_dates():
    """测试获取日期列表"""
    print("\n【2/6】测试获取日期列表...")
    try:
        response = requests.get(f"{BASE_URL}/api/dates?strategy=B1")
        data = response.json()
        if data.get("count", 0) > 0:
            print(f"✅ 获取日期成功: {data['count']} 个交易日")
            print(f"   最新日期: {data['dates'][0]}")
            return data['dates'][0]  # 返回最新日期用于后续测试
        else:
            print("❌ 无可用日期")
            return None
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return None


def test_get_picks(date):
    """测试获取候选池"""
    print(f"\n【3/6】测试获取候选池 (日期: {date})...")
    try:
        response = requests.get(f"{BASE_URL}/api/picks?date={date}&strategy=B1&filter_type=all")
        data = response.json()
        if data.get("count", 0) > 0:
            print(f"✅ 获取候选池成功: {data['count']} 只股票")
            print(f"   极致B1: {data.get('extreme_b1_count', 0)} 只")
            print(f"   示例股票: {data['stocks'][0]['code']}")
            return data['stocks'][0]['code']  # 返回第一只股票用于测试K线
        else:
            print("⚠️  候选池为空（该日期可能没有信号）")
            return None
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return None


def test_get_kline(code, date):
    """测试获取K线数据"""
    print(f"\n【4/6】测试获取K线数据 (股票: {code})...")
    try:
        response = requests.get(f"{BASE_URL}/api/stock/kline?code={code}&end_date={date}&limit=60")
        data = response.json()
        if data.get("count", 0) > 0:
            print(f"✅ 获取K线成功: {data['count']} 根K线")
            last_kline = data['klines'][-1]
            print(f"   最新收盘价: {last_kline['close']}")
            print(f"   最新日期: {last_kline['date']}")
            return True
        else:
            print("❌ K线数据为空")
            return False
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False


def test_backtest_flow(date):
    """测试回测流程"""
    print(f"\n【5/6】测试回测流程 (起始日期: {date})...")
    
    try:
        # 1. 开始回测
        print("   > 开始回测...")
        response = requests.post(f"{BASE_URL}/api/backtest/start", json={
            "start_date": date,
            "initial_capital": 1000000,
            "strategy": "B1"
        })
        data = response.json()
        session_id = data.get("session_id")
        
        if not session_id:
            print("❌ 创建会话失败")
            return False
        
        print(f"✅ 回测会话创建成功: {session_id}")
        
        # 2. 获取候选池
        print("   > 获取候选池...")
        response = requests.get(f"{BASE_URL}/api/backtest/candidates?session_id={session_id}&filter_type=all")
        data = response.json()
        
        if data.get("count", 0) == 0:
            print("⚠️  候选池为空，跳过交易测试")
            return True
        
        stock_code = data['stocks'][0]['code']
        print(f"✅ 候选池获取成功: {data['count']} 只股票，选择 {stock_code}")
        
        # 3. 执行买入
        print("   > 执行买入...")
        response = requests.post(f"{BASE_URL}/api/backtest/trade", json={
            "session_id": session_id,
            "action": "buy",
            "code": stock_code,
            "amount": 100000
        })
        data = response.json()
        
        if data.get("success"):
            print(f"✅ 买入成功: {data.get('message')}")
        else:
            print(f"❌ 买入失败: {data}")
            return False
        
        # 4. 推进到下一日
        print("   > 推进到下一日...")
        response = requests.post(f"{BASE_URL}/api/backtest/next", json={
            "session_id": session_id
        })
        data = response.json()
        
        if data.get("success"):
            print(f"✅ 推进成功: {data.get('message')}")
        else:
            print(f"⚠️  推进失败: {data.get('message')}")
        
        # 5. 结束回测
        print("   > 结束回测...")
        response = requests.post(f"{BASE_URL}/api/backtest/end", json={
            "session_id": session_id
        })
        data = response.json()
        
        if data.get("success"):
            summary = data.get("summary", {})
            print(f"✅ 回测结束")
            print(f"   初始资金: {summary.get('initial_capital')}")
            print(f"   最终权益: {summary.get('final_equity')}")
            print(f"   总收益率: {summary.get('total_return')}%")
            return True
        else:
            print(f"❌ 结束失败")
            return False
            
    except Exception as e:
        print(f"❌ 回测流程失败: {e}")
        return False


def test_performance_comparison():
    """测试性能对比（v1 vs v2）"""
    print("\n【6/6】性能对比测试...")
    
    # 获取一个测试日期
    try:
        response = requests.get(f"{BASE_URL}/api/dates?strategy=B1")
        data = response.json()
        if data.get("count", 0) == 0:
            print("⚠️  无可用日期，跳过性能测试")
            return
        
        test_date = data['dates'][0]
        
        # 测试v1（文件版）
        print(f"   > 测试v1（文件版）...")
        import time
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/v1/picks?date={test_date}&strategy=B1")
        v1_time = (time.time() - start) * 1000
        print(f"   v1 响应时间: {v1_time:.2f}ms")
        
        # 测试v2（数据库版）
        print(f"   > 测试v2（数据库版）...")
        start = time.time()
        response = requests.get(f"{BASE_URL}/api/picks?date={test_date}&strategy=B1")
        v2_time = (time.time() - start) * 1000
        print(f"   v2 响应时间: {v2_time:.2f}ms")
        
        # 计算提升
        if v2_time > 0:
            speedup = v1_time / v2_time
            print(f"✅ 性能提升: {speedup:.1f}x 倍")
        
    except Exception as e:
        print(f"⚠️  性能测试失败: {e}")


def main():
    """主函数"""
    print("="*60)
    print("API 功能测试")
    print("="*60)
    
    # 测试1: 健康检查
    if not test_health_check():
        sys.exit(1)
    
    # 测试2: 获取日期列表
    latest_date = test_get_dates()
    if not latest_date:
        print("\n❌ 无可用数据，请先运行数据迁移")
        sys.exit(1)
    
    # 测试3: 获取候选池
    stock_code = test_get_picks(latest_date)
    
    # 测试4: 获取K线（如果有股票代码）
    if stock_code:
        test_get_kline(stock_code, latest_date)
    
    # 测试5: 回测流程
    test_backtest_flow(latest_date)
    
    # 测试6: 性能对比
    test_performance_comparison()
    
    print("\n" + "="*60)
    print("🎉 所有测试完成！")
    print("="*60)


if __name__ == "__main__":
    main()
