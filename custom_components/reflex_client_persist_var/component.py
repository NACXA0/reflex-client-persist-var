""":func:`init_persist_var` 初始化组件。

该组件在页面上不渲染任何内容。它的职责是在应用首次挂载时，把每一个已注册的
:class:`PersistentVar` 以其默认值 *播种*（seed）进 ``localStorage``。

注意：``window.__persist`` 桥接器 —— 以及支撑首帧回退的同步默认值 *注册* ——
是由每个访问器 Var 通过 VarData 携带的（参见 :mod:`reflex_client_persist_var.var`），
因此任何渲染了 ``.value`` / ``.set`` / ... 表达式的页面都会带上它，即使没有
本组件。:func:`init_persist_var` 额外提供的，是首次运行时把默认值真正写入
``localStorage``。

它之于 ``localStorage`` 的作用，正如把 ``ClientStateVar`` 本身嵌入组件树之于
``useState`` 的作用：把它声明在组件树中，才使对应的 hook 得以触发。
"""

from __future__ import annotations

from typing import Iterable

import reflex as rx
from reflex.vars.base import LiteralVar, Var
from reflex.vars.base import VarData
from reflex.utils.imports import ImportVar

from .frontend_script import PERSIST_BRIDGE, PERSIST_GLOBAL_REF
from .var import PersistentVar

# 挂载时播种 hook 需要用到 ``useEffect`` 的导入。
_USE_EFFECT_IMPORT = {"react": [ImportVar(tag="useEffect")]}


def _js_literal(value) -> str:
    """把 Python 默认值（或一个 Var）渲染成 JS 字面量表达式。"""
    return str(LiteralVar.create(value))


class PersistVarInit(rx.Fragment):
    """不可见组件：引导 ``window.__persist`` 并播种默认值。

    它的贡献纯粹是副作用：注入 ``window.__persist`` 桥接脚本，并在挂载时
    把每个已注册 key 的默认值写入存储。

    继承自 ``rx.Fragment``（``library="react"``，``tag="Fragment"``）而不是裸
    ``tag = "span"``：Reflex 0.9 的编译器只有在设置 ``_is_tag_in_global_scope``
    时才会把 tag 作为字符串字面量加引号，因此普通 HTML tag 会被渲染为不带引号
    的标识符（``jsx(span,{})``）且没有任何 import，运行时直接崩溃并抛出
    ``ReferenceError: span is not defined``。而 Fragment 由编译器自身从 ``react``
    导入，所以这个不可见渲染目标总是已定义的。
    """

    def add_custom_code(self) -> list[str]:
        """把完整的桥接定义注入页面（幂等）。"""
        return [PERSIST_BRIDGE]

    def add_imports(self) -> dict[str, ...]:
        """为挂载 hook 导入 ``useEffect``。"""
        return _USE_EFFECT_IMPORT

    def add_hooks(self) -> list[str | Var]:
        """挂载时，把每个已注册 key 以默认值播种。

        在首次绘制后仅执行一次。当 key 已有值时 ``init`` 是空操作，因此
        重新挂载和热重载都是安全的。

        首帧 *渲染* 并不依赖此 hook：访问器 Var 会通过 VarData hook 同步注册
        各自的默认值（参见 :mod:`reflex_client_persist_var.var`），这些 hook
        在首次绘制之前就会执行。此挂载 hook 只是把种子值持久化到
        ``localStorage``。
        """
        pvars: Iterable[PersistentVar] = getattr(self, "_persist_vars", [])
        if not pvars:
            return []

        calls = ", ".join(
            f"{PERSIST_GLOBAL_REF}.init({_js_literal(pv._key)}, {_js_literal(pv._default)})"
            for pv in pvars
        )
        # 空依赖数组的 useEffect 只在挂载时执行恰好一次。
        return [
            "useEffect(() => { " + calls + "; }, [])",
        ]



def init_persist_var(vars: Iterable[PersistentVar] | PersistentVar,) -> rx.Component:
    """创建（不可见的）``reflex_client_persist_var`` 初始化器。

    把它放在任何使用 :class:`PersistentVar` 的页面根部附近，通常作为第一个
    子元素：:

        def index():
            return rx.fragment(
                init_persist_var([AppNotice, UserDraft]),
                rx.text(AppNotice.value),
                ...
            )

    参数:
        vars: 单个 :class:`PersistentVar`，或它们的可迭代对象。只会读取其中
            的 key 和默认值；返回的组件不渲染任何内容。

    返回:
        一个不可见组件；把它包含在组件树中后，会在挂载时把 ``localStorage``
        的默认值播种。建议在每个读取 ``.value`` 的页面上都放置它，这样默认值
        才会在首次运行时物理落入 ``localStorage``；而首帧回退本身无论有无
        本组件，都由访问器自身的 VarData hook 保证。
    """
    if isinstance(vars, PersistentVar):
        pvars = [vars]
    else:
        pvars = list(vars)

    for pv in pvars:
        if not isinstance(pv, PersistentVar):
            msg = (
                "init_persist_var expects PersistentVar instances, got "
                f"{type(pv).__name__}."
            )
            raise TypeError(msg)

    instance = PersistVarInit.create()
    # 把注册的 vars 暂存到实例上，add_hooks 才能读取它们。
    # ``Component`` 不是冻结的 dataclass，直接设置属性没有问题。
    object.__setattr__(instance, "_persist_vars", pvars)
    return instance
