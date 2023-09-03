# 1.0.7版本

1. 在Windows系统上必须使用Selector事件循环
2. REST客户端停止时，确保关闭所有会话
3. 等待异步关闭任务完成后，才停止事件循环

# 1.0.6版本

1. 修复aiohttp的代理参数proxy传空时必须为None的问题

# 1.0.5版本

1. 对Python 3.10后asyncio的修改支持
