"""reflex_client_persist_var — 面向 Reflex 的前端持久化变量（localStorage 后端）。

作为 Reflex 实验性 ``ClientStateVar`` 的 localStorage 后备方案。
:mod:`reflex_client_persist_var.var` 提供 :class:`PersistentVar` API，
:mod:`reflex_client_persist_var.component` 提供 :func:`init_persist_var`，
:mod:`reflex_client_persist_var.bump` 提供库级重渲染状态 :class:`PersistentState`。

重渲染是**库的核心能力**：``PersistentVar.value`` 的渲染表达式会隐式订阅
``PersistentState.persist_rev``（编译产物生成 ``useContext``），任何写入
（``push`` / ``clear`` 自动、前端 ``set`` 由调用方拼事件链）都会 bump 该
计数器，产生真实 delta，从而驱动所有读 ``PersistentVar.value`` 的组件重渲染。

快速开始::

    from reflex_client_persist_var import PersistentVar, PersistentState, init_persist_var
    import reflex as rx

    AppNotice = PersistentVar.create(key="app_notice", default_value="默认公告")

    class State(rx.State):
        def push_notice(self):
            yield AppNotice.push("最新公告")  # 写 + 自动重渲染（无需手动 bump）

    def index():
        return rx.fragment(
            init_persist_var([AppNotice]),
            rx.text(AppNotice.value),
            rx.button("推送", on_click=State.push_notice),
        )
"""

from .bump import PersistentState
from .component import init_persist_var
from .var import PersistentVar

__all__ = ["PersistentVar", "PersistentState", "init_persist_var"]

__version__ = "1.0.1"
