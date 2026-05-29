from __future__ import annotations

import asyncio
import copy
import time

from voicelink.mongodb import MongoDBHandler


class _FakeMongoDatabase:
    def __getitem__(self, name: str) -> object:
        return object()


class _FakeMongoClient:
    options: dict = {}

    def __init__(self, uri: str, **kwargs) -> None:
        self.uri = uri
        self.options = kwargs
        _FakeMongoClient.options = kwargs

    async def server_info(self) -> dict:
        return {}

    def __getitem__(self, name: str) -> _FakeMongoDatabase:
        return _FakeMongoDatabase()


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


def test_mongodb_pool_defaults_are_small_for_single_guild_homelab(monkeypatch) -> None:
    original_client = MongoDBHandler._client
    original_db = MongoDBHandler._db
    original_settings_db = MongoDBHandler._settings_db
    original_users_db = MongoDBHandler._users_db
    try:
        MongoDBHandler._client = None
        MongoDBHandler._db = None
        MongoDBHandler._settings_db = None
        MongoDBHandler._users_db = None
        monkeypatch.delenv("MONGODB_MAX_POOL_SIZE", raising=False)
        monkeypatch.delenv("MONGODB_MIN_POOL_SIZE", raising=False)
        monkeypatch.setattr("voicelink.mongodb.AsyncIOMotorClient", _FakeMongoClient)

        asyncio.run(MongoDBHandler.init("mongodb://mongo:27017", "vocard"))

        assert _FakeMongoClient.options["maxPoolSize"] == 10
        assert _FakeMongoClient.options["minPoolSize"] == 0
    finally:
        MongoDBHandler._client = original_client
        MongoDBHandler._db = original_db
        MongoDBHandler._settings_db = original_settings_db
        MongoDBHandler._users_db = original_users_db
