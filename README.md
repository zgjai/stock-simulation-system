# A股主观回测模拟系统

一个本地运行的A股主观交易回测平台，支持B1/B2/单针策略选股与逐日推进回测。

**项目状态**：✅ 核心功能已完成 | 🚀 数据库版本已上线（性能提升37倍）

---

## 🎯 项目特点

- **主观回测**：只能看到截至当前历史交易日的数据，避免未来函数
- **三大策略**：B1（低位窄幅）、B2（打底起爆）、单针（高位转弱）
- **完整交易规则**：涨跌停限制、T+1制度、滑点手续费精确计算
- **数据库优化**：使用SQLite存储1400万+日线数据，查询速度提升37倍 ⚡
- **本地运行**：无需服务器，数据完全本地化

## ⚡ 最新更新（v2.0）

- ✅ **数据库迁移完成**：1431万条数据已导入SQLite（4.6GB）
- ✅ **API性能提升**：查询速度提升10-37倍
- ✅ **双版本支持**：v1(文件)和v2(数据库)共存
- 📚 **完整文档**：迁移、测试、使用文档齐全

**详细信息**：查看 [`ARCHIVE_SUMMARY.md`](./ARCHIVE_SUMMARY.md)

## 📁 项目结构

```
stock_simulation_system/
├── origin_data/              # 原始CSV数据（前复权）
├── processed_data/           # 增强CSV（含指标+策略信号）
├── strategy_index/           # 策略索引JSON
├── learning_cases/           # 学习案例预计算数据
├── backend/                  # FastAPI后端
│   ├── app/                  # API服务
│   ├── scripts/              # 数据预处理脚本
│   └── requirements.txt
├── frontend/                 # Vue3前端
├── data/                     # 日志和数据库
├── logs/                     # 运行日志
├── factor_analysis/          # 因子分析结果
├── archive/                  # 归档文件（分析脚本、历史文档、备份数据）
├── config.yaml               # 配置文件
├── start.sh                  # 启动脚本
├── stop.sh                   # 停止脚本
└── restart.sh                # 重启脚本
```

## 🚀 快速开始

### 方式一：一键启动（推荐）

```bash
# 启动系统（自动检查环境并启动前后端）
./start.sh

# 停止系统
./stop.sh
```

### 方式二：手动启动

#### 1. 数据预处理

```bash
# 测试单个股票
python3 backend/scripts/test_single_stock.py --code 000001

# 处理样本股票（快速测试，约6秒）
python3 backend/scripts/preprocess_sample.py

# 批量处理全部股票（首次运行约需1-2小时）
python3 backend/scripts/preprocess_all.py

# 计算学习案例数据（可选，用于学习案例功能）
python3 backend/scripts/calc_learning_cases.py

# 计算量化因子（可选，用于因子分析）
python3 backend/scripts/calc_factors.py
```

#### 2. 启动后端API

```bash
# 安装依赖
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 启动服务
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 访问API文档: http://127.0.0.1:8000/docs
```

#### 3. 启动前端

```bash
# 安装依赖
cd frontend
npm install

# 启动开发服务器
npm run dev

# 访问页面: http://localhost:5173
```

## 📊 当前进度

### ✅ 已完成

- [x] **数据预处理层**
  - [x] 基础工具（涨跌停计算、异常检测、交易日历）
  - [x] 指标计算（KDJ、MACD、知行系列、洗盘线、均线）
  - [x] 策略计算（B1、B2、单针）
  - [x] 批量处理和增量更新脚本

- [x] **后端API（FastAPI）**
  - [x] 基础查询接口（交易日、策略列表、股票列表）
  - [x] 选股接口（候选池查询、K线数据）
  - [x] 回测核心接口（开始、交易、推进、回退、结束）
  - [x] 历史记录接口（查询历史、详情查看）

- [x] **前端界面（Vue 3 + TypeScript）**
  - [x] 回测设置页（参数配置、策略选择）
  - [x] 回测主页面（候选池列表、K线图表、持仓管理）
  - [x] K线图表（Lightweight Charts + 策略点标记）
  - [x] 技术指标副图（ECharts：成交量、KDJ、MACD）
  - [x] 交易面板（买入/卖出对话框）
  - [x] 账户信息展示
  - [x] 时间轴控制（下一日、回退）

### 🎁 核心功能

✨ **选股策略**
- B1策略：低位窄幅震荡（J≤16 + 振幅≤6% + 涨跌≤4%）
- B2策略：打底起爆（两日联动，先打底后突破）
- 单针策略：高位转弱（趋势过滤 + 单针形态识别）

✨ **交易规则**
- 涨跌停限制：主板10%、创业板/科创板20%、北交所30%
- T+1制度：当日买入次日才能卖出
- 滑点：默认0.15%
- 手续费：默认0.02%
- 加权成本：多次买入自动计算加权平均成本价

✨ **回测功能**
- 主观回测：只能看到当前日期之前的数据
- 逐日推进：手动点击"下一交易日"前进
- 回退功能：支持回退到上一交易日
- 实时持仓：显示成本价、当前价、浮动盈亏
- 完整日志：记录所有交易明细

✨ **学习案例（NEW）**
- 优秀案例展示：查看从当前日期开始，未来3/5/10日涨幅TOP5股票
- 多周期对比：通过Tab切换不同时间维度
- 快速查看：点击即可查看该股票的K线图
- 学习辅助：帮助提升选股能力，对比自己的决策与最优选择
- 详见：[学习案例功能说明](学习案例功能说明.md)

✨ **因子分析（NEW）**
- 11个量化因子：包括振幅、成交量比率、知行比率、J值、K线形态等
- 价格波动类：当日振幅、相对昨收涨跌幅、相对今开涨跌幅
- 成交量类：成交量/60日均量比率
- 技术指标类：知行比率、J值
- K线形态类：实体比例、上下影线比例、收盘价位置、连续小振幅天数
- 用途：寻找优秀案例的共性特征，优化选股策略
- 详见：[因子说明文档](因子说明文档.md)

### 📌 待优化（非必需）

- [ ] SQLite持久化（当前使用内存存储）
- [ ] 权益曲线图（当前仅显示实时数据）
- [ ] 统计指标（最大回撤、夏普比率等）
- [ ] 批量导出功能

## 📝 核心文件说明

### 数据预处理

- `backend/scripts/utils.py` - 基础工具函数
- `backend/scripts/indicators.py` - 技术指标计算
- `backend/scripts/strategies.py` - 选股策略计算
- `backend/scripts/preprocess_all.py` - 批量预处理
- `backend/scripts/calc_learning_cases.py` - 学习案例计算
- `backend/scripts/calc_factors.py` - 因子计算（用于因子分析）
- `backend/scripts/analyze_single_factor.py` - 单因子相关性分析
- `backend/scripts/generate_optimized_strategy.py` - 生成优化策略（如B1+）

### 后端API

- `backend/app/main.py` - FastAPI应用入口
- `backend/app/api/basic.py` - 基础查询API
- `backend/app/api/strategy.py` - 选股策略API
- `backend/app/api/backtest.py` - 回测管理API（含学习案例接口）

## 🔧 配置说明

编辑 `config.yaml`：

```yaml
data:
  origin_path: "./origin_data"
  processed_path: "./processed_data"
  index_path: "./strategy_index"
  learning_cases_path: "./learning_cases"  # 学习案例数据路径
  
indicators:
  wash_short_period: 3   # 洗盘线短期参数
  wash_long_period: 21   # 洗盘线长期参数
  
backtest:
  default_capital: 1000000      # 默认初始资金
  default_slippage: 0.0015      # 默认滑点
  default_commission: 0.0002    # 默认手续费
  
api:
  host: "127.0.0.1"
  port: 8000
```

## 🎓 高级功能：因子分析与策略优化

### 因子分析

通过量化因子找出优秀案例的共性特征：

```bash
# 单因子相关性分析（分析B1策略3日收益）
python3 backend/scripts/analyze_single_factor.py --strategy B1 --period 3d

# 分析所有周期（3d/5d/10d）
python3 backend/scripts/analyze_single_factor.py --strategy B1 --all-periods

# 指定时间范围分析（从2024年9月1日到现在）
python3 backend/scripts/analyze_single_factor.py --strategy B1 --period 3d \
  --start-date 20240901

# 分析特定时间段
python3 backend/scripts/analyze_single_factor.py --strategy B1 --period 3d \
  --start-date 20240901 --end-date 20241231
```

**输出**：
- `data/factor_analysis/single_factor_analysis_*.json` - 分析结果数据
- `data/factor_analysis/single_factor_report_*.txt` - 可读报告

### 增强版因子分析 (NEW)

重新评估因子有效性，使用"TOP3占比提升倍数"而非相关系数：

```bash
# 基于已有的分析结果生成增强版报告
python3 backend/scripts/analyze_factor_enhanced.py \
  --input data/factor_analysis/single_factor_analysis_B1_3d_A_20240901_end.json
```

**核心改进**：
- 使用提升倍数(最高组/最低组)评估因子效果
- TOP3集中度分析，找出最优值范围
- 多因子组合建议
- 详见：[增强版因子分析功能说明](增强版因子分析功能说明.md)

**为什么需要增强分析**：相关系数只衡量线性关系，但因子效果往往是非线性的。例如"当日振幅"相关系数仅0.0456，但TOP3占比能提升3.38倍！

### 因子最优区间分析 (NEW)

找出能覆盖最多TOP3的精确值域区间：

```bash
# 扫描所有可能的区间，找出最优筛选条件
python3 backend/scripts/analyze_factor_interval.py \
  --strategy B1 --period 3d --market-group A --start-date 20240901 \
  --min-coverage 0.6 --min-improvement 1.5
```

**核心功能**：
- 精确的值域区间搜索（如振幅4%-6%）
- 三维评估：覆盖率 + 提升倍数 + 样本占比
- 直接输出实战筛选条件
- 详见：[因子最优区间分析使用说明](因子最优区间分析-使用说明.md)

**实战示例**：发现振幅[4.0%, 5.5%]覆盖42%的TOP3，提升2.5倍，只需筛选17%的候选股票 - 这就是最优筛选条件！

### 策略优化

基于因子分析结果生成优化策略（如B1+）：

```bash
# 生成B1+策略（基于3日分析结果）
python3 backend/scripts/generate_optimized_strategy.py --base B1 --output B1_plus --period 3d

# 使用默认筛选条件
python3 backend/scripts/generate_optimized_strategy.py --base B1 --output B1_plus --use-default
```

**效果**：
- 自动应用因子筛选，缩小候选池
- 提高优秀案例命中率
- 可在前端直接选择B1_plus策略进行回测

**详细指南**：[因子分析与策略优化使用指南](因子分析与策略优化使用指南.md)

## 📈 API接口示例

### 获取候选池

```bash
curl "http://127.0.0.1:8000/api/picks?date=20251231&strategy=B1"
```

### 获取K线数据

```bash
curl "http://127.0.0.1:8000/api/stock/kline?code=000001&end_date=20251231&limit=60"
```

### 开始回测

```bash
curl -X POST "http://127.0.0.1:8000/api/backtest/start" \
  -H "Content-Type: application/json" \
  -d '{"start_date":"20251201","initial_capital":1000000}'
```

## 🎓 使用流程

1. **数据准备**：运行预处理脚本，生成增强数据和策略索引
2. **计算学习案例**（可选）：运行学习案例预计算脚本
3. **启动后端**：运行FastAPI服务
4. **开始回测**：
   - 选择起始日期和初始资金
   - 查看当日策略候选池
   - 浏览K线图，决定买入
   - 查看学习案例，学习优秀股票特征
   - 推进到下一交易日
   - 管理持仓，决定卖出
   - 重复直到结束

## 📄 相关文档

### 核心文档（保留在根目录）
- [README.md](README.md) - 项目主文档
- [config.yaml](config.yaml) - 系统配置文件

### 归档文档（archive/docs/）
- [产品需求文档（PRD）](archive/docs/回测网站PRD.md)
- [技术方案](archive/docs/整体技术方案.md)
- [开发启动指南](archive/docs/开发启动指南.md)
- [学习案例功能说明](archive/docs/学习案例功能说明.md)
- [因子说明文档](archive/docs/因子说明文档.md)
- [更多文档...](archive/README.md) - 查看归档目录说明

## ⚠️ 注意事项

1. **数据质量**：原始数据应为前复权价格
2. **存储空间**：全量处理约需5-10GB空间
3. **内存占用**：批量处理建议8GB+内存
4. **首次预处理**：处理5000+只股票约需1-2小时

## 📦 归档说明

为保持项目根目录整洁，便于后续迭代开发，已将以下内容归档到 `archive/` 目录：

- **文档归档** (`archive/docs/`): 功能说明文档、问题修复记录、开发总结等79个文档
- **脚本归档** (`archive/scripts/`): 分析脚本、测试脚本、验证脚本等
- **日志归档** (`archive/logs/`): 历史运行日志文件
- **备份归档** (`archive/backup/`): 历史版本备份数据

详细归档信息请查看：[archive/README.md](archive/README.md)

**归档时间**: 2026-02-15

## 🐛 常见问题

### Q: 预处理很慢怎么办？
A: 先运行 `preprocess_sample.py` 处理样本股票，验证功能正常后再全量处理。

### Q: API启动失败？
A: 检查端口8000是否被占用，可在 `config.yaml` 中修改端口。

### Q: 如何更新数据？
A: 更新 `origin_data` 后，运行 `python backend/scripts/update_data.py`（待开发）。

## 📞 技术支持

遇到问题请查看：
- API文档：http://127.0.0.1:8000/docs
- 日志文件：`data/update_log.txt`, `data/anomaly_log.txt`

---

**版本**: v1.0  
**创建日期**: 2025-01-26  
**状态**: 后端完成，前端开发中
