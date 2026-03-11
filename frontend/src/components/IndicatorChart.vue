<template>
  <div ref="chartRef" class="indicator-chart"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as echarts from 'echarts'

interface Props {
  data: any[]
  type: 'volume' | 'kdj' | 'macd' | 'wash' | 'brick'
  height?: number
}

const props = withDefaults(defineProps<Props>(), {
  height: 110
})

const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
let resizeHandler: (() => void) | null = null

const initChart = () => {
  if (!chartRef.value || !props.data || props.data.length === 0) return

  // ✅ 重要：先销毁旧的图表对象，释放内存
  if (chart) {
    try {
      chart.dispose()
      chart = null
    } catch (e) {
      console.warn('销毁图表失败:', e)
    }
  }

  chart = echarts.init(chartRef.value)

  let option: echarts.EChartsOption = {}

  switch (props.type) {
    case 'volume':
      option = {
        grid: { left: 10, right: 60, top: 30, bottom: 30 },
        xAxis: {
          type: 'category',
          data: props.data.map(d => d.date),
          axisLabel: { show: false }
        },
        yAxis: {
          type: 'value',
          axisLabel: { show: false },
          splitLine: { 
            show: true,
            lineStyle: { color: '#e0e0e0', type: 'dashed' }
          }
        },
        series: [
          {
            name: '成交量',
            type: 'bar',
            data: props.data.map(d => d.volume || 0),
            barWidth: '60%',
            itemStyle: {
              color: (params: any) => {
                const index = params.dataIndex
                if (index === 0) return '#f5465c'
                const prev = props.data[index - 1]
                const curr = props.data[index]
                return curr.close >= prev.close ? '#f5465c' : '#26a69a'
              }
            }
          },
          {
            name: 'VOL_MA5',
            type: 'line',
            data: props.data.map(d => d.vol_ma5 || null),
            smooth: false,
            lineStyle: { width: 1, color: '#ff9800' },
            showSymbol: false
          },
          {
            name: 'VOL_MA60',
            type: 'line',
            data: props.data.map(d => d.vol_ma60 || null),
            smooth: false,
            lineStyle: { width: 1, color: '#2196f3' },
            showSymbol: false
          }
        ],
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line' }
        },
        legend: {
          data: ['成交量', 'VOL_MA5', 'VOL_MA60'],
          top: 0,
          left: 'center',
          textStyle: { fontSize: 11 }
        }
      }
      break

    case 'kdj':
      option = {
        grid: { left: 10, right: 60, top: 30, bottom: 30 },
        xAxis: {
          type: 'category',
          data: props.data.map(d => d.date),
          axisLabel: { show: false }
        },
        yAxis: {
          type: 'value',
          scale: true,
          axisLabel: { show: false },
          splitLine: { 
            show: true,
            lineStyle: { color: '#e0e0e0', type: 'dashed' }
          }
        },
        series: [
          {
            name: 'K',
            type: 'line',
            data: props.data.map(d => d.kdj_k || null),
            smooth: false,
            lineStyle: { color: '#ff9800', width: 1 },
            showSymbol: false
          },
          {
            name: 'D',
            type: 'line',
            data: props.data.map(d => d.kdj_d || null),
            smooth: false,
            lineStyle: { color: '#2196f3', width: 1 },
            showSymbol: false
          },
          {
            name: 'J',
            type: 'line',
            data: props.data.map(d => d.kdj_j || null),
            smooth: false,
            lineStyle: { color: '#9c27b0', width: 1 },
            showSymbol: false
          }
        ],
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line' }
        },
        legend: {
          data: ['K', 'D', 'J'],
          top: 0,
          left: 'center',
          textStyle: { fontSize: 11 }
        }
      }
      break

    case 'macd':
      option = {
        grid: { left: 10, right: 60, top: 30, bottom: 30 },
        xAxis: {
          type: 'category',
          data: props.data.map(d => d.date),
          axisLabel: { show: false }
        },
        yAxis: {
          type: 'value',
          axisLabel: { show: false },
          splitLine: { 
            show: true,
            lineStyle: { color: '#e0e0e0', type: 'dashed' }
          }
        },
        series: [
          {
            name: 'DIF',
            type: 'line',
            data: props.data.map(d => d.macd_dif || null),
            smooth: false,
            lineStyle: { color: '#ff9800', width: 1 },
            showSymbol: false
          },
          {
            name: 'DEA',
            type: 'line',
            data: props.data.map(d => d.macd_dea || null),
            smooth: false,
            lineStyle: { color: '#2196f3', width: 1 },
            showSymbol: false
          },
          {
            name: 'MACD',
            type: 'bar',
            data: props.data.map(d => d.macd_hist || 0),
            barWidth: '60%',
            itemStyle: {
              color: (params: any) => {
                return params.value >= 0 ? '#f5465c' : '#26a69a'
              }
            }
          }
        ],
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line' }
        },
        legend: {
          data: ['DIF', 'DEA', 'MACD'],
          top: 0,
          left: 'center',
          textStyle: { fontSize: 11 }
        }
      }
      break

    case 'wash':
      option = {
        grid: { left: 10, right: 60, top: 30, bottom: 30 },
        xAxis: {
          type: 'category',
          data: props.data.map(d => d.date),
          axisLabel: { 
            show: true,
            fontSize: 10,
            rotate: 0
          }
        },
        yAxis: {
          type: 'value',
          axisLabel: { show: false },
          splitLine: { 
            show: true,
            lineStyle: { color: '#e0e0e0', type: 'dashed' }
          }
        },
        series: [
          {
            name: '单针短期',
            type: 'line',
            data: props.data.map(d => d.wash_short || null),
            smooth: false,
            lineStyle: { color: '#ff9800', width: 1 },
            showSymbol: false
          },
          {
            name: '单针长期',
            type: 'line',
            data: props.data.map(d => d.wash_long || null),
            smooth: false,
            lineStyle: { color: '#2196f3', width: 1 },
            showSymbol: false
          }
        ],
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line' }
        },
        legend: {
          data: ['单针短期', '单针长期'],
          top: 0,
          left: 'center',
          textStyle: { fontSize: 11 }
        }
      }
      break

    case 'brick': {
      // 砖型图：每根柱子从昨日值到今日值，用 ECharts candlestick 系列实现
      // candlestick data 格式：[open, close, low, high]
      // 涨（curr >= prev）→ 红色；跌 → 绿色
      // 用 open=prev, close=curr, low=min, high=max 模拟蜡烛柱
      const candleData = props.data.map((d, i) => {
        const curr = d.brick_value ?? 0
        const prev = i > 0 ? (props.data[i - 1].brick_value ?? 0) : curr
        return [
          parseFloat(prev.toFixed(4)),   // open
          parseFloat(curr.toFixed(4)),   // close
          parseFloat(Math.min(curr, prev).toFixed(4)), // low
          parseFloat(Math.max(curr, prev).toFixed(4)), // high
        ]
      })

      option = {
        grid: { left: 10, right: 60, top: 30, bottom: 30 },
        xAxis: {
          type: 'category',
          data: props.data.map(d => d.date),
          axisLabel: { show: true, fontSize: 10 },
          axisLine: { lineStyle: { color: '#ccc' } },
          splitLine: { show: false },
        },
        yAxis: {
          type: 'value',
          scale: true,
          axisLabel: { show: false },
          splitLine: {
            show: true,
            lineStyle: { color: '#e0e0e0', type: 'dashed' }
          }
        },
        series: [
          {
            name: '砖型图',
            type: 'candlestick',
            data: candleData,
            barMaxWidth: 12,
            itemStyle: {
              // 涨（close >= open）红色，跌绿色
              color: '#f5465c',
              color0: '#26a69a',
              borderColor: '#f5465c',
              borderColor0: '#26a69a',
            }
          }
        ],
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line' },
          formatter: (params: any) => {
            const idx = params[0]?.dataIndex
            if (idx === undefined) return ''
            const d = props.data[idx]
            const curr = d.brick_value ?? 0
            const body = d.brick_body ?? 0
            return `${d.date}<br/>砖型图: ${curr.toFixed(2)}<br/>主体长度: ${body.toFixed(2)}`
          }
        },
        legend: {
          data: ['砖型图'],
          top: 0,
          left: 'center',
          textStyle: { fontSize: 11 }
        }
      }
      break
    }
  }

  chart.setOption(option)
}

watch(() => props.data, () => {
  initChart()
}, { deep: true })

onMounted(() => {
  initChart()
  
  // 创建resize处理函数
  resizeHandler = () => {
    chart?.resize()
  }
  window.addEventListener('resize', resizeHandler)
})

// ✅ 重要：组件卸载时清理图表和事件监听器
onUnmounted(() => {
  // 移除resize监听器
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
    resizeHandler = null
  }
  
  // 销毁图表对象
  if (chart) {
    try {
      chart.dispose()
      chart = null
    } catch (e) {
      console.warn('销毁图表失败:', e)
    }
  }
})
</script>

<style scoped>
.indicator-chart {
  width: 100%;
  height: 100%;
}
</style>
