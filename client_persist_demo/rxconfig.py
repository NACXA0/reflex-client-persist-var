import reflex as rx

config = rx.Config(
    app_name="client_persist_demo",
    #Reflex 0.9 默认将应用程序模块推导为 "app_name.app_name"，其中
    # 预期位于 ./app_name/app_name.py。我们的入口点是一个包，位于.```/app_name/__init__.py（标准Reflex布局），因此我们将Reflex指向该目录```
    # 明确导入模块。这还能确保配置在不同环境下的稳定性
    # Reflex版本在默认模块推导上存在分歧。。
    app_module_import="client_persist_demo",
    # 明暗外观跟随系统（appearance="inherit"），页面不再提供手动切换按钮。
    plugins=[
        rx.plugins.RadixThemesPlugin(theme=rx.theme(appearance="inherit")), 
        rx.plugins.sitemap.SitemapPlugin()
    ]
)
