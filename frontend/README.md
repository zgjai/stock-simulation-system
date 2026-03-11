# A股主观回测系统 - 前端

基于 Vue 3 + TypeScript + Vite 构建的股票回测前端应用。

## 技术栈

- **Vue 3** - 渐进式JavaScript框架
- **TypeScript** - 类型安全
- **Vite** - 极速开发服务器
- **Element Plus** - UI组件库
- **Pinia** - 状态管理
- **Vue Router** - 路由管理
- **Axios** - HTTP客户端
- **Lightweight Charts** - K线图表库
- **ECharts** - 数据可视化

## 快速开始

### 安装依赖
```bash
npm install
```

### 开发模式
```bash
npm run dev
```

### 构建生产版本
```bash
npm run build
```

### 预览生产版本
```bash
npm run preview
```

## 项目结构

```
src/
├── api/           # API接口封装
├── assets/        # 静态资源
├── components/    # 通用组件
├── router/        # 路由配置
├── stores/        # Pinia状态管理
├── types/         # TypeScript类型定义
├── views/         # 页面组件
├── App.vue        # 根组件
└── main.ts        # 入口文件
```

## 主要功能

### 1. 回测设置页 (`/setup`)
- 选择起始日期
- 设置初始资金
- 选择策略
- 配置滑点和手续费

### 2. 回测主页 (`/backtest`)
- 候选池列表
- K线图表展示
- 交易操作（买入/卖出）
- 持仓管理
- 账户信息

## API代理配置

前端开发服务器已配置API代理，所有 `/api` 请求会自动转发到后端服务：

```typescript
// vite.config.ts
server: {
  proxy: {
    '/api': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true
    }
  }
}
```

## 环境要求

- Node.js >= 18
- npm >= 9

## 开发建议

### 代码规范
- 使用 TypeScript 进行类型检查
- 遵循 Vue 3 Composition API 风格
- 组件命名使用 PascalCase
- 文件命名使用 kebab-case

### 性能优化
- 使用 `computed` 缓存计算结果
- 使用 `v-if` 条件渲染大型组件
- 图表组件懒加载
- 防抖处理高频操作

## 常见问题

### 页面空白
检查浏览器控制台错误信息，通常是API连接问题。

### 无法连接后端
确保后端服务已启动（http://127.0.0.1:8000）

### npm install 失败
尝试使用国内镜像：
```bash
npm install --registry=https://registry.npmmirror.com
```
