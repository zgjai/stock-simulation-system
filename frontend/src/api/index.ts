import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000  // 增加到60秒
})

// 请求拦截器
api.interceptors.request.use(
  config => {
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  response => {
    return response.data
  },
  error => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

// API接口
export const backtestApi = {
  // 开始回测
  start(params: any) {
    return api.post('/backtest/start', params)
  },
  
  // 执行交易
  trade(params: any) {
    return api.post('/backtest/trade', params)
  },
  
  // 推进到下一日（v2数据库版，已优化批量查询）
  nextDay(params: any) {
    return api.post('/backtest/next', params)
  },
  
  // 回退一日
  rollback(params: any) {
    return api.post('/backtest/rollback', params)
  },
  
  // 结束回测
  end(params: any) {
    return api.post('/backtest/end', params)
  },
  
  // 获取状态
  getState(sessionId: string) {
    return api.get('/backtest/state', { params: { session_id: sessionId } })
  },
  
  // 获取历史记录
  getHistory() {
    return api.get('/backtest/history')
  },
  
  // 删除历史记录
  deleteHistory(sessionId: string) {
    return api.delete(`/backtest/history/${sessionId}`)
  },
  
  // 获取详细信息
  getDetail(sessionId: string) {
    return api.get('/backtest/detail', { params: { session_id: sessionId } })
  },
  
  // 获取学习案例
  getLearningCases(date: string, strategy: string) {
    return api.get('/backtest/learning-cases', { params: { date, strategy } })
  },
  
  // 添加到精选池
  addToFavorite(params: any) {
    return api.post('/backtest/favorite/add', params)
  },
  
  // 从精选池移除
  removeFromFavorite(params: any) {
    return api.post('/backtest/favorite/remove', params)
  },
  
  // 获取精选池
  getFavorites(sessionId: string) {
    return api.get('/backtest/favorite', { params: { session_id: sessionId } })
  }
}

export const strategyApi = {
  // 获取策略列表
  getStrategies() {
    return api.get('/strategies')
  },
  
  // 获取候选池（支持B3砖型比例参数）
  getPicks(date: string, strategy: string, filterType: string = 'all', brickRatio?: number) {
    const params: any = { date, strategy, filter_type: filterType }
    if (brickRatio !== undefined) params.brick_ratio = brickRatio
    return api.get('/picks', { params })
  },
  
  // 获取K线数据
  getKline(code: string, endDate: string, limit: number = 60) {
    return api.get('/stock/kline', { params: { code, end_date: endDate, limit } })
  }
}

export const basicApi = {
  // 获取交易日列表
  getTradeDates() {
    return api.get('/trade-dates')
  },
  
  // 获取股票列表
  getStockList() {
    return api.get('/stock/list')
  }
}

export default api
