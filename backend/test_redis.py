from redis_client import redis_client

redis_client.set("test", "hello")

print(redis_client.get("test"))