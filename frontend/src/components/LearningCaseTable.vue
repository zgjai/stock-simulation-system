<template>
  <div class="learning-case-table">
    <el-empty v-if="cases.length === 0" description="暂无数据" :image-size="60" />
    
    <el-table v-else :data="cases" size="small" stripe>
      <el-table-column prop="rank" label="排名" width="60" align="center">
        <template #default="{ $index }">
          <el-tag 
            :type="$index === 0 ? 'danger' : $index === 1 ? 'warning' : 'info'"
            size="small"
          >
            {{ $index + 1 }}
          </el-tag>
        </template>
      </el-table-column>
      
      <el-table-column prop="stock_code" label="代码" width="150">
        <template #default="{ row }">
          <div class="code-cell">
            <span>{{ row.stock_code }}</span>
            <el-tag v-if="row.is_extreme_b1" size="small" type="warning" effect="dark">极致</el-tag>
            <el-tag 
              v-if="row.consecutive_extreme_b1_days > 0" 
              size="small" 
              type="danger" 
              effect="plain"
              round
            >
              {{ row.consecutive_extreme_b1_days }}
            </el-tag>
            <!-- brick 策略：打分 + F6 红柱数 -->
            <template v-if="strategy === 'brick'">
              <span
                v-if="row.brick_score != null"
                class="lc-brick-score"
                :title="`多因子总分: ${row.brick_score}`"
              >{{ row.brick_score }}分</span>
              <span
                v-if="row.f6_red_count != null"
                class="lc-brick-f6"
                :title="`近6日(T-2~T-7)红柱数: ${row.f6_red_count}`"
              >F6:{{ row.f6_red_count }}</span>
            </template>
          </div>
        </template>
      </el-table-column>
      
      <el-table-column label="起始价" width="75">
        <template #default="{ row }">
          ¥{{ row.start_price }}
        </template>
      </el-table-column>
      
      <el-table-column label="最高价" width="75">
        <template #default="{ row }">
          ¥{{ row.max_price || row.end_price }}
        </template>
      </el-table-column>
      
      <el-table-column label="涨幅" width="100" align="center">
        <template #default="{ row }">
          <span 
            class="return-value"
            :class="{
              'high-return': row.return_pct >= 10,
              'medium-return': row.return_pct >= 5 && row.return_pct < 10,
              'low-return': row.return_pct < 5
            }"
          >
            +{{ row.return_pct }}%
          </span>
        </template>
      </el-table-column>
      
      <el-table-column label="最高价日期" width="100">
        <template #default="{ row }">
          {{ formatDate(row.max_date || row.end_date) }}
        </template>
      </el-table-column>
      
      <el-table-column label="操作" width="80" align="center">
        <template #default="{ row }">
          <el-button 
            type="primary" 
            size="small" 
            text
            @click="handleViewStock(row.stock_code)"
          >
            查看
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { defineProps, defineEmits } from 'vue'

interface LearningCase {
  stock_code: string
  start_price: number
  max_price?: number  // 新格式
  end_price?: number  // 旧格式兼容
  return_pct: number
  max_date?: string   // 新格式
  end_date?: string   // 旧格式兼容
  trading_days: number
  is_extreme_b1?: boolean // 是否满足极致B1条件
  consecutive_extreme_b1_days?: number // 连续极致B1天数
  brick_score?: number    // brick策略：多因子总分
  f6_red_count?: number   // brick策略：近6日红柱数
}

const props = defineProps<{
  cases: LearningCase[]
  period: number
  strategy?: string   // 可选，用于区分策略类型
}>()

const emit = defineEmits<{
  (e: 'view-stock', data: { stockCode: string; maxDate: string }): void
}>()

const formatDate = (dateStr: string) => {
  if (!dateStr || dateStr.length !== 8) return dateStr
  return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
}

const handleViewStock = (stockCode: string) => {
  // 找到对应的case数据，获取最高价日期
  const caseData = props.cases.find(c => c.stock_code === stockCode)
  const maxDate = caseData?.max_date || caseData?.end_date || ''
  
  emit('view-stock', { stockCode, maxDate })
}
</script>

<style scoped>
.learning-case-table {
  width: 100%;
}

.code-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.return-value {
  font-weight: bold;
  font-size: 13px;
}

.high-return {
  color: #f56c6c;
}

.medium-return {
  color: #e6a23c;
}

.low-return {
  color: #909399;
}

/* brick 策略：打分 + F6 徽章 */
.lc-brick-score {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 8px;
  white-space: nowrap;
  background: #f0f9eb;
  color: #5daf34;
  border: 1px solid #b3e19d;
  cursor: default;
}

.lc-brick-f6 {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 8px;
  white-space: nowrap;
  background: #fff3e0;
  color: #e65c00;
  border: 1px solid #ffcc80;
  cursor: default;
}
</style>
