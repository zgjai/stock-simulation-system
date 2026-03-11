import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { FavoriteStock } from '@/types'

export const useBacktestStore = defineStore('backtest', () => {
  const sessionId = ref('')
  const currentDate = ref('')
  const startDate = ref('')
  const cash = ref(0)
  const initialCapital = ref(1000000)
  const positions = ref<any[]>([])
  const soldPositions = ref<any[]>([]) // 已清仓股票
  const favoriteStocks = ref<FavoriteStock[]>([]) // 精选池
  const equity = ref(0)
  const tradeLog = ref<any[]>([])
  const snapshots = ref<any[]>([])
  const params = ref({
    slippage: 0.0015,
    commission_rate: 0.0002,
    strategy: 'B1'
  })
  const status = ref('idle') // idle, running, ended

  function setState(state: any) {
    sessionId.value = state.session_id || ''
    currentDate.value = state.current_date || ''
    startDate.value = state.start_date || ''
    cash.value = state.cash || 0
    initialCapital.value = state.initial_capital || 1000000
    // ✅ 确保始终是数组类型
    positions.value = Array.isArray(state.positions) ? state.positions : []
    soldPositions.value = Array.isArray(state.sold_positions) ? state.sold_positions : []
    favoriteStocks.value = Array.isArray(state.favorite_stocks) ? state.favorite_stocks : []
    equity.value = state.equity || 0
    tradeLog.value = state.trade_log || []
    snapshots.value = state.snapshots || []
    if (state.params) {
      params.value = state.params
    }
    status.value = state.status || 'running'
  }

  function reset() {
    sessionId.value = ''
    currentDate.value = ''
    startDate.value = ''
    cash.value = 0
    initialCapital.value = 1000000
    positions.value = []
    soldPositions.value = []
    favoriteStocks.value = []
    equity.value = 0
    tradeLog.value = []
    snapshots.value = []
    params.value = {
      slippage: 0.0015,
      commission_rate: 0.0002,
      strategy: 'B1'
    }
    status.value = 'idle'
  }

  return {
    sessionId,
    currentDate,
    startDate,
    cash,
    initialCapital,
    positions,
    soldPositions,
    favoriteStocks,
    equity,
    tradeLog,
    snapshots,
    params,
    status,
    setState,
    reset
  }
}, {
  persist: {
    key: 'stock-backtest',
    storage: localStorage,
    paths: [
      'sessionId',
      'currentDate',
      'startDate',
      'cash',
      'initialCapital',
      'positions',
      'soldPositions',
      'favoriteStocks',
      'equity',
      'params',
      'status'
    ]
  }
})
