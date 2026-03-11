<template>
  <div class="setup-container">
    <el-card class="setup-card">
      <template #header>
        <div class="card-header">
          <div class="header-content">
            <h2>A股主观回测系统</h2>
            <p>模拟真实交易环境，提升主观交易能力</p>
          </div>
          <el-button type="info" @click="viewHistory">
            <el-icon><Document /></el-icon>
            历史记录
          </el-button>
        </div>
      </template>

      <el-form :model="form" label-width="120px" size="large">
        <el-form-item label="起始日期">
          <el-date-picker
            v-model="form.startDate"
            type="date"
            placeholder="选择回测起始日期"
            :disabled-date="disabledDate"
            value-format="YYYYMMDD"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="初始资金">
          <el-input-number
            v-model="form.initialCapital"
            :min="100000"
            :max="10000000"
            :step="100000"
            :controls="true"
            style="width: 100%"
          />
          <span class="tip">范围：10万 - 1000万</span>
        </el-form-item>

        <el-form-item label="选股策略">
          <el-select v-model="form.strategy" placeholder="请选择策略" style="width: 100%">
            <el-option
              v-for="item in strategies"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            >
              <span>{{ item.name }}</span>
              <span style="color: #8492a6; font-size: 13px; margin-left: 10px">
                {{ item.description }}
              </span>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="滑点">
          <el-input-number
            v-model="form.slippage"
            :min="0.001"
            :max="0.003"
            :step="0.0001"
            :precision="4"
            style="width: 100%"
          />
          <span class="tip">默认0.15%，范围0.1%-0.3%</span>
        </el-form-item>

        <el-form-item label="手续费率">
          <el-input-number
            v-model="form.commissionRate"
            :min="0.0001"
            :max="0.001"
            :step="0.0001"
            :precision="4"
            style="width: 100%"
          />
          <span class="tip">默认万分之2</span>
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            style="width: 100%"
            :loading="loading"
            @click="startBacktest"
          >
            开始回测
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Document } from '@element-plus/icons-vue'
import { backtestApi, strategyApi } from '@/api'
import { useBacktestStore } from '@/stores/backtest'

const router = useRouter()
const backtestStore = useBacktestStore()

const form = ref({
  startDate: '',
  initialCapital: 1000000,
  strategy: 'B1',
  slippage: 0.0015,
  commissionRate: 0.0002
})

const strategies = ref<any[]>([])
const loading = ref(false)

onMounted(async () => {
  try {
    // 获取策略列表
    const res: any = await strategyApi.getStrategies()
    strategies.value = res.strategies || []
    
    // 设置默认日期为最近的交易日
    const dateRes: any = await strategyApi.getPicks('20251231', 'B1')
    if (dateRes.date) {
      form.value.startDate = dateRes.date
    }
  } catch (error) {
    console.error('初始化失败:', error)
  }
})

const disabledDate = (time: Date) => {
  // 禁用未来日期
  return time.getTime() > Date.now()
}

const startBacktest = async () => {
  if (!form.value.startDate) {
    ElMessage.warning('请选择起始日期')
    return
  }

  loading.value = true

  try {
    const res: any = await backtestApi.start({
      start_date: form.value.startDate,
      initial_capital: form.value.initialCapital,
      slippage: form.value.slippage,
      commission_rate: form.value.commissionRate,
      strategy: form.value.strategy
    })

    // 保存新的状态
    backtestStore.setState(res.state)

    ElMessage.success('回测开始！')
    
    // 等待一下确保state更新完成
    await nextTick()
    
    // 跳转到回测主页
    router.push('/backtest')
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '启动回测失败')
  } finally {
    loading.value = false
  }
}

// 查看历史记录
const viewHistory = () => {
  router.push('/history')
}
</script>

<style scoped>
.setup-container {
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.setup-card {
  width: 600px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-content {
  text-align: center;
  flex: 1;
}

.header-content h2 {
  margin: 0 0 10px 0;
  color: #303133;
}

.header-content p {
  margin: 0;
  color: #909399;
  font-size: 14px;
}

.tip {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}
</style>
