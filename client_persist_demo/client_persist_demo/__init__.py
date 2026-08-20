"""reflex-client-persist-var 演示应用。

覆盖 PRD 第 8 节的验收标准，以及复杂类型与卫生（限制）检查：

1. 首屏秒开 —— AppNotice.value 直接从 localStorage 渲染。
2. 前端写入 + 复杂类型 —— 字符串 Tab 实时直写 localStorage；字典 / 列表
   Tab 用「输入框 + 添加按钮 + Tag」交互式构建（点击 Tag 出现删除按钮），
   由后端校验后 push 持久化。
3. 后端推送 + 对照 —— 推送时同步更新一个传统后端 ``state.var``，
   直观对比「服务端值（内存态）」与「本地值（持久化）」。
4. 后端拉取 —— 点击按钮把本地值拉回后端。
5. 后端清除 —— 清除某个 key；值回落到默认值。

明暗外观跟随系统（``appearance="inherit"``）。限流与长度上限让这个公开
演示对服务器保持友好：每次后端操作间隔 ≥ 1 秒（toast 提示），每个输入
都做了长度限制（前端 ``max_length`` + 后端二次校验）。

库的简介与优势直接展示在标题下方；「应用场景速览」（7 类典型用法：UI 偏好、
表单草稿、首屏秒开、游客留存、高频轻量状态本地化、跨标签页共享、断线重连）
与「能力边界提醒」「为什么写入后页面会立即更新？」以默认折叠、轻视觉重量的
形式紧随其后，与 README「应用场景与能力边界」章节一一对应；右上角提供
GitHub 仓库链接。

在 ``client_persist_demo`` 目录下用 ``reflex run`` 运行。
"""

import time

import reflex as rx
from reflex.event import EventSpec
from reflex_client_persist_var import PersistentVar, PersistentState, init_persist_var

# 持久化变量：一条预置公告 + 三个复杂类型草稿。
# PersistentVar 是冻结数据类 —— 必须通过 .create() 构造。
AppNotice = PersistentVar.create(key="app_global_notice", default_value="默认公告")
UserDraftStr = PersistentVar.create(key="user_draft_str", default_value="")
UserDraftDict = PersistentVar.create(key="user_draft_dict", default_value={"标题": "笔记", "标签": ["reflex"]})
UserDraftList = PersistentVar.create(key="user_draft_list", default_value=["reflex", "localStorage"])


class PersistentCacheState(rx.State):
    """演示用后端状态"""

    # 示例3  后端推送的对照：传统后端 state（内存态，刷新即重置）。
    backend_notice: str = "初始公告 (服务端 state · 刷新即重置)"

    # 示例4  拉取值的回显。
    retrieved_value: str = "(尚未拉取)"

    # 示例2  dict 交互式 Tag 编辑器：后端镜像 + 输入框。
    dict_key_input: str = ""
    dict_value_input: str = ""
    draft_dict: dict = {"标题": "笔记"}  # 编辑镜像，改动后 push 到 localStorage
    armed_dict_tag: str = ""  # 当前显示删除按钮的 key（空 = 都不显示）

    # 示例2  list 交互式 Tag 编辑器。
    list_item_input: str = ""
    draft_list: list[str] = ["reflex", "localStorage"]
    armed_list_index: int = -1  # 当前显示删除按钮的下标（-1 = 都不显示）

    # 限流（本公开演示对服务器友好）：两次后端操作间隔 ≥ 1 秒。
    # 类常量（不加类型注解，因此不会成为状态变量）。
    ACTION_INTERVAL: float = 1.0

    # 私有运行时字段（不序列化到前端）。
    _last_action_ts: float = 0.0
    _notice_seq: int = 0

    def _rate_limited(self) -> EventSpec | None:
        """若触发限流，返回应 yield 的 toast 事件；否则返回 None。"""
        now = time.time()
        wait = self.ACTION_INTERVAL - (now - self._last_action_ts)
        if wait > 0:
            return rx.toast.warning(f"操作太频繁，请 {wait:.1f} 秒后再试")
        self._last_action_ts = now
        return None

    # 示例2  字典 Tag 编辑器 

    @rx.event
    def set_dict_key_input(self, value: str):
        """绑定键输入框（reflex 0.9 没有自动 setter）。"""
        self.dict_key_input = value

    @rx.event
    def set_dict_value_input(self, value: str):
        """绑定值输入框。"""
        self.dict_value_input = value

    @rx.event
    def add_dict_tag(self):
        """后端校验键值对后 push（复杂类型持久化）。"""
        toast = self._rate_limited()
        if toast:
            yield toast
            return
        key = self.dict_key_input.strip()
        value = self.dict_value_input.strip()
        if not key or not value:
            yield rx.toast.error("键和值都不能为空")
            return
        if len(key) > 20 or len(value) > 100:
            yield rx.toast.error("键最长 20 字符，值最长 100 字符")
            return
        # 不可变更新（整体赋值）比原地突变更可靠，避免个别版本/场景下 UI 不刷新。
        self.draft_dict = {**self.draft_dict, key: value}
        self.dict_key_input = ""
        self.dict_value_input = ""
        self.armed_dict_tag = ""
        yield rx.toast.success(f"已写入字典：{key} = {value}")
        yield UserDraftDict.push(dict(self.draft_dict))

    @rx.event
    def remove_dict_tag(self, key: str):
        """删除字典中的一个键并重新持久化。"""
        if key not in self.draft_dict:
            return
        # 不可变更新（整体赋值）比原地删除更可靠。
        self.draft_dict = {k: v for k, v in self.draft_dict.items() if k != key}
        self.armed_dict_tag = ""
        yield rx.toast.success(f"已删除键：{key}")
        yield UserDraftDict.push(dict(self.draft_dict))

    @rx.event
    def arm_dict_tag(self, key: str):
        """点击 Tag：再次点击取消，其他点击显示删除按钮。"""
        self.armed_dict_tag = "" if self.armed_dict_tag == key else key

    # 示例2 列表 Tag 编辑器 

    @rx.event
    def set_list_item_input(self, value: str):
        """绑定条目输入框。"""
        self.list_item_input = value

    @rx.event
    def add_list_tag(self):
        """后端校验后 push（复杂类型持久化）。"""
        toast = self._rate_limited()
        if toast:
            yield toast
            return
        item = self.list_item_input.strip()
        if not item:
            yield rx.toast.error("内容不能为空")
            return
        if len(item) > 100:
            yield rx.toast.error("单个条目最长 100 字符")
            return
        # 不可变更新（整体赋值）比原地 append 更可靠。
        self.draft_list = [*self.draft_list, item]
        self.list_item_input = ""
        self.armed_list_index = -1
        yield rx.toast.success(f"已添加条目：{item}")
        yield UserDraftList.push(list(self.draft_list))

    @rx.event
    def remove_list_tag(self, index: int):
        """删除列表中的一个条目并重新持久化。"""
        if not (0 <= index < len(self.draft_list)):
            return
        # 不可变更新（整体赋值）比原地 pop 更可靠。
        item = self.draft_list[index]
        self.draft_list = self.draft_list[:index] + self.draft_list[index + 1 :]
        self.armed_list_index = -1
        yield rx.toast.success(f"已删除条目：{item}")
        yield UserDraftList.push(list(self.draft_list))

    @rx.event
    def arm_list_tag(self, index: int):
        """点击 Tag：再次点击取消，其他点击显示删除按钮。"""
        self.armed_list_index = -1 if self.armed_list_index == index else index

    # 示例3、4、5 后端推送、拉取、清除 ---

    @rx.event
    def push_notice(self):
        """后端 -> 前端：推送一条新公告（验收 #3）。

        先更新传统后端状态变量，使推送过程清晰可见：
        服务端 state（内存）与本地持久化（localStorage）并排对照。
        """
        toast = self._rate_limited()
        if toast:
            yield toast
            return
        new_notice = f"公告 #{self._notice_seq} · {time.strftime('%H:%M:%S')}"
        self._notice_seq += 1
        self.backend_notice = new_notice
        yield rx.toast.success("已推送新公告")
        yield AppNotice.push(new_notice)

    @rx.event
    def retrieve_notice(self):
        """后端 <- 前端：把 localStorage 拉取到后端（#4）。"""
        toast = self._rate_limited()
        if toast:
            yield toast
            return
        yield rx.toast.info("正在从 localStorage 拉取…")
        yield AppNotice.retrieve(callback=self.receive_data)

    @rx.event
    def receive_data(self, value: str):
        """retrieve() 拿到本地值后回调的函数。"""
        self.retrieved_value = str(value)

    @rx.event
    def clear_notice(self):
        """后端清除：移除 key；值回落到默认值（#5）。"""
        toast = self._rate_limited()
        if toast:
            yield toast
            return
        yield rx.toast.success("已清除公告缓存，回落到默认值")
        yield AppNotice.clear()


# region demo展示辅助组件 

# 数据流步骤徽标的循环配色（soft 低饱和点缀）
_FLOW_COLORS = ("indigo", "cyan", "orange", "teal", "violet", "green")


def flow(*steps: str) -> rx.Component:
    """数据流转方向示意图：步骤之间用箭头连接，步骤徽标循环配色点缀。"""
    items = []
    for i, step in enumerate(steps):
        if i > 0:
            items.append(rx.icon(tag="arrow-right", size=14, color="var(--gray-9)"))
        items.append(
            rx.badge(step, variant="soft", color_scheme=_FLOW_COLORS[i % len(_FLOW_COLORS)])
        )
    return rx.hstack(items, wrap="wrap", align="center", spacing="2")


def local_badge(text: str = "本地值 · localStorage") -> rx.Component:
    """绿色徽标：标注来自 localStorage 的持久化值。"""
    return rx.badge(text, color_scheme="green", variant="soft", radius="full")


def server_badge(text: str = "服务端值 · state") -> rx.Component:
    """琥珀色徽标：标注仅存在于后端 state 的内存值。"""
    return rx.badge(text, color_scheme="amber", variant="soft", radius="full")


def value_panel(accent: str, badge_comp: rx.Component, value_comp: rx.Component) -> rx.Component:
    """带强调色左边框的值展示面板。accent: green(本地) / amber(服务端)。"""
    return rx.card(
        rx.vstack(
            badge_comp,
            rx.box(value_comp, width="100%"),
            align="start",
            spacing="2",
        ),
        variant="surface",
        width="100%",
        style={"border_left": f"4px solid var(--{accent}-9)"},
    )


def dict_tag(pair) -> rx.Component:
    """渲染一个字典 Tag：点击显示/隐藏其删除按钮。

    注意：Reflex 0.9 编译 ``rx.foreach(dict, fn)`` 时，回调实际收到的是
    ``(元素, 索引)`` 而非 ``(key, value)``——元素即 ``[key, value]`` 数组
    （编译产物为 ``Object.entries(...).map((elem, idx) => ...)``）。因此这里
    接收单个 ``pair`` 参数，取 ``pair[0]`` / ``pair[1]`` 作为键与值。若按
    ``dict_tag(key, value)`` 两个参数写，第二个参数会是索引而非值，导致
    键值连写（数组被 React 展开）、且 armed 比较恒假、删除按钮永不显示。
    """
    key, value = pair[0], pair[1]
    armed = PersistentCacheState.armed_dict_tag == key
    return rx.hstack(
        rx.badge(
            rx.text(key, ": ", value, size="2"),
            variant="soft",
            radius="full",
            cursor="pointer",
            on_click=PersistentCacheState.arm_dict_tag(key),
            _hover={"opacity": "0.85"},
        ),
        rx.cond(
            armed,
            rx.icon_button(
                rx.icon(tag="x", size=12),
                size="1",
                variant="ghost",
                color_scheme="red",
                on_click=PersistentCacheState.remove_dict_tag(key),
            ),
        ),
        spacing="1",
        align="center",
    )


def list_tag(item, index) -> rx.Component:
    """渲染一个列表 Tag：点击显示/隐藏其删除按钮。"""
    armed = PersistentCacheState.armed_list_index == index
    return rx.hstack(
        rx.badge(
            item,
            variant="soft",
            radius="full",
            cursor="pointer",
            on_click=PersistentCacheState.arm_list_tag(index),
            _hover={"opacity": "0.85"},
        ),
        rx.cond(
            armed,
            rx.icon_button(
                rx.icon(tag="x", size=12),
                size="1",
                variant="ghost",
                color_scheme="red",
                on_click=PersistentCacheState.remove_list_tag(index),
            ),
        ),
        spacing="1",
        align="center",
    )


def section_title(text: str) -> rx.Component:
    """卡片标题：编号 + 标题。"""
    return rx.text(text, size="5", weight="bold")


def demo_code_block(title: str, code: str) -> rx.Component:
    """默认折叠的 demo 示例代码块（手风琴 + 语法高亮）。

    与 README 中的折叠块对应：简洁风格标题 + 核心 API 片段。
    """
    return rx.accordion.root(
        rx.accordion.item(
            rx.accordion.header(
                rx.accordion.trigger(
                    rx.hstack(
                        rx.icon(tag="chevron-down", size=14, color="var(--gray-9)"),
                        rx.text(title, size="1", color_scheme="gray"),
                        spacing="2",
                        align="center",
                    ),
                    width="100%",
                ),
            ),
            rx.accordion.content(
                rx.code_block(
                    code,
                    language="python",
                    show_line_numbers=True,
                    width="100%",
                ),
                padding="0",
            ),
            value="code",
            width="100%",
        ),
        color_scheme="gray",
        variant="outline",
        style={"box_shadow": "none"},
        type="single",
        collapsible=True,
        width="100%",
    )

# endregion



# region 示例代码片段（与 README 折叠块一致，供页面内快速参考）

# 示例1 首屏读取（本地值，零后端往返）
_DEMO_CODE_1 = """\
# 1. 创建持久化变量（key 自动加 client-persist-var: 命名空间）
AppNotice = PersistentVar.create(key="app_global_notice", default_value="默认公告")

# 2. 直接渲染：首帧从 localStorage 读取，零后端往返
rx.text(AppNotice.value, size="6", weight="bold")
"""

# 示例2 前端写入 + 交互式 Tag 编辑（复杂类型）
_DEMO_CODE_2 = """\
UserDraftStr  = PersistentVar.create(key="user_draft_str", default_value="")
UserDraftDict = PersistentVar.create(key="user_draft_dict", default_value={"标题": "笔记"})

# 字符串：击键即写 localStorage，随后 bump 强制重渲染
rx.input(
    value=UserDraftStr.value,
    on_change=[UserDraftStr.set, PersistentState.persist_bump],
)

# 复杂类型（dict/list）：后端校验后 push 持久化 + 自动 bump
@rx.event
def add_dict_tag(self):
    ...
    yield UserDraftDict.push(dict(self.draft_dict))
"""

# 示例3 后端推送（服务端 vs 本地对照）
_DEMO_CODE_3 = """\
@rx.event
def push_notice(self):
    new_notice = f"公告 #{self._notice_seq} · {time.strftime('%H:%M:%S')}"
    yield AppNotice.push(new_notice)  # 写 localStorage + 自动追加 bump 重渲染
"""

# 示例4 后端拉取（前端 → 后端）
_DEMO_CODE_4 = """\
@rx.event
def retrieve_notice(self):
    yield AppNotice.retrieve(callback=self.receive_data)  # localStorage -> 后端

@rx.event
def receive_data(self, value: str):
    self.retrieved_value = str(value)  # 后端回显
"""

# 示例5 后端清除
_DEMO_CODE_5 = """\
@rx.event
def clear_notice(self):
    yield AppNotice.clear()  # 删除 key，值回落默认值（自动 bump 重渲染）
"""

# endregion


# region demo组件

# 示例1 首屏读取（本地值，零后端往返） 
def demo1() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                section_title("示例1 首屏读取"),
                rx.spacer(),
                rx.badge("零后端往返", color_scheme="green", variant="soft"),
            ),
            flow("localStorage", "React 首帧渲染"),
            value_panel(
                "green",
                local_badge(),
                rx.text(AppNotice.value, size="6", weight="bold"),
            ),
            rx.text(
                "页面加载时不访问后端；默认值在首帧渲染前注册，"
                "因此首帧即显示持久化值。",
                size="1",
                color_scheme="gray",
            ),
            demo_code_block("展开查看：示例1 首屏读取 · demo 代码", _DEMO_CODE_1),
            align="stretch",
            spacing="3",
            width="100%",
        ),
        variant="surface",
        width="100%",
    )

# 示例2 前端写入 + 交互式 Tag 编辑（复杂类型） 
def demo2() -> rx.Component:
    return rx.card(
        rx.vstack(
            section_title("示例2 前端写入 + 交互式 Tag 编辑"),
            rx.text(
                "字符串实时直写 localStorage；字典 / 列表用「输入框 + 添加按钮 + Tag」"
                "交互式构建，点击 Tag 显示删除按钮。",
                size="2",
                color_scheme="gray",
            ),
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger("字符串", value="str"),
                    rx.tabs.trigger("字典", value="dict"),
                    rx.tabs.trigger("列表", value="list"),
                ),
                rx.tabs.content(
                    rx.vstack(
                        flow("输入框", "localStorage"),
                        rx.input(
                            placeholder="输入草稿…",
                            value=UserDraftStr.value,
                            on_change=[UserDraftStr.set, PersistentState.persist_bump],
                            max_length=200,
                            width="100%",
                        ),
                        value_panel(
                            "green",
                            local_badge("本地草稿"),
                            rx.text(UserDraftStr.value),
                        ),
                        rx.text(
                            "击键即写：set 直写 localStorage，随后 bump 强制重渲染。",
                            size="1",
                            color_scheme="gray",
                        ),
                        align="stretch",
                        spacing="3",
                        width="100%",
                    ),
                    value="str",
                ),
                rx.tabs.content(
                    rx.vstack(
                        flow("输入框", "后端校验", "localStorage"),
                        rx.hstack(
                            rx.input(
                                placeholder="键",
                                value=PersistentCacheState.dict_key_input,
                                on_change=PersistentCacheState.set_dict_key_input,
                                max_length=20,
                                width="100%",
                            ),
                            rx.input(
                                placeholder="值",
                                value=PersistentCacheState.dict_value_input,
                                on_change=PersistentCacheState.set_dict_value_input,
                                max_length=100,
                                width="100%",
                            ),
                            rx.button(
                                "添加",
                                on_click=PersistentCacheState.add_dict_tag,
                            ),
                            spacing="2",
                            width="100%",
                        ),
                        rx.hstack(
                            local_badge("本地值 · 字典"),
                            rx.text(
                                "点击 Tag 显示删除按钮",
                                size="1",
                                color_scheme="gray",
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.flex(
                            rx.foreach(
                                PersistentCacheState.draft_dict,
                                dict_tag,
                            ),
                            wrap="wrap",
                            gap="2",
                        ),
                        rx.text(
                            "编辑镜像从默认值开始，每次改动校验后 push 到 localStorage"
                            "并 bump 重渲染。",
                            size="1",
                            color_scheme="gray",
                        ),
                        align="stretch",
                        spacing="3",
                        width="100%",
                    ),
                    value="dict",
                ),
                rx.tabs.content(
                    rx.vstack(
                        flow("输入框", "后端校验", "localStorage"),
                        rx.hstack(
                            rx.input(
                                placeholder="新条目…",
                                value=PersistentCacheState.list_item_input,
                                on_change=PersistentCacheState.set_list_item_input,
                                max_length=100,
                                width="100%",
                            ),
                            rx.button(
                                "添加",
                                on_click=PersistentCacheState.add_list_tag,
                            ),
                            spacing="2",
                            width="100%",
                        ),
                        rx.hstack(
                            local_badge("本地值 · 列表"),
                            rx.text(
                                "点击 Tag 显示删除按钮",
                                size="1",
                                color_scheme="gray",
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.flex(
                            rx.foreach(
                                PersistentCacheState.draft_list,
                                list_tag,
                            ),
                            wrap="wrap",
                            gap="2",
                        ),
                        rx.text(
                            "编辑镜像从默认值开始，每次改动校验后 push 到 localStorage"
                            "并 bump 重渲染。",
                            size="1",
                            color_scheme="gray",
                        ),
                        align="stretch",
                        spacing="3",
                        width="100%",
                    ),
                    value="list",
                ),
                default_value="str",
                width="100%",
            ),
            demo_code_block("展开查看：示例2 前端写入 · demo 代码", _DEMO_CODE_2),
            align="stretch",
            spacing="3",
            width="100%",
        ),
        variant="surface",
        width="100%",
    )

# 示例3 后端推送（服务端 vs 本地对照） 
def demo3() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                section_title("示例3 后端推送"),
                rx.spacer(),
                rx.badge("后端 → 前端", color_scheme="violet", variant="soft"),
            ),
            flow("后端 state", "push()", "localStorage", "前端渲染"),
            rx.button(
                "推送新公告",
                on_click=PersistentCacheState.push_notice,
            ),
            rx.flex(
                value_panel(
                    "amber",
                    server_badge(),
                    rx.code(PersistentCacheState.backend_notice),
                ),
                value_panel(
                    "green",
                    local_badge(),
                    rx.text(AppNotice.value),
                ),
                spacing="3",
                direction="column",
                width="100%",
            ),
            rx.text(
                "琥珀色 = 服务端值（内存态，刷新即重置）；绿色 = 本地值（已持久化，"
                "刷新仍在）。这就是持久化 vs 内存态的区别。",
                size="1",
                color_scheme="gray",
            ),
            demo_code_block("展开查看：示例3 后端推送 · demo 代码", _DEMO_CODE_3),
            align="stretch",
            spacing="3",
            width="100%",
        ),
        variant="surface",
        width="100%",
    )

# 示例4 后端拉取（前端 → 后端） 
def demo4() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                section_title("示例4 后端拉取"),
                rx.spacer(),
                rx.badge("前端 → 后端", color_scheme="cyan", variant="soft"),
            ),
            flow("localStorage", "retrieve()", "后端回调"),
            rx.button(
                "拉取公告到后端",
                on_click=PersistentCacheState.retrieve_notice,
            ),
            rx.flex(
                value_panel(
                    "green",
                    local_badge("localStorage 数据源"),
                    rx.text(AppNotice.value),
                ),
                value_panel(
                    "amber",
                    server_badge("后端收到"),
                    rx.text(PersistentCacheState.retrieved_value),
                ),
                spacing="3",
                direction="column",
                width="100%",
            ),
            demo_code_block("展开查看：示例4 后端拉取 · demo 代码", _DEMO_CODE_4),
            align="stretch",
            spacing="3",
            width="100%",
        ),
        variant="surface",
        width="100%",
    )

# 示例5 后端清除 
def demo5() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                section_title("示例5 后端清除"),
                rx.spacer(),
                rx.badge("后端 → localStorage", color_scheme="orange", variant="soft"),
            ),
            flow("clear()", "删除 localStorage key", "回落默认值"),
            rx.button(
                "清除公告缓存",
                on_click=PersistentCacheState.clear_notice,
            ),
            value_panel(
                "green",
                local_badge("清除后的值"),
                rx.text(AppNotice.value),
            ),
            rx.text(
                "clear() 只删除 localStorage 中该 key；默认值仍通过 register() "
                "在首帧生效，因此清除后立刻回落显示默认值。",
                size="1",
                color_scheme="gray",
            ),
            demo_code_block("展开查看：示例5 后端清除 · demo 代码", _DEMO_CODE_5),
            align="stretch",
            spacing="3",
            width="100%",
        ),
        variant="surface",
        width="100%",
    )

# 说明性折叠项（默认收起，仅标题 + slogan，轻视觉重量） 
def collapse_item(
    value: str,
    icon: str,
    title: str,
    slogan: str,
    content: rx.Component,
    icon_color: str = "var(--gray-9)",
) -> rx.Component:
    """一个默认收起的折叠项：chevron + 图标 + 标题 + slogan，展开后显示 content。"""
    return rx.accordion.item(
        rx.accordion.header(
            rx.accordion.trigger(
                rx.hstack(
                    rx.icon(tag="chevron-down", size=14, color="var(--gray-9)"),
                    rx.icon(tag=icon, size=14, color=icon_color),
                    rx.text(title, size="2", weight="medium"),
                    rx.text(slogan, size="1", color_scheme="gray"),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                width="100%",
            ),
        ),
        rx.accordion.content(
            content,
            padding="0",
        ),
        value=value,
        width="100%",
    )


# 重渲染机制说明（默认折叠） 
def tip() -> rx.Component:
    return rx.accordion.root(
        collapse_item(
            "rerender",
            "info",
            "为什么写入后页面会立即更新？",
            "localStorage 只是数据源，React 只在 state 变化时重渲染",
            rx.text(
                "库级 PersistentState 维护一个版本计数器，所有 PersistentVar.value"
                "渲染时都订阅它：每次写入（push / clear 自动、前端 set 由调用方"
                "追加）都会 bump 计数器，产生真实的前端 delta，强制页面重新求值"
                "所有 PersistentVar.value。若在组件树之外修改了 localStorage"
                "（如浏览器控制台、其他标签页），需要刷新或切换 Tab 触发重渲染"
                "才能看到新值。注意：bump 是后端事件，断网时 set 可写入 localStorage"
                "（数据不丢）但 UI 不会实时刷新，重连 / 刷新后即可见。",
                size="1",
                color_scheme="gray",
            ),
            icon_color="var(--iris-9)",
        ),
        color_scheme="gray",
        variant="outline",
        style={"box_shadow": "none"},
        type="single",
        collapsible=True,
        width="100%",
    )


# 简介与优势（直接展示在标题下方，不折叠） 
_ADVANTAGES = (
    "写入浏览器 localStorage 落盘：刷新、断网、重启浏览器都不丢",
    "首帧直读本地数据：零后端往返、零网络延迟，无「主题闪烁」",
    "同源标签页共享同一份数据：跨窗口、跨会话生效",
    "完整的后端读写能力：push / retrieve / clear 双向同步",
)


def intro() -> rx.Component:
    """库的简介与优势：直接展示（不折叠），位于标题正下方、示例之前。"""
    return rx.vstack(
        rx.text(
            "为 Reflex 提供基于浏览器 localStorage 的持久化前端状态：",
            size="2",
            color_scheme="gray",
        ),
        rx.flex(
            *[
                rx.hstack(
                    rx.icon(tag="check", size=12, color="var(--green-9)"),
                    rx.text(adv, size="1", color_scheme="gray"),
                    spacing="1",
                    align="center",
                )
                for adv in _ADVANTAGES
            ],
            direction="column",
            align="start",
            spacing="1",
        ),
        rx.text(
            "明暗外观跟随系统设置；为保护公开服务，每次后端操作间隔 ≥ 1 秒。",
            size="1",
            color_scheme="gray",
        ),
        align="start",
        spacing="2",
        width="100%",
    )


# 应用场景速览（与 README「应用场景与能力边界」章节一一对应） 

# (编号, 标题, 原生痛点, 方案价值, 典型场景)
_SCENARIOS = (
    (
        "1",
        "UI 偏好与个性化设置持久化",
        "深色模式、侧边栏状态、表格列配置、字体大小等 UI 设置，要么依赖用户登录后存数据库，"
        "要么刷新页面就重置；且首屏会先渲染默认样式，等后端状态同步后再切换，出现明显的「主题闪烁」。",
        "设置项直接存入 localStorage，首屏同步读取渲染，零网络延迟；无需登录即可跨会话持久化，"
        "刷新、重启浏览器都不丢失。",
        ("深浅主题切换", "侧边栏收起 / 展开记忆", "表格列显隐配置", "字体大小与缩放偏好", "界面语言选择"),
    ),
    (
        "2",
        "表单草稿自动保存，防止内容丢失",
        "长表单、富文本编辑、评论输入等场景，用户误刷新、网络断线重连、浏览器意外关闭后，"
        "输入内容全部清空；且逐字同步后端会产生大量 WebSocket 请求，网络差时输入卡顿明显。",
        "输入内容实时写入本地 localStorage，写入完全不依赖网络，无延迟；页面重开、刷新、断连"
        "重连后内容自动恢复。需要永久保存时，后端可通过 retrieve() 拉取草稿存入数据库。",
        ("长表单填写", "文章 / 工单编辑", "聊天输入框", "复杂筛选暂存", "问卷中途退出恢复"),
    ),
    (
        "3",
        "首屏「秒开」与离线内容兜底",
        "Reflex 原生渲染依赖 WebSocket 连接建立 + 后端状态同步，弱网、服务器负载高时首屏白屏"
        "时间长；离线状态下页面完全无法展示有效内容。",
        "核心展示内容优先从 localStorage 读取渲染，首帧即可呈现内容，无需等待后端往返；"
        "即使后端不可用、网络离线，也能展示上次缓存的数据，避免完全白屏。",
        ("首页公告 / 通知", "仪表盘缓存数据", "上次的列表筛选结果", "离线可用的工具类页面"),
    ),
    (
        "4",
        "游客态用户的行为数据留存",
        "未登录的游客用户，后端无法关联身份，购物车、浏览历史、收藏等状态无法持久化，"
        "用户流失率高；强制登录又会大幅提高使用门槛。",
        "无需登录即可将游客行为数据持久化在本地，跨会话、跨标签页生效；用户登录后再一键 "
        "retrieve() 同步到后端账号，平滑过渡。",
        ("游客购物车", "浏览历史", "搜索记录", "匿名收藏夹", "临时筛选偏好"),
    ),
    (
        "5",
        "高频轻量状态本地化，降低后端压力",
        "弹窗已读、引导提示关闭、折叠面板展开收起、列表每页条数等细碎状态，改动频繁、业务价值低，"
        "但全走后端状态会产生大量无效 WebSocket 通信，占用服务端内存与带宽。",
        "这类状态完全下沉到前端 localStorage 管理，不占用后端资源；仅在需要同步到账号时再回传后端。",
        ("新手引导已读标记", "通知弹窗关闭状态", "列表分页大小", "折叠菜单状态", "搜索历史记录"),
    ),
    (
        "6",
        "跨标签页的状态共享",
        "Reflex 每个标签页是独立的 WebSocket 连接，后端状态默认不互通；用户多开标签页时，"
        "设置、草稿等状态不一致，体验割裂。",
        "同源标签页共享同一份 localStorage 数据，一个标签页修改后，其他标签页刷新 / 切换 Tab "
        "即可同步；如需实时刷新，可监听 storage 事件调用 persist_bump。",
        ("多标签页编辑同一份草稿", "全局主题 / 租户设置", "购物车多页面共享"),
    ),
    (
        "7",
        "断线重连的体验平滑过渡",
        "网络波动导致 WebSocket 断开重连时，前端临时状态可能丢失，页面出现短暂重置，"
        "用户正在操作的内容中断。",
        "核心操作状态存在 localStorage，重连过程中 UI 不会丢失内容；重连成功后可选择通过 "
        "retrieve() 将本地数据同步回后端，用户无感知。",
        ("弱网下的表单填写", "实时编辑场景", "工业 / 监控类后台系统"),
    ),
)


# 场景卡片统一点缀色：默认蓝色系（靛蓝，与编号 1 的卡片相同）
_SCENARIO_ACCENT = "indigo"


def scenario_card(no: str, title: str, pain: str, value: str, scenes: tuple[str, ...]) -> rx.Component:
    """应用场景卡片：编号 + 标题 + 原生痛点 + 方案价值 + 典型场景 Tag，全部直接展示。

    编号徽标与场景 Tag 统一用 _SCENARIO_ACCENT（默认蓝色系）；痛点 / 价值 /
    典型场景三个区域各带小标题，正文用默认字色。
    """
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.badge(no, color_scheme=_SCENARIO_ACCENT, variant="soft", radius="full"),
                rx.text(title, size="2", weight="bold"),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            # 原生痛点
            rx.vstack(
                rx.hstack(
                    rx.icon(tag="triangle-alert", size=12, color="var(--amber-9)"),
                    rx.text("原生痛点", size="1", weight="bold"),
                    spacing="1",
                    align="center",
                ),
                rx.text(pain, size="1"),
                spacing="1",
                align="start",
                width="100%",
            ),
            # 方案价值
            rx.vstack(
                rx.hstack(
                    rx.icon(tag="check", size=12, color="var(--green-9)"),
                    rx.text("方案价值", size="1", weight="bold"),
                    spacing="1",
                    align="center",
                ),
                rx.text(value, size="1"),
                spacing="1",
                align="start",
                width="100%",
            ),
            rx.separator(),
            # 典型场景：分开的一个个 Tag
            rx.vstack(
                rx.hstack(
                    rx.icon(tag="layers", size=12, color="var(--indigo-9)"),
                    rx.text("典型场景", size="1", weight="bold"),
                    spacing="1",
                    align="center",
                ),
                rx.flex(
                    *[
                        rx.badge(s, size="1", variant="soft", color_scheme=_SCENARIO_ACCENT, radius="full")
                        for s in scenes
                    ],
                    wrap="wrap",
                    gap="2",
                ),
                spacing="1",
                align="start",
                width="100%",
            ),
            align="start",
            spacing="2",
            width="100%",
        ),
        variant="surface",
        width="100%",
    )


def scenarios() -> rx.Component:
    """应用场景速览 + 能力边界提醒：默认折叠，仅标题 + slogan（与 README 章节一致）。"""
    return rx.accordion.root(
        collapse_item(
            "use-cases",
            "layers",
            "应用场景速览",
            "持久化状态不只是「不丢」——7 类典型用法，对应 README 章节",
            rx.vstack(
                rx.grid(
                    *[scenario_card(*sc) for sc in _SCENARIOS],
                    columns=rx.breakpoints(initial="1", sm="2", lg="3"),
                    spacing="3",
                    width="100%",
                ),
                width="100%",
                spacing="3",
            ),
            icon_color="var(--indigo-9)",
        ),
        collapse_item(
            "boundary",
            "triangle-alert",
            "能力边界提醒",
            "容量 · 刷新时机 · 离线写入 · 非安全存储",
            rx.vstack(
                rx.text(
                    "1. localStorage 单域名容量约 5MB，不适合存储大量二进制数据或长列表；",
                    size="1",
                    color_scheme="gray",
                ),
                rx.text(
                    "2. 跨标签页数据天然共享，但 UI 不会自动实时刷新，需刷新 / 切换 Tab，"
                    "或手动监听 storage 事件调用 persist_bump；",
                    size="1",
                    color_scheme="gray",
                ),
                rx.text(
                    "3. 数据存储在前端，可被用户篡改，不适合存放敏感数据、权限校验类状态。",
                    size="1",
                    color_scheme="gray",
                ),
                rx.text(
                    "4. 断网时 set 仍可写入 localStorage（数据不丢），但 persist_bump 是"
                    "后端事件、无法送达，UI 不会实时刷新——重连 / 刷新后可见。",
                    size="1",
                    color_scheme="gray",
                ),
                align="start",
                spacing="1",
            ),
            icon_color="var(--amber-9)",
        ),
        color_scheme="gray",
        variant="outline",
        style={"box_shadow": "none"},
        type="multiple",
        collapsible=True,
        width="100%",
    )

# endregion


def index() -> rx.Component:
    return rx.container(
            # 1. 挂载时启动桥接并预置默认值。
            init_persist_var([AppNotice, UserDraftStr, UserDraftDict, UserDraftList]),
            rx.vstack(
                rx.hstack(
                    rx.heading("reflex-client-persist-var 演示", size="7"),
                    rx.spacer(),
                    rx.link(
                        rx.html(
                            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
                            'fill="var(--gray-11)" style="width:20px;height:20px;display:block">'
                            '<path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 '
                            '11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-'
                            '1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-'
                            '.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-'
                            '.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 '
                            '1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 '
                            '1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 '
                            '1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 '
                            '5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57'
                            'C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12z"/></svg>',
                        ),
                        href="https://github.com/nacxa0/reflex-client-persist-var",
                        is_external=True,
                        title="GitHub 仓库",
                    ),
                    align="center",
                    width="100%",
                ),

                # 简介与优势（直接展示，不折叠） 
                intro(),

                # 应用场景速览 + 能力边界提醒（默认折叠，轻视觉重量） 
                scenarios(),

                # 重渲染机制说明（默认折叠） 
                tip(),

                # 1 首屏读取（本地值，零后端往返） 
                demo1(),

                # 2 前端写入 + 交互式 Tag 编辑（复杂类型） 
                demo2(),

                # 3 后端推送（服务端 vs 本地对照） 
                demo3(),

                # 4 后端拉取（前端 → 后端） 
                demo4(),

                # 5 后端清除 
                demo5(),

                spacing="4",
                width="100%",
                align="stretch",
            ),
            size="4",
            width="100%",
        )


app = rx.App()
app.add_page(index)
