# PRD: Reflex 前端持久化缓存组件 (`reflex-pcache`)
## 1. 事件背景
Reflex 是一个前后端同构的全栈 Web 框架，其核心设计理念是**后端是单一数据源**。前端组件通过 WebSocket 与后端保持状态同步。
在开发中大型应用时，存在以下痛点：
1. **首屏加载延迟**：页面打开时，必须等待 WebSocket 建立连接，后端查询数据并序列化传输，前端才能渲染。在弱网环境下表现为白屏。
2. **高频交互网络开销**：如表单草稿、滑块拖动等高频前端交互，如果绑定到普通的 `state.var`，每次改动都会产生一次 WebSocket 往返，增加后端压力与网络延迟。
3. **无持久化缓存机制**：虽然 Reflex 提供了后端内存缓存方案，但一旦应用重启，缓存清空。用户希望“再次打开网页时，直接使用上次的本地缓存（如主题设置、全局公告、未提交表单）”，实现 0 网络延迟的“秒开”体验。
## 2. 需求分析
### 2.1 目标
开发一个可独立引用的 Reflex 自定义包（`reflex_pcache`），仿照 `ClientStateVar` 的操作模式，利用 TypeScript/JavaScript 桥接，为 Reflex 提供**基于浏览器 `localStorage` 的持久化前端状态管理**。
### 2.2 核心功能需求
1. **前端读取（零延迟）**：组件绑定变量时，直接在前端 JS 层面读取 `localStorage`，不依赖后端 WebSocket 同步即可完成首屏渲染。
2. **前端写入（高频防抖）**：前端事件触发写入时，直接写入浏览器 `localStorage`，不回传后端（或仅回传一个极轻量的 UI 刷新信号），适用于草稿保存等场景。
3. **后端写前端（主动推送）**：后端在业务逻辑中（如数据库配置更新），可将最新数据主动推送到前端，并自动更新到 `localStorage`。
4. **后端读前端（按需拉取）**：后端可通过事件触发，要求前端将当前的 `localStorage` 缓存数据回传给后端进行业务处理。
5. **长效持久化**：数据存储在浏览器硬盘，关闭网页、断网、重启电脑后再次打开网页，数据依然存在。
## 3. ClientStateVar 可参考的优缺点
在 Reflex 实验性 API (`rx._x.client_state`) 中存在 `ClientStateVar`，我们分析其优缺点作为参考：
*   **优点**：
    *   提供了前后端双向通信：后端可 `push`，前端可 `retrieve`。
    *   前端读取直接走 React 内存态，省去了 WebSocket 往返。
    *   前端写入不回后端，适合高频交互。
*   **缺点**：
    *   **非持久化**：底层基于 React `useState`，页面一刷新内存清空，无法实现“长效缓存秒开”。
    *   **API 不稳定**：处于 `rx._x` 命名空间，属于实验性特性。
    *   **无封装**：开发者仍需手动处理数据类型和事件绑定，缺少开箱即用的持久化封装。
## 4. 整体思路框架
本方案旨在结合 `ClientStateVar` 的“前后端双通操作模式”与 `localStorage` 的“长效持久化特性”。
### 4.1 架构与数据流向
```text
[浏览器 localStorage] <----> [全局 JS 管理器 window.__pcache] <----> [React 组件渲染]
                                     │ (桥接 rx.call_script / CustomEvent)
                                     ▼
[Reflex Python 后端 State] (提供 push/retrieve API)
```
### 4.2 核心难点与解决思路
*   **难点**：纯前端修改 `localStorage` 后，React 不会自动重新渲染 UI。
*   **解决思路**：设计一个隐藏的 `rx.State` 变量（如 `_pcache_trigger: int`）。前端 JS 执行写入操作后，通过 `CustomEvent` 向后端发送一个极轻量的信号触发该变量自增，从而强制 React 重新渲染，读取到最新的 `localStorage` 值。
## 5. 功能规格说明 (API 设计)
### 5.1 Python 包装层 API (`PersistentVar`)
```python
# 定义变量
AppNotice = PersistentVar(key="app_global_notice", default_value="默认公告")
# 1. 前端读：直接绑定到 UI 组件
rx.text(AppNotice.value)
# 2. 前端写：绑定到前端事件 (如 on_change)
rx.input(on_change=UserDraft.set())
# 3. 后端写前端：后端业务逻辑中调用
yield AppNotice.push("数据库最新公告")
# 4. 后端读前端：后端业务逻辑中调用，并指定回调函数
yield AppNotice.retrieve(callback_name="state.receive_data")
```
### 5.2 初始化组件
```python
# 在应用根节点注入初始化脚本，注册所有 PersistentVar 及其默认值
init_pcache(vars=[AppNotice, UserDraft])
```
## 6. 实现细节与代码结构 (AI-Coding 指南)
### 6.1 目录结构
```text
reflex_pcache/
├── __init__.py
├── frontend_script.py  # 存放注入前端的 TS/JS 字符串
└── var.py              # Python 包装器核心逻辑
```
### 6.2 前端脚本实现 (`frontend_script.py`)
编写注入前端的 JS 逻辑，负责管理 `localStorage` 并与 Reflex 事件系统通信。
*   `window.__pcache.init(key, default)`：初始化，若无值则写入默认值。
*   `window.__pcache.get(key)`：读取本地值。
*   `window.__pcache.set(key, value)`：写入本地，并触发 `reflex_event` 通知后端更新触发器。
*   `window.__pcache.retrieve(key, callback_name)`：读取本地值，并触发 `reflex_event` 将值传给后端指定回调。
### 6.3 Python 包装器实现 (`var.py`)
实现 `PersistentVar` 类，利用 `rx.Var.create` 生成前端表达式，利用 `rx.call_script` 执行前端动作。
*(详细伪代码及结构已在之前沟通中确认，需保持 `set`, `push`, `retrieve` 的逻辑闭环)*
## 7. 边界与异常处理
1. **存储容量超限**：浏览器 `localStorage` 通常限制为 5MB。`__pcache.set` 时需加入 `try...catch`，捕获 `QuotaExceededError`，并在控制台打印警告，不中断程序运行。
2. **JSON 序列化安全**：所有的值在写入前必须经过 `JSON.stringify`，读取时经过 `JSON.parse`，防止存入 `undefined` 导致解析报错。若解析失败，回退到 `default_value`。
3. **渲染时机问题**：首次渲染时若 `window.__pcache` 尚未初始化，`get` 方法应返回默认值兜底，避免前端 JS 报错白屏。
## 8. 验收标准
1. **首屏秒开**：断网状态下刷新页面，页面能立刻显示上次保存的 `localStorage` 数据，不白屏。
2. **前端独立写入**：在输入框中输入内容触发 `set()`，`localStorage` 中的值实时更新，不产生 WebSocket 网络请求（或仅有极小的触发器更新请求），UI 正确刷新。
3. **后端推送更新**：点击后端按钮触发 `push()`，前端 UI 立即更新为新值，刷新页面后新值依然存在。
4. **后端拉取数据**：触发 `retrieve()` 后，后端对应的 `callback` 函数能正确接收到前端 `localStorage` 中的数据。
