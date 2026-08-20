"""Front-end JavaScript bridge for ``reflex_pcache``.

This module holds the ``window.__pcache`` global manager definition that is
injected into the page via :func:`reflex_pcache.init_pcache`.

Responsibilities of the injected JS:

* ``window.__pcache.init(key, default)``  -- bootstrap a key with its default.
* ``window.__pcache.get(key)``            -- read + ``JSON.parse`` with fallback.
* ``window.__pcache.set(key, value)``     -- ``JSON.stringify`` write, swallow
  ``QuotaExceededError`` so a full store never crashes the UI.
* ``window.__pcache.retrieve(key)``       -- read for ``run_script`` round-trip.
* ``window.__pcache.clear(key)``          -- remove a single key.

All accessors are defensive: if ``window.__pcache`` is referenced before
:func:`init_pcache` has mounted (first-paint race, PRD §7.3), they degrade to
returning the *default* registered for that key instead of throwing — this is
what keeps the first paint white-screen-free even offline.
"""

from __future__ import annotations

# The global manager. It is assigned once and idempotently, so it is safe to
# inject via multiple components (every PersistentVar's VarData may carry it).
#
# Design notes:
#   * ``_defaults``   maps key -> default value (registered by ``init``).
#   * ``_storageKey`` namespaces every key under ``pcache:<key>`` so the app's
#     own localStorage entries never collide with this library.
#   * Everything is wrapped so that a single bad key never throws into React.
PCACHE_BRIDGE = r"""
window.__pcache = window.__pcache || (function () {
  var store = null;
  try {
    // localStorage may be unavailable (private mode / disabled), degrade
    // gracefully to an in-memory map so the rest of the app still works.
    store = window.localStorage || null;
    // Probe write access (Safari private mode throws on setItem).
    var probe = "__pcache_probe__";
    store.setItem(probe, "1");
    store.removeItem(probe);
  } catch (e) {
    store = null;
  }

  var defaults = {};      // key -> default value
  var memCache = {};      // fallback in-memory store when localStorage is gone

  function storageKey(key) {
    return "pcache:" + key;
  }

  function readRaw(key) {
    if (store !== null) {
      try {
        return store.getItem(storageKey(key));
      } catch (e) {
        return null;
      }
    }
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
        // PRD §7.1: QuotaExceededError (or SecurityError). Warn but never throw.
        if (window.console && console.warn) {
          console.warn("[reflex-pcache] localStorage write failed for key '"
            + key + "':", e);
        }
        // Fall back to memory so the current session still sees the value.
        memCache[key] = raw;
        return false;
      }
    }
    memCache[key] = raw;
    return true;
  }

  function asJSON(value) {
    // PRD §7.2: never persist the JS ``undefined`` sentinel — it round-trips
    // to ``null`` through JSON anyway and JSON.parse on it throws.
    if (value === undefined) {
      value = null;
    }
    try {
      return JSON.stringify(value);
    } catch (e) {
      if (window.console && console.warn) {
        console.warn("[reflex-pcache] JSON.stringify failed for key '" + key +
          "':", e);
      }
      return JSON.stringify(null);
    }
  }

  return {
    // Bootstrap: register the default and seed the key if it is empty. Safe to
    // call multiple times for the same key.
    init: function (key, defaultValue) {
      try {
        defaults[key] = defaultValue;
        if (readRaw(key) === null) {
          writeRaw(key, asJSON(defaultValue));
        }
      } catch (e) {
        if (window.console && console.warn) {
          console.warn("[reflex-pcache] init failed for key '" + key + "':", e);
        }
      }
    },

    // Read for rendering. Falls back to the registered default on any failure,
    // which is what makes first paint safe even before init has run (PRD §7.3).
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
        // PRD §7.2: corrupt entry -> fall back to default.
        if (window.console && console.warn) {
          console.warn("[reflex-pcache] JSON.parse failed for key '" + key +
            "', falling back to default:", e);
        }
        return Object.prototype.hasOwnProperty.call(defaults, key)
          ? defaults[key]
          : null;
      }
    },

    // Write from the front-end. Returns the written value so event chains can
    // chain off it. Never throws.
    set: function (key, value) {
      var raw = asJSON(value);
      writeRaw(key, raw);
      return value;
    },

    // Read for a backend round-trip (run_script with a callback). Same
    // fallback semantics as get().
    retrieve: function (key) {
      return this.get(key);
    },

    // Remove a single key.
    clear: function (key) {
      if (store !== null) {
        try {
          store.removeItem(storageKey(key));
        } catch (e) { /* ignore */ }
      }
      delete memCache[key];
    }
  };
})();
"""

# Marker expression a component can reference to force the bridge to be
# evaluated before any ``get``/``set`` call. Referenced via VarData so the
# framework hoists the script into the page exactly once.
PCACHE_GLOBAL_REF = "window.__pcache"
