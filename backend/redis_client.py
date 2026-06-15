import os

import redis

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _redis_client() -> redis.Redis:
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=False,
    )


redis_client = _redis_client()
