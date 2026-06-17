"""Demo app for reflex-pcache.

Exercises all four PRD §8 acceptance criteria:

1. First-paint instant load  -- AppNotice.value renders from localStorage.
2. Front-end independent write -- the draft input writes locally via set().
3. Backend push               -- a button pushes a new notice from the backend.
4. Backend retrieve           -- a button pulls the local value into the backend.

Run from the ``pcache_demo`` directory with ``reflex run``.
"""

import reflex as rx
from reflex_pcache import PersistentVar, init_pcache

# Two persistent vars, one seeded with a default, the other starts empty.
AppNotice = PersistentVar(key="app_global_notice", default_value="默认公告")
UserDraft = PersistentVar(key="user_draft", default_value="")


class PersistentCacheState(rx.State):
    """Backend state for the demo.

    The ``_pcache_trigger`` counter is the PRD §4.2 "hidden trigger": bumping
    it forces React to re-render, which re-evaluates every ``PersistentVar.value``
    expression and so reflects the new localStorage value on screen. Writes to
    localStorage do not, by themselves, make React re-render — this counter is
    what bridges that gap.

    Apps using reflex-pcache are expected to keep an equivalent counter and
    ``pcache_bump`` event in whichever of their own States holds the page that
    reads ``PersistentVar.value``. See the README for the one-time setup.
    """

    # Hidden trigger counter. Not displayed; only exists to force re-renders.
    _pcache_trigger: int = 0

    # Mirror of the retrieved value, shown back to the user (acceptance #4).
    retrieved_value: str = "(尚未拉取)"

    @rx.event
    def pcache_bump(self):
        """Increment the trigger to force a re-render after a local write."""
        self._pcache_trigger += 1

    @rx.event
    def push_notice(self):
        """Backend -> front-end: push a fresh notice (acceptance #3)."""
        yield AppNotice.push("数据库最新公告 (来自后端推送)")
        # Reflect it immediately on this render.
        self._pcache_trigger += 1

    @rx.event
    def retrieve_notice(self):
        """Backend <- front-end: pull localStorage into the backend (#4)."""
        yield AppNotice.retrieve(callback=self.receive_data)

    @rx.event
    def receive_data(self, value: str):
        """Callback invoked by retrieve() with the local value."""
        self.retrieved_value = str(value)


def _on_change_write(draft: PersistentVar):
    """Event chain: write to localStorage, then bump the render trigger."""
    return [draft.set(), PersistentCacheState.pcache_bump]


def index() -> rx.Component:
    return rx.container(
        # 1. Boot the bridge and seed defaults once on mount.
        init_pcache([AppNotice, UserDraft]),
        rx.color_mode.button(position="top-right"),
        rx.vstack(
            rx.heading("reflex-pcache 演示", size="7"),
            rx.text("刷新页面 / 断网后，下方公告仍来自 localStorage（秒开）."),

            # --- Acceptance #1: first-paint read from localStorage ---
            rx.card(
                rx.heading("① 首屏读取 (后端零往返)", size="5"),
                rx.text(AppNotice.value, size="6", weight="bold"),
                width="100%",
            ),

            # --- Acceptance #2: front-end local write ---
            rx.card(
                rx.heading("② 前端独立写入 (仅写 localStorage)", size="5"),
                rx.input(
                    placeholder="输入草稿…",
                    value=UserDraft.value,
                    on_change=_on_change_write(UserDraft),
                    width="100%",
                ),
                rx.text("当前草稿: ", UserDraft.value),
                width="100%",
            ),

            # --- Acceptance #3: backend push ---
            rx.card(
                rx.heading("③ 后端推送 (后端 -> 前端)", size="5"),
                rx.button("推送新公告", on_click=PersistentCacheState.push_notice),
                width="100%",
            ),

            # --- Acceptance #4: backend retrieve ---
            rx.card(
                rx.heading("④ 后端拉取 (前端 -> 后端)", size="5"),
                rx.button("拉取公告到后端", on_click=PersistentCacheState.retrieve_notice),
                rx.text("后端收到的值: ", PersistentCacheState.retrieved_value),
                width="100%",
            ),

            spacing="4",
            width="100%",
            align="stretch",
        ),
        size="4",
        max_width="640px",
    )


app = rx.App()
app.add_page(index)
