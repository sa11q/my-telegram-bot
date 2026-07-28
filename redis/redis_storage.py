import redis
import json
from typing import Optional, Any

class RedisStorage:
    def __init__(self, host: str, port: int, db: int):
        self.redis = redis.Redis(host=host, port=port, db=db, decode_responses=True)

    def set_state(self, user_id: int, state: str):
        self.redis.set(f"state:{user_id}", state)

    def get_state(self, user_id: int) -> Optional[str]:
        return self.redis.get(f"state:{user_id}")

    def set_data(self, user_id: int, data: dict):
        self.redis.set(f"data:{user_id}", json.dumps(data))

    def get_data(self, user_id: int) -> dict:
        data = self.redis.get(f"data:{user_id}")
        return json.loads(data) if data else {}
    
    def clear(self, user_id: int):
        self.redis.delete(f"state:{user_id}")
        self.redis.delete(f"data:{user_id}")
