import reflex as rx

config = rx.Config(
    app_name="client_persist_demo",
    # Reflex 0.9 默认将应用模块推导为 "app_name.app_name"（期望位于
    # ./app_name/app_name.py）。本 demo 的入口点是一个包，位于
    # ./app_name/__init__.py（标准 Reflex 布局），因此需要显式导入模块，
    # 以确保配置在不同 Reflex 版本间的稳定性。
    app_module_import="client_persist_demo",
    api_url='http://192.168.73.1',
    # 明暗外观跟随系统（appearance="inherit"），页面不再提供手动切换按钮。
    plugins=[
        rx.plugins.RadixThemesPlugin(theme=rx.theme(appearance="inherit")), 
        rx.plugins.sitemap.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin()
    ]
)
