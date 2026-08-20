# reflex-client-persist-var
**为 [Reflex](https://reflex.dev) 提供基于浏览器 `localStorage` 的持久化前端状态管理。**
开发`reflex-client-persist-var` 的灵感来自于[ClientStateVar](https://buridan-ui.reflex.run/docs/resources/client-state-var)。`ClientStateVar` 将状态保存在 React 的 `useState` 中——而 `useState` 的状态在每次页面刷新时都会被清除。  
`reflex-client-persist-var` 将状态存储在 `localStorage` 中，因此其值在重新加载、断线甚至重启后依然存在，从而实现真正的**首屏即时加载（"秒开"）**体验，**无需 WebSocket 往返通信**。
## 优势
1. 持久化：写入浏览器 `localStorage`，数据是持久化落盘存储。适合用户偏好、草稿、缓存等需要长期留存的场景。
2. 持久化附带优势：加载时直接应用持久化数据，首屏零网络开销。
3. 跨标签页数据共享
4. 完整的后端读写能力

## 操作
| 操作 | 方向 | 网络开销 |
|---|---|---|
| `var.value` | 从 `localStorage` 渲染 | 无 |
| `var.set` / `var.set_value(v)` | 前端事件 → `localStorage` | 一次微小通知（见下文） |
| `var.push(value)` | 后端 → `localStorage` | 一次脚本执行 |
| `var.retrieve(callback)` | `localStorage` → 后端 | 一次往返通信 |
| `var.clear()` | `clear()` → 删除 `localStorage`的`key` → 回落默认值 | 无 |

## 安装
```bash
uv add reflex-client-persist-var
```
> 要求 `reflex >= 0.9.0, < 1.0`。本库重度使用 Reflex 0.9 的未公开内部 API
> （`VarData` / `ArgsFunctionOperationBuilder` / `run_script` / `StateProxy` 等），
> 升级 Reflex 前请先验证兼容性。
## 快速开始
```python
import reflex as rx
from reflex_client_persist_var import PersistentVar, PersistentState, init_persist_var
AppNotice = PersistentVar.create(key="app_global_notice", default_value="默认公告")
UserDraft = PersistentVar.create(key="user_draft", default_value="")
class State(rx.State):
    retrieved: str = "(暂无内容)"
    @rx.event
    def push_notice(self):
        yield AppNotice.push("数据库最新公告")          # 写 + 自动重渲染
    @rx.event
    def pull_notice(self):
        yield AppNotice.retrieve(callback=self.receive)  # 前端 -> 后端
    @rx.event
    def receive(self, value: str):
        self.retrieved = str(value)
def index():
    return rx.fragment(
        init_persist_var([AppNotice, UserDraft]),        # 初始化 + 填充默认值
        rx.text(AppNotice.value),                   # 1. 前端读取
        rx.input(on_change=[UserDraft.set, PersistentState.persist_bump]),  # 2. 前端写入 + 刷新
        rx.button("Push", on_click=State.push_notice),
        rx.button("Pull", on_click=State.pull_notice),
    )
app = rx.App()
app.add_page(index)
```
## API
### `PersistentVar.create(key, default_value=None)`
创建一个持久化变量。`key` 会以 `client-persist-var:` 为前缀进行命名空间隔离，因此永远不会与你应用自身的 `localStorage` 条目发生冲突。  
`default_value` 既是在键缺失或损坏时返回的回退值，**也是**首次运行时写入 `localStorage` 的初始值。  
注意：`PersistentVar` 是 frozen dataclass，必须通过 `PersistentVar.create(...)` 构造，直接 `PersistentVar(key=...)` 会抛出 `TypeError`。
### `.value` *(属性)*
一个在客户端执行 `window.__persist.get(key)` 的 `Var`。可将其绑定到任何组件（包括 children 位置，如 `rx.text(AppNotice.value)`）。首屏直接从 `localStorage` 读取——无需后端参与；键缺失或损坏时返回注册的默认值。默认值会在首帧渲染**之前**同步注册（作为 hook 随访问器注入页面函数体），因此首帧即生效，无需等待挂载。

> **SSR / 预渲染（hydration）**：生产构建（`reflex run --env prod`）默认开启服务端
> 预渲染。服务器上没有 `localStorage`，因此 SSR 标记中 `value` 呈现为**默认值**；而
> 客户端首帧 hydration 期间直接读取已持久化的值。两者只有在该 key 从未被写入时才
> 恰好一致——否则首帧可能出现一次默认值闪现，并伴随一次 React hydration 差异提示
> （最终以客户端为准，后续渲染一致）。这是"首帧即读"设计的固有取舍；开发模式
> （默认关闭预渲染）不受影响。
### `.set`（属性）/ `.set_value(value=...)`
一个前端事件链 Var。可附加到触发器上：
```python
rx.input(on_change=[UserDraft.set, PersistentState.persist_bump])  # 转发事件参数 + 刷新
rx.button(on_click=[ThemeVar.set_value("dark"), PersistentState.persist_bump])  # 写入字面量 + 刷新
```
> **注意**：`set` 是**属性**而非方法。`on_change=UserDraft.set` 是正确写法；  
写成 `UserDraft.set()`（带括号）会对返回的 Var 再调用一次，生成非法事件链，编译期抛出 `ValueError: Invalid event chain`。
> **重要**：`set` / `set_value` 只写 `localStorage`，**不会**产生 React 状态变化——单独
> 使用时（不带 bump），页面其它位置通过 `.value` 渲染该值的组件不会自动刷新。
> 需要立即刷新请拼接 `PersistentState.persist_bump`（如上例）。非受控输入框自身的
> 显示不依赖 bump，但受控输入（`value=var.value`）必须拼接 bump 才能正常输入。
### `.push(value, bump=None)`
从**后端事件处理器**中将 `value` 写入客户端的 `localStorage`。必须使用 `yield` 或 `return`。**重渲染事件（`PersistentState.persist_bump`）会自动追加**到写事件链末尾，写入后页面立即刷新——无需手动传任何事件：
```python
@rx.event
def handler(self):
    yield AppNotice.push("updated")  # 写 + 自动重渲染
```
`bump` 参数可覆盖默认的重渲染事件（传入任意 `EventHandler`，如 `YourState.persist_bump`；实例级 `self.persist_bump` 也会被库自动还原处理）。
### `.retrieve(callback=handler)`
将当前 `localStorage` 的值发送到后端处理器。`callback` 是**处理器对象本身**（而非点分字符串）；实例级写法 `self.receive` 在 Reflex 0.9.8 下会被包成 `functools.partial`，库已自动还原，回调不会再被前端编译器静默丢弃：
```python
@rx.event
def handler(self):
    yield AppNotice.retrieve(callback=self.receive)
@rx.event
def receive(self, value: str):
    ...
```
### `.clear(bump=None)`
从 `localStorage` 中移除该键（由后端发起）。同 `.push()`，重渲染事件自动追加。
### `init_persist_var(vars)`
（不可见的）初始化器。在使用 `PersistentVar` 的任何页面根部附近包含一次。挂载时，如果某个已注册的键为空，它会把默认值实际写入 `localStorage`（首次运行的种子落盘）。桥接器与默认值注册由每个访问器通过 `VarData` 自动携带，即使不包含此组件页面也不会白屏——但它让默认值在首次运行时物理落盘，建议始终包含。
```python
init_persist_var([AppNotice, UserDraft])   # 或单个变量：init_persist_var(AppNotice)
```
### `PersistentState`
库级共享状态（固定 `rx.State` 类，自动注册），维护一个版本计数器 `persist_rev` 和事件 `persist_bump`（递增计数器）。它是所有 `PersistentVar` 组件的**订阅锚点**（见下文「为什么需要重新渲染触发器？」）。通常你不需要直接使用它——`push` / `clear` 已自动 bump——但以下场景会用到：
```python
from reflex_client_persist_var import PersistentState
# 前端事件链：写完 localStorage 后立即刷新（如 rx.input 的 on_change）
rx.input(on_change=[UserDraft.set, PersistentState.persist_bump])
# 后端任意事件里手动刷新
yield PersistentState.persist_bump
```
## 为什么需要重新渲染触发器？（重要）
写入 `localStorage` **并不会**触发 React 重新渲染——这正是 PRD 中指出的核心难点。`localStorage` 只是数据源，React 只在 state 变化时重渲染页面，所以写入后所有 `PersistentVar.value` 表达式不会自动重新求值，UI 不会更新（刷新页面或切换 Tab 触发重渲染后才会看到新值）。

因此重渲染被设计为**库的核心能力**，分两个层面实现：

1. **订阅（静态层）**：`PersistentVar.value` 的渲染表达式不只是 `window.__persist.get(key)`，还额外与一个恒真条件 `PersistentState.persist_rev >= 0` 做逻辑与。这使得编译产物中该组件会 `useContext` 订阅 `PersistentState` 并读取 `persist_rev`。React 的 `useContext` 语义保证：**只要 `PersistentState` 有任何 delta（context 值变化），所有订阅组件无条件重渲染**（不受 `memo` 影响）。
2. **bump（动态层）**：写操作产生 delta——`push` / `clear` 自动在事件链末尾追加 `PersistentState.persist_bump`（后端写 localStorage 的 `_call_function` 执行完毕后，事件回发后端递增 `persist_rev`）；前端 `set` 由调用方把 `PersistentState.persist_bump` 拼进 `on_change` 链。

bump 到达后 `persist_rev` 产生真实 delta，订阅组件重渲染，`window.__persist.get(key)` 被重新求值，界面即显示刚写入/清除的值。

> **为什么不用隐藏组件 / StorageEvent 方案？** 早期版本在页面根部渲染基于 `rx.ComponentState` 的隐藏计数器，并在写操作后 `yield persist_bump.State.bump`——该事件会被**静默丢弃**（`ComponentState.create()` 每次生成带全局序号的新动态 State 子类，事件不在注册表，回发时 `KeyError`）。后续尝试过"手动派发 `StorageEvent` 欺骗 Reflex 的 storage 监听器"，同样无效：Reflex 前端的 `handleStorage` 只处理 `storage_to_state_map` 里的 key，而该映射**只包含声明了 `client_storage sync=True` 的 backend var**——`PersistentVar` 是纯前端 localStorage 直读、无 backend var，key 不在映射中，事件被 `if (storage_to_state_map[e.key])` 直接过滤。更本质的是：即使 storage 事件被处理，`update_vars_internal` 只更新特定 var，也无法驱动"不订阅任何 state"的组件重渲染。**唯一可靠的路径是让读 `PersistentVar.value` 的组件真正订阅一个 backend state**——这就是 `PersistentState` 作为订阅锚点的原因。
>
> 若在组件树之外修改了 `localStorage`（如浏览器控制台、其他标签页），仍然需要刷新或切换 Tab 才能看到新值——React 不知道外部变化（storage 事件跨标签页由 Reflex 原生处理，但同样只针对 sync var）。
## 健壮性
所有边缘情况（PRD §7）均在注入的 JS 中处理：
-   **配额超限 / 存储禁用** —— `__persist.set` 会吞掉 `QuotaExceededError`（以及隐私模式下的 `SecurityError`），在会话期间回退到内存中的 Map，并记录一条警告。永不抛出异常。
-   **JSON 损坏** —— `__persist.get` 在任何 `JSON.parse` 失败时都会回退到注册的默认值；永不返回 `undefined`。
-   **首屏竞态条件** —— 桥接器与每个 key 的默认值**注册**（`__persist.register`）都以 `VarData` hook 的形式随访问器注入页面函数体，在首帧渲染之前同步执行。因此即使 `init_persist_var` 尚未挂载、`localStorage` 为空，首帧 `.value` 也会返回注册的默认值，而不是空白或异常。`init_persist_var` 挂载后的 `useEffect` 仅负责把默认值实际写入 `localStorage`（种子落盘）。
-   **类型约束（使用须知）** —— 存入 `localStorage` 的 JSON 值应与创建时 `default_value` 的类型保持一致。若类型不符（例如声明为 `str` 却写入了 `dict`），`.value` 会按存储内容原样返回，把对象传给 `rx.text` 之类只接受字符串子节点的组件将触发 React 渲染错误。
## 演示
`client_persist_demo` 覆盖了 PRD §8 的验收标准，每个卡片都带**数据流转箭头**，并用**颜色区分值来源**（绿色 = 本地值 localStorage，琥珀色 = 服务端值 state）：
1.  **首屏即时加载** —— 通知直接从 `localStorage` 渲染（零后端往返），刷新/离线依然显示。

<details>
<summary>展开查看：示例1 首屏读取 · demo 代码</summary>

```python
# 1. 创建持久化变量（key 自动加 client-persist-var: 命名空间）
AppNotice = PersistentVar.create(key="app_global_notice", default_value="默认公告")

# 2. 直接渲染：首帧从 localStorage 读取，零后端往返
rx.text(AppNotice.value, size="6", weight="bold")
```

</details>

2.  **前端写入 + 复杂类型** —— 字符串 Tab 实时直写；字典/列表 Tab 用「输入框 + 添加按钮 + Tag」交互式构建，点击 Tag 出现删除按钮，改动经后端校验后 `push` 持久化。

<details>
<summary>展开查看：示例2 前端写入 · demo 代码</summary>

```python
UserDraftStr  = PersistentVar.create(key="user_draft_str", default_value="")
UserDraftDict = PersistentVar.create(key="user_draft_dict", default_value={"标题": "笔记"})

# 字符串：击键即写 localStorage，随后 bump 强制重渲染
rx.input(
    value=UserDraftStr.value,
    on_change=[UserDraftStr.set, PersistentState.persist_bump],
)

# 复杂类型（dict/list）：后端校验后 push 持久化 + 自动 bump
@rx.event
def add_dict_tag(self):
    ...
    yield UserDraftDict.push(dict(self.draft_dict))
```

</details>

3.  **后端推送（含对照）** —— 按钮推送新通知，同时更新一个传统后端 `state.var`，并排展示「服务端值（刷新即重置）vs 本地值（刷新仍在）」。

<details>
<summary>展开查看：示例3 后端推送 · demo 代码</summary>

```python
@rx.event
def push_notice(self):
    new_notice = f"公告 #{self._notice_seq} · {time.strftime('%H:%M:%S')}"
    yield AppNotice.push(new_notice)  # 写 localStorage + 自动追加 bump 重渲染
```

</details>

4.  **后端检索** —— 按钮把本地值拉取到后端并回显。

<details>
<summary>展开查看：示例4 后端拉取 · demo 代码</summary>

```python
@rx.event
def retrieve_notice(self):
    yield AppNotice.retrieve(callback=self.receive_data)  # localStorage -> 后端

@rx.event
def receive_data(self, value: str):
    self.retrieved_value = str(value)  # 后端回显
```

</details>

5.  **后端清除** —— 清除 key 后值回落到默认值。

<details>
<summary>展开查看：示例5 后端清除 · demo 代码</summary>

```python
@rx.event
def clear_notice(self):
    yield AppNotice.clear()  # 删除 key，值回落默认值（自动 bump 重渲染）
```

</details>

另外：明暗外观跟随系统（`appearance="inherit"`）；每次后端操作限流 ≥ 1 秒，超频以 toast 提示；页面右上角提供 GitHub 仓库链接；标题下方直接展示库的简介与优势，随后以默认折叠、轻视觉重量的形式提供「应用场景速览」「能力边界提醒」「为什么写入后页面会立即更新？」三组说明（展开可见详情）。
## 应用场景与能力边界
> 持久化状态不只是「不丢」，它重塑了前端状态管理的形态。以下场景全部基于本库已实现的能力（`.value` 首帧直读、`.set` 前端直写、`.push` / `.retrieve` / `.clear` 后端读写），demo 页面标题下方有对应的速览折叠区（另有直接展示的简介与优势、右上角 GitHub 链接）。


### 1. UI 偏好与个性化设置持久化
- **原生痛点**：深色模式、侧边栏状态、表格列配置、字体大小等 UI 设置，要么依赖用户登录后存数据库，要么刷新页面就重置；且首屏会先渲染默认样式，等后端状态同步后再切换，出现明显的「主题闪烁」。
- **方案价值**：设置项直接存入 `localStorage`，首屏同步读取渲染，零网络延迟；无需登录即可跨会话持久化，刷新、重启浏览器都不丢失。
- **典型场景**：深浅主题切换、侧边栏收起 / 展开记忆、表格列显隐配置、字体大小与缩放偏好、界面语言选择。

### 2. 表单草稿自动保存，防止内容丢失
- **原生痛点**：长表单、富文本编辑、评论输入等场景，用户误刷新、网络断线重连、浏览器意外关闭后，输入内容全部清空；且逐字同步后端会产生大量 WebSocket 请求，网络差时输入卡顿明显。
- **方案价值**：输入内容实时写入本地 `localStorage`，写入完全不依赖网络，无延迟；页面重开、刷新、断连重连后内容自动恢复。需要永久保存时，后端可通过 `retrieve()` 将本地草稿拉取并存入数据库，兼顾输入体验和数据备份。
- **典型场景**：长表单填写、文章 / 工单编辑、聊天输入框、复杂筛选条件暂存、问卷填写中途退出恢复。

### 3. 首屏「秒开」与离线内容兜底
- **原生痛点**：Reflex 原生渲染依赖 WebSocket 连接建立 + 后端状态同步，弱网、服务器负载高时首屏白屏时间长；离线状态下页面完全无法展示有效内容。
- **方案价值**：核心展示内容优先从 `localStorage` 读取渲染，首帧即可呈现内容，无需等待后端往返；即使后端不可用、网络离线，也能展示上次缓存的数据，避免完全白屏。
- **典型场景**：首页公告 / 通知、仪表盘缓存数据、上次访问的列表筛选结果、离线可用的工具类页面。

### 4. 游客态用户的行为数据留存
- **原生痛点**：未登录的游客用户，后端无法关联身份，购物车、浏览历史、收藏等状态无法持久化，用户流失率高；强制登录又会大幅提高使用门槛。
- **方案价值**：无需登录即可将游客行为数据持久化在本地，跨会话、跨标签页生效；用户登录后再一键 `retrieve()` 同步到后端账号，平滑过渡。
- **典型场景**：电商游客购物车、内容站浏览历史、搜索记录、匿名收藏夹、临时筛选偏好。

### 5. 高频轻量状态本地化，降低后端压力
- **原生痛点**：弹窗已读状态、引导提示关闭状态、折叠面板展开 / 收起、列表每页条数等细碎状态，改动频繁、业务价值低，但全走后端状态会产生大量无效 WebSocket 通信，占用服务端内存与带宽。
- **方案价值**：这类状态完全下沉到前端 `localStorage` 管理，不占用后端资源；仅在需要同步到账号时再回传后端。
- **典型场景**：新手引导已读标记、通知弹窗关闭状态、列表分页大小、折叠菜单状态、搜索历史记录。

### 6. 跨标签页的状态共享
- **原生痛点**：Reflex 每个标签页是独立的 WebSocket 连接，后端状态默认不互通；用户多开标签页时，设置、草稿等状态不一致，体验割裂。
- **方案价值**：同源标签页共享同一份 `localStorage` 数据，一个标签页修改后，其他标签页刷新 / 切换 Tab 即可同步，实现成本极低。若需要实时刷新，可监听 `storage` 事件并调用 `persist_bump`（见上文「为什么需要重新渲染触发器？」）。
- **典型场景**：多标签页编辑同一份草稿、全局主题 / 租户设置跨窗口生效、购物车数据多页面共享。

### 7. 断线重连的体验平滑过渡
- **原生痛点**：网络波动导致 WebSocket 断开重连时，前端临时状态可能丢失，页面出现短暂重置，用户正在操作的内容中断。
- **方案价值**：核心操作状态存在 `localStorage`，重连过程中 UI 不会丢失内容；重连成功后可选择通过 `retrieve()` 将本地数据同步回后端，用户无感知。
- **典型场景**：弱网环境下的表单填写、实时编辑场景、工业 / 监控类后台系统。

### 能力边界提醒
1. **容量**：`localStorage` 单域名容量约 5MB，不适合存储大量二进制数据或长列表。
2. **刷新时机**：跨标签页数据天然共享，但 UI 不会自动实时刷新——需刷新 / 切换 Tab，或手动监听 `storage` 事件调用 `persist_bump`。
3. **非安全存储**：数据存储在前端，可被用户篡改，不适合存放敏感数据、权限校验类状态。
## 许可证
本软件以 **Apache License 2.0** 为主体许可，并附加商业授权条款（非商业免费、商业盈利需按日支付授权费）。完整条款见 [LICENSE](LICENSE) 文件。
### 致谢
[reflex](https://reflex.dev)  
[BurdianUI](https://buridan-ui.reflex.run/)  
各位帮助到我的AI
### 商业授权附加条款
- 非商业用途免费：本软件对个人学习、非盈利性组织及未产生任何直接或间接商业收入的使用者完全免费。
- 盈利行为定义：凡通过本软件（包括但不限于直接使用、二次开发、集成至其他产品或服务中）产生直接或间接收入的行为，均视为商业盈利行为。包括但不限于：销售本软件、销售基于本软件开发的衍生品、利用本软件提供付费服务、利用本软件进行内部运营以降低成本等。
- 每日授权费：若使用者发生上述盈利行为，有义务向版权所有者（[见下方alipay收款码]）支付商业授权费，标准为：使用者当地350ml可口可乐零售价 / 每个自然日。

![alipay收款码](project-docs/支付宝收款码.jpg)

