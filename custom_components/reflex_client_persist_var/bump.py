"""强制重渲染的库级状态。

``PersistentVar.value`` 的渲染表达式会隐式依赖
:attr:`PersistentState.persist_rev`，从而让显示组件真正订阅一个 backend
state（编译产物生成 ``useContext``）。任何 ``persist_rev`` 的变化
（delta）都会触发这些组件重渲染，重新求值 ``localStorage`` 直读表达式。

``push()`` / ``clear()`` 会自动把 :meth:`PersistentState.persist_bump`
追加到事件链，因此用户通常不需要手动处理重渲染。
"""

from __future__ import annotations

import reflex as rx


class PersistentState(rx.State):
    """库级共享状态：版本计数器，驱动所有 ``PersistentVar`` 组件重渲染。

    设计要点：

    - 必须是**固定类名**的普通 ``rx.State``（而非动态生成的类，也不是
      ``mixin``），这样事件名（``...PersistentState.persist_bump``）在前后端
      恒定，注册与路由都走标准路径。
    - 只要任意组件渲染了 ``PersistentVar.value``（其表达式引用了
      ``persist_rev``），本类就会被 Reflex 自动收集并注册为 app state，
      前端生成对应的 ``StateContexts`` 与 ``dispatch``。

    使用::

        from reflex_client_persist_var import PersistentState

        # 后端：任意事件里手动刷新（通常不需要，push/clear 已自动 bump）
        yield PersistentState.persist_bump

        # 前端事件链：写完 localStorage 后立即刷新
        rx.input(on_change=[UserDraft.set, PersistentState.persist_bump])
    """

    #: 版本计数器。每次 :meth:`persist_bump` 递增 1，产生前端 delta。
    #: 不能以下划线开头（backend var 才产生前端 delta 与订阅）。
    persist_rev: int = 0

    @rx.event
    def persist_bump(self) -> None:
        """递增版本计数器，触发所有订阅 ``PersistentVar.value`` 的组件重渲染。"""
        self.persist_rev += 1
