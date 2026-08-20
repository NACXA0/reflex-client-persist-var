"""``reflex_client_persist_var`` 的前端 JavaScript 桥接器。

本模块持有 ``window.__persist`` 全局管理器定义，它通过
:func:`reflex_client_persist_var.init_persist_var` 注入到页面中。

被注入 JS 的职责：

* ``window.__persist.register(key, default)`` -- 同步注册某个 key 的默认值
  （纯内存操作，不访问存储）。在页面函数顶部发出，即在首次绘制之前。
* ``window.__persist.init(key, default)``  -- 用默认值引导（bootstrap）某个 key。
* ``window.__persist.get(key)``            -- 读取 + ``JSON.parse``，带回退。
* ``window.__persist.set(key, value)``     -- ``JSON.stringify`` 写入，吞掉
  ``QuotaExceededError``，存储写满也不会让 UI 崩溃。
* ``window.__persist.retrieve(key)``       -- 供 ``run_script`` 往返读取。
* ``window.__persist.clear(key)``          -- 删除单个 key。

所有访问器都是防御性的：默认值在首次绘制 *之前* 就同步注册（``register``
随每个访问器作为 VarData hook 一起发出，落在页面函数顶部），因此当某个 key
缺失 —— 或者在 :func:`init_persist_var` 挂载之前就引用了 ``window.__persist``
—— 读取会返回该 key 已注册的默认值而不是抛错。这保证了首帧既不会白屏，
又有默认值兜底，即使离线也是如此（PRD §7.3）。

SSR 安全
--------
Reflex 0.9 会在服务器端预渲染页面，而服务器上没有 ``window``。因此每个涉及
``window.__persist`` 的表达式都被包裹在 ``typeof window !== "undefined"``
守卫中，使得服务端渲染既不会抛错，也不会执行浏览器专属逻辑。在客户端（这些
表达式唯一真正运行的地方）守卫恒为真，行为不受影响。渲染期读取（``get`` /
``value``）在 SSR 期间还会额外回退到已注册的默认值。

注意：生产构建（``reflex run --env prod``）默认开启预渲染，因此服务端输出的
标记以"默认值"呈现；而客户端首帧 hydration 期间会直接读取 localStorage 中已
持久化的值。两者只有在该 key 从未被写入时才恰好一致 —— 否则首帧可能有一次
默认值闪现，并伴随一次 React hydration 差异提示。这是"首帧即读持久化值"这一
核心设计的固有取舍（服务器无从得知 localStorage 内容），功能最终以客户端为准，
后续渲染均一致。
"""

from __future__ import annotations

# 每个浏览器专属表达式外围使用的守卫前缀。Reflex 在服务器上预渲染，那里
# ``window`` 未定义；加守卫可让 SSR 不抛错。
SSR_GUARD = "typeof window !== 'undefined'"

# 全局管理器。它只赋值一次且幂等，所以由多个组件重复注入都是安全的
# （每个 PersistentVar 的 VarData 都可能携带它）。
#
# 设计说明：
#   * ``_defaults``   映射 key -> 默认值（由 ``init`` 注册）。
#   * ``_storageKey`` 把所有 key 放在 ``client-persist-var:<key>`` 命名空间下，
#     避免与宿主应用自身的 localStorage 条目冲突。
#   * 所有内容都做了包裹处理，任何单个坏 key 都不会把异常抛进 React。
# 桥接器整体包裹在 ``if (typeof window !== 'undefined')`` 守卫中，因此在服务端
# 预渲染时是空操作（Reflex 0.9 在服务器上预渲染页面，那里 ``window`` 未定义）。
# 在客户端该守卫恒为真，行为不受影响。
PERSIST_BRIDGE = (
    "if (typeof window !== 'undefined') {" + r"""
window.__persist = window.__persist || (function () {
  var store = null;
  try {
    // localStorage 可能不可用（隐私模式 / 被禁用），优雅降级为内存映射，
    // 让应用其余部分仍能正常工作。
    store = window.localStorage || null;
    // 探测写入能力（Safari 隐私模式会在 setItem 时抛错）。
    var probe = "__persist_probe__";
    store.setItem(probe, "1");
    store.removeItem(probe);
  } catch (e) {
    store = null;
  }

  var defaults = {};      // key -> 默认值
  var memCache = {};      // localStorage 不可用时的内存兜底存储

  function storageKey(key) {
    return "client-persist-var:" + key;
  }

  function readRaw(key) {
    if (store !== null) {
      try {
        var raw = store.getItem(storageKey(key));
        if (raw !== null && raw !== undefined) {
          return raw;
        }
      } catch (e) { /* fall through to memCache */ }
    }
    // store 中无值（或读不到）时回退到 memCache，保证写失败降级到内存的
    // 新值也能被读回，而不是退回旧值 / 默认值。
    return Object.prototype.hasOwnProperty.call(memCache, key)
      ? memCache[key]
      : null;
  }

  function writeRaw(key, raw) {
    if (store !== null) {
      try {
        store.setItem(storageKey(key), raw);
        return true;
      } catch (e) {
        // PRD §7.1：QuotaExceededError（或 SecurityError）。告警但绝不抛出。
        if (window.console && console.warn) {
          console.warn("[reflex-client-persist-var] localStorage write failed for key '"
            + key + "':", e);
        }
        // 回退到内存：先清除 store 中该 key 的旧值（若存在），使后续 readRaw
        // 读不到旧值而回退到下方 memCache 中的新值 —— 否则会话内读到的仍是
        // 旧值/默认值，"当前会话仍能看到新值"的承诺无法兑现。
        try {
          store.removeItem(storageKey(key));
        } catch (e2) { /* 忽略 */ }
        memCache[key] = raw;
        return false;
      }
    }
    memCache[key] = raw;
    return true;
  }

  function asJSON(value) {
    // PRD §7.2：绝不持久化 JS 的 ``undefined`` 哨兵值 —— 它经过 JSON 往返后
    // 本来就变成 ``null``，而且对它做 JSON.parse 会抛错。
    if (value === undefined) {
      value = null;
    }
    try {
      return JSON.stringify(value);
    } catch (e) {
      if (window.console && console.warn) {
        console.warn("[reflex-client-persist-var] JSON.stringify failed for key '" + key +
          "':", e);
      }
      return JSON.stringify(null);
    }
  }

  return {
    // 同步默认值注册（纯内存，不访问存储）。在页面函数顶部、首次绘制之前
    // 发出，因此即使 localStorage 仍为空，get() 的默认值回退从第一帧起就可用
    // （PRD §7.3）。幂等且开销极小。
    register: function (key, defaultValue) {
      defaults[key] = defaultValue;
    },

    // 引导：注册默认值，并在 key 为空时写入种子值。对同一 key 可安全多次调用。
    init: function (key, defaultValue) {
      try {
        defaults[key] = defaultValue;
        if (readRaw(key) === null) {
          writeRaw(key, asJSON(defaultValue));
        }
      } catch (e) {
        if (window.console && console.warn) {
          console.warn("[reflex-client-persist-var] init failed for key '" + key + "':", e);
        }
      }
    },

    // 供渲染读取。任何失败都回退到已注册的默认值；默认值通过 register()
    // 在首次绘制之前就已注册，因此这个回退同样覆盖第一帧（PRD §7.3）。
    get: function (key) {
      try {
        var raw = readRaw(key);
        if (raw === null || raw === undefined) {
          return Object.prototype.hasOwnProperty.call(defaults, key)
            ? defaults[key]
            : null;
        }
        return JSON.parse(raw);
      } catch (e) {
        // PRD §7.2：条目损坏 -> 回退到默认值。
        if (window.console && console.warn) {
          console.warn("[reflex-client-persist-var] JSON.parse failed for key '" + key +
            "', falling back to default:", e);
        }
        return Object.prototype.hasOwnProperty.call(defaults, key)
          ? defaults[key]
          : null;
      }
    },

    // 从前端写入。返回写入的值，方便事件链继续串接。绝不抛出。
    set: function (key, value) {
      var raw = asJSON(value);
      writeRaw(key, raw);
      return value;
    },

    // 供后端往返读取（带回调的 run_script）。回退语义与 get() 相同。
    retrieve: function (key) {
      return this.get(key);
    },

    // 删除单个 key。
    clear: function (key) {
      if (store !== null) {
        try {
          store.removeItem(storageKey(key));
        } catch (e) { /* 忽略 */ }
      }
      delete memCache[key];
    }
  };
})();
""" + " }"
)

# 组件可以引用这个标记表达式，以强制桥接器在任何 ``get``/``set`` 调用之前
# 被求值。通过 VarData 引用，框架会把脚本恰好提升到页面中一次。
PERSIST_GLOBAL_REF = "window.__persist"
