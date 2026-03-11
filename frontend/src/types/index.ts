/**
 * TypeScript类型定义
 */

// 股票信息
export interface Stock {
  code: string
  close: number
  change_pct: number
  volume: number
}

// K线数据
export interface Kline {
  date: string
  open: number
  high: number
  low: number
  close: number
  volumn: number
  ema10_2?: number
  multi_line?: number
  ma5?: number
  ma10?: number
  kdj_k?: number
  kdj_d?: number
  kdj_j?: number
  macd_dif?: number
  macd_dea?: number
  macd_hist?: number
  wash_short?: number
  wash_long?: number
  b1_signal?: number
  b2_signal?: number
  b3_signal?: number
  single_needle_signal?: number
}

// 持仓信息
export interface Position {
  code: string
  shares: number
  cost_price: number
  current_price: number
  profit: number
  profit_pct: number
  holding_days: number
  buy_date: string
}

// 精选池股票
export interface FavoriteStock {
  stock_code: string
  stock_name: string
  add_date: string
  add_price: number
  current_price: number
  change_pct: number
  note: string
  is_extreme_b1: boolean
  consecutive_days: number
  is_bought: boolean
  buy_date?: string
}

// 回测参数
export interface BacktestParams {
  start_date: string
  initial_capital: number
  slippage: number
  commission_rate: number
  strategy: string
}

// 回测状态
export interface BacktestState {
  session_id: string
  current_date: string
  start_date: string
  cash: number
  initial_capital: number
  positions: Record<string, Position>
  equity: number
  trade_log: TradeLog[]
  snapshots: Snapshot[]
  params: {
    slippage: number
    commission_rate: number
    strategy: string
  }
  status: 'idle' | 'running' | 'ended'
}

// 交易记录
export interface TradeLog {
  date: string
  action: 'buy' | 'sell'
  code: string
  price: number
  shares: number
  amount: number
  commission: number
  profit?: number
}

// 快照
export interface Snapshot {
  date: string
  cash: number
  positions: Record<string, Position>
  equity: number
}

// 策略信息
export interface Strategy {
  id: string
  name: string
  description: string
}

// API响应类型
export interface ApiResponse<T = any> {
  success?: boolean
  message?: string
  data?: T
  [key: string]: any
}
