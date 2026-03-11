"""测试API接口"""
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_basic_apis():
    """测试基础API"""
    print("\n" + "="*60)
    print("测试基础API")
    print("="*60)
    
    # 1. 健康检查
    print("\n1. 健康检查...")
    resp = requests.get(f"{BASE_URL}/health")
    print(f"   状态: {resp.json()}")
    
    # 2. 获取策略列表
    print("\n2. 获取策略列表...")
    resp = requests.get(f"{BASE_URL}/api/strategies")
    data = resp.json()
    print(f"   策略数量: {len(data['strategies'])}")
    for s in data['strategies']:
        print(f"   - {s['id']}: {s['name']}")
    
    # 3. 获取股票列表
    print("\n3. 获取股票列表...")
    resp = requests.get(f"{BASE_URL}/api/stock/list")
    data = resp.json()
    print(f"   股票数量: {data['count']}")
    print(f"   示例: {data['stocks'][:5]}")
    
    # 4. 获取交易日
    print("\n4. 获取交易日列表...")
    resp = requests.get(f"{BASE_URL}/api/trade-dates")
    data = resp.json()
    print(f"   交易日数量: {data['count']}")
    print(f"   时间范围: {data['start']} ~ {data['end']}")


def test_strategy_api():
    """测试策略API"""
    print("\n" + "="*60)
    print("测试策略API")
    print("="*60)
    
    # 获取候选池
    print("\n1. 获取B1策略候选池（2025-12-31）...")
    resp = requests.get(f"{BASE_URL}/api/picks", params={
        "date": "20251231",
        "strategy": "B1"
    })
    data = resp.json()
    print(f"   候选池数量: {data['count']}")
    if data['stocks']:
        print(f"   示例股票: {data['stocks'][0]}")
    
    # 获取K线
    print("\n2. 获取K线数据（000001，截至2025-12-31）...")
    resp = requests.get(f"{BASE_URL}/api/stock/kline", params={
        "code": "000001",
        "end_date": "20251231",
        "limit": 5
    })
    data = resp.json()
    print(f"   K线数量: {data['count']}")
    if data['klines']:
        print(f"   最后一根: {data['klines'][-1]['date']} 收盘价={data['klines'][-1]['close']}")


def test_backtest_api():
    """测试回测API"""
    print("\n" + "="*60)
    print("测试回测API")
    print("="*60)
    
    # 1. 开始回测
    print("\n1. 开始回测...")
    resp = requests.post(f"{BASE_URL}/api/backtest/start", json={
        "start_date": "20251201",
        "initial_capital": 1000000,
        "strategy": "B1"
    })
    data = resp.json()
    session_id = data['session_id']
    print(f"   会话ID: {session_id}")
    print(f"   初始资金: {data['state']['cash']}")
    
    # 2. 买入股票
    print("\n2. 买入股票...")
    resp = requests.post(f"{BASE_URL}/api/backtest/trade", json={
        "session_id": session_id,
        "action": "buy",
        "code": "000001",
        "amount": 100000
    })
    data = resp.json()
    print(f"   {data['message']}")
    print(f"   剩余现金: {data['state']['cash']:.2f}")
    
    # 3. 推进到下一日
    print("\n3. 推进到下一交易日...")
    resp = requests.post(f"{BASE_URL}/api/backtest/next-day", json={
        "session_id": session_id
    })
    data = resp.json()
    print(f"   当前日期: {data['current_date']}")
    print(f"   持仓数量: {len(data['positions'])}")
    if data['positions']:
        pos = data['positions'][0]
        print(f"   持仓详情: {pos['code']} {pos['shares']}股, 成本={pos['cost_price']}, 当前价={pos['current_price']}, 盈亏={pos['profit']}")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("API接口测试")
    print("请确保后端已启动: cd backend && python -m app.main")
    print("="*60)
    
    try:
        test_basic_apis()
        test_strategy_api()
        test_backtest_api()
        
        print("\n" + "="*60)
        print("✅ 所有测试通过！")
        print("="*60 + "\n")
        
    except requests.exceptions.ConnectionError:
        print("\n✗ 连接失败，请先启动后端服务")
        print("  启动命令: cd backend && python -m app.main\n")
    except Exception as e:
        print(f"\n✗ 测试失败: {e}\n")
