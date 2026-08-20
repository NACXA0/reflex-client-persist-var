import reflex as rx

config = rx.Config(
    app_name="client_persist_demo",
    # Reflex 0.9 derives the app module as "app_name.app_name" by default, which
    # expects ./app_name/app_name.py. Our entrypoint is a package at
    # ./app_name/__init__.py (standard Reflex layout), so we point Reflex at the
    # importable module explicitly. This also keeps the config robust across
    # Reflex versions that disagree on the default module derivation.
    app_module_import="client_persist_demo",
    # 明暗外观跟随系统（appearance="inherit"），页面不再提供手动切换按钮。
    plugins=[
        rx.plugins.RadixThemesPlugin(theme=rx.theme(appearance="inherit")), 
        rx.plugins.sitemap.SitemapPlugin()
    ]
)
