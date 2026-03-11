<template>
  <div class="history-page">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <h3>回测历史记录</h3>
      </div>
      <div class="toolbar-right">
        <el-button @click="handleBack">返回设置</el-button>
      </div>
    </div>

    <!-- 历史记录列表 -->
    <div class="history-content">
      <el-card>
        <div v-loading="loading" class="history-list">
          <el-empty v-if="historyList.length === 0" description="暂无历史记录" />
          
          <el-table v-else :data="historyList" stripe>
            <el-table-column prop="session_id" label="会话ID" width="150">
              <template #default="{ row }">
                <el-text truncated>{{ row.session_id }}</el-text>
              </template>
            </el-table-column>
            <el-table-column prop="strategy" label="策略" width="100" />
            <el-table-column prop="start_date" label="开始日期" width="120">
              <template #default="{ row }">
                {{ formatDate(row.start_date) }}
              </template>
            </el-table-column>
            <el-table-column prop="end_date" label="结束日期" width="120">
              <template #default="{ row }">
                {{ formatDate(row.end_date) }}
              </template>
            </el-table-column>
            <el-table-column prop="initial_capital" label="初始资金" width="120">
              <template #default="{ row }">
                ¥{{ row.initial_capital.toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column prop="final_equity" label="最终权益" width="120">
              <template #default="{ row }">
                ¥{{ row.final_equity.toLocaleString() }}
              </template>
            </el-table-column>
            <el-table-column label="总收益" width="150">
              <template #default="{ row }">
                <span :class="getProfitClass(row)">
                  {{ getProfit(row) >= 0 ? '+' : '' }}¥{{ getProfit(row).toFixed(2) }}
                  ({{ getProfitPct(row) >= 0 ? '+' : '' }}{{ getProfitPct(row).toFixed(2) }}%)
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="trade_count" label="交易次数" width="100" />
            <el-table-column label="操作" width="180">
              <template #default="{ row }">
                <el-button type="primary" size="small" @click="viewDetail(row.session_id)">
                  查看详情
                </el-button>
                <el-button type="danger" size="small" @click="handleDelete(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { backtestApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'

const router = useRouter()
const loading = ref(false)
const historyList = ref<any[]>([])

// 加载历史记录
const loadHistory = async () => {
  loading.value = true
  try {
    const res: any = await backtestApi.getHistory()
    historyList.value = res.history || []
    
    // 按结束日期降序排序
    historyList.value.sort((a, b) => {
      return b.end_date.localeCompare(a.end_date)
    })
  } catch (error) {
    console.error('加载历史记录失败:', error)
    ElMessage.error('加载历史记录失败')
  } finally {
    loading.value = false
  }
}

// 格式化日期
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
}

// 计算收益
const getProfit = (row: any) => {
  return row.final_equity - row.initial_capital
}

// 计算收益率
const getProfitPct = (row: any) => {
  return (getProfit(row) / row.initial_capital) * 100
}

// 获取收益颜色类
const getProfitClass = (row: any) => {
  return getProfit(row) >= 0 ? 'profit-positive' : 'profit-negative'
}

// 查看详情
const viewDetail = (sessionId: string) => {
  router.push({
    name: 'HistoryDetail',
    params: { sessionId }
  })
}

// 删除记录
const handleDelete = async (row: any) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除会话 ${row.session_id} 吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    
    // 执行删除
    loading.value = true
    await backtestApi.deleteHistory(row.session_id)
    ElMessage.success('删除成功')
    
    // 重新加载列表
    await loadHistory()
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
      ElMessage.error('删除失败')
    }
  } finally {
    loading.value = false
  }
}

// 返回设置页
const handleBack = () => {
  router.push('/setup')
}

onMounted(() => {
  loadHistory()
})
</script>

<style scoped>
.history-page {
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

.history-content {
  flex: 1;
  padding: 20px;
  overflow: auto;
}

.history-list {
  min-height: 400px;
}

.profit-positive {
  color: #f56c6c;
  font-weight: bold;
}

.profit-negative {
  color: #67c23a;
  font-weight: bold;
}

:deep(.el-table) {
  font-size: 14px;
}

:deep(.el-table__header) {
  font-weight: 600;
}
</style>
