<template>
  <div class="detail-page">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <h3>回测详情</h3>
        <el-tag v-if="detail" type="primary" size="large">{{ detail.params?.strategy }}策略</el-tag>
      </div>
      <div class="toolbar-right">
        <el-button @click="handleBack">返回列表</el-button>
      </div>
    </div>

    <!-- 详情内容 -->
    <div v-loading="loading" class="detail-content">
      <template v-if="detail">
        <!-- 基本信息 -->
        <el-card class="info-card">
          <template #header>
            <span class="card-title">基本信息</span>
          </template>
          <el-descriptions :column="3" border>
            <el-descriptions-item label="会话ID">
              {{ detail.session_id }}
            </el-descriptions-item>
            <el-descriptions-item label="策略">
              {{ detail.params?.strategy }}
            </el-descriptions-item>
            <el-descriptions-item label="回测区间">
              {{ formatDate(detail.start_date) }} ~ {{ formatDate(detail.end_date) }}
            </el-descriptions-item>
            <el-descriptions-item label="回测天数">
              {{ detail.trade_days || 0 }}天
            </el-descriptions-item>
            <el-descriptions-item label="初始资金">
              ¥{{ detail.initial_capital.toLocaleString() }}
            </el-descriptions-item>
            <el-descriptions-item label="最终权益">
              ¥{{ detail.final_equity.toLocaleString() }}
            </el-descriptions-item>
            <el-descriptions-item label="总收益" :span="3">
              <span :class="totalProfit >= 0 ? 'profit-positive' : 'profit-negative'">
                {{ totalProfit >= 0 ? '+' : '' }}¥{{ totalProfit.toFixed(2) }}
                ({{ totalProfitPct >= 0 ? '+' : '' }}{{ totalProfitPct.toFixed(2) }}%)
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="年化收益率">
              <span :class="detail.annualized_return >= 0 ? 'profit-positive' : 'profit-negative'">
                {{ detail.annualized_return >= 0 ? '+' : '' }}{{ detail.annualized_return }}%
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="最大回撤">
              <span class="profit-negative">
                -{{ detail.max_drawdown?.toFixed(2) || 0 }}%
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="夏普比率">
              {{ detail.sharpe_ratio?.toFixed(3) || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="交易次数">
              {{ detail.trade_log?.length || 0 }}笔
            </el-descriptions-item>
            <el-descriptions-item label="买入次数">
              {{ buyCount }}笔
            </el-descriptions-item>
            <el-descriptions-item label="卖出次数">
              {{ sellCount }}笔
            </el-descriptions-item>
            <el-descriptions-item label="胜率">
              <span :class="detail.win_rate >= 50 ? 'profit-positive' : 'profit-negative'">
                {{ detail.win_rate?.toFixed(2) || 0 }}%
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="盈亏比">
              <span :class="detail.profit_loss_ratio >= 1 ? 'profit-positive' : 'profit-negative'">
                {{ detail.profit_loss_ratio?.toFixed(2) || 0 }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="平均持仓天数">
              {{ detail.avg_holding_days?.toFixed(1) || 0 }}天
            </el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 权益曲线 -->
        <el-card class="chart-card">
          <template #header>
            <span class="card-title">权益曲线</span>
          </template>
          <div ref="equityChartRef" class="equity-chart"></div>
        </el-card>

        <!-- 交易日志 -->
        <el-card class="log-card">
          <template #header>
            <div class="card-header">
              <span class="card-title">交易日志</span>
              <el-tag>{{ detail.trade_log?.length || 0 }}笔</el-tag>
            </div>
          </template>
          <el-table :data="detail.trade_log" stripe max-height="400">
            <el-table-column prop="date" label="日期" width="120">
              <template #default="{ row }">
                {{ formatDate(row.date) }}
              </template>
            </el-table-column>
            <el-table-column prop="action" label="操作" width="80">
              <template #default="{ row }">
                <el-tag :type="row.action === 'buy' ? 'success' : 'danger'" size="small">
                  {{ row.action === 'buy' ? '买入' : '卖出' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="code" label="股票代码" width="100" />
            <el-table-column prop="shares" label="股数" width="100" />
            <el-table-column prop="price" label="成交价" width="100">
              <template #default="{ row }">
                ¥{{ row.price?.toFixed(2) }}
              </template>
            </el-table-column>
            <el-table-column prop="amount" label="成交额" width="120">
              <template #default="{ row }">
                ¥{{ row.amount?.toFixed(2) }}
              </template>
            </el-table-column>
            <el-table-column prop="commission" label="手续费" width="100">
              <template #default="{ row }">
                ¥{{ row.commission?.toFixed(2) }}
              </template>
            </el-table-column>
            <el-table-column label="备注" min-width="200">
              <template #default="{ row }">
                {{ row.reason || '-' }}
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { backtestApi } from '@/api'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const detail = ref<any>(null)
const equityChartRef = ref<HTMLElement>()

// 计算总收益
const totalProfit = computed(() => {
  if (!detail.value) return 0
  return detail.value.final_equity - detail.value.initial_capital
})

// 计算收益率
const totalProfitPct = computed(() => {
  if (!detail.value) return 0
  return (totalProfit.value / detail.value.initial_capital) * 100
})

// 买入次数
const buyCount = computed(() => {
  if (!detail.value?.trade_log) return 0
  return detail.value.trade_log.filter((log: any) => log.action === 'buy').length
})

// 卖出次数
const sellCount = computed(() => {
  if (!detail.value?.trade_log) return 0
  return detail.value.trade_log.filter((log: any) => log.action === 'sell').length
})

// 加载详情
const loadDetail = async () => {
  loading.value = true
  try {
    const sessionId = route.params.sessionId as string
    const res: any = await backtestApi.getDetail(sessionId)
    detail.value = res
    
    // 渲染权益曲线
    await renderEquityChart()
  } catch (error) {
    console.error('加载详情失败:', error)
    ElMessage.error('加载详情失败')
  } finally {
    loading.value = false
  }
}

// 渲染权益曲线
const renderEquityChart = async () => {
  await new Promise(resolve => setTimeout(resolve, 100))
  
  if (!equityChartRef.value || !detail.value?.snapshots) return
  
  const chart = echarts.init(equityChartRef.value)
  
  const dates = detail.value.snapshots.map((s: any) => formatDate(s.date))
  const equities = detail.value.snapshots.map((s: any) => s.equity)
  
  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const data = params[0]
        return `${data.name}<br/>权益: ¥${data.value.toLocaleString()}`
      }
    },
    grid: {
      left: 80,
      right: 40,
      top: 40,
      bottom: 60
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: {
        rotate: 45,
        fontSize: 11
      }
    },
    yAxis: {
      type: 'value',
      name: '权益(元)',
      axisLabel: {
        formatter: (value: number) => {
          if (value >= 10000) {
            return (value / 10000).toFixed(1) + '万'
          }
          return value.toString()
        }
      }
    },
    series: [
      {
        name: '权益',
        type: 'line',
        data: equities,
        smooth: true,
        lineStyle: {
          color: '#409eff',
          width: 2
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(64, 158, 255, 0.3)' },
            { offset: 1, color: 'rgba(64, 158, 255, 0.05)' }
          ])
        },
        markLine: {
          silent: true,
          lineStyle: {
            color: '#e74c3c',
            type: 'dashed'
          },
          data: [
            {
              yAxis: detail.value.initial_capital,
              label: {
                formatter: '初始资金'
              }
            }
          ]
        }
      }
    ]
  }
  
  chart.setOption(option)
  
  window.addEventListener('resize', () => {
    chart.resize()
  })
}

// 格式化日期
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
}

// 返回列表
const handleBack = () => {
  router.push('/history')
}

onMounted(() => {
  loadDetail()
})
</script>

<style scoped>
.detail-page {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}

.toolbar {
  height: 60px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 15px;
}

.toolbar-left h3 {
  margin: 0;
}

.toolbar-right {
  display: flex;
  gap: 10px;
}

.detail-content {
  flex: 1;
  padding: 20px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-title {
  font-weight: 600;
  font-size: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.profit-positive {
  color: #f56c6c;
  font-weight: bold;
}

.profit-negative {
  color: #67c23a;
  font-weight: bold;
}

.equity-chart {
  width: 100%;
  height: 400px;
}

.info-card,
.chart-card,
.log-card {
  background: #fff;
}

:deep(.el-descriptions__label) {
  font-weight: 500;
}

:deep(.el-table) {
  font-size: 14px;
}
</style>
