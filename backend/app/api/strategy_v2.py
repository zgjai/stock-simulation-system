"""选股策略API - 数据库版本

使用SQLite数据库查询，替代文件读取
性能提升约37倍
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from datetime import datetime, timedelta
from functools import lru_cache
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from app.database_sqlite import SessionLocal, StockDaily, StrategyPick

router = APIRouter()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────────────────────
# Brick 多因子打分模型（实证甜区规则，来自 multi_factor_return_brick_report.txt）
# ──────────────────────────────────────────────────────────────────────────────

# 主板(00/60) 打分规则
_BRICK_SCORE_RULES_MAIN = {
    'f1': {'direction': 'low',  'sweet_thr': 1.400, 'bad_thr': 3.328},
    'f2': {'direction': 'high', 'sweet_thr': 3.931, 'bad_thr': 1.916},
    'f3_up':   {'direction': 'low',  'sweet_thr': 1.866, 'bad_thr': 3.532},
    'f3_down': {'direction': 'mid',  'sweet_lo': 3.916, 'sweet_hi': 20.527},
    'f4': {'direction': 'high', 'sweet_thr': 1.108, 'bad_thr': 1.047},
    'f5': {'direction': 'high', 'sweet_thr': 1.058, 'bad_thr': 1.017},
}

# 创业板/科创板/北交所(30/68/92) 打分规则
_BRICK_SCORE_RULES_GEM = {
    'f1': {'direction': 'low',  'sweet_thr': 1.386, 'bad_thr': 3.268},
    'f2': {'direction': 'high', 'sweet_thr': 4.677, 'bad_thr': 2.297},
    'f3_up':   {'direction': 'low',  'sweet_thr': 1.626, 'bad_thr': 3.027},
    'f3_down': {'direction': 'low',  'sweet_thr': 2.324, 'bad_thr': 6.383},
    'f4': {'direction': 'high', 'sweet_thr': 1.119, 'bad_thr': 1.053},
    'f5': {'direction': 'high', 'sweet_thr': 1.065, 'bad_thr': 1.018},
}


def _score_one_factor(val, rule: dict) -> int:
    """对单个因子值按规则打分，返回 +1 / 0 / -1"""
    if val is None:
        return 0
    d = rule['direction']
    if d == 'high':
        if val >= rule['sweet_thr']:
            return 1
        if val < rule['bad_thr']:
            return -1
        return 0
    elif d == 'low':
        if val <= rule['sweet_thr']:
            return 1
        if val > rule['bad_thr']:
            return -1
        return 0
    else:  # mid
        if rule['sweet_lo'] <= val <= rule['sweet_hi']:
            return 1
        return 0


def calc_brick_score(stock_code: str,
                     red_len: float, green_len: float,
                     change_pct: float,
                     multi_line: float, ema10_2: float,
                     close: float,
                     f6_red_count: int = None) -> dict:
    """
    计算 brick 策略多因子打分（含 F6：近6日红柱数量）。

    Returns:
        {
          'score': int,          # 总分
          'label': str,          # '优先关注' / '正常对待' / '谨慎回避'
          'factors': {...},
          'score_detail': {f1: +1, f2: 0, ...},
          'f6_red_count': int,   # 近6日(T-2~T-7)红动量柱天数
        }
    """
    prefix = stock_code[:2]
    rules = _BRICK_SCORE_RULES_MAIN if prefix in ('00', '60') else _BRICK_SCORE_RULES_GEM

    # 因子值
    f1 = round(red_len / green_len, 4) if green_len > 0 else None
    f2 = round(change_pct, 3)
    # F3：涨日用 f3_up，跌日用 f3_down
    f3_up   = round(red_len / f2, 4)   if f2 >= 0.2  else None
    f3_down = round(red_len / abs(f2), 4) if f2 <= -0.2 else None
    f4 = round(close / multi_line, 5) if multi_line and multi_line > 0 else None
    f5 = round(close / ema10_2, 5)    if ema10_2   and ema10_2   > 0 else None

    # 打分
    s1 = _score_one_factor(f1, rules['f1'])
    s2 = _score_one_factor(f2, rules['f2'])
    s3 = _score_one_factor(f3_up,   rules['f3_up'])   if f2 >= 0.2  else \
         _score_one_factor(f3_down, rules['f3_down'])  if f2 <= -0.2 else 0
    s4 = _score_one_factor(f4, rules['f4'])
    s5 = _score_one_factor(f5, rules['f5'])

    total = s1 + s2 + s3 + s4 + s5

    if total >= 2:
        label = '优先关注'
    elif total >= 0:
        label = '正常对待'
    else:
        label = '谨慎回避'

    return {
        'score': total,
        'label': label,
        'factors': {
            'f1': f1, 'f2': f2,
            'f3_up': f3_up, 'f3_down': f3_down,
            'f4': f4, 'f5': f5,
        },
        'score_detail': {
            'f1': s1, 'f2': s2, 'f3': s3, 'f4': s4, 'f5': s5,
        },
        'f6_red_count': f6_red_count,
    }


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@lru_cache(maxsize=100)
def get_all_trade_dates_from_db() -> List[str]:
    """从数据库获取所有交易日期（升序，缓存结果）"""
    db = SessionLocal()
    try:
        dates = db.query(StockDaily.trade_date)\
            .distinct()\
            .order_by(StockDaily.trade_date)\
            .all()
        return [d[0].strftime('%Y%m%d') for d in dates]
    finally:
        db.close()


def get_brick_momentum_directions_batch(stock_codes: list, date: str) -> dict:
    """
    批量获取多只股票当日和前一日的砖型动量柱方向，以及砖型选股所需的柱长度数据，
    同时计算 F6（T-2 ~ T-7 共6天内红动量柱数量）。
    
    Args:
        stock_codes: 股票代码列表
        date: 当前日期（YYYYMMDD）
        
    Returns:
        {stock_code: {
            "today_red": bool, "prev_red": bool,
            "today_delta": float,
            "prev_delta": float,
            "red_len": float,
            "green_len": float,
            "f6_red_count": int | None,   # T-2~T-7 中红柱天数，数据不足时为 None
        }, ...}
    """
    default = {"today_red": False, "prev_red": False, "today_delta": 0.0, "prev_delta": 0.0,
               "red_len": 0.0, "green_len": 0.0, "f6_red_count": None}
    if not stock_codes:
        return {}
    try:
        all_dates = get_all_trade_dates_from_db()
        if not all_dates:
            return {code: dict(default) for code in stock_codes}
        
        try:
            curr_idx = all_dates.index(date)
        except ValueError:
            return {code: dict(default) for code in stock_codes}
        
        if curr_idx < 2:
            return {code: dict(default) for code in stock_codes}
        
        # 需要 T、T-1、T-2 用于基础计算；T-2~T-7 用于 F6（需要 T-8 作为 T-7 的前一日）
        # 共需要 T ~ T-8，最多9个日期（curr_idx - 8 >= 0 时 F6 完整）
        max_lookback = min(curr_idx, 8)  # 最多往前8天
        needed_dates = [
            datetime.strptime(all_dates[curr_idx - i], '%Y%m%d').date()
            for i in range(max_lookback + 1)
        ]
        
        db = SessionLocal()
        rows = db.query(StockDaily.stock_code, StockDaily.trade_date, StockDaily.brick_value)\
            .filter(StockDaily.stock_code.in_(stock_codes))\
            .filter(StockDaily.trade_date.in_(needed_dates))\
            .all()
        db.close()
        
        # 按股票代码分组 brick_value，key = trade_date
        bv_map: dict = {}
        for row in rows:
            code = row.stock_code
            if code not in bv_map:
                bv_map[code] = {}
            bv_map[code][row.trade_date] = float(row.brick_value) if row.brick_value is not None else None
        
        result = {}
        for code in stock_codes:
            bv = bv_map.get(code, {})
            today_bv = bv.get(needed_dates[0])   # T
            prev_bv  = bv.get(needed_dates[1]) if len(needed_dates) > 1 else None  # T-1
            prev2_bv = bv.get(needed_dates[2]) if len(needed_dates) > 2 else None  # T-2
            
            today_red = (today_bv is not None and prev_bv is not None and today_bv > prev_bv)
            prev_red  = (prev_bv  is not None and prev2_bv is not None and prev_bv  > prev2_bv)
            
            today_delta = (today_bv - prev_bv) if (today_bv is not None and prev_bv is not None) else 0.0
            prev_delta  = (prev_bv - prev2_bv)  if (prev_bv  is not None and prev2_bv is not None) else 0.0
            
            red_len   = today_delta if today_delta > 0 else 0.0
            green_len = abs(prev_delta) if prev_delta < 0 else 0.0

            # F6：统计 T-2 ~ T-7 共6天的红动量柱数量
            # T-k 的动量柱 = brick_value[T-k] - brick_value[T-k-1]，即 needed_dates[k] - needed_dates[k+1]
            f6_red_count = None
            if max_lookback >= 8:  # 保证 needed_dates 有 T ~ T-8（共9个）
                f6_count = 0
                f6_valid = True
                for k in range(2, 8):  # k = 2..7
                    bv_k  = bv.get(needed_dates[k])      # T-k
                    bv_k1 = bv.get(needed_dates[k + 1])  # T-k-1
                    if bv_k is None or bv_k1 is None:
                        f6_valid = False
                        break
                    if bv_k > bv_k1:
                        f6_count += 1
                if f6_valid:
                    f6_red_count = f6_count
            
            result[code] = {
                "today_red": today_red,
                "prev_red":  prev_red,
                "today_delta": round(today_delta, 4),
                "prev_delta":  round(prev_delta, 4),
                "red_len":   round(red_len, 4),
                "green_len": round(green_len, 4),
                "f6_red_count": f6_red_count,
            }
        return result
        
    except Exception as e:
        print(f"批量获取砖型动量柱方向错误: {e}")
        return {code: dict(default) for code in stock_codes}


def check_extreme_b1_condition(stock_code: str, amplitude: float, volume_ratio: float) -> bool:
    """
    检查是否满足极致B1条件
    
    Args:
        stock_code: 股票代码
        amplitude: 振幅
        volume_ratio: 成交量比率
        
    Returns:
        是否满足极致B1条件
    """
    if amplitude is None or volume_ratio is None:
        return False
    
    # 判断市场分组
    prefix = stock_code[:2]
    if prefix in ['00', '60']:
        # 主板(00/60): 当日振幅>=2.68 且 成交量比率>=0.59
        return amplitude >= 2.68 and volume_ratio >= 0.59
    elif prefix in ['30', '68', '92']:
        # 创业板/科创板/北交所(30/68/92): 当日振幅>=3.46 且 成交量比率>=0.42
        return amplitude >= 3.46 and volume_ratio >= 0.42
    else:
        return False


def get_consecutive_extreme_b1_days(stock_code: str, date: str, max_days: int = 5) -> int:
    """
    计算截止到前一日，连续极致B1的天数
    
    Args:
        stock_code: 股票代码
        date: 当前日期（YYYYMMDD）
        max_days: 最大追溯天数
        
    Returns:
        连续极致B1天数 (0-max_days)
    """
    try:
        db = SessionLocal()
        
        # 获取所有交易日期
        all_dates = get_all_trade_dates_from_db()
        if not all_dates:
            return 0
        
        # 找到当前日期的索引
        try:
            curr_idx = all_dates.index(date)
        except ValueError:
            return 0
        
        consecutive_days = 0
        
        # 从前1日开始向前追溯
        for i in range(1, max_days + 1):
            if curr_idx - i < 0:
                break
            
            prev_date_str = all_dates[curr_idx - i]
            prev_date = datetime.strptime(prev_date_str, '%Y%m%d').date()
            
            # 查询前N日数据
            prev_data = db.query(StockDaily)\
                .filter(StockDaily.stock_code == stock_code)\
                .filter(StockDaily.trade_date == prev_date)\
                .first()
            
            if not prev_data:
                break
            
            # 检查前N日是否满足B1和极致B1条件
            if prev_data.b1_signal == 1 and check_extreme_b1_condition(
                stock_code, 
                prev_data.factor_amplitude, 
                prev_data.factor_volume_ratio
            ):
                consecutive_days = i
            else:
                break  # 一旦中断就停止
        
        db.close()
        return consecutive_days
        
    except Exception as e:
        print(f"计算连续极致B1天数错误: {e}")
        return 0


@router.get("/picks")
async def get_picks(
    date: str = Query(..., description="日期（YYYYMMDD格式）"),
    strategy: str = Query(..., description="策略名称（B1/B2/brick/single_needle）"),
    filter_type: str = Query("all", description="筛选类型（all/extreme_b1）"),
    brick_ratio: float = Query(0.667, description="砖型选股策略红柱/绿柱长度比例门槛（如0.667=2/3，1.0=1倍，1.5=1.5倍，2.0=2倍，3.0=3倍）")
):
    """
    获取指定日期和策略的候选池（数据库版本）
    
    Args:
        date: 日期（YYYYMMDD格式）
        strategy: 策略名称
        filter_type: 筛选类型（all=全部, extreme_b1=极致B1）
        
    Returns:
        候选池信息
    """
    try:
        db = SessionLocal()
        
        # 转换日期格式
        try:
            date_obj = datetime.strptime(date, '%Y%m%d').date()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误，应为YYYYMMDD")
        
        # 从 strategy_picks 表查询候选池
        picks = db.query(StrategyPick)\
            .filter(StrategyPick.strategy == strategy)\
            .filter(StrategyPick.trade_date == date_obj)\
            .all()
        
        if not picks:
            db.close()
            return {
                "date": date,
                "strategy": strategy,
                "filter_type": filter_type,
                "count": 0,
                "extreme_b1_count": 0,
                "stocks": []
            }
        
        # 构建返回数据
        stocks_info = []
        
        # 批量获取所有候选股票的砖型动量柱方向（一次查询，性能优化）
        all_stock_codes = [pick.stock_code for pick in picks]
        brick_dirs_map = get_brick_momentum_directions_batch(all_stock_codes, date)

        # brick策略：批量获取当日 multi_line / ema10_2 用于打分
        indicator_map: dict = {}
        if strategy == 'brick':
            try:
                rows = db.query(
                    StockDaily.stock_code,
                    StockDaily.multi_line,
                    StockDaily.ema10_2,
                ).filter(
                    StockDaily.stock_code.in_(all_stock_codes),
                    StockDaily.trade_date == date_obj,
                ).all()
                for r in rows:
                    indicator_map[r.stock_code] = {
                        'multi_line': float(r.multi_line) if r.multi_line is not None else None,
                        'ema10_2':    float(r.ema10_2)    if r.ema10_2    is not None else None,
                    }
            except Exception as e:
                print(f"批量获取指标数据错误: {e}")
        
        for pick in picks:
            # 检查是否满足极致B1条件
            is_extreme_b1 = pick.is_extreme_b1
            consecutive_extreme_b1_days = pick.consecutive_extreme_b1_days or 0
            
            # 如果filter_type是extreme_b1，只保留满足条件的
            if filter_type == 'extreme_b1' and not is_extreme_b1:
                continue
            
            # 获取砖型动量柱方向（当日和前一日）及柱长度
            default_brick = {"today_red": False, "prev_red": False, "today_delta": 0.0, "prev_delta": 0.0,
                             "red_len": 0.0, "green_len": 0.0, "f6_red_count": None}
            brick_dirs = brick_dirs_map.get(pick.stock_code, default_brick)
            today_brick_red = brick_dirs["today_red"]
            prev_brick_red  = brick_dirs["prev_red"]
            red_len   = brick_dirs.get("red_len", 0.0)
            green_len = brick_dirs.get("green_len", 0.0)
            f6_red_count = brick_dirs.get("f6_red_count")
            
            # 判断是否满足极致B1+条件：is_extreme_b1 且当日/前一日动量柱均为红柱 且当日下跌
            change_pct_val = float(pick.change_pct) if pick.change_pct else 0
            close_val      = float(pick.close)      if pick.close      else 0
            is_extreme_b1_plus = bool(
                is_extreme_b1 and
                today_brick_red and
                prev_brick_red and
                change_pct_val < 0
            )
            
            # 砖型选股策略：根据砖型比例动态过滤（绿转红 且 红柱长度 > 绿柱长度 × brick_ratio）
            if strategy == 'brick':
                is_green_to_red = (brick_dirs.get("prev_delta", 0.0) < 0 and brick_dirs.get("today_delta", 0.0) > 0)
                passes_ratio = (green_len > 0 and red_len > green_len * brick_ratio)
                brick_valid = is_green_to_red and passes_ratio
                if not brick_valid:
                    continue
            
            stock_info = {
                "code": pick.stock_code,
                "close": close_val,
                "change_pct": change_pct_val,
                "volume": int(pick.volume) if pick.volume else 0,
                "is_extreme_b1": bool(is_extreme_b1),
                "consecutive_extreme_b1_days": int(consecutive_extreme_b1_days),
                "factor_amplitude": float(pick.factor_amplitude) if pick.factor_amplitude else None,
                "factor_volume_ratio": float(pick.factor_volume_ratio) if pick.factor_volume_ratio else None,
                "today_brick_red": today_brick_red,
                "prev_brick_red": prev_brick_red,
                "is_extreme_b1_plus": is_extreme_b1_plus,
                # 砖型选股专属字段
                "brick_red_len": red_len,
                "brick_green_len": green_len,
                "brick_ratio_actual": round(red_len / green_len, 3) if green_len > 0 else None,
            }

            # brick策略：计算多因子打分（含 F6）
            if strategy == 'brick':
                ind = indicator_map.get(pick.stock_code, {})
                brick_score_result = calc_brick_score(
                    stock_code=pick.stock_code,
                    red_len=red_len,
                    green_len=green_len,
                    change_pct=change_pct_val,
                    multi_line=ind.get('multi_line'),
                    ema10_2=ind.get('ema10_2'),
                    close=close_val,
                    f6_red_count=f6_red_count,
                )
                stock_info['brick_score'] = brick_score_result
            
            stocks_info.append(stock_info)
        
        db.close()
        
        return {
            "date": date,
            "strategy": strategy,
            "filter_type": filter_type,
            "count": len(stocks_info),
            "extreme_b1_count": sum(1 for s in stocks_info if s.get('is_extreme_b1', False)),
            "extreme_b1_plus_count": sum(1 for s in stocks_info if s.get('is_extreme_b1_plus', False)),
            "stocks": stocks_info
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/stock/kline")
async def get_stock_kline(
    code: str = Query(..., description="股票代码"),
    end_date: str = Query(..., description="截止日期（YYYYMMDD）"),
    limit: int = Query(60, description="K线数量")
):
    """
    获取股票K线数据（数据库版本）
    
    Args:
        code: 股票代码
        end_date: 截止日期
        limit: K线数量
        
    Returns:
        K线数据及指标
    """
    try:
        db = SessionLocal()
        
        # 转换日期格式
        try:
            end_date_obj = datetime.strptime(end_date, '%Y%m%d').date()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误，应为YYYYMMDD")
        
        # 查询K线数据
        klines = db.query(StockDaily)\
            .filter(StockDaily.stock_code == code)\
            .filter(StockDaily.trade_date <= end_date_obj)\
            .order_by(StockDaily.trade_date.desc())\
            .limit(limit)\
            .all()
        
        if not klines:
            db.close()
            raise HTTPException(status_code=404, detail=f"股票 {code} 数据不存在")
        
        # 反转顺序（从旧到新）
        klines = list(reversed(klines))
        
        # 转换为前端需要的格式
        klines_data = []
        for k in klines:
            kline = {
                "date": k.trade_date.strftime('%Y-%m-%d'),
                "open": round(float(k.open), 2) if k.open else None,
                "high": round(float(k.high), 2) if k.high else None,
                "low": round(float(k.low), 2) if k.low else None,
                "close": round(float(k.close), 2) if k.close else None,
                "volume": int(k.volume) if k.volume else 0,
                "prev_close": round(float(k.prev_close), 2) if k.prev_close else None,
                
                # 技术指标
                "ma5": round(float(k.ma5), 2) if k.ma5 else None,
                "ma10": round(float(k.ma10), 2) if k.ma10 else None,
                "vol_ma5": int(k.vol_ma5) if k.vol_ma5 else 0,
                "vol_ma60": int(k.vol_ma60) if k.vol_ma60 else 0,
                
                "kdj_k": round(float(k.kdj_k), 2) if k.kdj_k else None,
                "kdj_d": round(float(k.kdj_d), 2) if k.kdj_d else None,
                "kdj_j": round(float(k.kdj_j), 2) if k.kdj_j else None,
                
                "macd_dif": round(float(k.macd_dif), 4) if k.macd_dif else None,
                "macd_dea": round(float(k.macd_dea), 4) if k.macd_dea else None,
                "macd_hist": round(float(k.macd_hist), 4) if k.macd_hist else None,
                
                # 知行和单针指标
                "ema10_2": round(float(k.ema10_2), 2) if k.ema10_2 else None,
                "multi_line": round(float(k.multi_line), 2) if k.multi_line else None,
                "wash_short": round(float(k.wash_short), 2) if k.wash_short else None,
                "wash_long": round(float(k.wash_long), 2) if k.wash_long else None,
                
                # 策略信号
                "b1_signal": int(k.b1_signal) if k.b1_signal else 0,
                "b2_signal": int(k.b2_signal) if k.b2_signal else 0,
                "single_needle_signal": int(k.single_needle_signal) if k.single_needle_signal else 0,
                "brick_signal": int(k.brick_signal) if k.brick_signal else 0,
                
                # 砖型图指标
                "brick_value": round(float(k.brick_value), 4) if k.brick_value is not None else 0,
                "brick_body": round(float(k.brick_body), 4) if k.brick_body is not None else 0,
            }
            klines_data.append(kline)
        
        db.close()
        
        return {
            "code": code,
            "count": len(klines_data),
            "klines": klines_data
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/dates")
async def get_available_dates(strategy: str = Query("B1", description="策略名称")):
    """
    获取可用的交易日期列表
    
    Args:
        strategy: 策略名称
        
    Returns:
        日期列表
    """
    try:
        db = SessionLocal()
        
        # 查询该策略的所有日期
        dates = db.query(StrategyPick.trade_date)\
            .filter(StrategyPick.strategy == strategy)\
            .distinct()\
            .order_by(StrategyPick.trade_date.desc())\
            .all()
        
        db.close()
        
        date_strs = [d[0].strftime('%Y%m%d') for d in dates]
        
        return {
            "strategy": strategy,
            "count": len(date_strs),
            "dates": date_strs
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
