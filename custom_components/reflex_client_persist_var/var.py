"""Python wrapper for persistent, ``localStorage``-backed front-end state.

``PersistentVar`` mirrors the operating mode of Reflex's experimental
``ClientStateVar`` (``reflex.experimental.client_state``) but swaps the
in-memory ``useState`` backing store for the browser's ``localStorage``.

That single change turns the client-only state into *long-lived* state: the
value survives reloads, disconnects and even reboots, enabling the
"first-paint instant load" experience described in the PRD without any
WebSocket round-trip.

Usage
-----
.. code-block:: python

    from reflex_pcache import PersistentVar, init_pcache

    AppNotice  = PersistentVar(key="app_global_notice", default_value="默认公告")
    UserDraft  = PersistentVar(key="user_draft",        default_value="")

    def index():
        return rx.fragment(
            init_pcache([AppNotice, UserDraft]),
            rx.text(AppNotice.value),                 # 1. front-end read
            rx.input(on_change=UserDraft.set()),      # 2. front-end write
            rx.button("推送", on_click=State.do_push),
            rx.button("拉取", on_click=State.do_retrieve),
        )

    class State(rx.State):
        @rx.event
        def do_push(self):
            yield AppNotice.push("数据库最新公告")     # 3. backend -> front-end

        @rx.event
        def do_retrieve(self):
            yield AppNotice.retrieve(callback=self.receive_data)  # 4. backend <- front-end

        @rx.event
        def receive_data(self, value):
            ...
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable, Union

import reflex as rx
from reflex.event import EventHandler, EventSpec, run_script
from reflex.vars.base import LiteralVar, Var
from reflex.vars.function import ArgsFunctionOperationBuilder, FunctionVar

from .frontend_script import PCACHE_BRIDGE, PCACHE_GLOBAL_REF

# Sentinel distinguishing "no argument given" (forward the event arg) from an
# explicit ``None`` (write JS ``null``). Mirrors ClientStateVar's ``NoValue``.
_NO_VALUE = object()

# A VarData carrying only the bridge script + a reference to the global. Every
# accessor Var we hand back carries this, so the bridge is guaranteed to be on
# the page the first time any PersistentVar is rendered, no matter which
# component touched it first (mirrors ClientStateVar's reliance on VarData
# propagation).
_BRIDGE_VAR_DATA = rx.vars.VarData(  # type: ignore[attr-defined]
    imports={},
    hooks={PCACHE_BRIDGE: None},
)


def _bridge_var(js_expr: str, var_type: Any = Any) -> Var:
    """Build a Var whose expression runs against ``window.__pcache``.

    Every such Var carries :data:`_BRIDGE_VAR_DATA` so the bridge script is
    injected into the page alongside the expression.
    """
    return Var(_js_expr=js_expr, _var_data=_BRIDGE_VAR_DATA).to(var_type)


def _js_str(value: Any) -> str:
    """Serialize a Python value to a literal JS expression string."""
    return str(LiteralVar.create(value))


@dataclasses.dataclass(eq=False, frozen=True, slots=True)
class PersistentVar(Var):
    """A Var persisted in the browser's ``localStorage``.

    Instances are created via :meth:`create`. They behave like an ordinary
    Reflex ``Var`` for the purposes of rendering (see :attr:`value`), and add
    four localStorage-aware operations:

    * :attr:`value`        -- read for rendering (no backend round-trip).
    * :meth:`set`/:meth:`set_value` -- write from a front-end event trigger.
    * :meth:`push`         -- write from a backend event handler.
    * :meth:`retrieve`     -- read into a backend event handler.
    """

    # The localStorage key (without the ``pcache:`` namespace the bridge adds).
    _key: str = dataclasses.field(default="")
    # The Python default registered at creation time; used for fallback in JS.
    _default: Any = dataclasses.field(default=None)

    def __hash__(self) -> int:  # Var instances are hashable; keep them so.
        return hash((self._key, str(self._var_type)))

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    @classmethod
    def create(
        cls,
        key: str,
        default_value: Any = None,
    ) -> "PersistentVar":
        """Create a persistent front-end var.

        Args:
            key: The localStorage key. Must be a non-empty string. Namespaced
                under ``pcache:`` internally so it never collides with the
                host app's own localStorage entries.
            default_value: Value used when the key is absent or corrupt, and
                the value seeded into localStorage on first run.

        Returns:
            A :class:`PersistentVar`.

        Raises:
            ValueError: If ``key`` is not a non-empty string.
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
            _js_expr=PCACHE_GLOBAL_REF,
            _var_type=default_var._var_type,
            _var_data=rx.vars.VarData(  # type: ignore[attr-defined]
                imports={},
                hooks={PCACHE_BRIDGE: None},
            ),
            _key=key,
            _default=default_value,
        )

    # ------------------------------------------------------------------ #
    # 1. Front-end read
    # ------------------------------------------------------------------ #
    @property
    def value(self) -> Var:
        """Accessor for rendering the current value.

        Evaluates ``window.__pcache.get("key")`` on the client, so the first
        paint reads straight from ``localStorage`` with no WebSocket
        round-trip. The registered default is returned if the key is missing,
        corrupt, or the bridge has not booted yet.
        """
        return _bridge_var(
            f'{PCACHE_GLOBAL_REF}.get("{self._key}")',
            self._var_type,
        )

    # ------------------------------------------------------------------ #
    # 2. Front-end write
    # ------------------------------------------------------------------ #
    def set_value(self, value: Any = _NO_VALUE) -> Var:
        """Return an event-chain Var that writes ``value`` to localStorage.

        Attach to a front-end event trigger. With no argument the inbound
        event argument (e.g. ``on_change``'s value) is forwarded verbatim,
        which is the high-frequency write path described in PRD §2.1.2.

        Args:
            value: A literal value to write. When omitted (the default), the
                triggering event's argument is written as-is. Pass ``None``
                explicitly to write JS ``null``.

        Returns:
            A ``FunctionVar`` / ``EventChain`` that performs the write when the
            event fires.
        """
        # The raw setter: ``__pcache.set`` bound to this key. It takes a
        # single remaining argument (the value) and writes it to localStorage.
        bound_setter = _bridge_var(
            f'{PCACHE_GLOBAL_REF}.set.bind({PCACHE_GLOBAL_REF}, "{self._key}")'
        ).to(FunctionVar)

        if value is _NO_VALUE:
            # Forward the event argument verbatim: build ``(arg) => bound(arg)``.
            arg_name = rx.vars.get_unique_variable_name()
            forwarder = ArgsFunctionOperationBuilder.create(
                args_names=(arg_name,),
                return_expr=bound_setter.call(Var(arg_name)),
            )
        else:
            # Ignore the event argument, always write the literal: ``() => bound(value)``.
            value_var = LiteralVar.create(value)
            forwarder = ArgsFunctionOperationBuilder.create(
                args_names=(),
                return_expr=bound_setter.call(value_var),
            )

        return forwarder.to(FunctionVar)

    @property
    def set(self) -> Var:
        """Event-chain Var forwarding the trigger argument to localStorage.

        Convenience for ``set_value()`` with no literal, i.e. the common
        ``on_change=MyVar.set`` case.
        """
        return self.set_value()

    # ------------------------------------------------------------------ #
    # 3. Backend -> front-end push
    # ------------------------------------------------------------------ #
    def push(self, value: Any) -> EventSpec:
        """Write ``value`` to the client's localStorage from the backend.

        Must be ``yield``-ed/returned by an event handler. After it runs the
        next render reads the new value via :attr:`value`. To also force an
        immediate re-render, pair with a trigger event (see README).

        Args:
            value: The value to push.

        Returns:
            An :class:`EventSpec` that runs the write on the client.
        """
        return run_script(
            f'{PCACHE_GLOBAL_REF}.set("{self._key}", {_js_str(value)})'
        )

    # ------------------------------------------------------------------ #
    # 4. Backend <- front-end retrieve
    # ------------------------------------------------------------------ #
    def retrieve(
        self,
        callback: Union[EventHandler, Callable, None] = None,
    ) -> EventSpec:
        """Send the current localStorage value to a backend event handler.

        Must be ``yield``-ed/returned by an event handler. The callback
        receives the parsed value as its first argument.

        Args:
            callback: The ``EventHandler`` (or handler-returning callable)
                that should receive the value. Pass the handler object
                directly, e.g. ``retrieve(callback=self.receive_data)``.

        Returns:
            An :class:`EventSpec` that evaluates the read on the client and
            dispatches the result to ``callback``.
        """
        return run_script(
            f'{PCACHE_GLOBAL_REF}.retrieve("{self._key}")',
            callback=callback,
        )

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #
    def clear(self) -> EventSpec:
        """Remove the key from localStorage (backend-initiated)."""
        return run_script(f'{PCACHE_GLOBAL_REF}.clear("{self._key}")')
