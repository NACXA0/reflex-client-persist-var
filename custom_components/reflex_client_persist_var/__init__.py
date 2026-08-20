"""reflex_pcache — persistent front-end state for Reflex.

A localStorage-backed counterpart to Reflex's experimental ``ClientStateVar``.
See :mod:`reflex_pcache.var` for the :class:`PersistentVar` API and
:mod:`reflex_pcache.component` for :func:`init_pcache`.

Quick start::

    from reflex_pcache import PersistentVar, init_pcache
    import reflex as rx

    AppNotice = PersistentVar(key="app_notice", default_value="默认公告")

    def index():
        return rx.fragment(
            init_pcache([AppNotice]),
            rx.text(AppNotice.value),
        )
"""

from .component import init_pcache
from .var import PersistentVar

__all__ = ["PersistentVar", "init_pcache"]

__version__ = "0.1.0"
