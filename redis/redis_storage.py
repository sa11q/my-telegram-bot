import json
from typing import Optional, Dict, Any
import redis.asyncio as redis

from utils.logger import error_logger


class RedisStorage:
    """
    Enterprise Redis Storage

    Используется для:
    - FSM состояний
    - временных данных
    - кэша
    - rate limit
    - блокировок
    """


    def __init__(
        self,
        host: str,
        port: int,
        db: int = 0,
        password: Optional[str] = None
    ):

        self.client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            socket_timeout=5,
            health_check_interval=30
        )


        self.default_ttl = 86400  # 24 часа


    # =========================
    # CONNECTION
    # =========================

    async def ping(self) -> bool:
        try:
            return await self.client.ping()

        except Exception as e:
            error_logger.error(
                f"Redis ping error: {e}"
            )
            return False



    async def close(self):

        try:
            await self.client.close()

        except Exception as e:
            error_logger.error(
                f"Redis close error: {e}"
            )



    # =========================
    # FSM STATES
    # =========================

    async def set_state(
        self,
        user_id: int,
        state: str,
        ttl: Optional[int] = None
    ):

        try:

            await self.client.set(
                f"fsm:state:{user_id}",
                state,
                ex=ttl or self.default_ttl
            )

        except Exception as e:

            error_logger.error(
                f"Redis set_state error: {e}"
            )



    async def get_state(
        self,
        user_id: int
    ) -> Optional[str]:

        try:

            return await self.client.get(
                f"fsm:state:{user_id}"
            )

        except Exception as e:

            error_logger.error(
                f"Redis get_state error: {e}"
            )

            return None



    async def clear_state(
        self,
        user_id:int
    ):

        await self.client.delete(
            f"fsm:state:{user_id}"
        )



    # =========================
    # USER TEMP DATA
    # =========================

    async def set_data(
        self,
        user_id:int,
        data:Dict[str,Any],
        ttl:Optional[int]=None
    ):

        try:

            await self.client.set(
                f"fsm:data:{user_id}",
                json.dumps(
                    data,
                    ensure_ascii=False
                ),
                ex=ttl or self.default_ttl
            )


        except Exception as e:

            error_logger.error(
                f"Redis set_data error: {e}"
            )



    async def get_data(
        self,
        user_id:int
    )->Dict[str,Any]:

        try:

            data = await self.client.get(
                f"fsm:data:{user_id}"
            )


            if not data:
                return {}


            return json.loads(data)


        except Exception as e:

            error_logger.error(
                f"Redis get_data error: {e}"
            )

            return {}



    async def update_data(
        self,
        user_id:int,
        data:Dict[str,Any]
    ):

        current = await self.get_data(user_id)

        current.update(data)

        await self.set_data(
            user_id,
            current
        )



    async def clear_data(
        self,
        user_id:int
    ):

        await self.client.delete(
            f"fsm:data:{user_id}"
        )



    async def clear_user_session(
        self,
        user_id:int
    ):

        await self.client.delete(
            f"fsm:data:{user_id}",
            f"fsm:state:{user_id}"
        )



    # =========================
    # RATE LIMIT
    # =========================


    async def check_rate_limit(
        self,
        user_id:int,
        action:str,
        limit:int,
        seconds:int
    )->bool:


        key = (
            f"ratelimit:"
            f"{action}:"
            f"{user_id}"
        )


        try:

            count = await self.client.incr(key)


            if count == 1:

                await self.client.expire(
                    key,
                    seconds
                )


            return count <= limit


        except Exception as e:

            error_logger.error(
                f"Rate limit error: {e}"
            )

            return True



    # =========================
    # DISTRIBUTED LOCKS
    # =========================


    async def acquire_lock(
        self,
        name:str,
        timeout:int=10
    )->bool:


        try:

            return await self.client.set(
                f"lock:{name}",
                "1",
                nx=True,
                ex=timeout
            )


        except Exception as e:

            error_logger.error(
                f"Lock error: {e}"
            )

            return False



    async def release_lock(
        self,
        name:str
    ):

        await self.client.delete(
            f"lock:{name}"
        )



    # =========================
    # CACHE
    # =========================


    async def cache_set(
        self,
        key:str,
        value:Any,
        ttl:int=300
    ):

        await self.client.set(
            f"cache:{key}",
            json.dumps(
                value,
                ensure_ascii=False
            ),
            ex=ttl
        )



    async def cache_get(
        self,
        key:str
    ):

        data = await self.client.get(
            f"cache:{key}"
        )

        if not data:
            return None

        return json.loads(data)



    async def cache_delete(
        self,
        key:str
    ):

        await self.client.delete(
            f"cache:{key}"
        )
