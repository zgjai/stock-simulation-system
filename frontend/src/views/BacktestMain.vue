<template>
  <div class="backtest-main">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <h3>回测进行中</h3>
        <el-tag type="primary" size="large">{{ backtestStore.currentDate }}</el-tag>
        <el-tag size="large">{{ backtestStore.params.strategy }}策略</el-tag>
      </div>
      <div class="toolbar-right">
        <el-button @click="showPositionDialog = true" :badge="positions.length">
          持仓({{ positions.length }})
        </el-button>
        <el-button @click="showAccountDialog = true">账户信息</el-button>
        <el-button :loading="rollbackLoading" @click="handleRollback">
          回退一日
        </el-button>
        <el-button type="primary" :loading="nextDayLoading" @click="handleNextDay">
          下一交易日
        </el-button>
        <el-button type="danger" @click="handleEndBacktest">
          结束回测
        </el-button>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="main-content">
      <!-- 左侧：候选池列表 -->
      <div class="left-panel">
        <el-card class="candidate-card">
          <template #header>
            <div class="card-header">
              <el-tabs v-model="activeTab" @tab-change="handleTabChange">
                <el-tab-pane label="候选池" name="candidates">
                  <template #label>
                    <span>候选池 <el-tag size="small">{{ candidates.length }}</el-tag></span>
                  </template>
                </el-tab-pane>
                <el-tab-pane v-if="backtestStore.params.strategy === 'B1'" label="极致B1" name="extreme_b1">
                  <template #label>
                    <span>极致B1 <el-tag size="small" type="warning">{{ extremeB1Candidates.length }}</el-tag></span>
                  </template>
                </el-tab-pane>
                <el-tab-pane v-if="backtestStore.params.strategy === 'B1'" label="极致B1+" name="extreme_b1_plus">
                  <template #label>
                    <span>极致B1+ <el-tag size="small" type="danger">{{ extremeB1PlusCandidates.length }}</el-tag></span>
                  </template>
                </el-tab-pane>
                <el-tab-pane label="精选池" name="favorites">
                  <template #label>
                    <span>精选池 <el-tag size="small" type="primary">{{ backtestStore.favoriteStocks.length }}</el-tag></span>
                  </template>
                </el-tab-pane>
                <el-tab-pane label="持仓" name="positions">
                  <template #label>
                    <span>持仓 <el-tag size="small" type="success">{{ positions.length }}</el-tag></span>
                  </template>
                </el-tab-pane>
                <el-tab-pane label="已清仓" name="sold">
                  <template #label>
                    <span>已清仓 <el-tag size="small" type="info">{{ soldPositions.length }}</el-tag></span>
                  </template>
                </el-tab-pane>
              </el-tabs>
            </div>
          </template>

          <!-- 候选池列表 -->
          <div v-show="activeTab === 'candidates'" v-loading="candidatesLoading" class="candidate-list">
            
            <!-- 砖型选股：打分筛选器 -->
            <div v-if="backtestStore.params.strategy === 'brick'" class="b3-filter-bar">
              <span class="b3-filter-label">打分筛选</span>
              <el-select
                v-model="b3ScoreFilter"
                size="small"
                style="width: 110px;"
              >
                <el-option
                  v-for="opt in b3ScoreFilterOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
              <span class="b3-filter-sep">|</span>
              <span class="b3-filter-label">F6红柱</span>
              <el-select
                v-model="b3F6Filter"
                size="small"
                style="width: 90px;"
              >
                <el-option
                  v-for="opt in b3F6FilterOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
              <span class="b3-count-tip">
                {{ filteredCandidates.length }} /
                {{ candidates.length }} 支
              </span>
            </div>

            <el-empty v-if="candidates.length === 0" description="当日无候选股票" />
            
            <!-- 批量操作工具栏 -->
            <div v-if="candidates.length > 0" class="batch-toolbar">
              <el-checkbox 
                v-model="selectAll" 
                :indeterminate="isIndeterminate"
                @change="handleSelectAll"
              >
                全选
              </el-checkbox>
              <el-button 
                v-if="selectedCodes.length > 0"
                type="warning" 
                size="small"
                plain
                @click="addToFavorite(selectedCodes)"
              >
                批量加入精选 ({{ selectedCodes.length }})
              </el-button>
              <el-button 
                v-if="selectedCodes.length > 0"
                type="primary" 
                size="small" 
                @click="openBatchBuyDialog"
              >
                批量买入 ({{ selectedCodes.length }})
              </el-button>
            </div>
            
            <!-- ── brick 策略专属：竖排卡片布局 ─────────────────── -->
            <template v-if="backtestStore.params.strategy === 'brick'">
              <div
                v-for="stock in filteredCandidates"
                :key="stock.code"
                class="candidate-item brick-candidate-item"
                :class="{
                  active: selectedStock === stock.code && activeTab === 'candidates',
                  selected: selectedCodes.includes(stock.code),
                  'brick-priority': stock.brick_score?.label === '优先关注',
                  'brick-caution':  stock.brick_score?.label === '谨慎回避',
                }"
                @click="selectStock(stock.code)"
              >
                <!-- 第一行：左侧（复选框+代码+打分）右侧（价格+涨跌+按钮） -->
                <div class="brick-row-top">
                  <!-- 左侧：复选框 + 代码 + 打分标签 -->
                  <div class="brick-left">
                    <el-checkbox
                      :model-value="selectedCodes.includes(stock.code)"
                      @update:model-value="(val) => toggleSelection(stock.code, val)"
                      @click.stop
                    />
                    <span class="stock-code-text">{{ stock.code }}</span>
                    <!-- 打分标签（简短文案） -->
                    <span
                      v-if="stock.brick_score"
                      class="brick-score-badge"
                      :class="{
                        'score-priority': stock.brick_score.label === '优先关注',
                        'score-normal':   stock.brick_score.label === '正常对待',
                        'score-caution':  stock.brick_score.label === '谨慎回避',
                      }"
                    >{{ brickScoreShort(stock.brick_score) }}</span>
                  </div>

                  <!-- 右侧：价格 + 涨跌 + 按钮（永不换行，不缩放） -->
                  <div class="brick-right">
                    <span class="brick-price-change">
                      <span class="brick-price">¥{{ stock.close }}</span>
                      <span class="brick-change" :class="stock.change_pct >= 0 ? 'rise' : 'fall'">
                        {{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct }}%
                      </span>
                    </span>
                    <el-button
                      v-if="!isInFavorites(stock.code)"
                      type="warning"
                      size="small"
                      plain
                      class="brick-btn-star"
                      @click.stop="addToFavorite([stock.code])"
                    >⭐</el-button>
                    <el-button v-else size="small" disabled class="brick-btn-star">✓</el-button>
                    <el-button
                      type="primary"
                      size="small"
                      class="brick-btn-buy"
                      @click.stop="openBuyDialog(stock.code)"
                    >买入</el-button>
                  </div>
                </div>

                <!-- 第二行：砖型柱数据 + F6红柱数 + 因子分值 -->
                <div class="brick-row-bottom">
                  <span class="brick-ratio-badge">
                    比例×{{ stock.brick_ratio_actual != null ? stock.brick_ratio_actual.toFixed(2) : '-' }}
                  </span>
                  <span class="brick-len-info">
                    红{{ stock.brick_red_len != null ? stock.brick_red_len.toFixed(3) : '-' }}
                    /绿{{ stock.brick_green_len != null ? stock.brick_green_len.toFixed(3) : '-' }}
                  </span>
                  <span class="brick-vol">{{ formatVolume(stock.volume) }}</span>
                  <!-- F6：近6日红柱数 -->
                  <span
                    v-if="stock.brick_score?.f6_red_count != null"
                    class="brick-f6-badge"
                    :title="`近6日(T-2~T-7)红柱数: ${stock.brick_score.f6_red_count}`"
                  >F6:{{ stock.brick_score.f6_red_count }}</span>
                  <!-- 逐因子得分 -->
                  <span v-if="stock.brick_score" class="brick-factor-scores">
                    <span
                      v-for="(s, key) in stock.brick_score.score_detail"
                      :key="key"
                      class="factor-score-dot"
                      :class="{ 'fs-pos': s > 0, 'fs-neg': s < 0, 'fs-neu': s === 0 }"
                      :title="factorLabel(key) + ': ' + (s > 0 ? '+1' : s < 0 ? '-1' : '0')"
                    >{{ factorLabel(key) }}{{ s > 0 ? '▲' : s < 0 ? '▼' : '─' }}</span>
                  </span>
                </div>
              </div>
            </template>

            <!-- ── 其他策略：原有横排布局（不变）────────────────── -->
            <template v-else>
            <div
              v-for="stock in candidates"
              :key="stock.code"
              class="candidate-item"
              :class="{ 
                active: selectedStock === stock.code && activeTab === 'candidates',
                selected: selectedCodes.includes(stock.code),
                'extreme-b1': stock.is_extreme_b1
              }"
              @click="selectStock(stock.code)"
            >
              <el-checkbox 
                :model-value="selectedCodes.includes(stock.code)"
                @update:model-value="(val) => toggleSelection(stock.code, val)"
                @click.stop
              />
              <div class="stock-code">
                {{ stock.code }}
                <el-tag v-if="stock.is_extreme_b1" size="small" type="warning" effect="dark">极致</el-tag>
                <el-tag 
                  v-if="stock.consecutive_extreme_b1_days > 0" 
                  size="small" 
                  type="danger" 
                  effect="plain"
                  round
                >
                  {{ stock.consecutive_extreme_b1_days }}
                </el-tag>
              </div>
              <div class="stock-info">
                <span class="price">¥{{ stock.close }}</span>
                <span
                  class="change"
                  :class="stock.change_pct >= 0 ? 'rise' : 'fall'"
                >
                  {{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct }}%
                </span>
              </div>
              <div class="stock-volume">{{ formatVolume(stock.volume) }}</div>
              <el-button
                v-if="!isInFavorites(stock.code)"
                type="warning"
                size="small"
                plain
                @click.stop="addToFavorite([stock.code])"
              >
                ⭐精选
              </el-button>
              <el-button
                v-else
                size="small"
                disabled
              >
                已加精选
              </el-button>
              <el-button
                type="primary"
                size="small"
                @click.stop="openBuyDialog(stock.code)"
              >
                买入
              </el-button>
            </div>
            </template>
          </div>

          <!-- 极致B1候选池列表 -->
          <div v-show="activeTab === 'extreme_b1'" v-loading="candidatesLoading" class="candidate-list">
            <el-empty v-if="extremeB1Candidates.length === 0" description="当日无极致B1候选股票" />
            
            <!-- 说明信息 -->
            <div v-if="extremeB1Candidates.length > 0" class="extreme-b1-tips">
              <el-alert 
                title="极致B1筛选条件" 
                type="warning"
                :closable="false"
                show-icon
              >
                <div class="tips-content">
                  <p><strong>主板(00/60):</strong> 当日振幅≥2.68 且 成交量比率≥0.59</p>
                  <p><strong>创业板/科创板/北交所(30/68/92):</strong> 当日振幅≥3.46 且 成交量比率≥0.42</p>
                </div>
              </el-alert>
            </div>
            
            <!-- 批量操作工具栏 -->
            <div v-if="extremeB1Candidates.length > 0" class="batch-toolbar">
              <el-checkbox 
                v-model="selectAll" 
                :indeterminate="isIndeterminateExtremeB1"
                @change="handleSelectAllExtremeB1"
              >
                全选
              </el-checkbox>
              <el-button 
                v-if="selectedCodes.length > 0"
                type="warning" 
                size="small"
                plain
                @click="addToFavorite(selectedCodes)"
              >
                批量加入精选 ({{ selectedCodes.length }})
              </el-button>
              <el-button 
                v-if="selectedCodes.length > 0"
                type="primary" 
                size="small" 
                @click="openBatchBuyDialog"
              >
                批量买入 ({{ selectedCodes.length }})
              </el-button>
            </div>
            
            <div
              v-for="stock in extremeB1Candidates"
              :key="stock.code"
              class="candidate-item extreme-b1"
              :class="{ 
                active: selectedStock === stock.code && activeTab === 'extreme_b1',
                selected: selectedCodes.includes(stock.code)
              }"
              @click="selectStock(stock.code)"
            >
              <el-checkbox 
                :model-value="selectedCodes.includes(stock.code)"
                @update:model-value="(val) => toggleSelection(stock.code, val)"
                @click.stop
              />
              <div class="stock-code-with-factors">
                <div class="stock-code">
                  {{ stock.code }}
                  <el-tag size="small" type="warning" effect="dark">极致</el-tag>
                  <el-tag 
                    v-if="stock.consecutive_extreme_b1_days > 0" 
                    size="small" 
                    type="danger" 
                    effect="plain"
                    round
                  >
                    {{ stock.consecutive_extreme_b1_days }}
                  </el-tag>
                </div>
                <div class="stock-factors">
                  <span class="factor-item">振幅: {{ stock.factor_amplitude !== null && stock.factor_amplitude !== undefined ? stock.factor_amplitude.toFixed(2) : '-' }}</span>
                  <span class="factor-item">量比: {{ stock.factor_volume_ratio !== null && stock.factor_volume_ratio !== undefined ? stock.factor_volume_ratio.toFixed(2) : '-' }}</span>
                </div>
              </div>
              <div class="stock-info">
                <span class="price">¥{{ stock.close }}</span>
                <span
                  class="change"
                  :class="stock.change_pct >= 0 ? 'rise' : 'fall'"
                >
                  {{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct }}%
                </span>
              </div>
              <div class="stock-volume">{{ formatVolume(stock.volume) }}</div>
              <el-button
                v-if="!isInFavorites(stock.code)"
                type="warning"
                size="small"
                plain
                @click.stop="addToFavorite([stock.code])"
              >
                ⭐精选
              </el-button>
              <el-button
                v-else
                size="small"
                disabled
              >
                已加精选
              </el-button>
              <el-button
                type="primary"
                size="small"
                @click.stop="openBuyDialog(stock.code)"
              >
                买入
              </el-button>
            </div>
          </div>

          <!-- 极致B1+候选池列表 -->
          <div v-show="activeTab === 'extreme_b1_plus'" v-loading="candidatesLoading" class="candidate-list">
            <el-empty v-if="extremeB1PlusCandidates.length === 0" description="当日无极致B1+候选股票" />
            
            <!-- 说明信息 -->
            <div v-if="extremeB1PlusCandidates.length > 0" class="extreme-b1-tips">
              <el-alert 
                title="极致B1+筛选条件" 
                type="error"
                :closable="false"
                show-icon
              >
                <div class="tips-content">
                  <p><strong>在极致B1基础上额外满足：</strong></p>
                  <p>① 当日砖型动量柱为红柱（当日brick_value &gt; 前一日brick_value）</p>
                  <p>② 前一日砖型动量柱为红柱（前一日brick_value &gt; 前两日brick_value）</p>
                  <p>③ 当日股价下跌（涨跌幅 &lt; 0）</p>
                </div>
              </el-alert>
            </div>
            
            <!-- 批量操作工具栏 -->
            <div v-if="extremeB1PlusCandidates.length > 0" class="batch-toolbar">
              <el-checkbox 
                v-model="selectAll" 
                :indeterminate="isIndeterminateExtremeB1Plus"
                @change="handleSelectAllExtremeB1Plus"
              >
                全选
              </el-checkbox>
              <el-button 
                v-if="selectedCodes.length > 0"
                type="warning" 
                size="small"
                plain
                @click="addToFavorite(selectedCodes)"
              >
                批量加入精选 ({{ selectedCodes.length }})
              </el-button>
              <el-button 
                v-if="selectedCodes.length > 0"
                type="primary" 
                size="small" 
                @click="openBatchBuyDialog"
              >
                批量买入 ({{ selectedCodes.length }})
              </el-button>
            </div>
            
            <div
              v-for="stock in extremeB1PlusCandidates"
              :key="stock.code"
              class="candidate-item extreme-b1 extreme-b1-plus"
              :class="{ 
                active: selectedStock === stock.code && activeTab === 'extreme_b1_plus',
                selected: selectedCodes.includes(stock.code)
              }"
              @click="selectStock(stock.code)"
            >
              <el-checkbox 
                :model-value="selectedCodes.includes(stock.code)"
                @update:model-value="(val) => toggleSelection(stock.code, val)"
                @click.stop
              />
              <div class="stock-code-with-factors">
                <div class="stock-code">
                  {{ stock.code }}
                  <el-tag size="small" type="danger" effect="dark">极致+</el-tag>
                  <el-tag 
                    v-if="stock.consecutive_extreme_b1_days > 0" 
                    size="small" 
                    type="danger" 
                    effect="plain"
                    round
                  >
                    {{ stock.consecutive_extreme_b1_days }}
                  </el-tag>
                </div>
                <div class="stock-factors">
                  <span class="factor-item">振幅: {{ stock.factor_amplitude !== null && stock.factor_amplitude !== undefined ? stock.factor_amplitude.toFixed(2) : '-' }}</span>
                  <span class="factor-item">量比: {{ stock.factor_volume_ratio !== null && stock.factor_volume_ratio !== undefined ? stock.factor_volume_ratio.toFixed(2) : '-' }}</span>
                  <span class="factor-item brick-red">今↑</span>
                  <span class="factor-item brick-red">昨↑</span>
                </div>
              </div>
              <div class="stock-info">
                <span class="price">¥{{ stock.close }}</span>
                <span
                  class="change"
                  :class="stock.change_pct >= 0 ? 'rise' : 'fall'"
                >
                  {{ stock.change_pct >= 0 ? '+' : '' }}{{ stock.change_pct }}%
                </span>
              </div>
              <div class="stock-volume">{{ formatVolume(stock.volume) }}</div>
              <el-button
                v-if="!isInFavorites(stock.code)"
                type="warning"
                size="small"
                plain
                @click.stop="addToFavorite([stock.code])"
              >
                ⭐精选
              </el-button>
              <el-button
                v-else
                size="small"
                disabled
              >
                已加精选
              </el-button>
              <el-button
                type="primary"
                size="small"
                @click.stop="openBuyDialog(stock.code)"
              >
                买入
              </el-button>
            </div>
          </div>

          <!-- 精选池列表 -->
          <div v-show="activeTab === 'favorites'" v-loading="favoritesLoading" class="candidate-list">
            <el-empty v-if="backtestStore.favoriteStocks.length === 0" description="精选池为空，从候选池或极致B1列表添加股票" />
            
            <!-- 统计信息 -->
            <div v-if="backtestStore.favoriteStocks.length > 0" class="favorites-stats">
              <el-alert 
                type="info"
                :closable="false"
              >
                <div class="stats-content">
                  <span>精选池共 {{ backtestStore.favoriteStocks.length }} 个</span>
                  <span>已买入 {{ boughtFavoritesCount }} 个 (平均{{ avgBoughtChange }}%)</span>
                  <span>未买入 {{ unboughtFavoritesCount }} 个 (平均{{ avgUnboughtChange }}%)</span>
                </div>
              </el-alert>
            </div>
            
            <div
              v-for="fav in backtestStore.favoriteStocks"
              :key="fav.stock_code"
              class="candidate-item favorite-item"
              :class="{ 
                active: selectedStock === fav.stock_code && activeTab === 'favorites',
                'is-bought': fav.is_bought,
                'extreme-b1': fav.is_extreme_b1
              }"
              @click="selectStock(fav.stock_code)"
            >
              <div class="favorite-header">
                <div class="stock-code">
                  {{ fav.stock_code }}
                  <el-tag v-if="fav.is_extreme_b1 && fav.consecutive_days > 0" size="small" type="warning" effect="dark">
                    ⚡{{ fav.consecutive_days }}天
                  </el-tag>
                  <el-tag v-if="fav.is_bought" size="small" type="success">
                    已买入✓
                  </el-tag>
                </div>
                <div class="favorite-date">
                  加入 {{ fav.add_date?.slice(4,6) }}/{{ fav.add_date?.slice(6,8) }}
                </div>
              </div>
              
              <div class="favorite-price-info">
                <div class="price-line">
                  <span class="label">加入:</span>
                  <span class="price">¥{{ fav.add_price?.toFixed(2) }}</span>
                </div>
                <div class="price-line">
                  <span class="label">当前:</span>
                  <span class="price">¥{{ fav.current_price?.toFixed(2) }}</span>
                  <span
                    class="change"
                    :class="fav.change_pct >= 0 ? 'rise' : 'fall'"
                  >
                    {{ fav.change_pct >= 0 ? '+' : '' }}{{ fav.change_pct }}%
                  </span>
                </div>
              </div>
              
              <div v-if="fav.note" class="favorite-note">
                <el-text size="small" type="info">{{ fav.note }}</el-text>
              </div>
              
              <div class="favorite-actions">
                <el-button
                  v-if="!fav.is_bought"
                  type="primary"
                  size="small"
                  @click.stop="openBuyDialog(fav.stock_code)"
                >
                  买入
                </el-button>
                <el-button
                  v-else
                  type="success"
                  size="small"
                  disabled
                >
                  已持仓
                </el-button>
                <el-button
                  size="small"
                  @click.stop="removeFromFavorite(fav.stock_code)"
                >
                  移除
                </el-button>
              </div>
            </div>
          </div>

          <!-- 持仓列表 -->
          <div v-show="activeTab === 'positions'" class="candidate-list">
            <el-empty v-if="positions.length === 0" description="暂无持仓" />
            
            <div
              v-for="pos in positions"
              :key="pos.code"
              class="candidate-item position-item"
              :class="{ active: selectedStock === pos.code && activeTab === 'positions' }"
              @click="selectStock(pos.code)"
            >
              <div class="stock-code-with-days">
                <div class="stock-code">{{ pos.code }}</div>
                <div class="holding-days">持仓{{ pos.holding_days || 0 }}天</div>
              </div>
              <div class="stock-info">
                <span class="price">¥{{ pos.current_price }}</span>
                <span
                  class="change"
                  :class="pos.profit_pct >= 0 ? 'rise' : 'fall'"
                >
                  {{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct }}%
                </span>
              </div>
              <div class="stock-volume">{{ pos.shares }}股</div>
              <el-button
                type="danger"
                size="small"
                @click.stop="openSellDialog(pos.code, pos.shares)"
              >
                卖出
              </el-button>
            </div>
          </div>

          <!-- 已清仓列表 -->
          <div v-show="activeTab === 'sold'" class="candidate-list">
            <el-empty v-if="soldPositions.length === 0" description="暂无已清仓股票" />
            
            <div
              v-for="sold in soldPositions"
              :key="`sold_${sold.code}_${sold.sell_date}`"
              class="candidate-item sold-item"
              :class="{ active: selectedStock === sold.code && activeTab === 'sold' }"
              @click="selectStock(sold.code)"
            >
              <div class="sold-header">
                <div class="stock-code">{{ sold.code }}</div>
                <div class="date-range">
                  {{ sold.buy_date }} ~ {{ sold.sell_date }}
                </div>
              </div>
              
              <div class="sold-content">
                <div class="sold-section">
                  <div class="section-title">已实现</div>
                  <div class="price-row">
                    <span class="label">成本</span>
                    <span class="value">¥{{ sold.cost_price }}</span>
                  </div>
                  <div class="price-row">
                    <span class="label">卖出</span>
                    <span class="value">¥{{ sold.sell_price }}</span>
                  </div>
                  <div class="profit-row">
                    <span class="label">盈亏</span>
                    <span 
                      class="profit-value"
                      :class="sold.profit_pct >= 0 ? 'rise' : 'fall'"
                    >
                      {{ sold.profit_pct >= 0 ? '+' : '' }}{{ sold.profit_pct }}%
                      ({{ sold.profit_pct >= 0 ? '+' : '' }}¥{{ sold.profit.toFixed(2) }})
                    </span>
                  </div>
                </div>
                
                <div class="sold-section">
                  <div class="section-title">当前价</div>
                  <div class="price-row">
                    <span class="label">现价</span>
                    <span class="value current-price">¥{{ sold.current_price || '-' }}</span>
                  </div>
                  <div class="profit-row" v-if="sold.potential_profit !== undefined">
                    <span class="label">潜在</span>
                    <span 
                      class="profit-value"
                      :class="sold.potential_profit_pct >= 0 ? 'rise' : 'fall'"
                    >
                      {{ sold.potential_profit_pct >= 0 ? '+' : '' }}{{ sold.potential_profit_pct }}%
                      ({{ sold.potential_profit >= 0 ? '+' : '' }}¥{{ sold.potential_profit.toFixed(2) }})
                    </span>
                  </div>
                  <div class="decision-indicator">
                    <el-tag 
                      v-if="sold.profit_pct !== undefined && sold.potential_profit_pct !== undefined"
                      :type="getDecisionType(sold.profit_pct, sold.potential_profit_pct)"
                      size="small"
                    >
                      {{ getDecisionText(sold.profit_pct, sold.potential_profit_pct) }}
                    </el-tag>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 右侧：K线图和学习案例 -->
      <div class="right-panel">
        <!-- K线图区域（固定高度，不滚动） -->
        <div class="chart-section">
          <el-card class="chart-card">
            <template #header>
              <div class="chart-header">
                <span>{{ selectedStock || '请选择股票' }}</span>
                <!-- 添加图例说明 -->
                <div v-if="selectedStock" class="legend-box">
                  <span class="legend-item">
                    <span class="legend-line" style="background: #2196f3; width: 20px; height: 3px;"></span>
                    知行多空线
                  </span>
                  <span class="legend-item">
                    <span class="legend-line" style="background: #9c27b0; width: 20px; height: 2px;"></span>
                    知行短期
                  </span>
                  <span class="legend-item">
                    <span class="legend-line" style="background: #ff9800; width: 20px; height: 2px;"></span>
                    MA5
                  </span>
                  <span class="legend-item">
                    <span class="legend-line" style="background: #4caf50; width: 20px; height: 2px;"></span>
                    MA10
                  </span>
                </div>
              </div>
            </template>
            
            <div v-if="selectedStock" class="chart-container">
              <!-- K线主图 -->
              <div class="kline-wrapper">
                <!-- 数据信息面板 -->
                <div v-if="currentKlineData" class="kline-info-panel">
                  <div class="info-row">
                    <span class="info-label">日期:</span>
                    <span class="info-value">{{ currentKlineData.date }}</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">开:</span>
                    <span class="info-value">{{ currentKlineData.open }}</span>
                    <span class="info-label">高:</span>
                    <span class="info-value">{{ currentKlineData.high }}</span>
                    <span class="info-label">低:</span>
                    <span class="info-value">{{ currentKlineData.low }}</span>
                    <span class="info-label">收:</span>
                    <span class="info-value" :class="currentKlineData.change >= 0 ? 'rise' : 'fall'">
                      {{ currentKlineData.close }}
                    </span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">涨幅:</span>
                    <span class="info-value" :class="currentKlineData.change >= 0 ? 'rise' : 'fall'">
                      {{ currentKlineData.change >= 0 ? '+' : '' }}{{ currentKlineData.change }}%
                    </span>
                    <span class="info-label">振幅:</span>
                    <span class="info-value">{{ currentKlineData.amplitude }}%</span>
                  </div>
                  <div class="info-row">
                    <span class="info-label">知行多空:</span>
                    <span class="info-value">{{ currentKlineData.multi_line }}</span>
                    <span class="info-label">知行短期:</span>
                    <span class="info-value">{{ currentKlineData.ema10_2 }}</span>
                  </div>
                </div>
                <div ref="chartRef" class="kline-chart"></div>
              </div>
              
              <!-- 副图区域 -->
              <div class="sub-charts">
                <!-- 成交量：始终显示 -->
                <IndicatorChart 
                  ref="volumeChartRef"
                  :data="klineData" 
                  type="volume" 
                  :height="130"
                  class="sub-chart"
                />
                <!-- 副图切换 Tab -->
                <div class="sub-indicator-tabs">
                  <span
                    class="sub-tab"
                    :class="{ active: subIndicatorTab === 'classic' }"
                    @click="subIndicatorTab = 'classic'"
                  >KDJ / 单针</span>
                  <span
                    class="sub-tab"
                    :class="{ active: subIndicatorTab === 'brick' }"
                    @click="subIndicatorTab = 'brick'"
                  >砖型图</span>
                </div>
                <!-- KDJ + 单针（classic 模式） -->
                <template v-if="subIndicatorTab === 'classic'">
                  <IndicatorChart 
                    ref="kdjChartRef"
                    :data="klineData" 
                    type="kdj" 
                    :height="130"
                    class="sub-chart"
                  />
                  <IndicatorChart 
                    ref="washChartRef"
                    :data="klineData" 
                    type="wash" 
                    :height="130"
                    class="sub-chart"
                  />
                </template>
                <!-- 砖型图（brick 模式，占双倍高度） -->
                <template v-else>
                  <IndicatorChart 
                    ref="brickChartRef"
                    :data="klineData" 
                    type="brick" 
                    :height="270"
                    class="sub-chart sub-chart-double"
                  />
                </template>
              </div>
            </div>
            <el-empty v-else description="点击左侧股票查看K线" />
          </el-card>
        </div>

        <!-- 学习案例面板（可滚动区域） -->
        <div class="learning-section">
          <el-card class="learning-card">
            <template #header>
              <div class="learning-header">
                <span>📊 学习案例 - 从当前日期开始的涨幅TOP3（按市场分组）</span>
                <el-button 
                  text 
                  @click="showLearningPanel = !showLearningPanel"
                >
                  {{ showLearningPanel ? '收起' : '展开' }}
                </el-button>
              </div>
            </template>
            
            <div v-if="showLearningPanel" v-loading="learningLoading" class="learning-content">
              <div class="learning-info">
                <span>当前日期：{{ backtestStore.currentDate }}</span>
                <span>策略：{{ backtestStore.params.strategy }}</span>
                <span v-if="learningCases.total_candidates > 0">
                  候选池：{{ learningCases.total_candidates }}只
                </span>
              </div>
              
              <el-tabs v-model="activePeriod" class="learning-tabs">
                <el-tab-pane label="3日" name="3d">
                  <!-- 主板组 -->
                  <div class="market-group">
                    <div class="market-group-header">
                      <span class="market-group-title">
                        🏦 {{ learningCases.market_groups?.A?.name || '主板(00/60)' }}
                      </span>
                      <span class="market-group-count">
                        ({{ learningCases.market_groups?.A?.total || 0 }}只)
                      </span>
                    </div>
                    <LearningCaseTable 
                      :cases="learningCases.market_groups?.A?.cases?.['3d'] || []"
                      :period="3"
                      :strategy="backtestStore.params.strategy"
                      @view-stock="viewLearningStock"
                    />
                  </div>
                  
                  <!-- 创业板/科创板组 -->
                  <div class="market-group">
                    <div class="market-group-header">
                      <span class="market-group-title">
                        🚀 {{ learningCases.market_groups?.B?.name || '创业板/科创板/北交所(30/68/92)' }}
                      </span>
                      <span class="market-group-count">
                        ({{ learningCases.market_groups?.B?.total || 0 }}只)
                      </span>
                    </div>
                    <LearningCaseTable 
                      :cases="learningCases.market_groups?.B?.cases?.['3d'] || []"
                      :period="3"
                      :strategy="backtestStore.params.strategy"
                      @view-stock="viewLearningStock"
                    />
                  </div>
                </el-tab-pane>
                
                <el-tab-pane label="5日" name="5d">
                  <!-- 主板组 -->
                  <div class="market-group">
                    <div class="market-group-header">
                      <span class="market-group-title">
                        🏦 {{ learningCases.market_groups?.A?.name || '主板(00/60)' }}
                      </span>
                      <span class="market-group-count">
                        ({{ learningCases.market_groups?.A?.total || 0 }}只)
                      </span>
                    </div>
                    <LearningCaseTable 
                      :cases="learningCases.market_groups?.A?.cases?.['5d'] || []"
                      :period="5"
                      :strategy="backtestStore.params.strategy"
                      @view-stock="viewLearningStock"
                    />
                  </div>
                  
                  <!-- 创业板/科创板组 -->
                  <div class="market-group">
                    <div class="market-group-header">
                      <span class="market-group-title">
                        🚀 {{ learningCases.market_groups?.B?.name || '创业板/科创板/北交所(30/68/92)' }}
                      </span>
                      <span class="market-group-count">
                        ({{ learningCases.market_groups?.B?.total || 0 }}只)
                      </span>
                    </div>
                    <LearningCaseTable 
                      :cases="learningCases.market_groups?.B?.cases?.['5d'] || []"
                      :period="5"
                      :strategy="backtestStore.params.strategy"
                      @view-stock="viewLearningStock"
                    />
                  </div>
                </el-tab-pane>
                
                <el-tab-pane label="10日" name="10d">
                  <!-- 主板组 -->
                  <div class="market-group">
                    <div class="market-group-header">
                      <span class="market-group-title">
                        🏦 {{ learningCases.market_groups?.A?.name || '主板(00/60)' }}
                      </span>
                      <span class="market-group-count">
                        ({{ learningCases.market_groups?.A?.total || 0 }}只)
                      </span>
                    </div>
                    <LearningCaseTable 
                      :cases="learningCases.market_groups?.A?.cases?.['10d'] || []"
                      :period="10"
                      :strategy="backtestStore.params.strategy"
                      @view-stock="viewLearningStock"
                    />
                  </div>
                  
                  <!-- 创业板/科创板组 -->
                  <div class="market-group">
                    <div class="market-group-header">
                      <span class="market-group-title">
                        🚀 {{ learningCases.market_groups?.B?.name || '创业板/科创板/北交所(30/68/92)' }}
                      </span>
                      <span class="market-group-count">
                        ({{ learningCases.market_groups?.B?.total || 0 }}只)
                      </span>
                    </div>
                    <LearningCaseTable 
                      :cases="learningCases.market_groups?.B?.cases?.['10d'] || []"
                      :period="10"
                      :strategy="backtestStore.params.strategy"
                      @view-stock="viewLearningStock"
                    />
                  </div>
                </el-tab-pane>
              </el-tabs>
              
              <div class="learning-tip">
                💡 提示：这些是从当前候选池中，按市场分组统计的未来涨幅最高股票，仅供学习参考。
              </div>
            </div>
          </el-card>
        </div>
      </div>
    </div>

    <!-- 买入对话框 -->
    <el-dialog v-model="buyDialogVisible" title="买入" width="400px">
      <el-form :model="buyForm" label-width="100px">
        <el-form-item label="股票代码">
          <el-input v-model="buyForm.code" disabled />
        </el-form-item>
        <el-form-item label="买入方式">
          <el-radio-group v-model="buyForm.type">
            <el-radio label="ratio">按比例</el-radio>
            <el-radio label="amount">按金额</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="buyForm.type === 'ratio'" label="仓位比例">
          <el-radio-group v-model="buyForm.ratio">
            <el-radio :label="1.0">全仓</el-radio>
            <el-radio :label="0.5">1/2</el-radio>
            <el-radio :label="0.33">1/3</el-radio>
            <el-radio :label="0.25">1/4</el-radio>
          </el-radio-group>
          <div v-if="buyForm.ratio === 1.0" class="warning-tip">
            ⚠️ 全仓买入风险较高，请谨慎操作
          </div>
        </el-form-item>
        <el-form-item v-else label="买入金额">
          <el-input-number
            v-model="buyForm.amount"
            :min="1000"
            :max="backtestStore.cash"
            :step="1000"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="buyDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="buyLoading" @click="handleBuy">
          确认买入
        </el-button>
      </template>
    </el-dialog>

    <!-- 批量买入对话框 -->
    <el-dialog v-model="batchBuyDialogVisible" title="批量买入" width="500px">
      <div class="batch-buy-info">
        <p>已选择 <strong>{{ selectedCodes.length }}</strong> 只股票</p>
        <p>可用资金: <strong>¥{{ backtestStore.cash.toLocaleString() }}</strong></p>
      </div>
      <el-form :model="batchBuyForm" label-width="120px">
        <el-form-item label="买入方式">
          <el-radio-group v-model="batchBuyForm.type">
            <el-radio label="average">平均分配</el-radio>
            <el-radio label="fixed">固定金额</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="batchBuyForm.type === 'average'" label="仓位比例">
          <el-radio-group v-model="batchBuyForm.ratio">
            <el-radio :label="1.0">全仓</el-radio>
            <el-radio :label="0.5">1/2</el-radio>
            <el-radio :label="0.33">1/3</el-radio>
            <el-radio :label="0.25">1/4</el-radio>
          </el-radio-group>
          <div class="tip">每只股票约 ¥{{ ((backtestStore.cash * batchBuyForm.ratio) / selectedCodes.length).toFixed(0) }}</div>
          <div v-if="batchBuyForm.ratio === 1.0" class="warning-tip">
            ⚠️ 全仓分配风险较高，建议分散投资
          </div>
        </el-form-item>
        <el-form-item v-else label="每只金额">
          <el-input-number
            v-model="batchBuyForm.amountPerStock"
            :min="1000"
            :max="backtestStore.cash"
            :step="1000"
            style="width: 100%"
          />
          <div class="tip">共需 ¥{{ (batchBuyForm.amountPerStock * selectedCodes.length).toLocaleString() }}</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchBuyDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchBuyLoading" @click="handleBatchBuy">
          确认批量买入
        </el-button>
      </template>
    </el-dialog>

    <!-- 卖出对话框 -->
    <el-dialog v-model="sellDialogVisible" title="卖出" width="400px">
      <el-form :model="sellForm" label-width="100px">
        <el-form-item label="股票代码">
          <el-input v-model="sellForm.code" disabled />
        </el-form-item>
        <el-form-item label="持仓股数">
          <el-input :value="sellForm.totalShares" disabled />
        </el-form-item>
        <el-form-item label="卖出股数">
          <el-input-number
            v-model="sellForm.shares"
            :min="100"
            :max="sellForm.totalShares"
            :step="100"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sellDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="sellLoading" @click="handleSell">
          确认卖出
        </el-button>
      </template>
    </el-dialog>

    <!-- 持仓对话框 -->
    <el-dialog v-model="showPositionDialog" title="持仓列表" width="800px">
      <el-table :data="positions" size="small" max-height="400">
        <el-table-column prop="code" label="代码" width="100" />
        <el-table-column prop="shares" label="股数" width="100" />
        <el-table-column prop="cost_price" label="成本价" width="100" />
        <el-table-column prop="current_price" label="现价" width="100" />
        <el-table-column prop="holding_days" label="持仓天数" width="100">
          <template #default="{ row }">
            {{ row.holding_days || 0 }}天
          </template>
        </el-table-column>
        <el-table-column label="盈亏" width="150">
          <template #default="{ row }">
            <span :class="row.profit >= 0 ? 'rise' : 'fall'">
              {{ row.profit >= 0 ? '+' : '' }}{{ row.profit.toFixed(2) }}
              ({{ row.profit_pct >= 0 ? '+' : '' }}{{ row.profit_pct }}%)
            </span>
          </template>
        </el-table-column>
        <el-table-column label="市值" width="120">
          <template #default="{ row }">
            {{ (row.current_price * row.shares).toFixed(2) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              type="danger"
              size="small"
              @click="openSellDialog(row.code, row.shares); showPositionDialog = false"
            >
              卖出
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="showPositionDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 账户信息对话框 -->
    <el-dialog v-model="showAccountDialog" title="账户信息" width="500px">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="当前日期">
          {{ backtestStore.currentDate }}
        </el-descriptions-item>
        <el-descriptions-item label="初始资金">
          ¥{{ backtestStore.initialCapital.toLocaleString() }}
        </el-descriptions-item>
        <el-descriptions-item label="可用现金">
          ¥{{ backtestStore.cash.toFixed(2) }}
        </el-descriptions-item>
        <el-descriptions-item label="持仓市值">
          ¥{{ positionValue.toFixed(2) }}
        </el-descriptions-item>
        <el-descriptions-item label="总资产">
          ¥{{ (backtestStore.cash + positionValue).toFixed(2) }}
        </el-descriptions-item>
        <el-descriptions-item label="总收益">
          <span :class="totalProfit >= 0 ? 'rise' : 'fall'">
            {{ totalProfit >= 0 ? '+' : '' }}{{ totalProfit.toFixed(2) }}
            ({{ totalProfitPct >= 0 ? '+' : '' }}{{ totalProfitPct }}%)
          </span>
        </el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createChart, ColorType } from 'lightweight-charts'
import { backtestApi, strategyApi } from '@/api'
import { useBacktestStore } from '@/stores/backtest'
import IndicatorChart from '@/components/IndicatorChart.vue'
import LearningCaseTable from '@/components/LearningCaseTable.vue'
import { useRouter } from 'vue-router'

const backtestStore = useBacktestStore()
const router = useRouter()

const candidates = ref<any[]>([])
const extremeB1Candidates = ref<any[]>([]) // 极致B1候选池
const extremeB1PlusCandidates = ref<any[]>([]) // 极致B1+候选池
const candidatesLoading = ref(false)
const selectedStock = ref('')
const selectedStockIndex = ref(-1) // 当前选中的候选池索引
const activeTab = ref('candidates') // 当前激活的标签页
const selectedCodes = ref<string[]>([]) // 批量选中的股票代码
const selectAll = ref(false) // 全选状态
const chartRef = ref<HTMLElement>()
const positions = ref<any[]>([])
const soldPositions = ref<any[]>([])
const klineData = ref<any[]>([])
const currentKlineData = ref<any>(null) // 当前悬停的K线数据

// B3砖型选股：固定用 2/3 比例拉取全量，前端按打分筛选
const b3BrickRatio = ref(0.667)
const b3ScoreFilter = ref('all')  // 'all' | 's5' | 's4' | 's23' | 's01' | 'sneg'
const b3ScoreFilterOptions = [
  { label: '全部',    value: 'all' },
  { label: '5分',    value: 's5' },
  { label: '4分',    value: 's4' },
  { label: '2-3分',  value: 's23' },
  { label: '0-1分',  value: 's01' },
  { label: '负分',   value: 'sneg' },
]

const b3F6Filter = ref('all')  // 'all' | 'f4p' | 'f3p' | 'f2m'
const b3F6FilterOptions = [
  { label: '全部',  value: 'all' },
  { label: '≥4天', value: 'f4p' },
  { label: '≥3天', value: 'f3p' },
  { label: '≤2天', value: 'f2m' },
]

// brick 候选池：按打分 + F6 过滤后的列表
const filteredCandidates = computed(() => {
  if (backtestStore.params.strategy !== 'brick') {
    return candidates.value
  }
  return candidates.value.filter(s => {
    // 打分过滤
    if (b3ScoreFilter.value !== 'all') {
      const sc: number = s.brick_score?.score ?? 0
      switch (b3ScoreFilter.value) {
        case 's5':   if (sc < 5)              return false; break
        case 's4':   if (sc !== 4)            return false; break
        case 's23':  if (sc < 2 || sc > 3)   return false; break
        case 's01':  if (sc < 0 || sc > 1)   return false; break
        case 'sneg': if (sc >= 0)             return false; break
      }
    }
    // F6 红柱数过滤
    if (b3F6Filter.value !== 'all') {
      const f6: number = s.brick_score?.f6_red_count ?? -1
      switch (b3F6Filter.value) {
        case 'f4p': if (f6 < 4) return false; break
        case 'f3p': if (f6 < 3) return false; break
        case 'f2m': if (f6 > 2 || f6 < 0) return false; break
      }
    }
    return true
  })
})

// 学习案例相关
const showLearningPanel = ref(false) // 默认收起
const activePeriod = ref('3d') // 当前激活的周期
const learningCases = ref<any>({
  date: '',
  strategy: '',
  total_candidates: 0,
  cases: {
    '3d': [],
    '5d': [],
    '10d': []
  }
})
const learningLoading = ref(false)

const buyDialogVisible = ref(false)
const buyForm = ref({
  code: '',
  type: 'ratio',
  ratio: 0.5,
  amount: 100000
})
const buyLoading = ref(false)

const batchBuyDialogVisible = ref(false)
const batchBuyForm = ref({
  type: 'average',
  ratio: 0.5,
  amountPerStock: 50000
})
const batchBuyLoading = ref(false)

const sellDialogVisible = ref(false)
const sellForm = ref({
  code: '',
  shares: 100,
  totalShares: 0
})
const sellLoading = ref(false)

const showAccountDialog = ref(false)
const showPositionDialog = ref(false)
const nextDayLoading = ref(false)
const rollbackLoading = ref(false)

// 副图chart引用
const volumeChartRef = ref()
const kdjChartRef = ref()
const washChartRef = ref()
const brickChartRef = ref()

// 副图切换：classic=KDJ+单针，brick=砖型图
const subIndicatorTab = ref<'classic' | 'brick'>('classic')

// 主图表对象引用（用于销毁）
let mainChart: any = null

// 计算属性
const positionValue = computed(() => {
  // ✅ 防御性编程：确保positions.value是数组
  if (!Array.isArray(positions.value) || positions.value.length === 0) {
    return 0
  }
  return positions.value.reduce((sum, pos) => sum + pos.current_price * pos.shares, 0)
})

const totalProfit = computed(() => {
  return backtestStore.cash + positionValue.value - backtestStore.initialCapital
})

const totalProfitPct = computed(() => {
  return ((totalProfit.value / backtestStore.initialCapital) * 100).toFixed(2)
})

// 全选状态计算
const isIndeterminate = computed(() => {
  return selectedCodes.value.length > 0 && selectedCodes.value.length < candidates.value.length
})

// 极致B1全选状态计算
const isIndeterminateExtremeB1 = computed(() => {
  return selectedCodes.value.length > 0 && selectedCodes.value.length < extremeB1Candidates.value.length
})

// 极致B1+全选状态计算
const isIndeterminateExtremeB1Plus = computed(() => {
  return selectedCodes.value.length > 0 && selectedCodes.value.length < extremeB1PlusCandidates.value.length
})

// 精选池相关
const favoritesLoading = ref(false)

// 精选池统计
const boughtFavoritesCount = computed(() => {
  return backtestStore.favoriteStocks.filter(f => f.is_bought).length
})

const unboughtFavoritesCount = computed(() => {
  return backtestStore.favoriteStocks.filter(f => !f.is_bought).length
})

const avgBoughtChange = computed(() => {
  const bought = backtestStore.favoriteStocks.filter(f => f.is_bought)
  if (bought.length === 0) return '0.00'
  const sum = bought.reduce((acc, f) => acc + (f.change_pct || 0), 0)
  return (sum / bought.length).toFixed(2)
})

const avgUnboughtChange = computed(() => {
  const unbought = backtestStore.favoriteStocks.filter(f => !f.is_bought)
  if (unbought.length === 0) return '0.00'
  const sum = unbought.reduce((acc, f) => acc + (f.change_pct || 0), 0)
  return (sum / unbought.length).toFixed(2)
})

// 检查是否在精选池中
const isInFavorites = (stockCode: string) => {
  return backtestStore.favoriteStocks.some(f => f.stock_code === stockCode)
}

// 添加到精选池
const addToFavorite = async (stockCodes: string[], note: string = '') => {
  try {
    await backtestApi.addToFavorite({
      session_id: backtestStore.sessionId,
      stock_codes: stockCodes,
      note
    })
    
    // 添加后刷新精选池，获取完整数据（包含实时价格）
    await refreshFavorites()
    
    // 清空选中状态
    selectedCodes.value = []
    selectAll.value = false
    
    ElMessage.success(`已添加 ${stockCodes.length} 个股票到精选池`)
  } catch (error: any) {
    console.error('添加到精选池失败:', error)
    ElMessage.error(error.response?.data?.detail || '添加到精选池失败')
  }
}

// 从精选池移除
const removeFromFavorite = async (stockCode: string) => {
  try {
    await ElMessageBox.confirm(
      '确定要从精选池移除该股票吗？',
      '确认移除',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    await backtestApi.removeFromFavorite({
      session_id: backtestStore.sessionId,
      stock_codes: [stockCode]
    })
    
    // 移除后刷新精选池，保持数据完整性
    await refreshFavorites()
    
    ElMessage.success('已从精选池移除')
  } catch (error: any) {
    if (error !== 'cancel') {
      console.error('移除失败:', error)
      ElMessage.error(error.response?.data?.detail || '移除失败')
    }
  }
}

// 刷新精选池价格
const refreshFavorites = async () => {
  try {
    const res: any = await backtestApi.getFavorites(backtestStore.sessionId)
    backtestStore.favoriteStocks = res.favorites || []
  } catch (error) {
    console.error('刷新精选池失败:', error)
  }
}

// 格式化成交量
const formatVolume = (vol: number) => {
  if (vol >= 100000000) {
    return (vol / 100000000).toFixed(2) + '亿'
  } else if (vol >= 10000) {
    return (vol / 10000).toFixed(2) + '万'
  }
  return vol.toString()
}

// brick 因子标签简称
const factorLabel = (key: string): string => {
  const map: Record<string, string> = {
    f1: 'F1', f2: 'F2', f3: 'F3', f4: 'F4', f5: 'F5',
  }
  return map[key] ?? key
}

// brick 打分标签简短显示：「优先▲+3」「回避▼-2」「正常 0」
const brickScoreShort = (bs: { label: string; score: number }): string => {
  const sc = bs.score
  const sign = sc > 0 ? '+' : ''
  if (bs.label === '优先关注') return `优先▲${sign}${sc}`
  if (bs.label === '谨慎回避') return `回避▼${sign}${sc}`
  return `正常 ${sign}${sc}`
}

// 切换选中状态
const toggleSelection = (code: string, checked: boolean) => {
  if (checked) {
    if (!selectedCodes.value.includes(code)) {
      selectedCodes.value.push(code)
    }
  } else {
    const index = selectedCodes.value.indexOf(code)
    if (index > -1) {
      selectedCodes.value.splice(index, 1)
    }
  }
}

// 加载候选池
const loadCandidates = async () => {
  // 检查currentDate是否有效
  if (!backtestStore.currentDate) {
    console.warn('当前日期为空，跳过加载候选池')
    return
  }
  
  candidatesLoading.value = true
  try {
    // 砖型选股策略传入砖型比例参数
    const brickRatio = backtestStore.params.strategy === 'brick' ? b3BrickRatio.value : undefined
    const res: any = await strategyApi.getPicks(
      backtestStore.currentDate,
      backtestStore.params.strategy,
      'all', // 获取全部候选池
      brickRatio
    )
    candidates.value = res.stocks || []
    
    // 筛选出极致B1候选股票
    if (backtestStore.params.strategy === 'B1') {
      extremeB1Candidates.value = candidates.value.filter(stock => stock.is_extreme_b1)
      extremeB1PlusCandidates.value = candidates.value.filter(stock => stock.is_extreme_b1_plus)
    } else {
      extremeB1Candidates.value = []
      extremeB1PlusCandidates.value = []
    }
    
    // 同时加载学习案例
    await loadLearningCases()
  } catch (error) {
    console.error('加载候选池失败:', error)
    ElMessage.error('加载候选池失败')
  } finally {
    candidatesLoading.value = false
  }
}

// 加载学习案例
const loadLearningCases = async () => {
  if (!backtestStore.currentDate || !backtestStore.params.strategy) {
    return
  }
  
  learningLoading.value = true
  try {
    const res: any = await backtestApi.getLearningCases(
      backtestStore.currentDate,
      backtestStore.params.strategy
    )
    console.log('📊 学习案例数据:', res)
    console.log('📊 市场分组:', res.market_groups)
    if (res.market_groups) {
      console.log('📊 主板数据:', res.market_groups.A)
      console.log('📊 创业板数据:', res.market_groups.B)
    }
    learningCases.value = res
  } catch (error) {
    console.error('加载学习案例失败:', error)
    // 不显示错误提示，静默失败
  } finally {
    learningLoading.value = false
  }
}

// 查看学习案例中的股票
const viewLearningStock = (data: { stockCode: string; maxDate: string }) => {
  selectStockWithDate(data.stockCode, data.maxDate)
}

// 选择股票（支持自定义截止日期）
const selectStockWithDate = async (code: string, endDate?: string) => {
  selectedStock.value = code
  // 更新选中索引（candidates tab 用过滤后的列表，保证键盘导航与显示一致）
  if (activeTab.value === 'candidates') {
    selectedStockIndex.value = filteredCandidates.value.findIndex(s => s.code === code)
  } else if (activeTab.value === 'extreme_b1') {
    selectedStockIndex.value = extremeB1Candidates.value.findIndex(s => s.code === code)
  } else if (activeTab.value === 'extreme_b1_plus') {
    selectedStockIndex.value = extremeB1PlusCandidates.value.findIndex(s => s.code === code)
  } else if (activeTab.value === 'favorites') {
    selectedStockIndex.value = backtestStore.favoriteStocks.findIndex(s => s.stock_code === code)
  } else if (activeTab.value === 'positions') {
    selectedStockIndex.value = positions.value.findIndex(s => s.code === code)
  } else {
    selectedStockIndex.value = soldPositions.value.findIndex(s => s.code === code)
  }
  await nextTick()
  loadKline(code, endDate)
}

// 选择股票（默认使用当前日期）
const selectStock = async (code: string) => {
  selectStockWithDate(code)
}

// 标签页切换
const handleTabChange = () => {
  // 切换标签页时清空选中状态
  selectedStock.value = ''
  selectedStockIndex.value = -1
}

// 通过索引选择股票
const selectStockByIndex = async (index: number) => {
  let stockList: any[]
  if (activeTab.value === 'candidates') {
    stockList = filteredCandidates.value  // 使用过滤后的列表（brick策略有筛选时）
  } else if (activeTab.value === 'extreme_b1') {
    stockList = extremeB1Candidates.value
  } else if (activeTab.value === 'extreme_b1_plus') {
    stockList = extremeB1PlusCandidates.value
  } else if (activeTab.value === 'favorites') {
    stockList = backtestStore.favoriteStocks
  } else if (activeTab.value === 'positions') {
    stockList = positions.value
  } else {
    stockList = soldPositions.value
  }
  
  if (index >= 0 && index < stockList.length) {
    const stock = stockList[index]
    // 精选池使用 stock_code，其他使用 code
    const stockCode = activeTab.value === 'favorites' ? stock.stock_code : stock.code
    selectedStock.value = stockCode
    selectedStockIndex.value = index
    
    // 滚动到可视区域
    await nextTick()
    scrollToSelectedItem()
    
    // 加载K线
    loadKline(stockCode)
  }
}

// 滚动到选中项
const scrollToSelectedItem = () => {
  const candidateList = document.querySelector('.candidate-list')
  let selectedItem: Element | null = null
  
  if (activeTab.value === 'candidates') {
    selectedItem = document.querySelector('.candidate-item.active:not(.position-item):not(.sold-item):not(.extreme-b1):not(.favorite-item)')
  } else if (activeTab.value === 'extreme_b1') {
    // 极致B1 Tab中,所有项都有extreme-b1 class，但没有extreme-b1-plus class
    selectedItem = document.querySelector('.candidate-item.active.extreme-b1:not(.extreme-b1-plus)')
  } else if (activeTab.value === 'extreme_b1_plus') {
    selectedItem = document.querySelector('.candidate-item.active.extreme-b1-plus')
  } else if (activeTab.value === 'favorites') {
    selectedItem = document.querySelector('.favorite-item.active')
  } else if (activeTab.value === 'positions') {
    selectedItem = document.querySelector('.position-item.active')
  } else {
    selectedItem = document.querySelector('.sold-item.active')
  }
  
  if (candidateList && selectedItem) {
    const listRect = candidateList.getBoundingClientRect()
    const itemRect = selectedItem.getBoundingClientRect()
    
    // 如果选中项不在可视区域内，滚动到它
    if (itemRect.top < listRect.top) {
      selectedItem.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else if (itemRect.bottom > listRect.bottom) {
      selectedItem.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }
}

// 处理键盘事件
const handleKeydown = (e: KeyboardEvent) => {
  let stockList: any[]
  if (activeTab.value === 'candidates') {
    stockList = filteredCandidates.value  // 使用过滤后的列表（brick策略有筛选时）
  } else if (activeTab.value === 'extreme_b1') {
    stockList = extremeB1Candidates.value
  } else if (activeTab.value === 'extreme_b1_plus') {
    stockList = extremeB1PlusCandidates.value
  } else if (activeTab.value === 'favorites') {
    stockList = backtestStore.favoriteStocks
  } else if (activeTab.value === 'positions') {
    stockList = positions.value
  } else {
    stockList = soldPositions.value
  }
  
  // 如果当前列表为空或正在加载，不处理
  if (stockList.length === 0 || (activeTab.value === 'candidates' && candidatesLoading.value)) {
    return
  }
  
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    // 上键：选择上一个
    const newIndex = selectedStockIndex.value <= 0 
      ? stockList.length - 1  // 循环到最后一个
      : selectedStockIndex.value - 1
    selectStockByIndex(newIndex)
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    // 下键：选择下一个
    const newIndex = selectedStockIndex.value >= stockList.length - 1 
      ? 0  // 循环到第一个
      : selectedStockIndex.value + 1
    selectStockByIndex(newIndex)
  }
}

// 加载K线
const loadKline = async (code: string, endDate?: string) => {
  try {
    // ✅ 清理旧数据，释放内存
    klineData.value = []
    currentKlineData.value = null
    
    // 如果没有指定截止日期，使用当前回测日期
    const targetDate = endDate || backtestStore.currentDate
    const res: any = await strategyApi.getKline(code, targetDate, 60)
    klineData.value = res.klines
    renderChart(res.klines)
  } catch (error) {
    ElMessage.error('加载K线失败')
  }
}

// 渲染K线图
const renderChart = (klines: any[]) => {
  if (!chartRef.value) return

  // ✅ 重要：先销毁旧的图表对象，释放内存
  if (mainChart) {
    try {
      mainChart.remove()
      mainChart = null
    } catch (e) {
      console.warn('销毁主图表失败:', e)
    }
  }

  // 清空DOM
  chartRef.value.innerHTML = ''

  // 创建新图表
  mainChart = createChart(chartRef.value, {
    width: chartRef.value.clientWidth,
    height: 400,
    layout: {
      background: { type: ColorType.Solid, color: '#ffffff' },
      textColor: '#333'
    },
    grid: {
      vertLines: { visible: false },
      horzLines: { visible: false }
    },
    timeScale: {
      borderColor: '#e1e1e1',
      timeVisible: true,
      secondsVisible: false
    },
    leftPriceScale: {
      visible: false
    },
    rightPriceScale: {
      borderColor: '#e1e1e1'
    },
    handleScroll: false,
    handleScale: false,
    crosshair: {
      mode: 1, // Normal crosshair mode
      vertLine: {
        width: 1,
        color: '#758696',
        style: 3, // LineStyle.LargeDashed
        labelBackgroundColor: '#4682B4'
      },
      horzLine: {
        width: 1,
        color: '#758696',
        style: 3,
        labelBackgroundColor: '#4682B4'
      }
    }
  })

  // K线主图
  const candlestickSeries = mainChart.addCandlestickSeries({
    upColor: '#f5465c',
    downColor: '#26a69a',
    borderUpColor: '#f5465c',
    borderDownColor: '#26a69a',
    wickUpColor: '#f5465c',
    wickDownColor: '#26a69a'
  })
  
  const data = klines.map(k => ({
    time: k.date,
    open: k.open,
    high: k.high,
    low: k.low,
    close: k.close
  }))
  
  candlestickSeries.setData(data)
  
  // 添加知行多空线
  const multiLineSeries = mainChart.addLineSeries({
    color: '#2196f3',
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false
  })
  multiLineSeries.setData(klines.filter(k => k.multi_line).map(k => ({ 
    time: k.date, 
    value: k.multi_line 
  })))
  
  // 添加知行短期趋势线
  const ema10Series = mainChart.addLineSeries({
    color: '#9c27b0',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false
  })
  ema10Series.setData(klines.filter(k => k.ema10_2).map(k => ({ 
    time: k.date, 
    value: k.ema10_2 
  })))
  
  // 添加MA5均线
  const ma5Series = mainChart.addLineSeries({
    color: '#ff9800',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false
  })
  ma5Series.setData(klines.filter(k => k.ma5).map(k => ({ 
    time: k.date, 
    value: k.ma5 
  })))
  
  // 添加MA10均线
  const ma10Series = mainChart.addLineSeries({
    color: '#4caf50',
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false
  })
  ma10Series.setData(klines.filter(k => k.ma10).map(k => ({ 
    time: k.date, 
    value: k.ma10 
  })))
  
  // 标记策略点
  const strategySignalKey = backtestStore.params.strategy === 'brick'
    ? 'brick_signal'
    : `signal_${backtestStore.params.strategy.toLowerCase()}`
  const markers = klines
    .filter(k => k[strategySignalKey] === 1 || k[`${backtestStore.params.strategy.toLowerCase()}_signal`] === 1)
    .map(k => ({
      time: k.date,
      position: 'belowBar',
      color: '#e91e63',
      shape: 'arrowUp',
      text: backtestStore.params.strategy
    }))
  
  if (markers.length > 0) {
    candlestickSeries.setMarkers(markers as any)
  }
  
  // 监听十字光标移动，更新数据面板
  mainChart.subscribeCrosshairMove((param: any) => {
    if (param.time) {
      const klineItem = klines.find(k => k.date === param.time)
      if (klineItem) {
        // 计算涨幅
        const change = klineItem.prev_close 
          ? ((klineItem.close - klineItem.prev_close) / klineItem.prev_close * 100).toFixed(2)
          : '0.00'
        
        // 计算振幅
        const amplitude = klineItem.prev_close
          ? ((klineItem.high - klineItem.low) / klineItem.prev_close * 100).toFixed(2)
          : '0.00'
        
        currentKlineData.value = {
          date: klineItem.date,
          open: klineItem.open?.toFixed(2) || '-',
          high: klineItem.high?.toFixed(2) || '-',
          low: klineItem.low?.toFixed(2) || '-',
          close: klineItem.close?.toFixed(2) || '-',
          change: change,
          amplitude: amplitude,
          multi_line: klineItem.multi_line?.toFixed(2) || '-',
          ema10_2: klineItem.ema10_2?.toFixed(2) || '-'
        }
      }
    } else {
      // 鼠标移出图表时，显示最后一根K线的数据
      if (klines.length > 0) {
        const lastKline = klines[klines.length - 1]
        const change = lastKline.prev_close 
          ? ((lastKline.close - lastKline.prev_close) / lastKline.prev_close * 100).toFixed(2)
          : '0.00'
        const amplitude = lastKline.prev_close
          ? ((lastKline.high - lastKline.low) / lastKline.prev_close * 100).toFixed(2)
          : '0.00'
        
        currentKlineData.value = {
          date: lastKline.date,
          open: lastKline.open?.toFixed(2) || '-',
          high: lastKline.high?.toFixed(2) || '-',
          low: lastKline.low?.toFixed(2) || '-',
          close: lastKline.close?.toFixed(2) || '-',
          change: change,
          amplitude: amplitude,
          multi_line: lastKline.multi_line?.toFixed(2) || '-',
          ema10_2: lastKline.ema10_2?.toFixed(2) || '-'
        }
      }
    }
  })
  
  mainChart.timeScale().fitContent()
  
  // 初始化显示最后一根K线数据
  if (klines.length > 0) {
    const lastKline = klines[klines.length - 1]
    const change = lastKline.prev_close 
      ? ((lastKline.close - lastKline.prev_close) / lastKline.prev_close * 100).toFixed(2)
      : '0.00'
    const amplitude = lastKline.prev_close
      ? ((lastKline.high - lastKline.low) / lastKline.prev_close * 100).toFixed(2)
      : '0.00'
    
    currentKlineData.value = {
      date: lastKline.date,
      open: lastKline.open?.toFixed(2) || '-',
      high: lastKline.high?.toFixed(2) || '-',
      low: lastKline.low?.toFixed(2) || '-',
      close: lastKline.close?.toFixed(2) || '-',
      change: change,
      amplitude: amplitude,
      multi_line: lastKline.multi_line?.toFixed(2) || '-',
      ema10_2: lastKline.ema10_2?.toFixed(2) || '-'
    }
  }
}

// 打开买入对话框
const openBuyDialog = (code: string) => {
  buyForm.value.code = code
  buyForm.value.type = 'ratio'
  buyForm.value.ratio = 0.5
  buyForm.value.amount = 100000
  buyDialogVisible.value = true
}

// 执行买入
const handleBuy = async () => {
  buyLoading.value = true
  try {
    let amount = 0
    if (buyForm.value.type === 'ratio') {
      amount = backtestStore.cash * buyForm.value.ratio
    } else {
      amount = buyForm.value.amount
    }

    await backtestApi.trade({
      session_id: backtestStore.sessionId,
      action: 'buy',
      code: buyForm.value.code,
      amount: amount
    })

    ElMessage.success('买入成功')
    buyDialogVisible.value = false
    
    // 刷新状态
    await refreshState()
  } catch (error: any) {
    // 检查是否是会话失效
    if (error?.response?.status === 404) {
      ElMessage.error({
        message: '回测会话已失效，请重新开始回测',
        duration: 3000,
        onClose: () => {
          backtestStore.reset()
          router.push('/setup')
        }
      })
    } else {
      ElMessage.error(error.response?.data?.detail || '买入失败')
    }
  } finally {
    buyLoading.value = false
  }
}

// 全选/取消全选
const handleSelectAll = (val: boolean) => {
  if (val) {
    selectedCodes.value = candidates.value.map(s => s.code)
  } else {
    selectedCodes.value = []
  }
}

// 极致B1全选处理
const handleSelectAllExtremeB1 = (val: boolean) => {
  if (val) {
    selectedCodes.value = extremeB1Candidates.value.map(s => s.code)
  } else {
    selectedCodes.value = []
  }
}

// 极致B1+全选处理
const handleSelectAllExtremeB1Plus = (val: boolean) => {
  if (val) {
    selectedCodes.value = extremeB1PlusCandidates.value.map(s => s.code)
  } else {
    selectedCodes.value = []
  }
}

// 打开批量买入对话框
const openBatchBuyDialog = () => {
  batchBuyForm.value = {
    type: 'average',
    ratio: 0.5,
    amountPerStock: 50000
  }
  batchBuyDialogVisible.value = true
}

// 执行批量买入
const handleBatchBuy = async () => {
  batchBuyLoading.value = true
  let successCount = 0
  let failCount = 0
  const errors: string[] = []
  
  try {
    // 计算每只股票的买入金额
    let amountPerStock = 0
    if (batchBuyForm.value.type === 'average') {
      amountPerStock = (backtestStore.cash * batchBuyForm.value.ratio) / selectedCodes.value.length
    } else {
      amountPerStock = batchBuyForm.value.amountPerStock
    }
    
    // 逐个买入
    for (const code of selectedCodes.value) {
      try {
        await backtestApi.trade({
          session_id: backtestStore.sessionId,
          action: 'buy',
          code: code,
          amount: amountPerStock
        })
        successCount++
      } catch (error: any) {
        failCount++
        errors.push(`${code}: ${error.response?.data?.detail || '失败'}`)
      }
    }
    
    // 显示结果
    if (failCount === 0) {
      ElMessage.success(`批量买入成功！共买入 ${successCount} 只股票`)
    } else {
      ElMessage.warning(`批量买入完成：成功 ${successCount} 只，失败 ${failCount} 只`)
      if (errors.length > 0 && errors.length <= 3) {
        errors.forEach(err => ElMessage.error(err))
      }
    }
    
    batchBuyDialogVisible.value = false
    selectedCodes.value = []
    selectAll.value = false
    
    // 刷新状态
    await refreshState()
  } catch (error: any) {
    ElMessage.error('批量买入失败')
  } finally {
    batchBuyLoading.value = false
  }
}

// 打开卖出对话框
const openSellDialog = (code: string, totalShares: number) => {
  sellForm.value.code = code
  sellForm.value.totalShares = totalShares
  sellForm.value.shares = totalShares
  sellDialogVisible.value = true
}

// 执行卖出
const handleSell = async () => {
  sellLoading.value = true
  try {
    await backtestApi.trade({
      session_id: backtestStore.sessionId,
      action: 'sell',
      code: sellForm.value.code,
      shares: sellForm.value.shares
    })

    ElMessage.success('卖出成功')
    sellDialogVisible.value = false
    
    // 刷新状态
    await refreshState()
    
    // 刷新精选池（更新 is_bought 状态及当前价格）
    await refreshFavorites()
  } catch (error: any) {
    // 检查是否是会话失效
    if (error?.response?.status === 404) {
      ElMessage.error({
        message: '回测会话已失效，请重新开始回测',
        duration: 3000,
        onClose: () => {
          backtestStore.reset()
          router.push('/setup')
        }
      })
    } else {
      ElMessage.error(error.response?.data?.detail || '卖出失败')
    }
  } finally {
    sellLoading.value = false
  }
}

// 下一交易日
const handleNextDay = async () => {
  nextDayLoading.value = true
  try {
    const res: any = await backtestApi.nextDay({
      session_id: backtestStore.sessionId
    })

    // 后端可能返回 success=false（如已到最后一个交易日）
    if (res.success === false) {
      ElMessage.warning(res.message || '无法推进')
      return
    }

    // 更新 store 状态 - 只更新必要的字段，保留 sessionId
    backtestStore.currentDate = res.current_date
    backtestStore.cash = res.cash
    // 同步更新本地 ref
    positions.value = res.positions || []
    soldPositions.value = res.sold_positions || []

    ElMessage.success(`已推进到 ${res.current_date}`)
    
    // 重新加载候选池
    await loadCandidates()
    
    // 刷新精选池价格
    await refreshFavorites()
    
    // 清空选中的股票和索引
    selectedStock.value = ''
    selectedStockIndex.value = -1
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '推进失败')
  } finally {
    nextDayLoading.value = false
  }
}

// 回退一日
const handleRollback = async () => {
  rollbackLoading.value = true
  try {
    const res: any = await backtestApi.rollback({
      session_id: backtestStore.sessionId
    })

    // 更新 store 状态 - 只更新必要的字段，保留 sessionId
    backtestStore.currentDate = res.current_date
    backtestStore.cash = res.cash
    // 同步更新本地 ref
    positions.value = res.positions || []
    soldPositions.value = res.sold_positions || []

    ElMessage.success(`已回退到 ${res.current_date}`)
    
    // 重新加载候选池
    await loadCandidates()
    
    // 刷新精选池价格
    await refreshFavorites()
    
    // 清空选中的股票和索引
    selectedStock.value = ''
    selectedStockIndex.value = -1
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '回退失败')
  } finally {
    rollbackLoading.value = false
  }
}

// 结束回测
const handleEndBacktest = async () => {
  try {
    await ElMessageBox.confirm(
      '确认结束本次回测吗？结束后将返回设置页面。',
      '提示',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    
    const res: any = await backtestApi.end({
      session_id: backtestStore.sessionId
    })
    
    // 显示详细统计信息
    await ElMessageBox.alert(
      `<div style="text-align: left; line-height: 1.8;">
        <h3 style="margin-top: 0;">回测结果</h3>
        <p><strong>总收益:</strong> <span style="color: ${res.total_profit_pct >= 0 ? '#f56c6c' : '#67c23a'}">${res.total_profit_pct >= 0 ? '+' : ''}${res.total_profit_pct}%</span> (${res.total_profit_pct >= 0 ? '+' : ''}¥${res.total_profit.toFixed(2)})</p>
        <p><strong>年化收益:</strong> <span style="color: ${res.annualized_return >= 0 ? '#f56c6c' : '#67c23a'}">${res.annualized_return >= 0 ? '+' : ''}${res.annualized_return}%</span></p>
        <p><strong>最大回撤:</strong> <span style="color: #67c23a">-${res.max_drawdown.toFixed(2)}%</span></p>
        <p><strong>夏普比率:</strong> ${res.sharpe_ratio.toFixed(3)}</p>
        <p><strong>胜率:</strong> ${res.win_rate.toFixed(2)}%</p>
        <p><strong>盈亏比:</strong> ${res.profit_loss_ratio.toFixed(2)}</p>
        <p><strong>交易次数:</strong> ${res.trade_count}笔 (买${res.buy_count}/卖${res.sell_count})</p>
        <p><strong>平均持仓:</strong> ${res.avg_holding_days.toFixed(1)}天</p>
        <p><strong>回测天数:</strong> ${res.trade_days}天</p>
      </div>`,
      '回测结束',
      {
        confirmButtonText: '查看历史记录',
        cancelButtonText: '返回设置',
        showCancelButton: true,
        dangerouslyUseHTMLString: true
      }
    ).then(() => {
      // 点击"查看历史记录"
      router.push('/history')
    }).catch(() => {
      // 点击"返回设置"
      router.push('/setup')
    })
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '结束失败')
    }
  }
}

// 判断卖出决策质量
const getDecisionType = (realizedPct: number, potentialPct: number) => {
  // 如果实际盈利 >= 潜在盈利，说明卖得好
  if (realizedPct >= potentialPct) {
    return 'success'
  }
  // 如果实际盈利 < 潜在盈利，说明卖早了
  if (realizedPct >= 0 && potentialPct > realizedPct) {
    return 'warning'
  }
  // 如果实际亏损，但如果继续持有会赚钱，说明卖早了
  if (realizedPct < 0 && potentialPct > 0) {
    return 'danger'
  }
  // 如果实际亏损 > 潜在亏损，说明止损正确
  if (realizedPct < 0 && realizedPct > potentialPct) {
    return 'success'
  }
  return 'info'
}

const getDecisionText = (realizedPct: number, potentialPct: number) => {
  if (realizedPct >= potentialPct) {
    return realizedPct >= 0 ? '卖出时机好' : '止损及时'
  }
  if (realizedPct >= 0 && potentialPct > realizedPct) {
    return '卖早了'
  }
  if (realizedPct < 0 && potentialPct > 0) {
    return '不该卖'
  }
  if (realizedPct < 0 && realizedPct > potentialPct) {
    return '止损正确'
  }
  return '持平'
}

// 刷新状态
const refreshState = async () => {
  // 检查sessionId是否有效
  if (!backtestStore.sessionId) {
    console.warn('会话ID为空，跳过刷新状态')
    throw new Error('会话ID为空')
  }
  
  try {
    const state: any = await backtestApi.getState(backtestStore.sessionId)
    // 更新 store（会触发 watch 自动同步到本地 ref）
    backtestStore.setState(state)
    // 手动同步一次，确保立即更新，并确保是数组类型
    positions.value = Array.isArray(state.positions) ? state.positions : []
    soldPositions.value = Array.isArray(state.sold_positions) ? state.sold_positions : []
  } catch (error) {
    console.error('刷新状态失败', error)
    // ✅ 抛出错误，让调用方处理
    throw error
  }
}

// 监听 store 的变化，自动同步到本地 ref（用于持久化恢复时的数据同步）
watch(() => backtestStore.positions, (newPositions) => {
  // ✅ 确保newPositions是数组
  if (Array.isArray(newPositions)) {
    positions.value = newPositions
  } else {
    positions.value = []
  }
}, { deep: true })

watch(() => backtestStore.soldPositions, (newSoldPositions) => {
  // ✅ 确保newSoldPositions是数组
  if (Array.isArray(newSoldPositions)) {
    soldPositions.value = newSoldPositions
  } else {
    soldPositions.value = []
  }
}, { deep: true })

onMounted(async () => {
  // 等待store状态准备好
  if (backtestStore.sessionId && backtestStore.currentDate) {
    try {
      // 刷新状态（从后端获取最新数据，验证会话是否有效）
      await refreshState()
      // 加载候选池
      await loadCandidates()
      
      // 添加键盘事件监听
      window.addEventListener('keydown', handleKeydown)
    } catch (error: any) {
      // 如果刷新状态失败（会话已过期），清空store并返回设置页
      console.error('刷新状态失败，会话可能已过期:', error)
      
      // 检查是否是404错误（会话不存在）
      if (error?.response?.status === 404) {
        // ✅ 更友好的提示信息
        ElMessage({
          message: '回测会话已失效（可能是后端服务重启导致），请重新开始回测',
          type: 'warning',
          duration: 3000
        })
        backtestStore.reset()
        router.push('/setup')
      } else {
        // 其他错误（如网络错误），不清空store，只提示
        ElMessage.error('加载失败：' + (error?.message || '未知错误'))
      }
      return
    }
  } else {
    // 如果状态未准备好，返回设置页
    ElMessage.warning('回测会话未初始化')
    router.push('/setup')
  }
})

// 组件卸载时移除键盘事件监听和清理图表
onUnmounted(() => {
  // 移除键盘监听
  window.removeEventListener('keydown', handleKeydown)
  
  // ✅ 重要：销毁主图表对象，释放内存
  if (mainChart) {
    try {
      mainChart.remove()
      mainChart = null
    } catch (e) {
      console.warn('销毁主图表失败:', e)
    }
  }
})
</script>

<style scoped>
.backtest-main {
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

.main-content {
  flex: 1;
  display: flex;
  gap: 10px;
  padding: 10px;
  overflow: hidden;
}

.left-panel {
  width: 350px;
  display: flex;
  flex-direction: column;
}

.right-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: hidden;
}

.candidate-card,
.position-card {
  height: 100%;
}

/* K线图区域（固定高度，完整展示） */
.chart-section {
  flex-shrink: 0;
  height: auto;
  min-height: 850px;
}

.chart-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.chart-card :deep(.el-card__body) {
  padding: 10px;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.position-card {
  height: 280px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header :deep(.el-tabs) {
  width: 100%;
}

.card-header :deep(.el-tabs__header) {
  margin: 0;
}

.card-header :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
}

.card-header :deep(.el-tabs__item) {
  padding: 0 15px;
  height: 36px;
  line-height: 36px;
}

.candidate-list {
  height: calc(100vh - 180px);
  overflow-y: auto;
  overflow-x: hidden;
}

.batch-toolbar {
  padding: 10px 12px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  gap: 10px;
  background: #f5f7fa;
}

.candidate-item {
  padding: 12px;
  border-bottom: 1px solid #ebeef5;
  cursor: pointer;
  transition: all 0.3s;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.candidate-item.selected {
  background: #f0f9ff;
}

.candidate-item:hover {
  background: #f5f7fa;
}

.candidate-item.active {
  background: #ecf5ff;
  border-left: 3px solid #409eff;
}

.batch-buy-info {
  background: #f0f9ff;
  padding: 15px;
  border-radius: 4px;
  margin-bottom: 15px;
}

.batch-buy-info p {
  margin: 5px 0;
}

.tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}

.warning-tip {
  font-size: 12px;
  color: #e6a23c;
  margin-top: 8px;
  padding: 8px 12px;
  background: #fdf6ec;
  border-left: 3px solid #e6a23c;
  border-radius: 4px;
}

.position-item {
  background: #f0f9ff;
}

.position-item:hover {
  background: #e1f3ff;
}

.position-item.active {
  background: #d1edff;
  border-left: 3px solid #67c23a;
}

.stock-code {
  font-weight: bold;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.stock-code-with-days {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.stock-code-with-days .stock-code {
  display: flex;
  align-items: center;
  gap: 6px;
}

.holding-days {
  font-size: 11px;
  color: #909399;
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 3px;
  display: inline-block;
  width: fit-content;
}

.stock-info {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.price {
  font-size: 14px;
  font-weight: bold;
}

.change {
  font-size: 12px;
}

.rise {
  color: #f56c6c;
}

.fall {
  color: #67c23a;
}

.stock-volume {
  font-size: 12px;
  color: #909399;
}

.chart-container {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.kline-wrapper {
  position: relative;
  width: 100%;
  height: 400px;
}

.kline-info-panel {
  position: absolute;
  top: 10px;
  left: 10px;
  background: rgba(255, 255, 255, 0.95);
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  padding: 8px 12px;
  font-size: 12px;
  z-index: 10;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  min-width: 400px;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.info-row:last-child {
  margin-bottom: 0;
}

.info-label {
  color: #666;
  font-weight: 500;
}

.info-value {
  color: #333;
  font-weight: 600;
}

.kline-chart {
  width: 100%;
  height: 400px;
}

.sub-charts {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 10px;
}

.sub-chart {
  width: 100%;
  height: 130px;
}

.sub-chart-double {
  height: 270px;
}

.sub-indicator-tabs {
  display: flex;
  gap: 0;
  border-bottom: 1px solid #e4e7ed;
  margin: 2px 0 0 0;
}

.sub-tab {
  padding: 4px 16px;
  font-size: 12px;
  cursor: pointer;
  color: #909399;
  border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
  user-select: none;
}

.sub-tab:hover {
  color: #409eff;
}

.sub-tab.active {
  color: #409eff;
  border-bottom-color: #409eff;
  font-weight: 600;
}

.legend-box {
  display: flex;
  gap: 15px;
  align-items: center;
  font-size: 12px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

.legend-line {
  display: inline-block;
  border-radius: 1px;
}

/* 已清仓样式 */
.sold-item {
  background: #fafafa;
  flex-direction: column;
  align-items: stretch;
  padding: 10px 12px;
}

.sold-item:hover {
  background: #f0f0f0;
}

.sold-item.active {
  background: #e6f7ff;
  border-left: 3px solid #1890ff;
}

.sold-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.date-range {
  font-size: 11px;
  color: #999;
}

.sold-content {
  display: flex;
  gap: 15px;
}

.sold-section {
  flex: 1;
  padding: 8px;
  background: white;
  border-radius: 4px;
  border: 1px solid #f0f0f0;
}

.section-title {
  font-size: 11px;
  color: #999;
  margin-bottom: 6px;
  font-weight: 500;
}

.price-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  margin-bottom: 4px;
}

.price-row .label {
  color: #666;
}

.price-row .value {
  font-weight: 600;
  color: #333;
}

.current-price {
  color: #1890ff !important;
}

.profit-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #f0f0f0;
}

.profit-row .label {
  color: #666;
}

.profit-value {
  font-weight: 600;
  font-size: 11px;
}

.decision-indicator {
  margin-top: 8px;
  text-align: center;
}

/* 学习案例区域（可滚动） */
.learning-section {
  flex-shrink: 0;
  margin-top: 10px;
  margin-bottom: 20px;
}

.learning-card {
  width: 100%;
}

.learning-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 500;
}

.learning-content {
  height: 100%;
  overflow-y: auto;
}

.learning-info {
  display: flex;
  gap: 20px;
  padding: 10px 0;
  font-size: 13px;
  color: #606266;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 10px;
}

.learning-tabs {
  margin-top: 10px;
}

.learning-tabs :deep(.el-tabs__header) {
  margin-bottom: 10px;
}

.learning-tip {
  margin-top: 10px;
  padding: 8px 12px;
  background: #f0f9ff;
  border-left: 3px solid #409eff;
  border-radius: 4px;
  font-size: 12px;
  color: #606266;
}

/* 市场分组样式 */
.market-group {
  margin-bottom: 20px;
}

.market-group:last-child {
  margin-bottom: 0;
}

.market-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 6px;
  margin-bottom: 10px;
  box-shadow: 0 2px 4px rgba(102, 126, 234, 0.2);
}

.market-group-title {
  font-size: 14px;
  font-weight: 600;
  color: white;
}

.market-group-count {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.9);
  background: rgba(255, 255, 255, 0.2);
  padding: 2px 8px;
  border-radius: 10px;
}

/* 极致B1相关样式 */
.candidate-item.extreme-b1 {
  border-left: 3px solid #e6a23c;
  background: linear-gradient(to right, #fdf6ec 0%, #ffffff 100%);
}

.candidate-item.extreme-b1:hover {
  background: linear-gradient(to right, #fef0dc 0%, #f5f7fa 100%);
}

/* 极致B1+样式（在极致B1基础上用红色边框区分） */
.candidate-item.extreme-b1-plus {
  border-left: 3px solid #f56c6c;
  background: linear-gradient(to right, #fef0f0 0%, #ffffff 100%);
}

.candidate-item.extreme-b1-plus:hover {
  background: linear-gradient(to right, #fde2e2 0%, #f5f7fa 100%);
}

.factor-item.brick-red {
  color: #f56c6c;
  font-weight: bold;
}

.candidate-item.extreme-b1.active {
  background: linear-gradient(to right, #f5dab1 0%, #ecf5ff 100%);
  border-left: 3px solid #e6a23c;
}

.extreme-b1-tips {
  margin-bottom: 10px;
  padding: 0 12px;
}

.extreme-b1-tips .tips-content p {
  margin: 4px 0;
  font-size: 12px;
  line-height: 1.6;
}

.stock-code-with-factors {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-width: 0;
  max-width: 60%;
}

.stock-code-with-factors .stock-code {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.stock-factors {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: #909399;
}

.factor-item {
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 3px;
}

/* 精选池样式 */
.favorites-stats {
  margin-bottom: 12px;
}

.stats-content {
  display: flex;
  justify-content: space-around;
  font-size: 12px;
}

.stats-content span {
  color: #606266;
}

.favorite-item {
  background: #fafafa;
  flex-direction: column;
  align-items: stretch;
  padding: 10px 12px;
  gap: 8px;
}

.favorite-item:hover {
  background: #f0f0f0;
}

.favorite-item.active {
  background: #e6f7ff;
  border-left: 3px solid #1890ff;
}

.favorite-item.is-bought {
  background: #f0f9ff;
  border-left: 3px solid #52c41a;
}

.favorite-item.extreme-b1 {
  background: #fffbf0;
}

.favorite-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.favorite-date {
  font-size: 11px;
  color: #999;
}

.favorite-price-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 0;
}

.price-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.price-line .label {
  color: #999;
  width: 40px;
}

.price-line .price {
  font-weight: 500;
  color: #333;
}

.favorite-note {
  padding: 6px 8px;
  background: white;
  border-radius: 4px;
  border: 1px solid #f0f0f0;
  font-size: 12px;
}

.favorite-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.favorite-actions .el-button {
  flex: 1;
  max-width: 80px;
}

/* B3砖型选股 - 比例过滤器 */
.b3-filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fff8f0;
  border-bottom: 1px solid #ffe0b2;
  flex-wrap: wrap;
}

.b3-filter-label {
  font-size: 12px;
  color: #e65c00;
  white-space: nowrap;
  font-weight: 500;
}

.b3-count-tip {
  font-size: 11px;
  color: #999;
  margin-left: 4px;
}

.b3-filter-sep {
  color: #ccc;
  margin: 0 4px;
  font-size: 14px;
  line-height: 1;
}

/* B3砖型柱数据展示 */
.b3-brick-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 80px;
}

.brick-ratio-badge {
  font-size: 11px;
  font-weight: 600;
  color: #d84315;
  background: #fff3e0;
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
}

.brick-len-info {
  font-size: 10px;
  color: #888;
  white-space: nowrap;
}

/* ── Brick 策略专属竖排卡片 ───────────────────────────── */
.brick-candidate-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px 8px 12px;
  border-bottom: 1px solid #ebeef5;
  cursor: pointer;
  transition: background 0.2s;
  width: 100%;
  box-sizing: border-box;
  min-width: 0;
}

.brick-candidate-item:hover { background: #f5f7fa; }
.brick-candidate-item.active {
  background: #ecf5ff;
  border-left: 3px solid #409eff;
}
.brick-candidate-item.selected { background: #f0f9ff; }

/* 优先关注：浅绿左边框 */
.brick-candidate-item.brick-priority {
  border-left: 3px solid #67c23a;
  background: linear-gradient(to right, #f0f9eb 0%, #ffffff 100%);
}
.brick-candidate-item.brick-priority:hover {
  background: linear-gradient(to right, #e1f3d8 0%, #f5f7fa 100%);
}
.brick-candidate-item.brick-priority.active {
  background: linear-gradient(to right, #d4edda 0%, #ecf5ff 100%);
  border-left: 3px solid #409eff;
}

/* 谨慎回避：浅灰左边框 */
.brick-candidate-item.brick-caution {
  border-left: 3px solid #c0c4cc;
  background: #fafafa;
}

/* 第一行：左右两侧布局 */
.brick-row-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  min-width: 0;
}

/* 左侧：复选框 + 代码 + 打分标签，允许收缩但不溢出 */
.brick-left {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}

/* 右侧：价格 + 涨跌 + 按钮，固定宽度不缩放 */
.brick-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  white-space: nowrap;
}

/* 价格和涨跌垂直叠放 */
.brick-price-change {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0;
  line-height: 1.3;
}

/* 精选按钮：仅图标，紧凑 */
.brick-btn-star.el-button {
  padding: 4px 6px;
  min-width: 28px;
  width: 28px;
  font-size: 13px;
}

/* 买入按钮：固定宽度 */
.brick-btn-buy.el-button {
  padding: 4px 8px;
  min-width: 42px;
}

.stock-code-text {
  font-weight: bold;
  font-size: 14px;
  flex-shrink: 0;
  white-space: nowrap;
  letter-spacing: 0.3px;
}

/* 打分标签 */
.brick-score-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 8px;
  white-space: nowrap;
  flex-shrink: 0;
}
.score-priority { background: #f0f9eb; color: #5daf34; border: 1px solid #b3e19d; }
.score-normal   { background: #f4f4f5; color: #909399; border: 1px solid #d3d4d6; }
.score-caution  { background: #f9f9f9; color: #aaaaaa; border: 1px solid #dcdfe6; }

/* F6 红柱数徽章 */
.brick-f6-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 4px;
  border-radius: 8px;
  white-space: nowrap;
  flex-shrink: 0;
  background: #fff3e0;
  color: #e65c00;
  border: 1px solid #ffcc80;
}

.brick-price {
  font-size: 12px;
  font-weight: 600;
  color: #303133;
}

.brick-change {
  font-size: 11px;
  font-weight: 500;
}

/* 第二行 */
.brick-row-bottom {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 22px;
  flex-wrap: wrap;
}

.brick-vol {
  font-size: 11px;
  color: #909399;
}

/* 逐因子得分小图标 */
.brick-factor-scores {
  display: flex;
  gap: 3px;
  flex-wrap: wrap;
}

.factor-score-dot {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 3px;
  white-space: nowrap;
  cursor: default;
}
.fs-pos { color: #e6451a; background: #fff0eb; }
.fs-neg { color: #909399; background: #f4f4f5; }
.fs-neu { color: #c0c4cc; background: #fafafa; }
</style>
