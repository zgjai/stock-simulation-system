"""回测管理API - 数据库版本

使用SQLite数据库查询，支持会话持久化
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
import sys
import json
import os
import pandas as pd

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # 指向项目根目录（包含learning_cases的目录）
sys.path.append(str(PROJECT_ROOT))

from app.database_sqlite import SessionLocal, StockDaily, StrategyPick, BacktestSession as DBBacktestSession, LearningCase
from app.api.strategy_v2 import (check_extreme_b1_condition, get_consecutive_extreme_b1_days,
                                  get_brick_momentum_directions_batch, calc_brick_score)

# 数据路径
PROCESSED_PATH = os.path.join(PROJECT_ROOT, "processed_data")

router = APIRouter()

# 内存中的回测会话（暂时保留，未来迁移到数据库）
backtest_sessions = {}


def get_or_restore_session(session_id: str) -> Dict:
    """获取会话数据（仅从内存）"""
    if session_id not in backtest_sessions:
        raise HTTPException(status_code=404, detail="回测会话不存在或已过期，请重新开始回测")
    
    return backtest_sessions[session_id]


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


class FavoriteStockRequest(BaseModel):
    """精选池操作请求"""
    session_id: str
    stock_codes: List[str]
    note: Optional[str] = ""


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


def get_stock_data_from_db(code: str, date: str) -> Optional[Dict]:
    """从数据库获取股票指定日期的数据"""
    try:
        db = SessionLocal()
        date_obj = datetime.strptime(date, '%Y%m%d').date()
        
        stock = db.query(StockDaily)\
            .filter(StockDaily.stock_code == code)\
            .filter(StockDaily.trade_date == date_obj)\
            .first()
        
        db.close()
        
        if not stock:
            return None
        
        # 计算涨跌停价
        limit_ratio = get_limit_ratio(code)
        limit_up = calc_limit_price(float(stock.prev_close), limit_ratio, 1)
        limit_down = calc_limit_price(float(stock.prev_close), limit_ratio, -1)
        
        return {
            'date': date,
            'code': code,
            'open': float(stock.open) if stock.open else 0,
            'high': float(stock.high) if stock.high else 0,
            'low': float(stock.low) if stock.low else 0,
            'close': float(stock.close) if stock.close else 0,
            'volume': int(stock.volume) if stock.volume else 0,
            'prev_close': float(stock.prev_close) if stock.prev_close else 0,
            'limit_up': limit_up,
            'limit_down': limit_down,
            'can_trade': 1,  # 数据库中有数据即可交易
            'b1_signal': int(stock.b1_signal) if stock.b1_signal else 0,
            'b2_signal': int(stock.b2_signal) if stock.b2_signal else 0,
            'single_needle_signal': int(stock.single_needle_signal) if stock.single_needle_signal else 0,
        }
    except Exception as e:
        print(f"查询股票数据错误: {e}")
        return None


def get_next_trade_date_from_db(current_date: str) -> Optional[str]:
    """从数据库获取下一个交易日"""
    try:
        db = SessionLocal()
        date_obj = datetime.strptime(current_date, '%Y%m%d').date()
        
        next_date = db.query(StockDaily.trade_date)\
            .filter(StockDaily.trade_date > date_obj)\
            .distinct()\
            .order_by(StockDaily.trade_date)\
            .first()
        
        db.close()
        
        if next_date:
            return next_date[0].strftime('%Y%m%d')
        return None
    except Exception as e:
        print(f"查询下一交易日错误: {e}")
        return None


def get_prev_trade_date_from_db(current_date: str) -> Optional[str]:
    """从数据库获取上一个交易日"""
    try:
        db = SessionLocal()
        date_obj = datetime.strptime(current_date, '%Y%m%d').date()
        
        prev_date = db.query(StockDaily.trade_date)\
            .filter(StockDaily.trade_date < date_obj)\
            .distinct()\
            .order_by(StockDaily.trade_date.desc())\
            .first()
        
        db.close()
        
        if prev_date:
            return prev_date[0].strftime('%Y%m%d')
        return None
    except Exception as e:
        print(f"查询上一交易日错误: {e}")
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
    
    backtest_sessions[session_id] = {
        "session_id": session_id,
        "current_date": request.start_date,
        "start_date": request.start_date,
        "cash": request.initial_capital,
        "initial_capital": request.initial_capital,
        "positions": {},  # {code: {shares, cost_price, buy_date}}
        "sold_positions": [],  # 已清仓的股票历史记录
        "favorite_stocks": [],  # 精选池
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
    
    # 持久化到数据库
    db = SessionLocal()
    try:
        db_session = DBBacktestSession(
            session_id=session_id,
            start_date=request.start_date,
            current_date=request.start_date,
            initial_capital=request.initial_capital,
            cash=request.initial_capital,
            strategy=request.strategy,
            status='running',
            slippage=request.slippage,
            commission_rate=request.commission_rate,
            created_at=datetime.now()
        )
        db.add(db_session)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"保存会话到数据库失败: {str(e)}")
    finally:
        db.close()
    
    return {
        "session_id": session_id,
        "state": backtest_sessions[session_id]
    }


@router.post("/trade")
async def trade(request: TradeRequest):
    """
    执行交易（数据库版本）
    
    Args:
        request: 交易请求
        
    Returns:
        更新后的状态
    """
    session = get_or_restore_session(request.session_id)
    current_date = session['current_date']
    
    # 从数据库获取股票当日数据
    stock_data = get_stock_data_from_db(request.code, current_date)
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
        
        # 更新精选池中的已买入状态
        if 'favorite_stocks' in session:
            for fav in session['favorite_stocks']:
                if fav['stock_code'] == request.code and not fav.get('is_bought'):
                    fav['is_bought'] = True
                    fav['buy_date'] = current_date
        
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
            'profit_pct': profit_pct
        })
        
        # 完全清仓后同步更新精选池中的 is_bought 状态
        if shares == pos['shares'] and 'favorite_stocks' in session:
            for fav in session['favorite_stocks']:
                if fav['stock_code'] == request.code:
                    fav['is_bought'] = False
                    fav['buy_date'] = None
                    break
        
        return {
            "success": True,
            "message": f"卖出成功: {request.code} {shares}股 @{round(sell_price, 2)}，盈亏: {profit} ({profit_pct}%)",
            "state": session
        }


@router.post("/next")
async def next_day(request: NextDayRequest):
    """
    推进到下一日（数据库版本 - 批量查询优化）
    """
    session = get_or_restore_session(request.session_id)
    current_date = session['current_date']
    
    # 1. 计算当前权益（用于保存快照）
    current_equity = session['cash']
    for code, pos in session['positions'].items():
        current_equity += pos.get('market_value', pos['cost_price'] * pos['shares'])
    
    # 2. 保存快照（用于回退）
    snapshot = {
        'date': current_date,
        'cash': session['cash'],
        'positions': {k: v.copy() for k, v in session['positions'].items()},
        'sold_positions': [s.copy() for s in session.get('sold_positions', [])],
        'favorite_stocks': [f.copy() for f in session.get('favorite_stocks', [])],
        'trade_days': session.get('trade_days', 0)
    }
    if 'snapshots' not in session:
        session['snapshots'] = []
    session['snapshots'].append(snapshot)
    if len(session['snapshots']) > 10:
        session['snapshots'].pop(0)
    
    # 3. 保存权益曲线（使用元组格式，与初始化注释一致）
    session['equity_curve'].append((current_date, round(current_equity, 2)))
    
    # 4. 获取下一个交易日
    next_date = get_next_trade_date_from_db(current_date)
    
    if not next_date:
        return {
            "success": False,
            "message": "已到最后一个交易日",
            "state": session
        }
    
    # 5. 更新当前日期
    session['current_date'] = next_date
    session['trade_days'] += 1
    
    # 6. 批量查询所有股票的下一日数据（性能优化关键）
    db = SessionLocal()
    try:
        next_date_obj = datetime.strptime(next_date, '%Y%m%d').date()
        
        # 收集需要查询的股票代码
        all_codes = list(session['positions'].keys())
        all_codes.extend([s['code'] for s in session.get('sold_positions', [])])
        all_codes = list(set(all_codes))  # 去重
        
        if all_codes:
            # ⚡ 批量查询（一次SQL，而不是N次）
            stocks_data = db.query(StockDaily)\
                .filter(StockDaily.stock_code.in_(all_codes))\
                .filter(StockDaily.trade_date == next_date_obj)\
                .all()
            
            # 转换为字典，方便查找
            stocks_dict = {s.stock_code: s for s in stocks_data}
            
            # 7. 更新持仓市值（使用批量查询结果）
            total_market_value = 0
            positions_with_price = []
            for code, pos in session['positions'].items():
                stock = stocks_dict.get(code)
                if stock:
                    current_price = float(stock.close)
                    market_value = current_price * pos['shares']
                    holding_days = session['trade_days'] - pos.get('buy_trade_days', 0) + 1
                    
                    # 更新持仓数据
                    pos['current_price'] = current_price
                    pos['market_value'] = market_value
                    pos['profit_pct'] = round((current_price - pos['cost_price']) / pos['cost_price'] * 100, 2)
                    
                    total_market_value += market_value
                    
                    positions_with_price.append({
                        'code': code,
                        'shares': pos['shares'],
                        'cost_price': pos['cost_price'],
                        'current_price': round(current_price, 2),
                        'profit': round((current_price - pos['cost_price']) * pos['shares'], 2),
                        'profit_pct': pos['profit_pct'],
                        'holding_days': holding_days,
                        'buy_date': pos['buy_date']
                    })
            
            # 8. 更新已清仓股票的当前价格（使用批量查询结果）
            sold_positions_with_price = []
            for sold_pos in session.get('sold_positions', []):
                stock = stocks_dict.get(sold_pos['code'])
                sold_pos_with_price = sold_pos.copy()
                if stock:
                    current_price = float(stock.close)
                    sold_pos_with_price['current_price'] = round(current_price, 2)
                    potential_profit = round((current_price - sold_pos['cost_price']) * sold_pos['shares'], 2)
                    potential_profit_pct = round((current_price - sold_pos['cost_price']) / sold_pos['cost_price'] * 100, 2)
                    sold_pos_with_price['potential_profit'] = potential_profit
                    sold_pos_with_price['potential_profit_pct'] = potential_profit_pct
                else:
                    sold_pos_with_price['current_price'] = None
                    sold_pos_with_price['potential_profit'] = None
                    sold_pos_with_price['potential_profit_pct'] = None
                sold_positions_with_price.append(sold_pos_with_price)
        else:
            positions_with_price = []
            sold_positions_with_price = []
            total_market_value = 0
        
        total_equity = session['cash'] + total_market_value
        
        return {
            "success": True,
            "message": f"推进到 {next_date}",
            "current_date": next_date,
            "cash": session['cash'],
            "total_equity": round(total_equity, 2),
            "positions": positions_with_price,
            "sold_positions": sold_positions_with_price,
            "state": session
        }
        
    finally:
        db.close()


@router.post("/rollback")
async def rollback(request: NextDayRequest):
    """
    回退到上一日
    """
    session = get_or_restore_session(request.session_id)
    
    # 检查是否有可回退的快照
    if 'snapshots' not in session or len(session['snapshots']) == 0:
        raise HTTPException(status_code=400, detail="无法回退，没有历史快照")
    
    # 获取最后一个快照
    snapshot = session['snapshots'].pop()
    
    # 恢复状态
    session['current_date'] = snapshot['date']
    session['cash'] = snapshot['cash']
    session['positions'] = {k: v.copy() for k, v in snapshot['positions'].items()}
    session['sold_positions'] = [s.copy() for s in snapshot.get('sold_positions', [])]
    session['favorite_stocks'] = [f.copy() for f in snapshot.get('favorite_stocks', [])]
    session['trade_days'] = snapshot.get('trade_days', 0)
    
    # 移除权益曲线最后一个点
    if session.get('equity_curve') and len(session['equity_curve']) > 0:
        session['equity_curve'].pop()
    
    # 获取当前状态
    db = SessionLocal()
    try:
        date_obj = datetime.strptime(session['current_date'], '%Y%m%d').date()
        
        # 收集需要查询的股票代码
        all_codes = list(session['positions'].keys())
        all_codes.extend([s['code'] for s in session.get('sold_positions', [])])
        all_codes = list(set(all_codes))
        
        if all_codes:
            stocks_data = db.query(StockDaily)\
                .filter(StockDaily.stock_code.in_(all_codes))\
                .filter(StockDaily.trade_date == date_obj)\
                .all()
            
            stocks_dict = {s.stock_code: s for s in stocks_data}
            
            # 更新持仓价格
            positions_with_price = []
            total_market_value = 0
            for code, pos in session['positions'].items():
                stock = stocks_dict.get(code)
                if stock:
                    current_price = float(stock.close)
                    market_value = current_price * pos['shares']
                    holding_days = session['trade_days'] - pos.get('buy_trade_days', 0) + 1
                    
                    total_market_value += market_value
                    
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
            
            # 更新已清仓股票价格
            sold_positions_with_price = []
            for sold_pos in session.get('sold_positions', []):
                stock = stocks_dict.get(sold_pos['code'])
                sold_pos_with_price = sold_pos.copy()
                if stock:
                    current_price = float(stock.close)
                    sold_pos_with_price['current_price'] = round(current_price, 2)
                    potential_profit = round((current_price - sold_pos['cost_price']) * sold_pos['shares'], 2)
                    potential_profit_pct = round((current_price - sold_pos['cost_price']) / sold_pos['cost_price'] * 100, 2)
                    sold_pos_with_price['potential_profit'] = potential_profit
                    sold_pos_with_price['potential_profit_pct'] = potential_profit_pct
                else:
                    sold_pos_with_price['current_price'] = None
                    sold_pos_with_price['potential_profit'] = None
                    sold_pos_with_price['potential_profit_pct'] = None
                sold_positions_with_price.append(sold_pos_with_price)
        else:
            positions_with_price = []
            sold_positions_with_price = []
            total_market_value = 0
        
        total_equity = session['cash'] + total_market_value
        
        return {
            "success": True,
            "message": f"已回退到 {session['current_date']}",
            "current_date": session['current_date'],
            "cash": session['cash'],
            "total_equity": round(total_equity, 2),
            "positions": positions_with_price,
            "sold_positions": sold_positions_with_price,
            "state": session
        }
    finally:
        db.close()


@router.get("/state")
async def get_state(session_id: str):
    """获取回测状态"""
    session = get_or_restore_session(session_id)
    
    # 获取持仓列表（包含当前价格）
    db = SessionLocal()
    try:
        positions_with_price = []
        if session.get('current_date'):
            date_obj = datetime.strptime(session['current_date'], '%Y%m%d').date()
            
            for code, pos in session.get('positions', {}).items():
                stock = db.query(StockDaily)\
                    .filter(StockDaily.stock_code == code)\
                    .filter(StockDaily.trade_date == date_obj)\
                    .first()
                
                if stock:
                    current_price = float(stock.close)
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
        
        # 获取已清仓列表（包含当前价格）
        sold_positions_with_price = []
        for sold_pos in session.get('sold_positions', []):
            sold_pos_with_price = sold_pos.copy()
            if session.get('current_date'):
                stock = db.query(StockDaily)\
                    .filter(StockDaily.stock_code == sold_pos['code'])\
                    .filter(StockDaily.trade_date == date_obj)\
                    .first()
                
                if stock:
                    current_price = float(stock.close)
                    sold_pos_with_price['current_price'] = round(current_price, 2)
                    potential_profit = round((current_price - sold_pos['cost_price']) * sold_pos['shares'], 2)
                    potential_profit_pct = round((current_price - sold_pos['cost_price']) / sold_pos['cost_price'] * 100, 2)
                    sold_pos_with_price['potential_profit'] = potential_profit
                    sold_pos_with_price['potential_profit_pct'] = potential_profit_pct
            
            sold_positions_with_price.append(sold_pos_with_price)
        
        return {
            "session_id": session_id,
            "current_date": session.get('current_date'),
            "cash": session.get('cash', 0),
            "initial_capital": session.get('initial_capital', 0),
            "positions": positions_with_price,
            "sold_positions": sold_positions_with_price,
            "favorite_stocks": session.get('favorite_stocks', []),
            "params": session.get('params', {}),
            "status": session.get('status', 'running')
        }
    finally:
        db.close()


@router.post("/end")
async def end_backtest(request: EndBacktestRequest):
    """结束回测并计算完整统计指标"""
    if request.session_id not in backtest_sessions:
        # 尝试从数据库恢复会话
        db = SessionLocal()
        try:
            db_session = db.query(DBBacktestSession).filter(
                DBBacktestSession.session_id == request.session_id
            ).first()
            
            if not db_session:
                raise HTTPException(status_code=404, detail="回测会话不存在")
            
            # 会话已经在数据库中标记为finished，返回之前保存的结果
            if db_session.status == 'finished':
                return {
                    "session_id": request.session_id,
                    "start_date": db_session.start_date or "",
                    "end_date": db_session.end_date or "",
                    "initial_capital": float(db_session.initial_capital or 0),
                    "final_equity": float(db_session.final_equity or 0),
                    "total_profit": float(db_session.final_equity or 0) - float(db_session.initial_capital or 0),
                    "total_profit_pct": ((float(db_session.final_equity or 0) - float(db_session.initial_capital or 0)) / float(db_session.initial_capital or 1)) * 100,
                    "trade_count": 0,  # 可以从交易记录表查询
                    "buy_count": 0,
                    "sell_count": 0,
                    "strategy": db_session.strategy or "",
                    "annualized_return": 0,
                    "max_drawdown": 0,
                    "sharpe_ratio": 0,
                    "win_rate": 0,
                    "profit_loss_ratio": 0,
                    "avg_holding_days": 0,
                    "trade_days": 0,
                    "message": "会话已结束"
                }
            else:
                # 会话未完成，尝试从数据库恢复会话数据
                if not db_session.session_data:
                    raise HTTPException(status_code=400, detail="会话数据已丢失，无法结束回测。请重新开始回测。")
                
                # 从JSON恢复会话数据到内存
                try:
                    session_data = json.loads(db_session.session_data)
                    backtest_sessions[request.session_id] = session_data
                    print(f"从数据库恢复会话: {request.session_id}")
                except Exception as e:
                    print(f"恢复会话数据失败: {str(e)}")
                    raise HTTPException(status_code=500, detail=f"恢复会话数据失败: {str(e)}")
        finally:
            db.close()
    
    session = backtest_sessions[request.session_id]
    
    # 计算最终权益（需要使用当日收盘价计算持仓市值）
    db = SessionLocal()
    try:
        current_date_obj = datetime.strptime(session['current_date'], '%Y%m%d').date()
        
        # 批量查询所有持仓股票的当日收盘价
        position_codes = list(session['positions'].keys())
        total_market_value = 0
        
        if position_codes:
            stocks_data = db.query(StockDaily)\
                .filter(StockDaily.stock_code.in_(position_codes))\
                .filter(StockDaily.trade_date == current_date_obj)\
                .all()
            
            stocks_dict = {s.stock_code: s for s in stocks_data}
            
            # 使用当日收盘价重新计算持仓市值
            for code, pos in session['positions'].items():
                stock = stocks_dict.get(code)
                if stock:
                    current_price = float(stock.close)
                    market_value = current_price * pos['shares']
                    total_market_value += market_value
                    # 更新持仓的最终价格和市值
                    pos['current_price'] = current_price
                    pos['market_value'] = market_value
                else:
                    # 如果无法获取当日价格，使用已保存的市值
                    total_market_value += pos.get('market_value', pos['cost_price'] * pos['shares'])
        
        final_equity = session['cash'] + total_market_value
    finally:
        db.close()
    
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
        # 兼容多种格式：字典 {'date': ..., 'equity': ...}、元组 (date, equity)、列表 [date, equity]
        try:
            if isinstance(item, dict):
                equity = float(item.get('equity', 0))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                # 元组或列表格式，第二个元素是equity
                equity = float(item[1])
            else:
                # 无法识别的格式，跳过
                continue
        except (ValueError, TypeError, IndexError) as e:
            # 转换失败，跳过该数据点
            print(f"警告: equity_curve数据格式错误: {item}, 错误: {e}")
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
                # 兼容多种格式获取equity值
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
                
                if prev_equity > 0:  # 避免除零
                    daily_return = (curr_equity - prev_equity) / prev_equity
                    returns.append(daily_return)
            except (ValueError, TypeError, IndexError) as e:
                # 转换失败，跳过该数据点
                print(f"警告: 计算收益率时数据格式错误，跳过")
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
    
    # 返回完整统计指标
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
        # 高级统计指标
        "annualized_return": round(annualized_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe_ratio, 3),
        "win_rate": round(win_rate, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "avg_holding_days": round(avg_holding_days, 1),
        "trade_days": trade_days
    }
    
    # 更新数据库中的会话状态
    db = SessionLocal()
    try:
        db_session = db.query(DBBacktestSession).filter(
            DBBacktestSession.session_id == request.session_id
        ).first()
        
        if db_session:
            db_session.status = 'finished'
            db_session.end_date = session['current_date']
            db_session.final_equity = final_equity
            db_session.updated_at = datetime.now()
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"更新数据库失败: {str(e)}")
    finally:
        db.close()
    
    return result



@router.get("/candidates")
async def get_candidates(
    session_id: str,
    filter_type: str = "all"
):
    """
    获取当前日期的候选池（数据库版本）
    """
    session = get_or_restore_session(session_id)
    current_date = session['current_date']
    strategy = session['params']['strategy']
    
    # 使用数据库查询候选池
    db = SessionLocal()
    try:
        date_obj = datetime.strptime(current_date, '%Y%m%d').date()
        
        picks = db.query(StrategyPick)\
            .filter(StrategyPick.strategy == strategy)\
            .filter(StrategyPick.trade_date == date_obj)\
            .all()
        
        stocks_info = []
        for pick in picks:
            # 如果filter_type是extreme_b1，只保留满足条件的
            if filter_type == 'extreme_b1' and not pick.is_extreme_b1:
                continue
            
            stocks_info.append({
                "code": pick.stock_code,
                "close": float(pick.close) if pick.close else 0,
                "change_pct": float(pick.change_pct) if pick.change_pct else 0,
                "volume": int(pick.volume) if pick.volume else 0,
                "is_extreme_b1": bool(pick.is_extreme_b1),
                "consecutive_extreme_b1_days": int(pick.consecutive_extreme_b1_days or 0)
            })
        
        return {
            "date": current_date,
            "strategy": strategy,
            "filter_type": filter_type,
            "count": len(stocks_info),
            "stocks": stocks_info
        }
    finally:
        db.close()


@router.get("/learning-cases")
async def get_learning_cases(date: str, strategy: str):
    """
    获取学习案例（优秀案例）- 从JSON文件读取
    
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
            """为案例添加极致B1标记、连续极致B1天数，以及 brick 策略的打分和F6"""
            marked_cases = {}
            db = SessionLocal()

            # brick策略：批量预取砖型方向+F6数据
            brick_dirs_map: dict = {}
            if strategy == 'brick':
                all_codes = list({
                    case.get('stock_code', '')
                    for cases_list in cases_dict.values()
                    for case in cases_list
                    if case.get('stock_code')
                })
                if all_codes:
                    brick_dirs_map = get_brick_momentum_directions_batch(all_codes, date)

            try:
                date_obj = datetime.strptime(date, '%Y%m%d').date()
                
                for period, cases_list in cases_dict.items():
                    marked_list = []
                    for case in cases_list:
                        stock_code = case.get('stock_code', '')

                        # ── 极致B1 标记（仅 B1 策略）──────────────────
                        is_extreme_b1 = False
                        consecutive_extreme_b1_days = 0
                        if strategy == 'B1':
                            try:
                                stock_data = db.query(StockDaily)\
                                    .filter(StockDaily.stock_code == stock_code)\
                                    .filter(StockDaily.trade_date == date_obj)\
                                    .first()
                                if stock_data:
                                    is_extreme_b1 = check_extreme_b1_condition(
                                        stock_code,
                                        float(stock_data.factor_amplitude or 0),
                                        float(stock_data.factor_volume_ratio or 0)
                                    )
                                    if is_extreme_b1:
                                        consecutive_extreme_b1_days = get_consecutive_extreme_b1_days(stock_code, date)
                            except Exception as e:
                                print(f"处理股票 {stock_code} 时出错: {e}")
                        case['is_extreme_b1'] = bool(is_extreme_b1)
                        case['consecutive_extreme_b1_days'] = int(consecutive_extreme_b1_days)

                        # ── brick 策略：打分 + F6 ─────────────────────
                        if strategy == 'brick' and stock_code:
                            try:
                                stock_data = db.query(StockDaily)\
                                    .filter(StockDaily.stock_code == stock_code)\
                                    .filter(StockDaily.trade_date == date_obj)\
                                    .first()
                                if stock_data:
                                    brick_dirs = brick_dirs_map.get(stock_code, {})
                                    red_len   = brick_dirs.get('red_len', 0.0)
                                    green_len = brick_dirs.get('green_len', 0.0)
                                    f6_red_count = brick_dirs.get('f6_red_count')
                                    close_val  = float(stock_data.close or 0)
                                    prev_close = float(stock_data.prev_close or 0)
                                    change_pct = round((close_val - prev_close) / prev_close * 100, 3) if prev_close else 0.0
                                    multi_line = float(stock_data.multi_line) if stock_data.multi_line else None
                                    ema10_2    = float(stock_data.ema10_2)    if stock_data.ema10_2    else None
                                    # 若 red_len/green_len 为 0（信号日可能不是绿转红），仍计算用于展示
                                    bs = calc_brick_score(
                                        stock_code=stock_code,
                                        red_len=red_len,
                                        green_len=green_len,
                                        change_pct=change_pct,
                                        multi_line=multi_line,
                                        ema10_2=ema10_2,
                                        close=close_val,
                                        f6_red_count=f6_red_count,
                                    )
                                    case['brick_score'] = bs.get('score')
                                    case['f6_red_count'] = f6_red_count
                            except Exception as e:
                                print(f"brick打分 {stock_code} 出错: {e}")

                        marked_list.append(case)
                        
                    marked_cases[period] = marked_list
            finally:
                db.close()
            
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


@router.get("/history")
async def get_backtest_history():
    """
    获取历史回测记录列表
    
    从内存会话和数据库中查询已结束的回测记录
    
    Returns:
        历史记录列表
    """
    history = []
    
    # 1. 从内存会话中获取已结束的回测
    for session_id, session in backtest_sessions.items():
        if session.get('status') == 'finished':
            history.append({
                "session_id": session_id,
                "start_date": session.get('start_date', ''),
                "end_date": session.get('end_date', ''),
                "initial_capital": float(session.get('initial_capital', 0)),
                "final_equity": float(session.get('final_equity', 0)),
                "strategy": session.get('params', {}).get('strategy', ''),
                "trade_count": len(session.get('trade_log', []))
            })
    
    # 2. 从数据库中获取已保存的回测记录
    db = SessionLocal()
    try:
        db_sessions = db.query(DBBacktestSession).filter(
            DBBacktestSession.status == 'finished'
        ).order_by(
            DBBacktestSession.created_at.desc()
        ).limit(100).all()  # 最多返回100条记录
        
        for db_session in db_sessions:
            # 避免重复（如果内存中已有）
            if db_session.session_id not in [h['session_id'] for h in history]:
                history.append({
                    "session_id": db_session.session_id,
                    "start_date": db_session.start_date or '',
                    "end_date": db_session.end_date or '',
                    "initial_capital": float(db_session.initial_capital or 0),
                    "final_equity": float(db_session.final_equity or 0),
                    "strategy": db_session.strategy or '',
                    "trade_count": 0  # 需要额外查询交易记录表
                })
    finally:
        db.close()
    
    # 按结束日期降序排序
    history.sort(key=lambda x: x.get('end_date', ''), reverse=True)
    
    return {"history": history}


@router.delete("/history/{session_id}")
async def delete_backtest_history(session_id: str):
    """
    删除历史回测记录
    
    Args:
        session_id: 回测会话ID
    
    Returns:
        删除结果
    """
    deleted = False
    
    # 1. 从内存中删除
    if session_id in backtest_sessions:
        del backtest_sessions[session_id]
        deleted = True
    
    # 2. 从数据库中删除
    db = SessionLocal()
    try:
        db_session = db.query(DBBacktestSession).filter(
            DBBacktestSession.session_id == session_id
        ).first()
        
        if db_session:
            db.delete(db_session)
            db.commit()
            deleted = True
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除数据库记录失败: {str(e)}")
    finally:
        db.close()
    
    if not deleted:
        raise HTTPException(status_code=404, detail="回测记录不存在")
    
    return {"message": "删除成功", "session_id": session_id}


@router.get("/detail")
async def get_backtest_detail(session_id: str):
    """
    获取回测详细信息
    
    Args:
        session_id: 会话ID
        
    Returns:
        详细信息(包含交易日志和权益曲线以及统计指标)
    """
    # 1. 先从内存中查找
    session = None
    if session_id in backtest_sessions:
        session = backtest_sessions[session_id]
    else:
        # 2. 从数据库中查找
        db = SessionLocal()
        try:
            db_session = db.query(DBBacktestSession).filter(
                DBBacktestSession.session_id == session_id
            ).first()
            
            if not db_session:
                raise HTTPException(status_code=404, detail="回测会话不存在")
            
            # 从数据库重建会话数据（简化版，只包含基本信息）
            session = {
                'session_id': db_session.session_id,
                'start_date': db_session.start_date or '',
                'end_date': db_session.end_date or '',
                'current_date': db_session.current_date or '',
                'initial_capital': float(db_session.initial_capital or 0),
                'final_equity': float(db_session.final_equity or 0),
                'cash': float(db_session.cash or 0),
                'status': db_session.status or 'finished',
                'params': {
                    'strategy': db_session.strategy or '',
                    'slippage': float(db_session.slippage or 0),
                    'commission_rate': float(db_session.commission_rate or 0)
                },
                'positions': {},
                'trade_log': [],
                'equity_curve': [],
                'trade_days': 0
            }
        finally:
            db.close()
    
    # 3. 计算最终权益（如果还没有）
    final_equity = session.get('final_equity', 0)
    if final_equity == 0:
        db = SessionLocal()
        try:
            current_date_obj = datetime.strptime(session['current_date'], '%Y%m%d').date()
            final_equity = session['cash']
            
            # 查询持仓股票的当日价格
            position_codes = list(session['positions'].keys())
            if position_codes:
                stocks_data = db.query(StockDaily)\
                    .filter(StockDaily.stock_code.in_(position_codes))\
                    .filter(StockDaily.trade_date == current_date_obj)\
                    .all()
                
                stocks_dict = {s.stock_code: s for s in stocks_data}
                for code, pos in session['positions'].items():
                    stock = stocks_dict.get(code)
                    if stock:
                        final_equity += float(stock.close) * pos['shares']
        finally:
            db.close()
    
    # 4. 计算总收益
    initial_capital = session['initial_capital']
    total_profit = final_equity - initial_capital
    total_profit_pct = (total_profit / initial_capital) * 100 if initial_capital > 0 else 0
    
    # 5. 计算交易统计
    trade_log = session.get('trade_log', [])
    buy_count = len([log for log in trade_log if log['action'] == 'buy'])
    sell_count = len([log for log in trade_log if log['action'] == 'sell'])
    
    # 6. 计算年化收益率
    trade_days = session.get('trade_days', 0)
    if trade_days > 0:
        annualized_return = ((1 + total_profit_pct / 100) ** (244 / trade_days) - 1) * 100
    else:
        annualized_return = 0
    
    # 7. 使用equity_curve计算最大回撤
    max_drawdown = 0
    peak_equity = initial_capital
    equity_curve = session.get('equity_curve', [])
    
    for item in equity_curve:
        try:
            # 兼容多种格式：字典、元组、列表
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
        if peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    
    # 8. 计算夏普比率
    sharpe_ratio = 0
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            try:
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
            except (ValueError, TypeError, IndexError):
                continue
            
            if prev_equity > 0:
                daily_return = (curr_equity - prev_equity) / prev_equity
                returns.append(daily_return)
        
        if len(returns) > 0:
            import numpy as np
            mean_return = np.mean(returns)
            std_return = np.std(returns)
            risk_free_rate = 0.03 / 244
            sharpe_ratio = (mean_return - risk_free_rate) / std_return * np.sqrt(244) if std_return > 0 else 0
    
    # 9. 计算胜率和盈亏比
    winning_trades = 0
    losing_trades = 0
    total_win_amount = 0
    total_loss_amount = 0
    
    buy_positions = {}
    for log in trade_log:
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
    
    # 10. 计算平均持仓天数
    holding_days_list = []
    for log in trade_log:
        if log['action'] == 'sell' and 'holding_days' in log:
            holding_days_list.append(log.get('holding_days', 0))
    
    avg_holding_days = sum(holding_days_list) / len(holding_days_list) if holding_days_list else 0
    
    # 11. 将equity_curve转换为前端需要的格式
    snapshots_for_frontend = []
    for item in equity_curve:
        if isinstance(item, dict):
            snapshots_for_frontend.append({
                "date": item.get('date', ''),
                "equity": item.get('equity', 0)
            })
        else:
            snapshots_for_frontend.append({
                "date": item[0] if len(item) > 0 else '',
                "equity": item[1] if len(item) > 1 else 0
            })
    
    # 12. 返回完整详情
    return {
        "session_id": session_id,
        "params": session.get('params', {}),
        "start_date": session.get('start_date', ''),
        "end_date": session.get('end_date', session.get('current_date', '')),
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "total_profit": round(total_profit, 2),
        "total_profit_pct": round(total_profit_pct, 2),
        "trade_log": trade_log,
        "snapshots": snapshots_for_frontend,
        # 统计指标
        "trade_days": trade_days,
        "trade_count": len(trade_log),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "annualized_return": round(annualized_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe_ratio, 3),
        "win_rate": round(win_rate, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "avg_holding_days": round(avg_holding_days, 1)
    }


@router.post("/favorite/add")
async def add_to_favorite(request: FavoriteStockRequest):
    """
    添加股票到精选池
    
    Args:
        request: 精选池请求（包含股票代码列表和备注）
        
    Returns:
        更新后的精选池
    """
    session = get_or_restore_session(request.session_id)
    current_date = session['current_date']
    
    # 初始化精选池（如果不存在）
    if 'favorite_stocks' not in session:
        session['favorite_stocks'] = []
    
    # 从数据库查询股票信息
    db = SessionLocal()
    try:
        date_obj = datetime.strptime(current_date, '%Y%m%d').date()
        strategy = session['params']['strategy']
        
        # 批量查询股票数据
        stocks_data = db.query(StockDaily)\
            .filter(StockDaily.stock_code.in_(request.stock_codes))\
            .filter(StockDaily.trade_date == date_obj)\
            .all()
        
        stocks_dict = {s.stock_code: s for s in stocks_data}
        
        # 查询极致B1信息（从候选池表）
        picks_data = db.query(StrategyPick)\
            .filter(StrategyPick.stock_code.in_(request.stock_codes))\
            .filter(StrategyPick.trade_date == date_obj)\
            .filter(StrategyPick.strategy == strategy)\
            .all()
        
        picks_dict = {p.stock_code: p for p in picks_data}
        
        # 获取已在精选池中的股票代码
        existing_codes = {fav['stock_code'] for fav in session['favorite_stocks']}
        
        added_count = 0
        for stock_code in request.stock_codes:
            # 跳过已存在的
            if stock_code in existing_codes:
                continue
            
            stock = stocks_dict.get(stock_code)
            if not stock:
                continue
            
            pick = picks_dict.get(stock_code)
            
            # 检查是否已买入
            is_bought = stock_code in session['positions']
            buy_date = session['positions'][stock_code]['buy_date'] if is_bought else None
            
            favorite_item = {
                "stock_code": stock_code,
                "stock_name": stock_code,  # 暂时使用股票代码作为名称
                "add_date": current_date,
                "add_price": float(stock.close),
                "note": request.note,
                "is_extreme_b1": bool(pick.is_extreme_b1) if pick else False,
                "consecutive_days": int(pick.consecutive_extreme_b1_days or 0) if pick else 0,
                "is_bought": is_bought,
                "buy_date": buy_date
            }
            
            session['favorite_stocks'].append(favorite_item)
            added_count += 1
        
        return {
            "success": True,
            "message": f"已添加 {added_count} 个股票到精选池",
            "favorite_stocks": session['favorite_stocks']
        }
    finally:
        db.close()


@router.post("/favorite/remove")
async def remove_from_favorite(request: FavoriteStockRequest):
    """
    从精选池移除股票
    
    Args:
        request: 精选池请求（包含股票代码列表）
        
    Returns:
        更新后的精选池
    """
    session = get_or_restore_session(request.session_id)
    
    if 'favorite_stocks' not in session:
        session['favorite_stocks'] = []
    
    # 移除指定的股票
    removed_count = 0
    session['favorite_stocks'] = [
        fav for fav in session['favorite_stocks']
        if fav['stock_code'] not in request.stock_codes
    ]
    removed_count = len(request.stock_codes)
    
    return {
        "success": True,
        "message": f"已从精选池移除 {removed_count} 个股票",
        "favorite_stocks": session['favorite_stocks']
    }


@router.get("/favorite")
async def get_favorite_stocks(session_id: str):
    """
    获取精选池列表（包含实时价格和极致B1信息）
    
    Args:
        session_id: 会话ID
        
    Returns:
        精选池列表
    """
    session = get_or_restore_session(session_id)
    current_date = session['current_date']
    strategy = session['params']['strategy']
    
    if 'favorite_stocks' not in session:
        session['favorite_stocks'] = []
    
    # 从数据库获取当前价格
    db = SessionLocal()
    try:
        date_obj = datetime.strptime(current_date, '%Y%m%d').date()
        
        stock_codes = [fav['stock_code'] for fav in session['favorite_stocks']]
        
        if not stock_codes:
            return {
                "date": current_date,
                "count": 0,
                "favorites": []
            }
        
        # 批量查询当前价格
        stocks_data = db.query(StockDaily)\
            .filter(StockDaily.stock_code.in_(stock_codes))\
            .filter(StockDaily.trade_date == date_obj)\
            .all()
        
        stocks_dict = {s.stock_code: s for s in stocks_data}
        
        # 批量查询极致B1信息（从候选池表）
        picks_data = db.query(StrategyPick)\
            .filter(StrategyPick.stock_code.in_(stock_codes))\
            .filter(StrategyPick.trade_date == date_obj)\
            .filter(StrategyPick.strategy == strategy)\
            .all()
        
        picks_dict = {p.stock_code: p for p in picks_data}
        
        # 更新精选池的当前价格和极致B1信息
        favorites_with_price = []
        for fav in session['favorite_stocks']:
            stock = stocks_dict.get(fav['stock_code'])
            pick = picks_dict.get(fav['stock_code'])
            fav_with_price = fav.copy()
            
            if stock:
                current_price = float(stock.close)
                fav_with_price['current_price'] = current_price
                fav_with_price['change_pct'] = round(
                    (current_price - fav['add_price']) / fav['add_price'] * 100, 2
                )
            else:
                fav_with_price['current_price'] = fav['add_price']
                fav_with_price['change_pct'] = 0
            
            # 更新极致B1信息（随着日期推进，极致B1状态可能变化）
            if pick:
                fav_with_price['is_extreme_b1'] = bool(pick.is_extreme_b1)
                fav_with_price['consecutive_days'] = int(pick.consecutive_extreme_b1_days or 0)
            else:
                # 如果当前日期不在候选池中，保持原有的极致B1标记，但天数置为0
                fav_with_price['consecutive_days'] = 0
            
            # 检查是否已买入（实时状态）
            is_bought = fav['stock_code'] in session['positions']
            fav_with_price['is_bought'] = is_bought
            if is_bought and not fav.get('buy_date'):
                fav_with_price['buy_date'] = session['positions'][fav['stock_code']]['buy_date']
            
            favorites_with_price.append(fav_with_price)
        
        # 按加入日期排序（最新的在前）
        favorites_with_price.sort(key=lambda x: x['add_date'], reverse=True)
        
        return {
            "date": current_date,
            "count": len(favorites_with_price),
            "favorites": favorites_with_price
        }
    finally:
        db.close()
