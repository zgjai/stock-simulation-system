"""回测管理API"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd
import json
import os
from datetime import datetime
from pathlib import Path

# 导入策略模块的函数
import sys
sys.path.append(str(Path(__file__).parent))
from strategy import check_b1_condition, check_extreme_b1_condition, get_consecutive_extreme_b1_days

router = APIRouter()

# 获取项目根目录的绝对路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
PROCESSED_PATH = str(PROJECT_ROOT / "processed_data")
INDEX_PATH = str(PROJECT_ROOT / "strategy_index")

# 内存中的回测会话（简化版，生产环境应使用SQLite）
backtest_sessions = {}

# 股票数据缓存（减少重复读取文件）
_stock_data_cache = {}  # {code: DataFrame}

def clear_stock_cache():
    """清理股票数据缓存"""
    global _stock_data_cache
    _stock_data_cache.clear()


class BacktestStartRequest(BaseModel):
    """开始回测请求"""
    start_date: str  # YYYYMMDD
    initial_capital: float = 1000000
    slippage: float = 0.0015
    commission_rate: float = 0.0002
    strategy: str = "B1"


class TradeRequest(BaseModel):
    """交易请求"""
    session_id: str
    action: str  # 'buy' or 'sell'
    code: str
    shares: Optional[int] = None
    amount: Optional[float] = None  # 买入金额（与shares二选一）


class NextDayRequest(BaseModel):
    """推进到下一日"""
    session_id: str


class EndBacktestRequest(BaseModel):
    """结束回测"""
    session_id: str


def get_limit_ratio(stock_code: str) -> Decimal:
    """获取涨跌停比例"""
    prefix = stock_code[:2]
    if prefix in ['00', '60']:
        return Decimal('0.10')
    elif prefix in ['30', '68']:
        return Decimal('0.20')
    elif prefix == '92':
        return Decimal('0.30')
    return Decimal('0.10')


def calc_limit_price(prev_close: float, limit_ratio: Decimal, direction: int) -> float:
    """计算涨跌停价"""
    price = Decimal(str(prev_close)) * (Decimal('1') + direction * limit_ratio)
    return float(price.quantize(Decimal('0.01'), ROUND_HALF_UP))


def get_stock_data(code: str, date: str) -> Optional[Dict]:
    """获取股票指定日期的数据（带缓存优化）"""
    global _stock_data_cache
    
    try:
        # 检查缓存
        if code not in _stock_data_cache:
            df = pd.read_csv(f"{PROCESSED_PATH}/{code}.csv")
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
            _stock_data_cache[code] = df
        
        df = _stock_data_cache[code]
        row = df[df['date'] == date]
        if len(row) > 0:
            return row.iloc[0].to_dict()
        return None
    except:
        return None


def get_next_trade_date(current_date: str) -> Optional[str]:
    """获取下一个交易日"""
    # 从策略索引目录获取所有交易日（最可靠的数据源）
    # 因为索引文件的文件名就是交易日期
    strategy_dir = f"{INDEX_PATH}/B1"  # 默认使用B1策略的索引
    if not os.path.exists(strategy_dir):
        return None
    
    # 获取所有日期文件，提取日期并排序
    dates = []
    for filename in os.listdir(strategy_dir):
        if filename.endswith('.json'):
            date_str = filename.replace('.json', '')
            dates.append(date_str)
    
    dates.sort()
    
    try:
        idx = dates.index(current_date)
        if idx < len(dates) - 1:
            return dates[idx + 1]
    except ValueError:
        # 如果当前日期不在列表中，返回第一个大于当前日期的交易日
        for date in dates:
            if date > current_date:
                return date
    
    return None


def get_prev_trade_date(current_date: str) -> Optional[str]:
    """获取上一个交易日"""
    # 从策略索引目录获取所有交易日（最可靠的数据源）
    strategy_dir = f"{INDEX_PATH}/B1"  # 默认使用B1策略的索引
    if not os.path.exists(strategy_dir):
        return None
    
    # 获取所有日期文件，提取日期并排序
    dates = []
    for filename in os.listdir(strategy_dir):
        if filename.endswith('.json'):
            date_str = filename.replace('.json', '')
            dates.append(date_str)
    
    dates.sort()
    
    try:
        idx = dates.index(current_date)
        if idx > 0:
            return dates[idx - 1]
    except ValueError:
        # 如果当前日期不在列表中，返回第一个小于当前日期的交易日
        for date in reversed(dates):
            if date < current_date:
                return date
    
    return None


@router.post("/start")
async def start_backtest(request: BacktestStartRequest):
    """
    开始回测
    
    Args:
        request: 回测参数
        
    Returns:
        会话ID和初始状态
    """
    session_id = f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # 清理股票数据缓存，避免多次回测时内存累积
    clear_stock_cache()
    
    backtest_sessions[session_id] = {
        "session_id": session_id,
        "current_date": request.start_date,
        "start_date": request.start_date,
        "cash": request.initial_capital,
        "initial_capital": request.initial_capital,
        "positions": {},  # {code: {shares, cost_price, buy_date}}
        "sold_positions": [],  # 已清仓的股票历史记录
        "trade_log": [],
        "snapshots": [],  # 只保留最近的快照用于回退
        "equity_curve": [],  # 只保留(date, equity)元组，节省内存
        "params": {
            "slippage": request.slippage,
            "commission_rate": request.commission_rate,
            "strategy": request.strategy
        },
        "status": "running",
        "trade_days": 0  # 记录交易日天数，避免重复计算
    }
    
    # ✅ 返回的state应该与getState接口一致，positions转换为数组格式
    return {
        "session_id": session_id,
        "state": {
            "session_id": session_id,
            "current_date": request.start_date,
            "start_date": request.start_date,
            "cash": request.initial_capital,
            "initial_capital": request.initial_capital,
            "positions": [],  # ✅ 空数组，而不是空字典
            "sold_positions": [],
            "trade_log": [],
            "params": {
                "slippage": request.slippage,
                "commission_rate": request.commission_rate,
                "strategy": request.strategy
            },
            "status": "running",
            "trade_days": 0
        }
    }


@router.post("/trade")
async def trade(request: TradeRequest):
    """
    执行交易
    
    Args:
        request: 交易请求
        
    Returns:
        更新后的状态
    """
    if request.session_id not in backtest_sessions:
        raise HTTPException(status_code=404, detail="回测会话不存在")
    
    session = backtest_sessions[request.session_id]
    current_date = session['current_date']
    
    # 获取股票当日数据
    stock_data = get_stock_data(request.code, current_date)
    if not stock_data:
        raise HTTPException(status_code=400, detail=f"股票 {request.code} 在 {current_date} 无数据")
    
    if request.action == 'buy':
        # 买入逻辑
        if stock_data['can_trade'] == 0:
            raise HTTPException(status_code=400, detail="股票停牌或数据异常")
        
        # 计算买入价和股数
        # 若当日收盘价达到涨停，视为以涨停价买入（回测验证场景），不再阻止买入
        is_limit_up = stock_data['close'] >= stock_data['limit_up']
        if is_limit_up:
            buy_price = stock_data['limit_up']  # 以涨停价成交
        else:
            buy_price = stock_data['close'] * (1 + session['params']['slippage'])
        
        if request.amount:
            # 按金额买入
            shares = int(request.amount / buy_price / 100) * 100
        else:
            shares = request.shares
        
        if shares < 100:
            raise HTTPException(status_code=400, detail="资金不足一手（100股）")
        
        total_cost = buy_price * shares
        commission = total_cost * session['params']['commission_rate']
        total_amount = total_cost + commission
        
        if total_amount > session['cash']:
            raise HTTPException(status_code=400, detail="资金不足")
        
        # 更新现金
        session['cash'] -= total_amount
        
        # 更新持仓
        if request.code in session['positions']:
            # 加仓，重新计算成本价
            pos = session['positions'][request.code]
            total_shares = pos['shares'] + shares
            total_cost_value = pos['cost_price'] * pos['shares'] + buy_price * shares
            new_cost_price = total_cost_value / total_shares
            
            session['positions'][request.code] = {
                'shares': total_shares,
                'cost_price': round(new_cost_price, 2),
                'buy_date': pos['buy_date'],
                'buy_trade_days': pos['buy_trade_days']  # 保留原始买入交易日天数
            }
        else:
            session['positions'][request.code] = {
                'shares': shares,
                'cost_price': round(buy_price, 2),
                'buy_date': current_date,
                'buy_trade_days': session.get('trade_days', 0)  # 记录买入时的交易日天数
            }
        
        # 记录交易日志
        log_entry = {
            'date': current_date,
            'action': 'buy',
            'code': request.code,
            'price': round(buy_price, 2),
            'shares': shares,
            'amount': round(total_cost, 2),
            'commission': round(commission, 2)
        }
        if is_limit_up:
            log_entry['note'] = '涨停价买入'
        session['trade_log'].append(log_entry)
        
        buy_msg = f"买入成功: {request.code} {shares}股 @{round(buy_price, 2)}"
        if is_limit_up:
            buy_msg += "（涨停价）"
        return {
            "success": True,
            "message": buy_msg,
            "state": session
        }
    
    elif request.action == 'sell':
        # 卖出逻辑
        if request.code not in session['positions']:
            raise HTTPException(status_code=400, detail="未持有该股票")
        
        pos = session['positions'][request.code]
        
        # T+1检查
        if pos['buy_date'] == current_date:
            raise HTTPException(status_code=400, detail="T+1限制，当日买入不可当日卖出")
        
        if stock_data['can_trade'] == 0:
            raise HTTPException(status_code=400, detail="股票停牌或数据异常")
        
        if stock_data['close'] <= stock_data['limit_down']:
            raise HTTPException(status_code=400, detail="跌停无法卖出")
        
        shares = request.shares if request.shares else pos['shares']
        
        if shares > pos['shares']:
            raise HTTPException(status_code=400, detail="卖出数量超过持仓")
        
        # 计算卖出价
        sell_price = stock_data['close'] * (1 - session['params']['slippage'])
        total_amount = sell_price * shares
        commission = total_amount * session['params']['commission_rate']
        net_amount = total_amount - commission
        
        # 更新现金
        session['cash'] += net_amount
        
        # 计算持仓天数（使用记录的交易日天数）
        holding_days = session.get('trade_days', 0) - pos.get('buy_trade_days', 0) + 1
        
        # 计算盈亏
        profit = round((sell_price - pos['cost_price']) * shares - commission, 2)
        profit_pct = round((sell_price - pos['cost_price']) / pos['cost_price'] * 100, 2)
        
        # 更新持仓
        if shares == pos['shares']:
            # 完全清仓，记录到已清仓列表
            session['sold_positions'].append({
                'code': request.code,
                'buy_date': pos['buy_date'],
                'sell_date': current_date,
                'cost_price': pos['cost_price'],
                'sell_price': round(sell_price, 2),
                'shares': shares,
                'profit': profit,
                'profit_pct': profit_pct,
                'holding_days': holding_days
            })
            del session['positions'][request.code]
        else:
            session['positions'][request.code]['shares'] -= shares
        
        # 记录交易日志
        session['trade_log'].append({
            'date': current_date,
            'action': 'sell',
            'code': request.code,
            'price': round(sell_price, 2),
            'shares': shares,
            'amount': round(total_amount, 2),
            'commission': round(commission, 2),
            'profit': profit,
            'holding_days': holding_days
        })
        
        return {
            "success": True,
            "message": f"卖出成功: {request.code} {shares}股 @{round(sell_price, 2)}",
            "state": session
        }


@router.post("/rollback")
async def rollback(request: NextDayRequest):
    """
    回退到上一交易日
    
    Args:
        request: 请求参数
        
    Returns:
        回退后的状态
    """
    if request.session_id not in backtest_sessions:
        raise HTTPException(status_code=404, detail="回测会话不存在")
    
    session = backtest_sessions[request.session_id]
    
    # 检查是否有快照可回退
    if len(session['snapshots']) == 0:
        raise HTTPException(status_code=400, detail="已是第一个交易日,无法回退")
    
    # 恢复上一日的快照
    last_snapshot = session['snapshots'].pop()
    session['cash'] = last_snapshot['cash']
    session['positions'] = last_snapshot['positions']
    session['current_date'] = last_snapshot['date']
    session['trade_days'] = max(0, session.get('trade_days', 0) - 1)
    
    # 从equity_curve删除最后一条
    if session.get('equity_curve'):
        session['equity_curve'].pop()
    
    # 删除当日的交易记录
    session['trade_log'] = [
        log for log in session['trade_log'] 
        if log['date'] != last_snapshot['date']
    ]
    
    # 准备返回数据
    positions_list = []
    for code, pos in session['positions'].items():
        stock_data = get_stock_data(code, session['current_date'])
        if stock_data:
            current_price = stock_data['close']
            # 使用记录的交易日天数计算持仓天数
            holding_days = session.get('trade_days', 0) - pos.get('buy_trade_days', 0) + 1
            positions_list.append({
                'code': code,
                'shares': pos['shares'],
                'cost_price': pos['cost_price'],
                'current_price': round(current_price, 2),
                'profit': round((current_price - pos['cost_price']) * pos['shares'], 2),
                'profit_pct': round((current_price - pos['cost_price']) / pos['cost_price'] * 100, 2),
                'buy_date': pos['buy_date'],
                'holding_days': holding_days
            })
    
    # 更新已清仓股票的当前价格
    sold_positions_list = []
    for sold_pos in session.get('sold_positions', []):
        stock_data = get_stock_data(sold_pos['code'], session['current_date'])
        sold_pos_with_price = sold_pos.copy()
        if stock_data:
            sold_pos_with_price['current_price'] = round(stock_data['close'], 2)
            # 计算如果没卖出的潜在收益
            potential_profit = round((stock_data['close'] - sold_pos['cost_price']) * sold_pos['shares'], 2)
            potential_profit_pct = round((stock_data['close'] - sold_pos['cost_price']) / sold_pos['cost_price'] * 100, 2)
            sold_pos_with_price['potential_profit'] = potential_profit
            sold_pos_with_price['potential_profit_pct'] = potential_profit_pct
        else:
            sold_pos_with_price['current_price'] = None
            sold_pos_with_price['potential_profit'] = None
            sold_pos_with_price['potential_profit_pct'] = None
        sold_positions_list.append(sold_pos_with_price)
    
    return {
        "success": True,
        "current_date": session['current_date'],
        "cash": session['cash'],
        "positions": positions_list,
        "sold_positions": sold_positions_list
    }


@router.post("/next-day")
async def next_day(request: NextDayRequest):
    """
    推进到下一交易日
    
    Args:
        request: 请求参数
        
    Returns:
        下一日的状态
    """
    if request.session_id not in backtest_sessions:
        raise HTTPException(status_code=404, detail="回测会话不存在")
    
    session = backtest_sessions[request.session_id]
    current_date = session['current_date']
    
    # 计算当前权益
    current_equity = session['cash']
    for code, pos in session['positions'].items():
        stock_data = get_stock_data(code, current_date)
        if stock_data:
            current_equity += stock_data['close'] * pos['shares']
    
    # 保存轻量级快照（只保留最近10个用于回退）
    snapshot = {
        'date': current_date,
        'cash': session['cash'],
        'positions': {k: v.copy() for k, v in session['positions'].items()}  # 深拷贝positions
    }
    
    session['snapshots'].append(snapshot)
    # 只保留最近10个快照，节省内存
    if len(session['snapshots']) > 10:
        session['snapshots'].pop(0)
    
    # 保存权益曲线数据（轻量级）
    if 'equity_curve' not in session:
        session['equity_curve'] = []
    session['equity_curve'].append((current_date, round(current_equity, 2)))
    
    # 推进到下一日
    next_date = get_next_trade_date(current_date)
    if not next_date:
        raise HTTPException(status_code=400, detail="已到达最后一个交易日")
    
    session['current_date'] = next_date
    session['trade_days'] = session.get('trade_days', 0) + 1
    
    # ===== 内存优化：推进到下一日后，清理不必要的数据 =====
    # 1. 清理股票数据缓存（保留当前持仓的股票数据）
    if len(_stock_data_cache) > 50:  # 缓存超过50只股票时清理
        held_codes = set(session['positions'].keys())
        codes_to_remove = [code for code in _stock_data_cache.keys() if code not in held_codes]
        # 只保留最近使用的20只非持仓股票
        if len(codes_to_remove) > 20:
            for code in codes_to_remove[:-20]:
                del _stock_data_cache[code]
    
    # 更新持仓的当前价格（用于显示浮动盈亏）
    positions_with_price = []
    for code, pos in session['positions'].items():
        stock_data = get_stock_data(code, next_date)
        if stock_data:
            current_price = stock_data['close']
            # 使用记录的交易日天数计算持仓天数
            holding_days = session.get('trade_days', 0) - pos.get('buy_trade_days', 0) + 1
            positions_with_price.append({
                'code': code,
                'shares': pos['shares'],
                'cost_price': pos['cost_price'],
                'current_price': round(current_price, 2),
                'profit': round((current_price - pos['cost_price']) * pos['shares'], 2),
                'profit_pct': round((current_price - pos['cost_price']) / pos['cost_price'] * 100, 2),
                'holding_days': holding_days,
                'buy_date': pos['buy_date']
            })
    
    # 更新已清仓股票的当前价格
    sold_positions_with_price = []
    for sold_pos in session.get('sold_positions', []):
        stock_data = get_stock_data(sold_pos['code'], next_date)
        sold_pos_with_price = sold_pos.copy()
        if stock_data:
            sold_pos_with_price['current_price'] = round(stock_data['close'], 2)
            # 计算如果没卖出的潜在收益
            potential_profit = round((stock_data['close'] - sold_pos['cost_price']) * sold_pos['shares'], 2)
            potential_profit_pct = round((stock_data['close'] - sold_pos['cost_price']) / sold_pos['cost_price'] * 100, 2)
            sold_pos_with_price['potential_profit'] = potential_profit
            sold_pos_with_price['potential_profit_pct'] = potential_profit_pct
        else:
            sold_pos_with_price['current_price'] = None
            sold_pos_with_price['potential_profit'] = None
            sold_pos_with_price['potential_profit_pct'] = None
        sold_positions_with_price.append(sold_pos_with_price)
    
    return {
        "success": True,
        "current_date": next_date,
        "cash": session['cash'],
        "positions": positions_with_price,
        "sold_positions": sold_positions_with_price,
        "equity": current_equity
    }


@router.post("/end")
async def end_backtest(request: EndBacktestRequest):
    """
    结束回测
    
    Args:
        request: 请求参数
        
    Returns:
        回测结果统计（含高级指标）
    """
    if request.session_id not in backtest_sessions:
        raise HTTPException(status_code=404, detail="回测会话不存在")
    
    session = backtest_sessions[request.session_id]
    
    # 计算最终权益
    final_equity = session['cash']
    for code, pos in session['positions'].items():
        stock_data = get_stock_data(code, session['current_date'])
        if stock_data:
            final_equity += stock_data['close'] * pos['shares']
    
    # 计算总收益
    total_profit = final_equity - session['initial_capital']
    total_profit_pct = (total_profit / session['initial_capital']) * 100
    
    # 计算交易统计
    buy_count = len([log for log in session['trade_log'] if log['action'] == 'buy'])
    sell_count = len([log for log in session['trade_log'] if log['action'] == 'sell'])
    
    # 计算年化收益率（使用复利公式）
    trade_days = session.get('trade_days', 0)
    if trade_days > 0:
        # 使用复利公式: (1 + 总收益率) ^ (244/回测天数) - 1
        annualized_return = ((1 + total_profit_pct / 100) ** (244 / trade_days) - 1) * 100
    else:
        annualized_return = 0
    
    # 使用equity_curve计算最大回撤（更高效）
    max_drawdown = 0
    peak_equity = session['initial_capital']
    
    equity_curve = session.get('equity_curve', [])
    for item in equity_curve:
        try:
            # 兼容多种格式
            if isinstance(item, dict):
                equity = float(item.get('equity', 0))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                equity = float(item[1])
            else:
                continue
        except (ValueError, TypeError, IndexError):
            continue
            
        if equity > peak_equity:
            peak_equity = equity
        drawdown = (peak_equity - equity) / peak_equity * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    # 计算夏普比率（简化版，假设无风险利率为3%）
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            try:
                # 兼容多种格式
                if isinstance(equity_curve[i-1], dict):
                    prev_equity = float(equity_curve[i-1].get('equity', 0))
                elif isinstance(equity_curve[i-1], (list, tuple)) and len(equity_curve[i-1]) >= 2:
                    prev_equity = float(equity_curve[i-1][1])
                else:
                    continue
                
                if isinstance(equity_curve[i], dict):
                    curr_equity = float(equity_curve[i].get('equity', 0))
                elif isinstance(equity_curve[i], (list, tuple)) and len(equity_curve[i]) >= 2:
                    curr_equity = float(equity_curve[i][1])
                else:
                    continue
                
                daily_return = (curr_equity - prev_equity) / prev_equity
                returns.append(daily_return)
            except (ValueError, TypeError, IndexError):
                continue
        
        if len(returns) > 0:
            import numpy as np
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            risk_free_rate = 0.03 / 244  # 年化3%转日收益
            sharpe_ratio = (mean_return - risk_free_rate) / std_return * np.sqrt(244) if std_return > 0 else 0
        else:
            sharpe_ratio = 0
    else:
        sharpe_ratio = 0
    
    # 计算胜率和盈亏比
    winning_trades = 0
    losing_trades = 0
    total_win_amount = 0
    total_loss_amount = 0
    
    # 通过配对买卖计算盈亏
    buy_positions = {}  # {code: [(shares, cost_price), ...]}
    
    for log in session['trade_log']:
        code = log['code']
        if log['action'] == 'buy':
            if code not in buy_positions:
                buy_positions[code] = []
            buy_positions[code].append({
                'shares': log['shares'],
                'cost': log['price']
            })
        elif log['action'] == 'sell':
            if code in buy_positions and buy_positions[code]:
                # 使用FIFO原则匹配买入
                remaining_shares = log['shares']
                sell_price = log['price']
                
                while remaining_shares > 0 and buy_positions[code]:
                    buy_record = buy_positions[code][0]
                    matched_shares = min(remaining_shares, buy_record['shares'])
                    
                    profit = (sell_price - buy_record['cost']) * matched_shares
                    
                    if profit > 0:
                        winning_trades += 1
                        total_win_amount += profit
                    elif profit < 0:
                        losing_trades += 1
                        total_loss_amount += abs(profit)
                    
                    remaining_shares -= matched_shares
                    buy_record['shares'] -= matched_shares
                    
                    if buy_record['shares'] <= 0:
                        buy_positions[code].pop(0)
    
    win_rate = (winning_trades / (winning_trades + losing_trades) * 100) if (winning_trades + losing_trades) > 0 else 0
    profit_loss_ratio = (total_win_amount / total_loss_amount) if total_loss_amount > 0 else 0
    
    # 计算平均持仓天数
    holding_days_list = []
    for log in session['trade_log']:
        if log['action'] == 'sell' and 'holding_days' in log:
            holding_days_list.append(log.get('holding_days', 0))
    
    avg_holding_days = sum(holding_days_list) / len(holding_days_list) if holding_days_list else 0
    
    # 标记为已结束
    session['status'] = 'finished'
    session['end_date'] = session['current_date']
    session['final_equity'] = final_equity
    
    # 清理大对象，释放内存
    session['snapshots'] = []  # 清空快照
    
    # 清理stock_data_cache（回测结束后不再需要）
    clear_stock_cache()
    
    result = {
        "session_id": request.session_id,
        "start_date": session['start_date'],
        "end_date": session['current_date'],
        "initial_capital": session['initial_capital'],
        "final_equity": round(final_equity, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "trade_count": len(session['trade_log']),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "strategy": session['params']['strategy'],
        # 新增高级统计指标
        "annualized_return": round(annualized_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe_ratio, 3),
        "win_rate": round(win_rate, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "avg_holding_days": round(avg_holding_days, 1),
        "trade_days": trade_days
    }
    
    return result


@router.get("/history")
async def get_backtest_history():
    """
    获取历史回测记录列表
    
    Returns:
        历史记录列表
    """
    history = []
    for session_id, session in backtest_sessions.items():
        if session['status'] == 'finished':
            history.append({
                "session_id": session_id,
                "start_date": session['start_date'],
                "end_date": session.get('end_date', ''),
                "initial_capital": session['initial_capital'],
                "final_equity": session.get('final_equity', 0),
                "strategy": session['params']['strategy'],
                "trade_count": len(session['trade_log'])
            })
    
    return {"history": history}


@router.get("/detail")
async def get_backtest_detail(session_id: str):
    """
    获取回测详细信息
    
    Args:
        session_id: 会话ID
        
    Returns:
        详细信息(包含交易日志和权益曲线以及统计指标)
    """
    if session_id not in backtest_sessions:
        raise HTTPException(status_code=404, detail="回测会话不存在")
    
    session = backtest_sessions[session_id]
    
    # 计算最终权益
    final_equity = session.get('final_equity', 0)
    if final_equity == 0:
        final_equity = session['cash']
        for code, pos in session['positions'].items():
            stock_data = get_stock_data(code, session['current_date'])
            if stock_data:
                final_equity += stock_data['close'] * pos['shares']
    
    # 计算总收益
    total_profit = final_equity - session['initial_capital']
    total_profit_pct = (total_profit / session['initial_capital']) * 100
    
    # 计算交易统计
    buy_count = len([log for log in session['trade_log'] if log['action'] == 'buy'])
    sell_count = len([log for log in session['trade_log'] if log['action'] == 'sell'])
    
    # 计算年化收益率（使用复利公式）
    trade_days = session.get('trade_days', 0)
    if trade_days > 0:
        # 使用复利公式: (1 + 总收益率) ^ (244/回测天数) - 1
        annualized_return = ((1 + total_profit_pct / 100) ** (244 / trade_days) - 1) * 100
    else:
        annualized_return = 0
    
    # 使用equity_curve计算最大回撤
    max_drawdown = 0
    peak_equity = session['initial_capital']
    equity_curve = session.get('equity_curve', [])
    
    for item in equity_curve:
        try:
            # 兼容多种格式
            if isinstance(item, dict):
                equity = float(item.get('equity', 0))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                equity = float(item[1])
            else:
                continue
        except (ValueError, TypeError, IndexError):
            continue
            
        if equity > peak_equity:
            peak_equity = equity
        drawdown = (peak_equity - equity) / peak_equity * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    # 计算夏普比率
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i-1][1]
            curr_equity = equity_curve[i][1]
            daily_return = (curr_equity - prev_equity) / prev_equity
            returns.append(daily_return)
        
        if len(returns) > 0:
            import numpy as np
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            risk_free_rate = 0.03 / 244
            sharpe_ratio = (mean_return - risk_free_rate) / std_return * np.sqrt(244) if std_return > 0 else 0
        else:
            sharpe_ratio = 0
    else:
        sharpe_ratio = 0
    
    # 计算胜率和盈亏比
    winning_trades = 0
    losing_trades = 0
    total_win_amount = 0
    total_loss_amount = 0
    
    buy_positions = {}
    for log in session['trade_log']:
        code = log['code']
        if log['action'] == 'buy':
            if code not in buy_positions:
                buy_positions[code] = []
            buy_positions[code].append({
                'shares': log['shares'],
                'cost': log['price']
            })
        elif log['action'] == 'sell':
            if code in buy_positions and buy_positions[code]:
                remaining_shares = log['shares']
                sell_price = log['price']
                
                while remaining_shares > 0 and buy_positions[code]:
                    buy_record = buy_positions[code][0]
                    matched_shares = min(remaining_shares, buy_record['shares'])
                    
                    profit = (sell_price - buy_record['cost']) * matched_shares
                    
                    if profit > 0:
                        winning_trades += 1
                        total_win_amount += profit
                    elif profit < 0:
                        losing_trades += 1
                        total_loss_amount += abs(profit)
                    
                    remaining_shares -= matched_shares
                    buy_record['shares'] -= matched_shares
                    
                    if buy_record['shares'] <= 0:
                        buy_positions[code].pop(0)
    
    win_rate = (winning_trades / (winning_trades + losing_trades) * 100) if (winning_trades + losing_trades) > 0 else 0
    profit_loss_ratio = (total_win_amount / total_loss_amount) if total_loss_amount > 0 else 0
    
    # 计算平均持仓天数
    holding_days_list = []
    for log in session['trade_log']:
        if log['action'] == 'sell' and 'holding_days' in log:
            holding_days_list.append(log.get('holding_days', 0))
    
    avg_holding_days = sum(holding_days_list) / len(holding_days_list) if holding_days_list else 0
    
    # 将equity_curve转换为前端需要的格式
    snapshots_for_frontend = [{"date": d, "equity": e} for d, e in equity_curve]
    
    return {
        "session_id": session_id,
        "params": session['params'],
        "start_date": session['start_date'],
        "end_date": session.get('end_date', session['current_date']),
        "initial_capital": session['initial_capital'],
        "final_equity": round(final_equity, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "trade_log": session['trade_log'],
        "snapshots": snapshots_for_frontend,  # 使用轻量级的equity_curve
        # 统计指标
        "trade_days": trade_days,
        "trade_count": len(session['trade_log']),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "annualized_return": round(annualized_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe_ratio, 3),
        "win_rate": round(win_rate, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "avg_holding_days": round(avg_holding_days, 1)
    }


@router.get("/state")
async def get_state(session_id: str):
    """
    获取回测状态
    
    Args:
        session_id: 会话ID
        
    Returns:
        当前状态
    """
    if session_id not in backtest_sessions:
        raise HTTPException(status_code=404, detail="回测会话不存在")
    
    session = backtest_sessions[session_id]
    
    # 将positions转换为数组格式,并添加当前价格
    positions_list = []
    current_date = session['current_date']
    
    for code, pos in session['positions'].items():
        stock_data = get_stock_data(code, current_date)
        if stock_data:
            current_price = stock_data['close']
            # 使用记录的交易日天数计算持仓天数
            holding_days = session.get('trade_days', 0) - pos.get('buy_trade_days', 0) + 1
            positions_list.append({
                'code': code,
                'shares': pos['shares'],
                'cost_price': pos['cost_price'],
                'current_price': round(current_price, 2),
                'profit': round((current_price - pos['cost_price']) * pos['shares'], 2),
                'profit_pct': round((current_price - pos['cost_price']) / pos['cost_price'] * 100, 2),
                'buy_date': pos['buy_date'],
                'holding_days': holding_days
            })
    
    # 为已清仓股票添加当前价格
    sold_positions_list = []
    for sold_pos in session.get('sold_positions', []):
        stock_data = get_stock_data(sold_pos['code'], current_date)
        sold_pos_with_price = sold_pos.copy()
        if stock_data:
            sold_pos_with_price['current_price'] = round(stock_data['close'], 2)
            # 计算如果没卖出的潜在收益
            potential_profit = round((stock_data['close'] - sold_pos['cost_price']) * sold_pos['shares'], 2)
            potential_profit_pct = round((stock_data['close'] - sold_pos['cost_price']) / sold_pos['cost_price'] * 100, 2)
            sold_pos_with_price['potential_profit'] = potential_profit
            sold_pos_with_price['potential_profit_pct'] = potential_profit_pct
        else:
            sold_pos_with_price['current_price'] = None
            sold_pos_with_price['potential_profit'] = None
            sold_pos_with_price['potential_profit_pct'] = None
        sold_positions_list.append(sold_pos_with_price)
    
    return {
        "session_id": session['session_id'],
        "current_date": session['current_date'],
        "start_date": session['start_date'],
        "cash": session['cash'],
        "initial_capital": session['initial_capital'],
        "positions": positions_list,
        "sold_positions": sold_positions_list,
        "trade_log": session['trade_log'],
        "params": session['params'],
        "status": session['status'],
        "trade_days": session.get('trade_days', 0)
    }


@router.get("/learning-cases")
async def get_learning_cases(date: str, strategy: str):
    """
    获取学习案例（优秀案例）
    
    Args:
        date: 当前日期（YYYYMMDD）
        strategy: 策略名称（B1/B2/single_needle）
        
    Returns:
        学习案例数据（包含市场分组和3日、5日、10日的TOP3）
    """
    learning_cases_path = PROJECT_ROOT / "learning_cases"
    case_file = learning_cases_path / strategy / f"{date}.json"
    
    if not case_file.exists():
        # 如果文件不存在，返回空数据
        return {
            "date": date,
            "strategy": strategy,
            "total_candidates": 0,
            "market_groups": {
                "A": {
                    "name": "主板(00/60)",
                    "total": 0,
                    "cases": {"3d": [], "5d": [], "10d": []}
                },
                "B": {
                    "name": "创业板/科创板/北交所(30/68/92)",
                    "total": 0,
                    "cases": {"3d": [], "5d": [], "10d": []}
                }
            }
        }
    
    try:
        with open(case_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 辅助函数：为案例添加极致B1标记和连续天数
        def add_extreme_b1_mark(cases_dict: dict, group_key: str) -> dict:
            """为案例添加极致B1标记和连续极致B1天数"""
            if strategy != 'B1':
                return cases_dict
            
            marked_cases = {}
            for period, cases_list in cases_dict.items():
                marked_list = []
                for case in cases_list:
                    stock_code = case.get('stock_code', '')
                    is_extreme_b1 = False
                    consecutive_extreme_b1_days = 0
                    
                    # 读取股票当日数据检查因子
                    try:
                        stock_file = f"{PROCESSED_PATH}/{stock_code}.csv"
                        if os.path.exists(stock_file):
                            df = pd.read_csv(stock_file)
                            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')
                            row = df[df['date'] == date]
                            
                            if len(row) > 0:
                                row_data = row.iloc[0].to_dict()
                                
                                # 检查是否满足极致B1条件
                                is_extreme_b1 = check_extreme_b1_condition(stock_code, row_data, check_b1_first=False)
                                
                                # 如果满足极致B1,计算连续天数
                                if is_extreme_b1:
                                    consecutive_extreme_b1_days = get_consecutive_extreme_b1_days(stock_code, date)
                    except Exception as e:
                        # 记录错误但继续处理
                        print(f"处理股票 {stock_code} 时出错: {e}")
                    
                    case['is_extreme_b1'] = bool(is_extreme_b1)
                    case['consecutive_extreme_b1_days'] = int(consecutive_extreme_b1_days)
                    marked_list.append(case)
                    
                marked_cases[period] = marked_list
            return marked_cases
        
        # 检查是否是新格式（market_groups）
        if "market_groups" in data:
            # 新格式：转换为前端需要的格式
            market_groups = {}
            for group_key, group_data in data["market_groups"].items():
                top_cases = group_data.get("top_cases", {})
                # 为案例添加极致B1标记
                marked_cases = add_extreme_b1_mark(top_cases, group_key)
                
                market_groups[group_key] = {
                    "name": group_data.get("name", ""),
                    "total": group_data.get("total", 0),
                    "cases": marked_cases
                }
            
            return {
                "date": data.get("date", date),
                "strategy": data.get("strategy", strategy),
                "total_candidates": data.get("total_candidates", 0),
                "market_groups": market_groups
            }
        else:
            # 旧格式兼容：转换为新格式
            top_cases = data.get("top_cases", {"3d": [], "5d": [], "10d": []})
            marked_cases = add_extreme_b1_mark(top_cases, "A")
            
            # 将所有股票归为主板组
            return {
                "date": data.get("date", date),
                "strategy": data.get("strategy", strategy),
                "total_candidates": data.get("total_candidates", 0),
                "market_groups": {
                    "A": {
                        "name": "全部股票",
                        "total": data.get("total_candidates", 0),
                        "cases": marked_cases
                    },
                    "B": {
                        "name": "创业板/科创板/北交所(30/68/92)",
                        "total": 0,
                        "cases": {"3d": [], "5d": [], "10d": []}
                    }
                }
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取学习案例失败: {str(e)}")
