"""基于 ``localStorage`` 的持久化前端状态的 Python 封装。

``PersistentVar`` 镜像了 Reflex 实验性 ``ClientStateVar``
（``reflex.experimental.client_state``）的工作方式，但把内存中的 ``useState``
后备存储换成了浏览器的 ``localStorage``。

这一处改动就把纯客户端状态变成了 *长期存活* 的状态：值在刷新、断线甚至重启后
依然存在，实现了 PRD 中描述的“首帧即时加载”体验，完全无需 WebSocket 往返。

用法
----
.. code-block:: python

    from reflex_client_persist_var import PersistentVar, init_persist_var

    AppNotice  = PersistentVar.create(key="app_global_notice", default_value="默认公告")
    UserDraft  = PersistentVar.create(key="user_draft",        default_value="")

    def index():
        return rx.fragment(
            init_persist_var([AppNotice, UserDraft]),
            rx.text(AppNotice.value),                 # 1. 前端读取
            rx.input(on_change=UserDraft.set),        # 2. 前端写入
            rx.button("推送", on_click=State.do_push),
            rx.button("拉取", on_click=State.do_retrieve),
        )

    class State(rx.State):
        @rx.event
        def do_push(self):
            yield AppNotice.push("数据库最新公告")     # 3. 后端 -> 前端

        @rx.event
        def do_retrieve(self):
            yield AppNotice.retrieve(callback=self.receive_data)  # 4. 后端 <- 前端

        @rx.event
        def receive_data(self, value):
            ...
"""

from __future__ import annotations

import dataclasses
import functools
from typing import Any, Callable, Union

import reflex as rx
from reflex.event import EventHandler, EventSpec, run_script
from reflex.vars.base import LiteralVar, Var
from reflex.vars.function import ArgsFunctionOperationBuilder, FunctionVar

from .bump import PersistentState
from .frontend_script import PERSIST_BRIDGE, PERSIST_GLOBAL_REF

# 哨兵值，用来区分“未传参数”（转发事件参数）和显式传入 ``None``（写入 JS 的
# ``null``）。与 ClientStateVar 的 ``NoValue`` 一致。
_NO_VALUE = object()

# 我们返回的每个访问器 Var 都会挂载携带桥接脚本的 VarData（镜像 ClientStateVar
# 对 VarData 传播的依赖），因此只要任意 PersistentVar 第一次被渲染，桥接器就
# 一定在页面上 —— 包括放在 children 位置的访问器 Var，它们的 VarData 会穿过
# LiteralVar/Bare 管线继续传播。


def _bridge_var(
    js_expr: str,
    var_type: Any = Any,
    *,
    key: str | None = None,
    default: Any = None,
) -> Var:
    """构造一个表达式针对 ``window.__persist`` 执行的 Var。

    返回的 Var 携带一个 VarData hook，把桥接脚本与表达式一起注入。

    当给定 ``key`` 时，会额外增加一个 hook 同步注册该 var 的默认值。hook 在
    页面函数顶部发出 —— 即首次绘制之前 —— 因此 ``get()`` 的默认值回退从第一帧
    起就可用了（PRD §7.3），而不是只能等到 :func:`init_persist_var` 在挂载时
    通过 ``useEffect`` 播种之后。
    """
    hooks: dict = {PERSIST_BRIDGE: None}
    if key is not None:
        # 字典插入顺序保证桥接器（上文已定义）在本次调用之前发出。hook 字符串
        # 按完全匹配去重，因此同一个 key 渲染 N 次也只会注册一次。
        #
        # 加守卫是为了让注册在服务端预渲染（Reflex 0.9）期间变成空操作：那里
        # ``window`` 未定义，桥接器自然还没有被安装。
        hooks[
            f"typeof window !== 'undefined' && {PERSIST_GLOBAL_REF} "
            f"&& {PERSIST_GLOBAL_REF}.register({_js_str(key)}, {_js_str(default)})"
        ] = None
    return Var(
        _js_expr=js_expr,
        _var_data=rx.vars.VarData(  # type: ignore[attr-defined]
            imports={},
            hooks=hooks,
        ),
    ).to(var_type)


def _js_str(value: Any) -> str:
    """把一个 Python 值序列化为字面量 JS 表达式的字符串。"""
    return str(LiteralVar.create(value))


def _normalize_callback(callback: Any) -> Any:
    """把事件回调规范化为 ``format_queue_events`` 可接受的形式。

    Reflex 0.9.8 通过 ``StateProxy.__getattr__`` 解析实例级事件处理器访问
    （``self.receive_data``），它会用 ``functools.partial(func, self)`` 包裹
    处理器。前端编译器（``reflex.utils.format.format_queue_events``）只识别
    ``EventHandler`` / ``EventSpec`` / lambda —— 一个 ``partial`` 会被静默跳过，
    回调事件链随之丢失（``queueEvents([])``），于是 ``retrieve(callback=self.receive_data)``
    永远不会把值派发回后端。

    这里我们把 partial 解包回等价的 ``EventHandler``，让回调能通过编译并抵达
    注册的状态处理器。
    """
    if isinstance(callback, functools.partial):
        fn = callback.func
        instance = callback.args[0] if callback.args else None
        if instance is not None and isinstance(instance, rx.State):
            return EventHandler(fn=fn, state=type(instance))
    return callback


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class PersistentVar(Var):
    """持久化在浏览器 ``localStorage`` 中的 Var。

    实例通过 :meth:`create` 创建。渲染方面（参见 :attr:`value`）它就像普通的
    Reflex ``Var`` 一样使用，同时额外提供五个 localStorage 感知的操作：

    * :attr:`value`                   -- 供渲染读取（无需后端往返）。
    * :attr:`set` / :meth:`set_value` -- 从前端事件触发写入。
    * :meth:`push`                    -- 从后端事件处理器写入。
    * :meth:`retrieve`                -- 读入后端事件处理器。
    * :meth:`clear`                   -- 删除该 key（后端发起）。
    """

    # localStorage 的 key（不含桥接器追加的 ``client-persist-var:`` 命名空间）。
    _key: str = dataclasses.field(default="")
    # 创建时注册的 Python 默认值；用于 JS 侧的回退。
    _default: Any = dataclasses.field(default=None)

    def __hash__(self) -> int:  # Var 实例可哈希；这里保持这一点。
        return hash((self._key, str(self._var_type)))

    # ------------------------------------------------------------------ #
    # 构造
    # ------------------------------------------------------------------ #
    @classmethod
    def create(
        cls,
        key: str,
        default_value: Any = None,
    ) -> "PersistentVar":
        """创建一个持久化前端 var。

        参数:
            key: localStorage 的 key。必须是非空字符串。内部会加上
                ``client-persist-var:`` 命名空间，因此绝不会与宿主应用自己的
                localStorage 条目冲突。
            default_value: 当 key 缺失或损坏时使用的值，也是首次运行时写入
                localStorage 的种子值。

        返回:
            一个 :class:`PersistentVar`。

        异常:
            ValueError: 如果 ``key`` 不是非空字符串。
        """
        if not isinstance(key, str) or not key:
            msg = "key must be a non-empty string."
            raise ValueError(msg)

        default_var = (
            LiteralVar.create(default_value)
            if not isinstance(default_value, Var)
            else default_value
        )

        return cls(
            _js_expr=PERSIST_GLOBAL_REF,
            _var_type=default_var._var_type,
            _var_data=rx.vars.VarData(  # type: ignore[attr-defined]
                imports={},
                hooks={PERSIST_BRIDGE: None},
            ),
            _key=key,
            _default=default_value,
        )

    # ------------------------------------------------------------------ #
    # 1. 前端读取
    # ------------------------------------------------------------------ #
    @property
    def value(self) -> Var:
        """用于渲染当前值的访问器。

        在客户端求值 ``window.__persist.get(key)``，因此首帧直接从
        ``localStorage`` 读取，没有 WebSocket 往返。当 key 缺失或损坏时返回
        已注册的默认值：默认值在首次绘制 *之前* 就同步注册了（通过 VarData
        hook），所以这个回退从第一帧起就生效 —— 甚至早于 ``init_persist_var``
        把种子值写入 ``localStorage``。

        该表达式还带有一个 *订阅依赖*：它与 ``PersistentState.persist_rev >= 0``
        （恒为真）做与运算，这会让宿主组件订阅库级版本计数器（编译器会为它
        发出 ``useContext``）。任何 bump —— ``push`` / ``clear`` 会自动追加一个
        —— 都会产生状态 delta，触发组件重渲染，从而重新执行上面的 localStorage
        读取。这正是写入无需手动刷新就能看到的原理。
        """
        # SSR 安全：在服务器上（没有 ``window``）返回已注册的默认值，这样预渲染
        # 出的标记与客户端首帧一致，hydration 无警告；在客户端则从 localStorage
        # 读取。
        ssr_default = _js_str(self._default)
        get_expr = _bridge_var(
            f"(typeof window !== 'undefined' ? {PERSIST_GLOBAL_REF}.get({_js_str(self._key)}) : {ssr_default})",
            self._var_type,
            key=self._key,
            default=self._default,
        )
        # 恒真订阅依赖（persist_rev 初始为 0，0 >= 0 恒为真）：让所在组件订阅
        # 库级版本计数器。persist_rev 变化产生 delta -> context 变化 -> 组件重渲染。
        dep = PersistentState.persist_rev >= 0
        return (dep & get_expr).to(self._var_type)

    # ------------------------------------------------------------------ #
    # 2. 前端写入
    # ------------------------------------------------------------------ #
    def set_value(self, value: Any = _NO_VALUE) -> Var:
        """返回一个把 ``value`` 写入 localStorage 的事件链 Var。

        挂到前端事件触发上。不带参数时，入站事件参数（例如 ``on_change`` 的
        value）会被原样转发，这正是 PRD §2.1.2 所说的高频写入路径。

        参数:
            value: 要写入的字面量值。省略（默认）时，把触发事件的参数原样
                写入；显式传 ``None`` 则写入 JS 的 ``null``。

        返回:
            一个 ``FunctionVar`` / ``EventChain``，事件触发时执行写入。
        """
        # 原始 setter：绑定到当前 key 的 ``__persist.set``。它只接收剩余的一个
        # 参数（即 value）并写入 localStorage。SSR 安全：服务端预渲染（无
        # ``window``）时产出一个空操作函数，这样 prop 仍是合法的事件处理器，
        # React 不会抛错。
        bound_setter = _bridge_var(
            f"(typeof window !== 'undefined' ? {PERSIST_GLOBAL_REF}.set.bind({PERSIST_GLOBAL_REF}, {_js_str(self._key)}) : (function(){{}}))"
        ).to(FunctionVar)

        if value is _NO_VALUE:
            # 原样转发事件参数：构造 ``(arg) => bound(arg)``。
            arg_name = rx.vars.get_unique_variable_name()
            forwarder = ArgsFunctionOperationBuilder.create(
                args_names=(arg_name,),
                return_expr=bound_setter.call(Var(arg_name)),
            )
        else:
            # 忽略事件参数，始终写入字面量：``() => bound(value)``。
            value_var = LiteralVar.create(value)
            forwarder = ArgsFunctionOperationBuilder.create(
                args_names=(),
                return_expr=bound_setter.call(value_var),
            )

        return forwarder.to(FunctionVar)

    @property
    def set(self) -> Var:
        """把触发参数转发到 localStorage 的事件链 Var。

        是 ``set_value()`` 不带字面量时的便捷形式，即常见的
        ``on_change=MyVar.set`` 用法。

        直接按属性使用（``on_change=MyVar.set``）。若调用它 —— ``MyVar.set()``
        —— 会产生非法的事件链，并在编译期抛出 ``ValueError``。
        """
        return self.set_value()

    # ------------------------------------------------------------------ #
    # 3. 后端 -> 前端推送
    # ------------------------------------------------------------------ #
    def push(
        self,
        value: Any,
        bump: Any = None,
    ) -> list[EventSpec]:
        """从后端把 ``value`` 写入客户端的 localStorage。

        必须在事件处理器中 ``yield``/返回。重渲染触发器
        （``PersistentState.persist_bump``）会被 *自动追加*，因此下一次渲染就会
        通过 :attr:`value` 立即拿到新值 —— 无需手动刷新事件。

        参数:
            value: 要推送的值。
            bump: 可选的默认重渲染触发器覆盖。接受类级 ``EventHandler``
                （``YourState.persist_bump``）或实例级处理器
                （``self.persist_bump``，会自动解包）。传入显式值可替换默认
                bump；省略则使用自动追加的那个。

        返回:
            一个 ``EventSpec`` 列表：先是写入，然后是 bump 事件。
        """
        events: list = [
            run_script(
                f"{PERSIST_GLOBAL_REF}.set({_js_str(self._key)}, {_js_str(value)})"
            )
        ]
        events.append(
            _normalize_callback(bump)
            if bump is not None
            else PersistentState.persist_bump
        )
        return events

    # ------------------------------------------------------------------ #
    # 4. 后端 <- 前端拉取
    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        callback: Union[EventHandler, Callable, None] = None,
        bump: Any = None,
    ) -> EventSpec | list[EventSpec]:
        """把当前 localStorage 的值发送给一个后端事件处理器。

        必须在事件处理器中 ``yield``/返回。回调会收到解析后的值作为第一个参数。

        参数:
            callback: 接收值的 ``EventHandler``（或返回处理器的可调用对象）。
                直接传处理器对象，例如 ``retrieve(callback=self.receive_data)``。
                Reflex 0.9.8 会把实例级访问包裹进 ``functools.partial``；这里
                会自动解包，避免回调被前端编译器静默丢弃。
            bump: retrieve 之后追加的可选触发事件（细节见 :meth:`push`）。

        返回:
            一个 :class:`EventSpec`：在客户端求值读取，并把结果派发给
            ``callback``（如果给了 ``bump`` 还会追加）。
        """
        events: list = [
            run_script(
                f"{PERSIST_GLOBAL_REF}.retrieve({_js_str(self._key)})",
                callback=_normalize_callback(callback),
            )
        ]
        if bump is not None:
            events.append(_normalize_callback(bump))
        return events[0] if len(events) == 1 else events

    # ------------------------------------------------------------------ #
    # 便捷辅助
    # ------------------------------------------------------------------ #
    def clear(self, bump: Any = None) -> list[EventSpec]:
        """从 localStorage 删除该 key（后端发起）。

        与 :meth:`push` 一样，会自动追加一个重渲染触发器
        （``PersistentState.persist_bump``）。

        参数:
            bump: 可选的默认重渲染触发器覆盖（细节见 :meth:`push`）。

        返回:
            一个 ``EventSpec`` 列表：先是 clear，然后是 bump 事件。
        """
        events: list = [run_script(f"{PERSIST_GLOBAL_REF}.clear({_js_str(self._key)})")]
        events.append(
            _normalize_callback(bump)
            if bump is not None
            else PersistentState.persist_bump
        )
        return events
