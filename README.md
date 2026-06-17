# reflex-pcache

**Persistent front-end state for [Reflex](https://reflex.dev), backed by browser `localStorage`.**

`reflex-pcache` is a localStorage-backed counterpart to Reflex's experimental
`ClientStateVar` (`reflex.experimental.client_state`). `ClientStateVar` keeps
state in React's `useState` — which is wiped on every page refresh. `reflex-pcache`
keeps it in `localStorage`, so the value survives reloads, disconnects and even
reboots, enabling a true **first-paint instant-load ("秒开")** experience with
**zero WebSocket round-trip**.

| Operation | Direction | Network |
|---|---|---|
| `var.value` | render from `localStorage` | none |
| `var.set()` | front-end event → `localStorage` | one tiny bump (see below) |
| `var.push(value)` | backend → `localStorage` | one script eval |
| `var.retrieve(callback)` | `localStorage` → backend | one round-trip |

## Install

```bash
uv add reflex-pcache
```

> Requires `reflex >= 0.9.2`.

## Quick start

```python
import reflex as rx
from reflex_pcache import PersistentVar, init_pcache

AppNotice = PersistentVar(key="app_global_notice", default_value="默认公告")
UserDraft = PersistentVar(key="user_draft", default_value="")

class State(rx.State):
    # (1) The re-render trigger — see "Why a trigger?" below.
    _pcache_trigger: int = 0
    retrieved: str = "(nothing yet)"

    @rx.event
    def pcache_bump(self):
        self._pcache_trigger += 1

    @rx.event
    def push_notice(self):
        yield AppNotice.push("数据库最新公告")          # backend -> front-end

    @rx.event
    def pull_notice(self):
        yield AppNotice.retrieve(callback=self.receive)  # front-end -> backend

    @rx.event
    def receive(self, value: str):
        self.retrieved = str(value)

def index():
    return rx.fragment(
        init_pcache([AppNotice, UserDraft]),          # boot + seed defaults
        rx.text(AppNotice.value),                    # 1. front-end read
        rx.input(on_change=UserDraft.set()),         # 2. front-end write
        rx.button("Push", on_click=State.push_notice),
        rx.button("Pull", on_click=State.pull_notice),
    )

app = rx.App()
app.add_page(index)
```

## API

### `PersistentVar.create(key, default_value=None)`

Create a persistent var. `key` is namespaced under `pcache:` so it never
collides with your app's own `localStorage` entries. `default_value` is both the
fallback returned when the key is missing/corrupt **and** the value seeded into
`localStorage` on first run.

### `.value`  *(property)*

A `Var` that evaluates `window.__pcache.get(key)` on the client. Bind it to any
component: `rx.text(AppNotice.value)`. First paint reads straight from
`localStorage` — no backend involved.

### `.set`  /  `.set_value(value=...)`

A front-end event-chain Var. Attach to a trigger:

```python
rx.input(on_change=UserDraft.set)          # forward the event arg verbatim
rx.input(on_change=UserDraft.set())        # equivalent, parens optional
rx.button(on_click=ThemeVar.set_value("dark"))   # write a literal
```

### `.push(value)`

Write `value` to the client's `localStorage` **from a backend event handler**.
Must be `yield`-ed/returned:

```python
@rx.event
def handler(self):
    yield AppNotice.push("updated")
```

### `.retrieve(callback=handler)`

Send the current `localStorage` value into a backend handler. `callback` is the
**handler object itself** (not a dotted string):

```python
@rx.event
def handler(self):
    yield AppNotice.retrieve(callback=self.receive)

@rx.event
def receive(self, value: str):
    ...
```

### `.clear()`

Remove the key from `localStorage` (backend-initiated).

### `init_pcache(vars)`

The (invisible) initializer. Include it once near the root of any page that uses
a `PersistentVar`. It injects the `window.__pcache` bridge and, on mount, seeds
every registered key with its default if empty.

```python
init_pcache([AppNotice, UserDraft])   # or a single var: init_pcache(AppNotice)
```

## Why a re-render trigger? (important)

Writing to `localStorage` does **not** make React re-render — that's the core
difficulty called out in the PRD. `reflex-pcache` therefore expects the **host
app** to own a tiny trigger counter and a `pcache_bump` event in whichever of
its States backs the page that reads `.value`:

```python
class State(rx.State):
    _pcache_trigger: int = 0

    @rx.event
    def pcache_bump(self):
        self._pcache_trigger += 1
```

Then, for front-end writes that must update the screen immediately, chain the
write with a bump:

```python
def write_and_refresh(var):
    return [var.set(), State.pcache_bump]

rx.input(on_change=write_and_refresh(UserDraft))
```

`push()` can self-bump from the same handler. The counter is never displayed;
it exists only to invalidate the render so the `.value` expressions re-read
`localStorage`. (A library cannot ship a global `State`, so this one-time setup
lives in your app — the `pcache_demo` shows a complete, copy-pasteable example.)

## Robustness

All edge cases (PRD §7) are handled in the injected JS:

- **Quota exceeded / storage disabled** — `__pcache.set` swallows
  `QuotaExceededError` (and private-mode `SecurityError`), falls back to an
  in-memory map for the session, and logs a warning. Never throws.
- **Corrupt JSON** — `__pcache.get` falls back to the registered default on any
  `JSON.parse` failure; never returns `undefined`.
- **First-paint race** — if `.value` is evaluated before `init_pcache` has
  mounted, the bridge is still injected (every accessor carries the bridge via
  `VarData`), and reads return the default rather than throwing.

## Demo

```bash
cd pcache_demo
pip install -e ..        # install reflex-pcache in editable mode
pip install -r requirements.txt
reflex init              # first run only, populates .web
reflex run
```

The demo exercises all four PRD §8 acceptance criteria:

1. **First-paint instant load** — refresh/offline, the notice still shows.
2. **Front-end independent write** — typing in the draft box updates
   `localStorage` and the UI in real time (no backend call for the data).
3. **Backend push** — the button pushes a new notice that persists across reloads.
4. **Backend retrieve** — the button pulls the local value into the backend and
   echoes it back.

## Development / packaging

This package follows the official `reflex component` layout. To build a
distributable:

```bash
reflex component build      # produces dist/*.tar.gz and dist/*.whl
twine upload dist/*         # or: uv publish dist/*
```

## License

Apache-2.0, matching Reflex.
