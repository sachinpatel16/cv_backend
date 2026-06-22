import asyncio

def run_async(coro):
    """Utility helper to run async coroutines inside synchronous Celery tasks."""
    async def wrapper():
        try:
            return await coro
        finally:
            from database.session import engine
            await engine.dispose()
    return asyncio.run(wrapper())
