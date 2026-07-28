import json
import os
import aiofiles
import shutil
from typing import List, Optional
from database.models import User, Match, Tournament
from utils.locks import file_lock

class BaseRepository:
    async def get_user(self, user_id: int) -> Optional[User]: pass
    async def save_user(self, user: User): pass
    async def get_tournament(self, t_id: str) -> Optional[Tournament]: pass
    async def save_tournament(self, tournament: Tournament): pass

class JSONRepository(BaseRepository):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.backup_path = file_path + ".bak"
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w') as f:
                json.dump({"users": {}, "matches": {}, "tournaments": {}}, f)

    async def _read_db(self) -> dict:
        async with file_lock:
            try:
                async with aiofiles.open(self.file_path, mode='r') as f:
                    content = await f.read()
                    return json.loads(content)
            except (json.JSONDecodeError, FileNotFoundError):
                if os.path.exists(self.backup_path):
                    shutil.copy(self.backup_path, self.file_path)
                    async with aiofiles.open(self.file_path, mode='r') as f:
                        return json.loads(await f.read())
                return {"users": {}, "matches": {}, "tournaments": {}}

    async def _write_db(self, data: dict):
        async with file_lock:
            shutil.copy(self.file_path, self.backup_path)
            async with aiofiles.open(self.file_path, mode='w') as f:
                await f.write(json.dumps(data, default=str, indent=2))

    async def get_user(self, user_id: int) -> Optional[User]:
        data = await self._read_db()
        user_data = data["users"].get(str(user_id))
        return User(**user_data) if user_data else None

    async def save_user(self, user: User):
        data = await self._read_db()
        data["users"][str(user.id)] = user.model_dump()
        await self._write_db(data)

    async def get_tournament(self, t_id: str) -> Optional[Tournament]:
        data = await self._read_db()
        t_data = data["tournaments"].get(t_id)
        return Tournament(**t_data) if t_data else None

    async def save_tournament(self, tournament: Tournament):
        data = await self._read_db()
        data["tournaments"][tournament.id] = tournament.model_dump()
        await self._write_db(data)
