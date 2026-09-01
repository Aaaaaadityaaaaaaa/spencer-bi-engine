import sys
import re

with open('backend/services/redis_manager.py', 'r', encoding='utf-8') as f:
    content = f.read()

rate_limit_method = """    def rate_limit(self, key: str, limit: int, window: int) -> bool:
        \"\"\"Returns True if allowed, False if rate limited.
        Implements a simple fixed-window counter using Redis.\"\"\"
        redis_key = f"rate:{key}"
        current = self.client.incr(redis_key)
        if current == 1:
            self.client.expire(redis_key, window)
        return current <= limit

    def pin_schema"""

content = content.replace("    def pin_schema", rate_limit_method)

with open('backend/services/redis_manager.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Added rate_limit to RedisManager")
