"""The :func:`init_pcache` initializer component.

It renders nothing on screen. Its only job is to ensure every registered
:class:`PersistentVar` is *seeded* into ``localStorage`` with its default value
the first time the app mounts, and to guarantee the ``window.__pcache`` bridge
exists before any ``.value`` read happens (first-paint race, PRD §7.3).

It does for ``localStorage`` what embedding the ``ClientStateVar`` itself does
for ``useState``: declaring it in the tree is what makes the hook fire.
"""

from __future__ import annotations

import json
from typing import Iterable

import reflex as rx
from reflex.vars.base import Var
from reflex.vars.base import VarData
from reflex.utils.imports import ImportVar

from .frontend_script import PCACHE_BRIDGE, PCACHE_GLOBAL_REF
from .var import PersistentVar

# ``useEffect`` import needed for the mount-time seeding hook.
_USE_EFFECT_IMPORT = {"react": [ImportVar(tag="useEffect")]}


def _js_literal(value) -> str:
    """Render a Python default as a JS literal via JSON (safe subset)."""
    return json.dumps(value, ensure_ascii=False)


class PCacheInit(rx.Component):
    """Invisible component that boots ``window.__pcache`` and seeds defaults.

    Its contribution is pure side-effect: injecting the ``window.__pcache``
    bridge script and seeding each registered key with its default value on
    mount.
    """

    tag = "span"

    def add_custom_code(self) -> list[str]:
        """Inject the full bridge definition into the page (idempotent)."""
        return [PCACHE_BRIDGE]

    def add_imports(self) -> dict[str, ...]:
        """Import ``useEffect`` for the mount hook."""
        return _USE_EFFECT_IMPORT

    def add_hooks(self) -> list[str | Var]:
        """On mount, seed each registered key with its default value.

        Runs once after first paint. ``init`` is a no-op when the key already
        holds a value, so re-mounts and hot-reloads are safe.
        """
        pvars: Iterable[PersistentVar] = getattr(self, "_pcache_vars", [])
        if not pvars:
            return []

        calls = ", ".join(
            f'{PCACHE_GLOBAL_REF}.init("{pv._key}", {_js_literal(pv._default)})'
            for pv in pvars
        )
        # useEffect with an empty dependency array runs exactly once on mount.
        return [
            "useEffect(() => { " + calls + "; }, [])",
        ]



def init_pcache(
    vars: Iterable[PersistentVar] | PersistentVar,
) -> rx.Component:
    """Create the (invisible) ``reflex_pcache`` initializer.

    Place it once near the root of any page that uses a :class:`PersistentVar`,
    typically as the first child::

        def index():
            return rx.fragment(
                init_pcache([AppNotice, UserDraft]),
                rx.text(AppNotice.value),
                ...
            )

    Args:
        vars: A single :class:`PersistentVar` or an iterable of them. Only the
            keys/default values are read; the returned component renders
            nothing.

    Returns:
        An invisible component that, when included in the tree, seeds
        ``localStorage`` defaults on mount.
    """
    if isinstance(vars, PersistentVar):
        pvars = [vars]
    else:
        pvars = list(vars)

    for pv in pvars:
        if not isinstance(pv, PersistentVar):
            msg = (
                "init_pcache expects PersistentVar instances, got "
                f"{type(pv).__name__}."
            )
            raise TypeError(msg)

    instance = PCacheInit.create()
    # Stash the registered vars on the instance so add_hooks can read them.
    # ``Component`` is not a frozen dataclass; setting an attribute is fine.
    object.__setattr__(instance, "_pcache_vars", pvars)
    return instance
