改法很简单：把阻塞的调用挪到 `async def` 里，再用 `await` 等结果。

```python
import asyncio
import aiohttp

async def fetch(session, url):
    async with session.get(url) as resp:
        return await resp.text()

async def fetch_all(urls):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch(session, url) for url in urls]
        return await asyncio.gather(*tasks)
```

两个要点：网络请求用 `aiohttp` 这类异步库，不要用同步的 `requests`；多个请求一起发，用 `asyncio.gather` 收结果，这样并发度才上得去。

注意每个 `async with` 都要正确退出哦，否则连接不会被释放，跑到一半可能会把连接池耗光。如果只是偶尔几秒的等待，用 `asyncio.to_thread` 包一层同步函数也可以，代码会短很多。
