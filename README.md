# reflex-pcache
**为 [Reflex](https://reflex.dev) 提供基于浏览器 `localStorage` 的持久化前端状态管理。**
`reflex-pcache` 是 Reflex 实验性 `ClientStateVar`（`reflex.experimental.client_state`）的 `localStorage` 后备方案。`ClientStateVar` 将状态保存在 React 的 `useState` 中——而 `useState` 的状态在每次页面刷新时都会被清除。`reflex-pcache` 将状态存储在 `localStorage` 中，因此其值在重新加载、断线甚至重启后依然存在，从而实现真正的**首屏即时加载（"秒开"）**体验，**无需 WebSocket 往返通信**。
| 操作 | 方向 | 网络开销 |
|---|---|---|
| `var.value` | 从 `localStorage` 渲染 | 无 |
| `var.set()` | 前端事件 → `localStorage` | 一次微小通知（见下文） |
| `var.push(value)` | 后端 → `localStorage` | 一次脚本执行 |
| `var.retrieve(callback)` | `localStorage` → 后端 | 一次往返通信 |
## 安装
```bash
uv add reflex-pcache
```
> 要求 `reflex >= 0.9.2`。
## 快速开始
```python
import reflex as rx
from reflex_pcache import PersistentVar, init_pcache
AppNotice = PersistentVar(key="app_global_notice", default_value="默认公告")
UserDraft = PersistentVar(key="user_draft", default_value="")
class State(rx.State):
    # (1) 重新渲染触发器 —— 见下文“为什么需要触发器？”。
    _pcache_trigger: int = 0
    retrieved: str = "(暂无内容)"
    @rx.event
    def pcache_bump(self):
        self._pcache_trigger += 1
    @rx.event
    def push_notice(self):
        yield AppNotice.push("数据库最新公告")          # 后端 -> 前端
    @rx.event
    def pull_notice(self):
        yield AppNotice.retrieve(callback=self.receive)  # 前端 -> 后端
    @rx.event
    def receive(self, value: str):
        self.retrieved = str(value)
def index():
    return rx.fragment(
        init_pcache([AppNotice, UserDraft]),          # 初始化 + 填充默认值
        rx.text(AppNotice.value),                    # 1. 前端读取
        rx.input(on_change=UserDraft.set()),         # 2. 前端写入
        rx.button("Push", on_click=State.push_notice),
        rx.button("Pull", on_click=State.pull_notice),
    )
app = rx.App()
app.add_page(index)
```
## API
### `PersistentVar.create(key, default_value=None)`
创建一个持久化变量。`key` 会以 `pcache:` 为前缀进行命名空间隔离，因此永远不会与你应用自身的 `localStorage` 条目发生冲突。`default_value` 既是在键缺失或损坏时返回的回退值，**也是**首次运行时写入 `localStorage` 的初始值。
### `.value` *(属性)*
一个在客户端执行 `window.__pcache.get(key)` 的 `Var`。可将其绑定到任何组件：`rx.text(AppNotice.value)`。首屏直接从 `localStorage` 读取——无需后端参与。
### `.set` / `.set_value(value=...)`
一个前端事件链 Var。可附加到触发器上：
```python
rx.input(on_change=UserDraft.set)          # 原样转发事件参数
rx.input(on_change=UserDraft.set())        # 等效，括号可选
rx.button(on_click=ThemeVar.set_value("dark"))   # 写入字面量
```
### `.push(value)`
从**后端事件处理器**中将 `value` 写入客户端的 `localStorage`。必须使用 `yield` 或 `return`：
```python
@rx.event
def handler(self):
    yield AppNotice.push("updated")
```
### `.retrieve(callback=handler)`
将当前 `localStorage` 的值发送到后端处理器。`callback` 是**处理器对象本身**（而非点分字符串）：
```python
@rx.event
def handler(self):
    yield AppNotice.retrieve(callback=self.receive)
@rx.event
def receive(self, value: str):
    ...
```
### `.clear()`
从 `localStorage` 中移除该键（由后端发起）。
### `init_pcache(vars)`
（不可见的）初始化器。在使用 `PersistentVar` 的任何页面根部附近包含一次。它会注入 `window.__pcache` 桥接器，并在挂载时，如果某个已注册的键为空，则用其默认值填充它。
```python
init_pcache([AppNotice, UserDraft])   # 或单个变量：init_pcache(AppNotice)
```
## 为什么需要重新渲染触发器？（重要）
写入 `localStorage` **并不会**触发 React 重新渲染——这正是 PRD 中指出的核心难点。因此，`reflex-pcache` 期望**宿主应用**在支持读取 `.value` 的页面所对应的 State 中，拥有一个微小的触发器计数器和一个 `pcache_bump` 事件：
```python
class State(rx.State):
    _pcache_trigger: int = 0
    @rx.event
    def pcache_bump(self):
        self._pcache_trigger += 1
```
然后，对于必须立即更新屏幕的前端写入，将写入操作与一个 bump 链接起来：
```python
def write_and_refresh(var):
    return [var.set(), State.pcache_bump]
rx.input(on_change=write_and_refresh(UserDraft))
```
`push()` 可以从同一个处理器中自行 bump。该计数器从不显示；它的存在仅仅是为了使渲染失效，从而让 `.value` 表达式重新读取 `localStorage`。（库无法提供全局的 `State`，因此这一一次性设置存在于你的应用中——`pcache_demo` 展示了一个完整、可复制粘贴的示例。）
## 健壮性
所有边缘情况（PRD §7）均在注入的 JS 中处理：
-   **配额超限 / 存储禁用** —— `__pcache.set` 会吞掉 `QuotaExceededError`（以及隐私模式下的 `SecurityError`），在会话期间回退到内存中的 Map，并记录一条警告。永不抛出异常。
-   **JSON 损坏** —— `__pcache.get` 在任何 `JSON.parse` 失败时都会回退到注册的默认值；永不返回 `undefined`。
-   **首屏竞态条件** —— 如果 `.value` 在 `init_pcache` 挂载之前被求值，桥接器仍会被注入（每个访问器都通过 `VarData` 携带桥接器），读取操作会返回默认值而不是抛出异常。
## 演示
该演示涵盖了 PRD §8 的所有四项验收标准：
1.  **首屏即时加载** —— 刷新/离线时，通知依然显示。
2.  **前端独立写入** —— 在草稿框中输入会实时更新 `localStorage` 和 UI（无需为数据调用后端）。
3.  **后端推送** —— 按钮会推送一条在重新加载后依然存在的新通知。
4.  **后端检索** —— 按钮会将本地值拉取到后端并回显。
## 开发与打包
本包遵循官方的 `reflex component` 布局。要构建可分发包：
```bash
reflex component build      # 生成 dist/*.tar.gz 和 dist/*.whl
twine upload dist/*         # 或：uv publish dist/*
```
## 许可证
Apache-2.0
### 许可证附加条款
- 非商业用途免费：本软件对个人学习、非盈利性组织及未产生任何直接或间接商业收入的使用者完全免费。
- 盈利行为定义：凡通过本软件（包括但不限于直接使用、二次开发、集成至其他产品或服务中）产生直接或间接收入的行为，均视为商业盈利行为。包括但不限于：销售本软件、销售基于本软件开发的衍生品、利用本软件提供付费服务、利用本软件进行内部运营以降低成本等。
- 每日授权费：若使用者发生上述盈利行为，有义务向版权所有者（[见下方alipay收款码]）支付商业授权费，标准为：使用者当地350ml可口可乐零售价 / 每个自然日。

![alipay收款码](project-docs/支付宝收款码.jpg)

