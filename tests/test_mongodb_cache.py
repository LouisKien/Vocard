from __future__ import annotations

import asyncio
import copy
import time

from voicelink.mongodb import MongoDBHandler


def test_cleanup_cache_removes_expired_settings_and_user_entries() -> None:
    original_settings = copy.deepcopy(MongoDBHandler._settings_buffer)
    original_users = copy.deepcopy(MongoDBHandler._users_buffer)
    original_last_access = copy.deepcopy(MongoDBHandler._last_access)
    try:
        expired_at = time.time() - MongoDBHandler._CACHE_TTL - 1
        MongoDBHandler._settings_buffer = {100: {"_id": 100}}
        MongoDBHandler._users_buffer = {200: {"_id": 200}}
        MongoDBHandler._last_access = {100: expired_at, 200: expired_at}

        asyncio.run(MongoDBHandler.cleanup_cache())

        assert MongoDBHandler._settings_buffer == {}
        assert MongoDBHandler._users_buffer == {}
        assert MongoDBHandler._last_access == {}
    finally:
        MongoDBHandler._settings_buffer = original_settings
        MongoDBHandler._users_buffer = original_users
        MongoDBHandler._last_access = original_last_access
