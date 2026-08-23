
import asyncio, os, uuid
from redis.asyncio import Redis

async def main():
    redis = Redis.from_url(
        os.environ["REDIS_URL"],
        decode_responses=True,
        socket_connect_timeout=10,
        socket_timeout=10,
    )
    key = f"carecoordinator:smoke:{uuid.uuid4()}"
    try:
        print("PING:", await redis.ping())
        await redis.set(key, "ok", ex=60)
        assert await redis.get(key) == "ok"
        print("SET/GET: ok")

        try:
            print("FT._LIST:", await redis.execute_command("FT._LIST"))
        except Exception as exc:
            print("LANGGRAPH MODULE CHECK FAILED:", repr(exc))
    finally:
        await redis.delete(key)
        await redis.aclose()

asyncio.run(main())
