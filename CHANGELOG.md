# 1.2.0版本

1. 替换aiohttp异步通讯模式，改为使用requests多线程模式
2. 替换使用pyproject.toml配置
3. ruff和mypy代码质量优化

# 1.1.1版本

1. 调整connector的初始化位置

# 1.1.0版本

1. 关闭底层连接的SSL检查，解决Mac系统报错

# 1.0.9版本

1. 对于同步request函数也支持json参数

# 1.0.8版本

1. 发送请求时，支持传入json参数

# 1.0.7版本

1. 在Windows系统上必须使用Selector事件循环
2. REST客户端停止时，确保关闭所有会话
3. 等待异步关闭任务完成后，才停止事件循环

# 1.0.6版本

1. 修复aiohttp的代理参数proxy传空时必须为None的问题

# 1.0.5版本

1. 对Python 3.10后asyncio的修改支持
