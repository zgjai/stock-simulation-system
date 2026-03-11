#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试历史记录优化功能
1. 测试删除功能
2. 测试最终权益计算（包含持仓市值）
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000/api"

def test_delete_history():
    """测试删除历史记录功能"""
    print("\n=== 测试删除历史记录功能 ===")
    
    # 1. 获取历史记录列表
    print("\n1. 获取历史记录...")
    response = requests.get(f"{BASE_URL}/backtest/history")
    if response.status_code == 200:
        data = response.json()
        history_list = data.get('history', [])
        print(f"   当前有 {len(history_list)} 条历史记录")
        
        if history_list:
            # 显示前3条
            for i, record in enumerate(history_list[:3]):
                print(f"   [{i+1}] {record['session_id'][:20]}... | "
                      f"{record.get('strategy', 'N/A')} | "
                      f"权益: ¥{record.get('final_equity', 0):,.0f}")
            
            # 2. 选择一条记录进行删除测试
            if len(history_list) > 0:
                test_session = history_list[0]
                session_id = test_session['session_id']
                
                print(f"\n2. 测试删除记录: {session_id[:20]}...")
                confirm = input("   确认删除? (y/n): ")
                
                if confirm.lower() == 'y':
                    delete_response = requests.delete(
                        f"{BASE_URL}/backtest/history/{session_id}"
                    )
                    
                    if delete_response.status_code == 200:
                        print("   ✓ 删除成功")
                        
                        # 3. 验证删除
                        print("\n3. 验证删除结果...")
                        verify_response = requests.get(f"{BASE_URL}/backtest/history")
                        if verify_response.status_code == 200:
                            new_history = verify_response.json().get('history', [])
                            print(f"   删除后剩余 {len(new_history)} 条记录")
                            
                            # 检查是否真的删除了
                            deleted = session_id not in [h['session_id'] for h in new_history]
                            if deleted:
                                print("   ✓ 验证成功：记录已从列表中移除")
                            else:
                                print("   ✗ 验证失败：记录仍在列表中")
                    else:
                        print(f"   ✗ 删除失败: {delete_response.text}")
                else:
                    print("   取消删除测试")
        else:
            print("   没有历史记录可供测试")
    else:
        print(f"   ✗ 获取历史记录失败: {response.status_code}")


def test_final_equity_calculation():
    """测试最终权益计算（包含持仓）"""
    print("\n\n=== 测试最终权益计算 ===")
    
    # 1. 创建一个新的回测会话
    print("\n1. 创建回测会话...")
    start_params = {
        "strategy": "B1",
        "start_date": "20251231",
        "initial_capital": 1000000,
        "slippage": 0.002,
        "commission_rate": 0.0003
    }
    
    response = requests.post(f"{BASE_URL}/backtest/start", json=start_params)
    if response.status_code != 200:
        print(f"   ✗ 创建回测失败: {response.status_code}")
        return
    
    data = response.json()
    session_id = data['session_id']
    print(f"   ✓ 会话创建成功: {session_id[:20]}...")
    
    # 2. 执行一些交易（买入）
    print("\n2. 获取候选池并买入股票...")
    
    # 推进到下一日
    next_response = requests.post(f"{BASE_URL}/backtest/next", 
                                  json={"session_id": session_id})
    if next_response.status_code != 200:
        print(f"   ✗ 推进失败")
        return
    
    state = next_response.json()['state']
    current_date = state['current_date']
    print(f"   当前日期: {current_date}")
    
    # 获取候选池
    candidates_url = f"{BASE_URL}/backtest/candidates?session_id={session_id}"
    candidates_response = requests.get(candidates_url)
    
    if candidates_response.status_code == 200:
        candidates = candidates_response.json().get('stocks', [])
        print(f"   候选池有 {len(candidates)} 只股票")
        
        # 买入前3只股票
        if candidates:
            for stock in candidates[:3]:
                code = stock['code']
                price = stock.get('close', 0)
                if price > 0:
                    shares = 10000  # 买入10000股
                    trade_params = {
                        "session_id": session_id,
                        "action": "buy",
                        "code": code,
                        "shares": shares
                    }
                    
                    trade_response = requests.post(f"{BASE_URL}/backtest/trade", 
                                                   json=trade_params)
                    if trade_response.status_code == 200:
                        print(f"   ✓ 买入 {code} {shares}股 @¥{price:.2f}")
    
    # 3. 推进几日（不卖出，保持持仓）
    print("\n3. 推进5日...")
    for i in range(5):
        next_response = requests.post(f"{BASE_URL}/backtest/next", 
                                      json={"session_id": session_id})
        if next_response.status_code == 200:
            state = next_response.json()['state']
            print(f"   日期: {state['current_date']}")
    
    # 4. 结束回测并检查最终权益
    print("\n4. 结束回测并检查最终权益...")
    
    # 先获取当前状态
    state_response = requests.get(f"{BASE_URL}/backtest/state", 
                                  params={"session_id": session_id})
    if state_response.status_code == 200:
        current_state = state_response.json()
        cash = current_state.get('cash', 0)
        positions = current_state.get('positions', [])
        
        print(f"\n   当前现金: ¥{cash:,.2f}")
        print(f"   持仓数量: {len(positions)}")
        
        total_position_value = 0
        for pos in positions:
            market_value = pos.get('market_value', 0)
            total_position_value += market_value
            print(f"   - {pos['code']}: {pos['shares']}股, "
                  f"成本¥{pos['cost_price']:.2f}, "
                  f"现价¥{pos.get('current_price', 0):.2f}, "
                  f"市值¥{market_value:,.2f}")
        
        expected_equity = cash + total_position_value
        print(f"\n   预期最终权益: ¥{cash:,.2f} + ¥{total_position_value:,.2f} = ¥{expected_equity:,.2f}")
    
    # 结束回测
    end_response = requests.post(f"{BASE_URL}/backtest/end", 
                                 json={"session_id": session_id})
    
    if end_response.status_code == 200:
        summary = end_response.json()
        final_equity = summary.get('final_equity', 0)
        total_profit = summary.get('total_profit', 0)
        total_profit_pct = summary.get('total_profit_pct', 0)
        
        print(f"\n   ✓ 回测结束")
        print(f"   最终权益: ¥{final_equity:,.2f}")
        print(f"   总收益: ¥{total_profit:,.2f} ({total_profit_pct:+.2f}%)")
        
        # 验证最终权益是否包含持仓
        if abs(final_equity - expected_equity) < 0.01:
            print(f"   ✓ 验证成功：最终权益正确包含了持仓市值")
        else:
            print(f"   ⚠ 最终权益与预期有差异")
            print(f"     预期: ¥{expected_equity:,.2f}")
            print(f"     实际: ¥{final_equity:,.2f}")
            print(f"     差额: ¥{abs(final_equity - expected_equity):,.2f}")
    else:
        print(f"   ✗ 结束回测失败: {end_response.status_code}")


def main():
    """主测试流程"""
    print("=" * 60)
    print("历史记录优化功能测试")
    print("=" * 60)
    
    while True:
        print("\n请选择测试项目:")
        print("1. 测试删除历史记录功能")
        print("2. 测试最终权益计算（包含持仓）")
        print("3. 全部测试")
        print("0. 退出")
        
        choice = input("\n请输入选择 (0-3): ").strip()
        
        if choice == '1':
            test_delete_history()
        elif choice == '2':
            test_final_equity_calculation()
        elif choice == '3':
            test_final_equity_calculation()
            test_delete_history()
        elif choice == '0':
            print("\n再见!")
            break
        else:
            print("无效选择，请重试")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n测试已中断")
    except Exception as e:
        print(f"\n测试出错: {str(e)}")
        import traceback
        traceback.print_exc()
